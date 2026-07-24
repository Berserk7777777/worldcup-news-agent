import plotly.graph_objects as go

from monitoring.metrics import (
    aggregate_retrieval_sources,
    aggregate_source_types,
    aggregate_time_by_agent,
    aggregate_tokens_by_agent,
    aggregate_tokens_by_model,
    build_historical_series,
)
from monitoring.schemas import (
    AgentEvent,
    ModelCallRecord,
    RetrievalRecord,
    RunRecord,
    StageRecord,
)


def _style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title,
        height=380,
        margin=dict(l=45, r=25, t=60, b=45),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def create_agent_duration_bar(stages: list[StageRecord]) -> go.Figure | None:
    values = aggregate_time_by_agent(stages)
    if not values:
        return None
    fig = go.Figure(go.Bar(
        x=list(values),
        y=list(values.values()),
        text=[f"{value:.2f}" for value in values.values()],
        textposition="outside",
        hovertemplate="%{x}<br>耗时 %{y:.3f} 秒<extra></extra>",
    ))
    fig.update_yaxes(title="秒")
    return _style(fig, "各 Agent 运行耗时（秒）")


def create_model_token_bar(
    model_calls: list[ModelCallRecord],
) -> go.Figure | None:
    values = aggregate_tokens_by_model(model_calls)
    if not values:
        return None
    totals = [metric.total_tokens for metric in values.values()]
    fig = go.Figure(go.Bar(
        x=list(values),
        y=totals,
        text=totals,
        textposition="outside",
        hovertemplate="%{x}<br>Token %{y:,}<extra></extra>",
    ))
    fig.update_yaxes(title="Token")
    return _style(fig, "各模型 Token 消耗")


def create_input_output_token_bar(
    model_calls: list[ModelCallRecord],
) -> go.Figure | None:
    values = aggregate_tokens_by_model(model_calls)
    if not values:
        return None
    names = list(values)
    fig = go.Figure([
        go.Bar(
            name="输入 Token",
            x=names,
            y=[values[name].input_tokens for name in names],
            text=[values[name].input_tokens for name in names],
            textposition="outside",
            hovertemplate="%{x}<br>输入 %{y:,}<extra></extra>",
        ),
        go.Bar(
            name="输出 Token",
            x=names,
            y=[values[name].output_tokens for name in names],
            text=[values[name].output_tokens for name in names],
            textposition="outside",
            hovertemplate="%{x}<br>输出 %{y:,}<extra></extra>",
        ),
    ])
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="Token")
    return _style(fig, "模型输入与输出 Token 对比")


def create_source_hit_bar(
    records: list[RetrievalRecord],
) -> go.Figure | None:
    values = aggregate_retrieval_sources(records)
    if not values:
        return None
    fig = go.Figure(go.Bar(
        x=list(values),
        y=list(values.values()),
        text=list(values.values()),
        textposition="outside",
        hovertemplate="%{x}<br>命中 %{y} 篇<extra></extra>",
    ))
    fig.update_yaxes(title="文档数")
    return _style(fig, "RAG 检索来源命中分布")


def create_top_k_relevance_bar(
    records: list[RetrievalRecord],
) -> go.Figure | None:
    scored = [
        (
            record.document_title or "未命名文档",
            record.rerank_score
            if record.rerank_score is not None
            else record.retrieval_score,
            record.rank,
        )
        for record in records
        if record.rerank_score is not None or record.retrieval_score is not None
    ]
    if not scored:
        return None
    scored.sort(key=lambda item: item[2] if item[2] is not None else 10**9, reverse=True)
    labels = [title if len(title) <= 30 else title[:29] + "…" for title, _, _ in scored]
    scores = [score for _, score, _ in scored]
    titles = [title for title, _, _ in scored]
    fig = go.Figure(go.Bar(
        x=scores,
        y=labels,
        orientation="h",
        text=[f"{score:.3f}" for score in scores],
        textposition="outside",
        customdata=titles,
        hovertemplate="%{customdata}<br>相关性 %{x:.4f}<extra></extra>",
    ))
    fig.update_xaxes(title="相关性得分")
    return _style(fig, "Top-K 检索结果相关性")


def _pie(labels, values, title):
    if not labels or not any(values):
        return None
    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        textinfo="label+percent",
        hovertemplate="%{label}<br>%{value:,}（%{percent}）<extra></extra>",
    ))
    return _style(fig, title)


def create_agent_token_pie(stages: list[StageRecord]) -> go.Figure | None:
    values = aggregate_tokens_by_agent(stages)
    return _pie(
        list(values),
        [metric.total_tokens for metric in values.values()],
        "各 Agent Token 消耗占比",
    )


def create_agent_time_pie(stages: list[StageRecord]) -> go.Figure | None:
    values = aggregate_time_by_agent(stages)
    return _pie(list(values), list(values.values()), "各 Agent 运行时间占比")


def create_source_type_pie(
    records: list[RetrievalRecord],
) -> go.Figure | None:
    values = aggregate_source_types(records)
    return _pie(list(values), list(values.values()), "RAG 知识来源类型占比")


def create_call_type_pie(
    model_calls: list[ModelCallRecord],
) -> go.Figure | None:
    values: dict[str, int] = {}
    for call in model_calls:
        name = call.call_type or "unknown"
        values[name] = values.get(name, 0) + 1
    return _pie(list(values), list(values.values()), "模型调用类型占比")


def _history_line(runs, value_name, title, y_title, percent=False):
    series = build_historical_series(runs)
    points = [
        item for item in series
        if item.get(value_name) is not None
    ]
    if not points:
        return None
    values = [item[value_name] * 100 if percent else item[value_name] for item in points]
    fig = go.Figure(go.Scatter(
        x=[item["started_at"] for item in points],
        y=values,
        mode="lines+markers+text",
        text=[f"{value:.1f}" for value in values],
        textposition="top center",
        customdata=[item["run_id"] for item in points],
        hovertemplate="Run %{customdata}<br>%{x}<br>%{y:.2f}<extra></extra>",
    ))
    fig.update_yaxes(title=y_title)
    fig.update_xaxes(title="开始时间")
    return _style(fig, title)


def create_token_history_line(runs: list[RunRecord]) -> go.Figure | None:
    return _history_line(runs, "total_tokens", "历史运行 Token 消耗趋势", "Token")


def create_duration_history_line(runs: list[RunRecord]) -> go.Figure | None:
    return _history_line(
        runs, "total_elapsed_seconds", "历史运行耗时趋势（秒）", "秒"
    )


def create_evidence_coverage_line(runs: list[RunRecord]) -> go.Figure | None:
    return _history_line(
        runs,
        "evidence_coverage",
        "事实证据覆盖率趋势（%）",
        "覆盖率（%）",
        percent=True,
    )


def create_retrieval_history_line(runs: list[RunRecord]) -> go.Figure | None:
    return _history_line(
        runs, "retrieved_documents", "历史检索文档数量趋势", "文档数"
    )


def create_agent_sankey(
    events: list[AgentEvent], stages: list[StageRecord]
) -> go.Figure | None:
    links = []
    labels = {
        "task_request": "任务请求",
        "evidence_request": "证据请求",
        "evidence_response": "证据返回",
        "draft_handoff": "写作交接",
        "review_request": "审校请求",
        "review_result": "审校结果",
        "image_request": "图片请求",
        "image_result": "图片结果",
        "final_result": "最终结果",
        "error": "错误",
    }
    for event in sorted(events, key=lambda item: item.sequence):
        links.append((
            event.from_agent,
            event.to_agent,
            labels.get(event.event_type, event.event_type),
            event.content_summary,
        ))
    if not links:
        agents = [stage.agent_name for stage in sorted(stages, key=lambda item: item.sequence)]
        if not agents:
            return None
        path = ["User", *agents, "Final Output"]
        links = [
            (path[index], path[index + 1], "阶段流转", "")
            for index in range(len(path) - 1)
        ]
    nodes = []
    for source, target, _, _ in links:
        if source not in nodes:
            nodes.append(source)
        if target not in nodes:
            nodes.append(target)
    fig = go.Figure(go.Sankey(
        node=dict(label=nodes, pad=18, thickness=18),
        link=dict(
            source=[nodes.index(source) for source, _, _, _ in links],
            target=[nodes.index(target) for _, target, _, _ in links],
            value=[1] * len(links),
            label=[label for _, _, label, _ in links],
            customdata=[
                f"{source} → {target}<br>{label}<br>{summary}"
                for source, target, label, summary in links
            ],
            hovertemplate="%{customdata}<extra></extra>",
        ),
    ))
    return _style(fig, "Agent 协作流程")
