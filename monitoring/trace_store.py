import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path

from monitoring.schemas import (
    AgentEvent,
    ModelCallRecord,
    RetrievalRecord,
    RunRecord,
    StageRecord,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT,
    user_query TEXT,
    task_type TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    total_elapsed_seconds REAL,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    llm_call_count INTEGER DEFAULT 0,
    embedding_call_count INTEGER DEFAULT 0,
    rerank_call_count INTEGER DEFAULT 0,
    image_call_count INTEGER DEFAULT 0,
    retrieved_documents INTEGER DEFAULT 0,
    used_documents INTEGER DEFAULT 0,
    total_claims INTEGER DEFAULT 0,
    supported_claims INTEGER DEFAULT 0,
    unsupported_claims INTEGER DEFAULT 0,
    evidence_coverage REAL,
    article_character_count INTEGER,
    generated_image_count INTEGER DEFAULT 0,
    error_stage TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    stage_name TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    model_name TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    elapsed_seconds REAL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    input_summary TEXT,
    output_summary TEXT,
    error_message TEXT,
    metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS retrieval_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    stage_id INTEGER REFERENCES stages(id) ON DELETE SET NULL,
    query TEXT,
    document_id TEXT,
    document_title TEXT,
    source_name TEXT,
    source_type TEXT,
    source_url TEXT,
    published_at TEXT,
    rank INTEGER,
    retrieval_score REAL,
    rerank_score REAL,
    used_in_answer INTEGER DEFAULT 0,
    chunk_preview TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    event_type TEXT NOT NULL,
    content_summary TEXT,
    created_at TEXT NOT NULL,
    metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS model_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    stage_id INTEGER REFERENCES stages(id) ON DELETE SET NULL,
    agent_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    call_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    elapsed_seconds REAL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_task_type ON runs(task_type);
CREATE INDEX IF NOT EXISTS idx_stages_run_id ON stages(run_id);
CREATE INDEX IF NOT EXISTS idx_stages_agent_name ON stages(agent_name);
CREATE INDEX IF NOT EXISTS idx_stages_model_name ON stages(model_name);
CREATE INDEX IF NOT EXISTS idx_retrieval_run_id ON retrieval_records(run_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_source_name ON retrieval_records(source_name);
CREATE INDEX IF NOT EXISTS idx_agent_events_run_id ON agent_events(run_id);
CREATE INDEX IF NOT EXISTS idx_model_calls_run_id ON model_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_model_calls_model_name ON model_calls(model_name);
"""


class TraceStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._uri = str(db_path) == ":memory:"
        self._database = str(self.db_path)
        self._anchor = None
        if self._uri:
            self._database = (
                f"file:agent_traces_{uuid.uuid4().hex}?mode=memory&cache=shared"
            )
            self._anchor = sqlite3.connect(self._database, uri=True)
            self._configure(self._anchor)
        self.initialize_database()

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.row_factory = sqlite3.Row

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self._database, uri=self._uri, timeout=5)
        self._configure(connection)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize_database(self) -> None:
        if not self._uri:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(SCHEMA)

    @staticmethod
    def _record(row: sqlite3.Row | None, record_type):
        if row is None:
            return None
        names = {field.name for field in fields(record_type)}
        return record_type(**{key: row[key] for key in row.keys() if key in names})

    def create_run(
        self, run_id, session_id, user_query, task_type, started_at
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, session_id, user_query, task_type, started_at,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?)
                """,
                (run_id, session_id, user_query, task_type, started_at, started_at),
            )

    def finish_run(self, run_id, ended_at, **aggregated_metrics) -> None:
        allowed = {
            "total_elapsed_seconds",
            "total_input_tokens",
            "total_output_tokens",
            "total_tokens",
            "llm_call_count",
            "embedding_call_count",
            "rerank_call_count",
            "image_call_count",
            "retrieved_documents",
            "used_documents",
            "total_claims",
            "supported_claims",
            "unsupported_claims",
            "evidence_coverage",
            "article_character_count",
            "generated_image_count",
        }
        values = {key: value for key, value in aggregated_metrics.items() if key in allowed}
        assignments = ["ended_at = ?", "status = 'success'"]
        parameters = [ended_at]
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            parameters.append(value)
        parameters.append(run_id)
        with self._connection() as connection:
            connection.execute(
                f"UPDATE runs SET {', '.join(assignments)} WHERE run_id = ?",
                parameters,
            )

    def fail_run(
        self,
        run_id,
        error_stage,
        error_message,
        ended_at,
        total_elapsed_seconds=None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = 'failed', error_stage = ?, error_message = ?,
                    ended_at = ?, total_elapsed_seconds = COALESCE(?, total_elapsed_seconds)
                WHERE run_id = ?
                """,
                (
                    error_stage,
                    error_message,
                    ended_at,
                    total_elapsed_seconds,
                    run_id,
                ),
            )

    def create_stage(
        self,
        run_id,
        sequence,
        stage_name,
        agent_name,
        operation_type,
        model_name,
        started_at,
        input_summary,
        metadata_json,
    ) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO stages (
                    run_id, sequence, stage_name, agent_name, operation_type,
                    model_name, status, started_at, input_summary, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)
                """,
                (
                    run_id,
                    sequence,
                    stage_name,
                    agent_name,
                    operation_type,
                    model_name,
                    started_at,
                    input_summary,
                    metadata_json,
                ),
            )
            return cursor.lastrowid

    def complete_stage(
        self,
        stage_id,
        ended_at,
        elapsed_seconds,
        output_summary,
        input_tokens,
        output_tokens,
        total_tokens,
        metadata_json,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE stages
                SET status = 'success', ended_at = ?, elapsed_seconds = ?,
                    output_summary = ?, input_tokens = ?, output_tokens = ?,
                    total_tokens = ?, metadata_json = ?
                WHERE id = ?
                """,
                (
                    ended_at,
                    elapsed_seconds,
                    output_summary,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    metadata_json,
                    stage_id,
                ),
            )

    def fail_stage(
        self, stage_id, error_message, ended_at, elapsed_seconds=None
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE stages
                SET status = 'failed', error_message = ?, ended_at = ?,
                    elapsed_seconds = COALESCE(?, elapsed_seconds)
                WHERE id = ?
                """,
                (error_message, ended_at, elapsed_seconds, stage_id),
            )

    def record_model_call(self, **fields_to_write) -> int:
        columns = [
            "run_id",
            "stage_id",
            "agent_name",
            "model_name",
            "call_type",
            "started_at",
            "ended_at",
            "elapsed_seconds",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "status",
            "error_message",
            "metadata_json",
        ]
        values = [fields_to_write.get(column) for column in columns]
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                INSERT INTO model_calls ({', '.join(columns)})
                VALUES ({', '.join('?' for _ in columns)})
                """,
                values,
            )
            return cursor.lastrowid

    def record_retrieval_items(self, items: list[dict]) -> None:
        if not items:
            return
        columns = [
            "run_id",
            "stage_id",
            "query",
            "document_id",
            "document_title",
            "source_name",
            "source_type",
            "source_url",
            "published_at",
            "rank",
            "retrieval_score",
            "rerank_score",
            "used_in_answer",
            "chunk_preview",
            "metadata_json",
            "created_at",
        ]
        values = [[item.get(column) for column in columns] for item in items]
        with self._connection() as connection:
            connection.executemany(
                f"""
                INSERT INTO retrieval_records ({', '.join(columns)})
                VALUES ({', '.join('?' for _ in columns)})
                """,
                values,
            )

    def record_agent_event(
        self,
        run_id,
        sequence,
        from_agent,
        to_agent,
        event_type,
        content_summary,
        metadata_json,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO agent_events (
                    run_id, sequence, from_agent, to_agent, event_type,
                    content_summary, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)
                """,
                (
                    run_id,
                    sequence,
                    from_agent,
                    to_agent,
                    event_type,
                    content_summary,
                    metadata_json,
                ),
            )

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._record(row, RunRecord)

    def _get_records(self, table, run_id, order_by, record_type):
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE run_id = ? ORDER BY {order_by}",
                (run_id,),
            ).fetchall()
        return [self._record(row, record_type) for row in rows]

    def get_run_stages(self, run_id: str) -> list[StageRecord]:
        return self._get_records("stages", run_id, "sequence, id", StageRecord)

    def get_run_model_calls(self, run_id: str) -> list[ModelCallRecord]:
        return self._get_records("model_calls", run_id, "id", ModelCallRecord)

    def get_run_retrieval_records(self, run_id: str) -> list[RetrievalRecord]:
        return self._get_records(
            "retrieval_records", run_id, "rank, id", RetrievalRecord
        )

    def get_run_agent_events(self, run_id: str) -> list[AgentEvent]:
        return self._get_records(
            "agent_events", run_id, "sequence, id", AgentEvent
        )

    def list_runs(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
        task_type: str | None = None,
        model_name: str | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        clauses = []
        parameters = []
        if start_date:
            clauses.append("r.started_at >= ?")
            parameters.append(start_date)
        if end_date:
            clauses.append("r.started_at <= ?")
            parameters.append(end_date)
        if status:
            clauses.append("r.status = ?")
            parameters.append(status)
        if task_type:
            clauses.append("r.task_type = ?")
            parameters.append(task_type)
        if model_name:
            clauses.append(
                "EXISTS (SELECT 1 FROM model_calls m "
                "WHERE m.run_id = r.run_id AND m.model_name = ?)"
            )
            parameters.append(model_name)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(max(1, min(int(limit), 1000)))
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT r.* FROM runs r{where} ORDER BY r.started_at DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [self._record(row, RunRecord) for row in rows]

    def get_historical_metrics(self, limit: int = 500) -> list[RunRecord]:
        return self.list_runs(limit=limit)

    def get_distinct_task_types(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT task_type FROM runs "
                "WHERE task_type IS NOT NULL AND task_type != '' ORDER BY task_type"
            ).fetchall()
        return [row[0] for row in rows]

    def get_distinct_model_names(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT model_name FROM model_calls "
                "WHERE model_name IS NOT NULL AND model_name != '' ORDER BY model_name"
            ).fetchall()
        return [row[0] for row in rows]

    def delete_run(self, run_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
