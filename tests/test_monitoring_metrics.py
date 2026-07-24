import unittest

from monitoring.metrics import (
    aggregate_retrieval_sources,
    aggregate_source_types,
    aggregate_time_by_agent,
    aggregate_tokens_by_agent,
    aggregate_tokens_by_model,
    build_historical_series,
    calculate_success_rate,
)
from monitoring.schemas import ModelCallRecord, RetrievalRecord, RunRecord, StageRecord


class MonitoringMetricsTests(unittest.TestCase):
    def test_01_aggregate_tokens_by_agent(self):
        stages = [
            StageRecord(agent_name="Planner", input_tokens=10, output_tokens=5, total_tokens=15),
            StageRecord(agent_name="Planner", input_tokens=2, output_tokens=3, total_tokens=5),
        ]
        self.assertEqual(aggregate_tokens_by_agent(stages)["Planner"].total_tokens, 20)

    def test_02_aggregate_tokens_by_model(self):
        calls = [
            ModelCallRecord(model_name="model-a", total_tokens=10),
            ModelCallRecord(model_name="model-a", total_tokens=20),
        ]
        self.assertEqual(aggregate_tokens_by_model(calls)["model-a"].total_tokens, 30)

    def test_03_aggregate_time_by_agent(self):
        stages = [
            StageRecord(agent_name="Writer", elapsed_seconds=1.5),
            StageRecord(agent_name="Writer", elapsed_seconds=2.0),
        ]
        self.assertEqual(aggregate_time_by_agent(stages)["Writer"], 3.5)

    def test_04_aggregate_retrieval_sources(self):
        records = [
            RetrievalRecord(source_name="FIFA"),
            RetrievalRecord(source_name="FIFA"),
            RetrievalRecord(source_name=""),
        ]
        self.assertEqual(aggregate_retrieval_sources(records), {"FIFA": 2, "未知来源": 1})

    def test_05_aggregate_source_types(self):
        records = [
            RetrievalRecord(source_type="official"),
            RetrievalRecord(source_type="government"),
            RetrievalRecord(source_type=None),
        ]
        self.assertEqual(
            aggregate_source_types(records),
            {"官方来源": 1, "政府机构": 1, "其他": 1},
        )

    def test_06_calculate_success_rate(self):
        runs = [RunRecord(status="success"), RunRecord(status="failed")]
        self.assertEqual(calculate_success_rate(runs), 0.5)

    def test_07_empty_inputs_return_safe_defaults(self):
        self.assertEqual(aggregate_tokens_by_agent([]), {})
        self.assertEqual(aggregate_tokens_by_model([]), {})
        self.assertEqual(aggregate_retrieval_sources([]), {})
        self.assertEqual(calculate_success_rate([]), 0.0)

    def test_08_historical_series_sorted_by_time(self):
        runs = [
            RunRecord(run_id="later", started_at="2026-07-23T11:00:00"),
            RunRecord(run_id="earlier", started_at="2026-07-23T10:00:00"),
        ]
        self.assertEqual(build_historical_series(runs)[0]["run_id"], "earlier")


if __name__ == "__main__":
    unittest.main()
