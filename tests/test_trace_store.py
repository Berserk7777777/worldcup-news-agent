import unittest

from monitoring.trace_store import TraceStore


class TraceStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = TraceStore(":memory:")
        self.store.create_run(
            "run-1", "session-1", "世界杯新闻", "news_generation", "2026-07-23T10:00:00"
        )

    def test_01_empty_db_initialize(self):
        self.store.initialize_database()
        self.assertIsNone(self.store.get_run("missing"))

    def test_02_create_run(self):
        run = self.store.get_run("run-1")
        self.assertEqual(run.status, "running")

    def test_03_finish_run(self):
        self.store.finish_run("run-1", "2026-07-23T10:01:00", total_tokens=42)
        run = self.store.get_run("run-1")
        self.assertEqual((run.status, run.total_tokens), ("success", 42))

    def test_04_create_and_complete_stage(self):
        stage_id = self._stage()
        self.store.complete_stage(
            stage_id, "2026-07-23T10:00:02", 2.0, "完成", 10, 5, 15, None
        )
        stage = self.store.get_run_stages("run-1")[0]
        self.assertEqual((stage.status, stage.total_tokens), ("success", 15))

    def test_05_record_model_call(self):
        call_id = self.store.record_model_call(
            run_id="run-1",
            stage_id=None,
            agent_name="Planner Agent",
            model_name="model-a",
            call_type="chat",
            started_at="2026-07-23T10:00:00",
            ended_at="2026-07-23T10:00:01",
            elapsed_seconds=1.0,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            status="success",
            error_message=None,
            metadata_json=None,
        )
        self.assertGreater(call_id, 0)
        self.assertEqual(self.store.get_run_model_calls("run-1")[0].total_tokens, 15)

    def test_06_record_retrieval_items(self):
        self.store.record_retrieval_items(
            [{
                "run_id": "run-1",
                "stage_id": None,
                "query": "决赛",
                "document_id": "doc-1",
                "document_title": "世界杯决赛",
                "source_name": "FIFA",
                "source_type": "official",
                "source_url": "https://example.com",
                "published_at": "2026-07-20",
                "rank": 1,
                "retrieval_score": 0.9,
                "rerank_score": None,
                "used_in_answer": 1,
                "chunk_preview": "比赛摘要",
                "metadata_json": None,
                "created_at": "2026-07-23T10:00:00",
            }]
        )
        self.assertEqual(len(self.store.get_run_retrieval_records("run-1")), 1)

    def test_07_record_agent_event(self):
        self.store.record_agent_event(
            "run-1", 1, "User", "Planner Agent", "task_request", "摘要", None
        )
        self.assertEqual(self.store.get_run_agent_events("run-1")[0].to_agent, "Planner Agent")

    def test_08_query_complete_run(self):
        self.store.finish_run("run-1", "2026-07-23T10:01:00")
        runs = self.store.list_runs(status="success")
        self.assertEqual([run.run_id for run in runs], ["run-1"])

    def test_09_cascade_delete_run(self):
        self._stage()
        self.store.record_agent_event(
            "run-1", 1, "User", "Planner Agent", "task_request", "摘要", None
        )
        self.store.delete_run("run-1")
        self.assertIsNone(self.store.get_run("run-1"))
        self.assertEqual(self.store.get_run_stages("run-1"), [])
        self.assertEqual(self.store.get_run_agent_events("run-1"), [])

    def test_10_special_characters_in_query(self):
        query = """比赛 ' " ; -- DROP TABLE runs"""
        self.store.create_run(
            "run-special", "session", query, "news_generation", "2026-07-23T11:00:00"
        )
        self.assertEqual(self.store.get_run("run-special").user_query, query)
        self.assertIsNotNone(self.store.get_run("run-1"))

    def _stage(self):
        return self.store.create_stage(
            "run-1", 1, "任务规划", "Planner Agent", "llm", "model-a",
            "2026-07-23T10:00:00", "输入", None
        )


if __name__ == "__main__":
    unittest.main()
