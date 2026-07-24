import unittest

from monitoring.trace_recorder import AgentTraceRecorder
from monitoring.trace_store import TraceStore


class TraceRecorderTests(unittest.TestCase):
    def setUp(self):
        self.store = TraceStore(":memory:")
        self.recorder = AgentTraceRecorder(
            self.store, "session-1", "生成世界杯新闻"
        )
        self.run_id = self.recorder.start_run()

    def test_01_start_run_generates_uuid(self):
        self.assertEqual(len(self.run_id), 36)

    def test_02_start_stage_status_running(self):
        stage_id = self._stage()
        self.assertEqual(self.store.get_run_stages(self.run_id)[0].status, "running")
        self.assertGreater(stage_id, 0)

    def test_03_complete_stage_records_timing_and_tokens(self):
        stage_id = self._stage()
        self.recorder.complete_stage(stage_id, "完成", 10, 5, 15)
        stage = self.store.get_run_stages(self.run_id)[0]
        self.assertEqual(stage.total_tokens, 15)
        self.assertIsNotNone(stage.elapsed_seconds)

    def test_04_fail_stage_records_failure(self):
        stage_id = self._stage()
        self.recorder.fail_stage(stage_id, RuntimeError("失败"))
        self.assertEqual(self.store.get_run_stages(self.run_id)[0].status, "failed")

    def test_05_finish_run_aggregates_tokens(self):
        stage_id = self._stage()
        self.recorder.complete_stage(stage_id, "完成", 8, 2, 10)
        self.recorder.finish_run()
        self.assertEqual(self.store.get_run(self.run_id).total_tokens, 10)

    def test_06_finish_run_counts_llm_calls(self):
        stage_id = self._stage()
        self.recorder.record_model_call(
            stage_id, "Planner Agent", "model-a", "chat", 8, 2, 10
        )
        self.recorder.finish_run()
        self.assertEqual(self.store.get_run(self.run_id).llm_call_count, 1)

    def test_07_evidence_coverage_calculated(self):
        self.recorder.finish_run(total_claims=4, supported_claims=3)
        self.assertEqual(self.store.get_run(self.run_id).evidence_coverage, 0.75)

    def test_08_evidence_coverage_null_when_zero_claims(self):
        self.recorder.finish_run()
        self.assertIsNone(self.store.get_run(self.run_id).evidence_coverage)

    def test_09_fail_run_preserves_completed_stages(self):
        stage_id = self._stage()
        self.recorder.complete_stage(stage_id, "完成")
        error = RuntimeError("后续失败")
        with self.assertRaises(RuntimeError):
            self.recorder.fail_run("图片生成", error)
        self.assertEqual(self.store.get_run_stages(self.run_id)[0].status, "success")
        self.assertEqual(self.store.get_run(self.run_id).status, "failed")

    def test_10_error_message_sanitized(self):
        secret = "sk-123456789012345678901234"
        with self.assertRaises(RuntimeError):
            self.recorder.fail_run("模型调用", RuntimeError(f"Bearer {secret}"))
        message = self.store.get_run(self.run_id).error_message
        self.assertNotIn(secret, message)
        self.assertIn("[TOKEN_REDACTED]", message)

    def _stage(self):
        return self.recorder.start_stage(
            "任务规划", "Planner Agent", "llm", "model-a", "输入摘要"
        )


if __name__ == "__main__":
    unittest.main()
