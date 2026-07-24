import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from monitoring.metrics import calculate_evidence_coverage
from monitoring.sanitization import safe_summary, sanitize_error, sanitize_text
from monitoring.trace_store import TraceStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(value):
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return sanitize_text(str(value))


def _metadata_json(metadata: dict | None) -> str | None:
    return json.dumps(_clean(metadata), ensure_ascii=False) if metadata else None


@dataclass
class StageHandle:
    stage_id: int


class AgentTraceRecorder:
    def __init__(
        self,
        store: TraceStore,
        session_id: str,
        user_query: str,
        task_type: str = "news_generation",
    ):
        self.store = store
        self.session_id = safe_summary(sanitize_text(session_id), 150)
        self.user_query = safe_summary(sanitize_text(user_query), 150)
        self.task_type = safe_summary(sanitize_text(task_type), 100)
        self.run_id: str | None = None
        self._run_start: float | None = None
        self._stage_starts: dict[int, float] = {}
        self._stage_sequence = 0
        self._event_sequence = 0

    def start_run(self) -> str:
        self.run_id = str(uuid.uuid4())
        self._run_start = time.perf_counter()
        self.store.create_run(
            self.run_id, self.session_id, self.user_query, self.task_type, _now()
        )
        return self.run_id

    def start_stage(
        self,
        stage_name: str,
        agent_name: str,
        operation_type: str,
        model_name: str | None = None,
        input_summary: str = "",
        metadata: dict | None = None,
    ) -> int:
        if not self.run_id:
            raise RuntimeError("请先调用 start_run")
        self._stage_sequence += 1
        stage_id = self.store.create_stage(
            self.run_id,
            self._stage_sequence,
            safe_summary(sanitize_text(stage_name), 100),
            safe_summary(sanitize_text(agent_name), 100),
            safe_summary(sanitize_text(operation_type), 50),
            safe_summary(sanitize_text(model_name), 200) if model_name else None,
            _now(),
            safe_summary(sanitize_text(input_summary), 300),
            _metadata_json(metadata),
        )
        self._stage_starts[stage_id] = time.perf_counter()
        return stage_id

    def complete_stage(
        self,
        stage_id: int,
        output_summary: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        metadata: dict | None = None,
    ) -> None:
        started = self._stage_starts.pop(stage_id, time.perf_counter())
        self.store.complete_stage(
            stage_id,
            _now(),
            round(time.perf_counter() - started, 3),
            safe_summary(sanitize_text(output_summary), 300),
            input_tokens,
            output_tokens,
            total_tokens,
            _metadata_json(metadata),
        )

    def fail_stage(self, stage_id: int, error: Exception) -> None:
        started = self._stage_starts.pop(stage_id, time.perf_counter())
        self.store.fail_stage(
            stage_id,
            sanitize_error(error),
            _now(),
            round(time.perf_counter() - started, 3),
        )

    def record_model_call(
        self,
        stage_id: int,
        agent_name: str,
        model_name: str,
        call_type: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        status: str = "success",
        error: Exception | None = None,
        metadata: dict | None = None,
        elapsed_seconds: float | None = None,
    ) -> None:
        if not self.run_id:
            raise RuntimeError("请先调用 start_run")
        now = _now()
        self.store.record_model_call(
            run_id=self.run_id,
            stage_id=stage_id,
            agent_name=safe_summary(sanitize_text(agent_name), 100),
            model_name=safe_summary(sanitize_text(model_name), 200),
            call_type=safe_summary(sanitize_text(call_type), 50),
            started_at=now,
            ended_at=now,
            elapsed_seconds=round(elapsed_seconds or 0.0, 3),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            status=status,
            error_message=sanitize_error(error) if error else None,
            metadata_json=_metadata_json(metadata),
        )

    def record_retrieval(
        self, stage_id: int, query: str, items: list[dict]
    ) -> None:
        if not self.run_id:
            raise RuntimeError("请先调用 start_run")
        now = _now()
        records = []
        for item in items:
            records.append(
                {
                    "run_id": self.run_id,
                    "stage_id": stage_id,
                    "query": safe_summary(sanitize_text(query), 300),
                    "document_id": sanitize_text(item.get("document_id", "")),
                    "document_title": safe_summary(
                        sanitize_text(item.get("document_title", "")), 300
                    ),
                    "source_name": safe_summary(
                        sanitize_text(item.get("source_name", "")), 200
                    ),
                    "source_type": safe_summary(
                        sanitize_text(item.get("source_type", "other")), 50
                    ),
                    "source_url": safe_summary(
                        sanitize_text(item.get("source_url", "")), 1000
                    ),
                    "published_at": item.get("published_at"),
                    "rank": item.get("rank"),
                    "retrieval_score": item.get("retrieval_score"),
                    "rerank_score": item.get("rerank_score"),
                    "used_in_answer": int(bool(item.get("used_in_answer"))),
                    "chunk_preview": safe_summary(
                        sanitize_text(item.get("chunk_preview", "")), 300
                    ),
                    "metadata_json": _metadata_json(item.get("metadata")),
                    "created_at": now,
                }
            )
        self.store.record_retrieval_items(records)

    def record_agent_message(
        self,
        from_agent: str,
        to_agent: str,
        event_type: str,
        content_summary: str,
        metadata: dict | None = None,
    ) -> None:
        if not self.run_id:
            raise RuntimeError("请先调用 start_run")
        self._event_sequence += 1
        self.store.record_agent_event(
            self.run_id,
            self._event_sequence,
            safe_summary(sanitize_text(from_agent), 100),
            safe_summary(sanitize_text(to_agent), 100),
            safe_summary(sanitize_text(event_type), 50),
            safe_summary(sanitize_text(content_summary), 300),
            _metadata_json(metadata),
        )

    def _aggregated_metrics(self) -> dict:
        stages = self.store.get_run_stages(self.run_id or "")
        calls = self.store.get_run_model_calls(self.run_id or "")
        retrieval = self.store.get_run_retrieval_records(self.run_id or "")
        token_rows = calls or stages
        return {
            "total_input_tokens": sum(row.input_tokens or 0 for row in token_rows),
            "total_output_tokens": sum(row.output_tokens or 0 for row in token_rows),
            "total_tokens": sum(row.total_tokens or 0 for row in token_rows),
            "llm_call_count": sum(call.call_type == "chat" for call in calls),
            "embedding_call_count": sum(
                call.call_type == "embedding" for call in calls
            ),
            "rerank_call_count": sum(call.call_type == "rerank" for call in calls),
            "image_call_count": sum(call.call_type == "image" for call in calls),
            "retrieved_documents": len(retrieval),
            "used_documents": sum(bool(row.used_in_answer) for row in retrieval),
        }

    def finish_run(
        self,
        article_character_count: int | None = None,
        generated_image_count: int = 0,
        total_claims: int = 0,
        supported_claims: int = 0,
        unsupported_claims: int = 0,
    ) -> None:
        if not self.run_id:
            raise RuntimeError("请先调用 start_run")
        metrics = self._aggregated_metrics()
        metrics.update(
            total_elapsed_seconds=round(
                time.perf_counter() - (self._run_start or time.perf_counter()), 3
            ),
            article_character_count=article_character_count,
            generated_image_count=generated_image_count,
            total_claims=total_claims,
            supported_claims=supported_claims,
            unsupported_claims=unsupported_claims,
            evidence_coverage=calculate_evidence_coverage(
                supported_claims, total_claims
            ),
        )
        self.store.finish_run(self.run_id, _now(), **metrics)

    def fail_run(self, error_stage: str, error: Exception) -> None:
        if not self.run_id:
            raise error
        elapsed = round(
            time.perf_counter() - (self._run_start or time.perf_counter()), 3
        )
        self.store.fail_run(
            self.run_id,
            safe_summary(sanitize_text(error_stage), 100),
            sanitize_error(error),
            _now(),
            elapsed,
        )
        raise error

    @contextmanager
    def stage(
        self,
        stage_name: str,
        agent_name: str,
        operation_type: str,
        model_name: str | None = None,
        input_summary: str = "",
        metadata: dict | None = None,
    ):
        stage_id = self.start_stage(
            stage_name,
            agent_name,
            operation_type,
            model_name,
            input_summary,
            metadata,
        )
        try:
            yield StageHandle(stage_id)
        except Exception as error:
            self.fail_stage(stage_id, error)
            raise
        else:
            self.complete_stage(stage_id)
