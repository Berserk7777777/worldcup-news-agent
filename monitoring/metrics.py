from monitoring.schemas import (
    ModelCallRecord,
    RetrievalRecord,
    RunRecord,
    StageMetrics,
    StageRecord,
)


def _value(item, name, default=None):
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def calculate_success_rate(runs: list[RunRecord]) -> float:
    return sum(_value(run, "status") == "success" for run in runs) / len(runs) if runs else 0.0


def aggregate_tokens_by_agent(stages: list[StageRecord]) -> dict[str, StageMetrics]:
    result: dict[str, StageMetrics] = {}
    for stage in stages:
        name = _value(stage, "agent_name", "") or "未知 Agent"
        metric = result.setdefault(name, StageMetrics())
        metric.input_tokens += _value(stage, "input_tokens", 0) or 0
        metric.output_tokens += _value(stage, "output_tokens", 0) or 0
        metric.total_tokens += _value(stage, "total_tokens", 0) or 0
        metric.elapsed_seconds += _value(stage, "elapsed_seconds", 0.0) or 0.0
    return result


def aggregate_tokens_by_model(
    model_calls: list[ModelCallRecord],
) -> dict[str, StageMetrics]:
    result: dict[str, StageMetrics] = {}
    for call in model_calls:
        name = _value(call, "model_name", "") or "未知模型"
        metric = result.setdefault(name, StageMetrics())
        metric.input_tokens += _value(call, "input_tokens", 0) or 0
        metric.output_tokens += _value(call, "output_tokens", 0) or 0
        metric.total_tokens += _value(call, "total_tokens", 0) or 0
        metric.elapsed_seconds += _value(call, "elapsed_seconds", 0.0) or 0.0
    return result


def aggregate_time_by_agent(stages: list[StageRecord]) -> dict[str, float]:
    return {
        name: metric.elapsed_seconds
        for name, metric in aggregate_tokens_by_agent(stages).items()
    }


def aggregate_retrieval_sources(records: list[RetrievalRecord]) -> dict[str, int]:
    result: dict[str, int] = {}
    for record in records:
        name = _value(record, "source_name", "") or "未知来源"
        result[name] = result.get(name, 0) + 1
    return result


def aggregate_source_types(records: list[RetrievalRecord]) -> dict[str, int]:
    labels = {
        "official": "官方来源",
        "news_agency": "权威通讯社",
        "sports_media": "体育媒体",
        "government": "政府机构",
        "other": "其他",
    }
    result: dict[str, int] = {}
    for record in records:
        label = labels.get(_value(record, "source_type"), "其他")
        result[label] = result.get(label, 0) + 1
    return result


def calculate_evidence_coverage(
    supported_claims: int, total_claims: int
) -> float | None:
    if total_claims <= 0:
        return None
    return max(0.0, min(1.0, supported_claims / total_claims))


def build_historical_series(runs: list[RunRecord]) -> list[dict]:
    ordered = sorted(runs, key=lambda run: _value(run, "started_at", "") or "")
    return [
        {
            "run_id": _value(run, "run_id"),
            "started_at": _value(run, "started_at"),
            "total_tokens": _value(run, "total_tokens", 0),
            "total_elapsed_seconds": _value(run, "total_elapsed_seconds"),
            "evidence_coverage": _value(run, "evidence_coverage"),
            "retrieved_documents": _value(run, "retrieved_documents", 0),
            "status": _value(run, "status"),
        }
        for run in ordered
    ]
