import csv
import dataclasses
import io
import json
import time
from datetime import date, timedelta

import streamlit as st

from monitoring import DEFAULT_TRACE_STORE
from monitoring.metrics import calculate_success_rate
from monitoring.sanitization import safe_summary, sanitize_text
from monitoring.visualizations import (
    create_agent_duration_bar,
    create_agent_sankey,
    create_agent_time_pie,
    create_agent_token_pie,
    create_call_type_pie,
    create_duration_history_line,
    create_evidence_coverage_line,
    create_input_output_token_bar,
    create_model_token_bar,
    create_retrieval_history_line,
    create_source_hit_bar,
    create_source_type_pie,
    create_token_history_line,
    create_top_k_relevance_bar,
)
from ui import apply_newsroom_style, render_brand, render_sidebar_user, render_topbar


st.set_page_config(
    page_title="智能体运行监控中心",
    page_icon=":material/monitoring:",
    layout="wide",
)

apply_newsroom_style()
render_topbar("运行监控")
st.caption("AGENT OPERATIONS CENTER")
st.title("智能体运行监控中心")
st.caption("查看世界杯新闻智能体的运行轨迹、模型调用、Token 消耗、RAG 检索和多 Agent 协作过程。")

for key, default in {
    "monitor_selected_run_id": None,
    "monitor_run_list": [],
    "monitor_replay_active": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

query_run_id = st.query_params.get("run_id")
if isinstance(query_run_id, list):
    query_run_id = query_run_id[0] if query_run_id else None
if query_run_id:
    st.session_state["monitor_selected_run_id"] = query_run_id


def _chart(factory, *args, empty_message="此图表暂无数据"):
    try:
        figure = factory(*args)
        if figure is None:
            st.info(empty_message)
        else:
            st.plotly_chart(
                figure,
                width="stretch",
                theme="streamlit",
                config={"displayModeBar": False},
            )
    except Exception:
        st.warning("此图表数据暂不可用")


def _csv_bytes(records) -> bytes:
    rows = [dataclasses.asdict(record) for record in records]
    if not rows:
        return b""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return sanitize_text(output.getvalue()).encode("utf-8-sig")


def _json_bytes(payload) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return sanitize_text(text).encode("utf-8")


with st.sidebar:
    render_brand()
    st.page_link("app.py", label="首页 / AI 编辑台", icon=":material/home:")
    st.page_link(
        "pages/04_Match_Center.py",
        label="赛事档案",
        icon=":material/sports_soccer:",
    )
    st.page_link(
        "pages/05_History.py",
        label="历史记录",
        icon=":material/history:",
    )
    st.page_link(
        "pages/01_Knowledge_Base.py",
        label="知识库",
        icon=":material/database:",
    )
    st.page_link(
        "pages/06_Settings.py",
        label="设置",
        icon=":material/settings:",
    )
    st.subheader("筛选条件")
    date_range = st.date_input(
        "日期范围",
        value=(date.today() - timedelta(days=30), date.today()),
    )
    statuses = st.multiselect(
        "运行状态",
        ["全部", "success", "failed", "running", "cancelled"],
        default=["全部"],
    )
    task_types = ["全部", *DEFAULT_TRACE_STORE.get_distinct_task_types()]
    task_type = st.selectbox("任务类型", task_types)
    model_names = DEFAULT_TRACE_STORE.get_distinct_model_names()
    selected_models = st.multiselect("使用模型", model_names)
    exact_run_id = st.text_input("Run ID 精确查找")
    limit = st.slider("最大显示记录数", 10, 200, 50)
    if st.button("刷新数据", width="stretch"):
        st.session_state["monitor_run_list"] = []
        st.rerun()
    render_sidebar_user()

if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = end_date = date_range

if exact_run_id.strip():
    exact_run = DEFAULT_TRACE_STORE.get_run(exact_run_id.strip())
    runs = [exact_run] if exact_run else []
else:
    runs = DEFAULT_TRACE_STORE.list_runs(
        start_date=f"{start_date.isoformat()}T00:00:00",
        end_date=f"{end_date.isoformat()}T23:59:59",
        task_type=None if task_type == "全部" else task_type,
        limit=limit,
    )
    if statuses and "全部" not in statuses:
        runs = [run for run in runs if run.status in statuses]
    if selected_models:
        required_models = set(selected_models)
        runs = [
            run
            for run in runs
            if required_models
            <= {
                call.model_name
                for call in DEFAULT_TRACE_STORE.get_run_model_calls(run.run_id)
            }
        ]

st.session_state["monitor_run_list"] = runs
if not runs:
    st.info("暂无智能体运行记录。请先在世界杯新闻助手页面执行一次任务。")
    st.stop()

run_ids = {run.run_id for run in runs}
selected_run_id = st.session_state.get("monitor_selected_run_id")
if selected_run_id not in run_ids:
    selected_run_id = runs[0].run_id
    st.session_state["monitor_selected_run_id"] = selected_run_id

current_run = DEFAULT_TRACE_STORE.get_run(selected_run_id)
stages = DEFAULT_TRACE_STORE.get_run_stages(selected_run_id)
model_calls = DEFAULT_TRACE_STORE.get_run_model_calls(selected_run_id)
retrieval_records = DEFAULT_TRACE_STORE.get_run_retrieval_records(selected_run_id)
events = DEFAULT_TRACE_STORE.get_run_agent_events(selected_run_id)
historical_runs = DEFAULT_TRACE_STORE.get_historical_metrics()

st.caption(f"当前 Run：`{selected_run_id}`")
if current_run.status == "running":
    st.info("本次运行仍在进行中，可使用“刷新数据”查看最新阶段。")
elif current_run.status == "failed":
    st.error(
        f"失败阶段：{current_run.error_stage or '未知'}；"
        f"{current_run.error_message or '无错误摘要'}"
    )

live_tokens = sum(call.total_tokens or 0 for call in model_calls)
live_elapsed = sum(stage.elapsed_seconds or 0 for stage in stages)
run_tokens = live_tokens if current_run.status == "running" else current_run.total_tokens
run_elapsed = (
    live_elapsed
    if current_run.status == "running" and current_run.total_elapsed_seconds is None
    else current_run.total_elapsed_seconds
)
coverage_values = [
    run.evidence_coverage
    for run in historical_runs
    if run.evidence_coverage is not None
]
historical_coverage = (
    sum(coverage_values) / len(coverage_values) if coverage_values else None
)
coverage_delta = (
    (current_run.evidence_coverage - historical_coverage) * 100
    if current_run.evidence_coverage is not None and historical_coverage is not None
    else None
)

row1 = st.columns(4)
row1[0].metric("总运行次数", len(runs))
row1[1].metric("成功率", f"{calculate_success_rate(runs):.1%}")
row1[2].metric(
    "当前 Run 总耗时",
    f"{run_elapsed:.2f} 秒" if run_elapsed is not None else "进行中",
)
row1[3].metric(
    "当前 Run 总 Token",
    f"{run_tokens:,}" if run_tokens is not None else "暂无数据",
)
row2 = st.columns(4)
row2[0].metric("LLM 调用次数", sum(call.call_type == "chat" for call in model_calls))
row2[1].metric("RAG 检索文档数", len(retrieval_records))
row2[2].metric("使用模型数", len({call.model_name for call in model_calls}))
row2[3].metric(
    "事实证据覆盖率",
    f"{current_run.evidence_coverage:.1%}"
    if current_run.evidence_coverage is not None
    else "暂无数据",
    delta=f"{coverage_delta:+.1f}%" if coverage_delta is not None else None,
)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔍 运行总览",
    "🤖 模型与 Token",
    "📚 RAG 检索",
    "📈 历史趋势",
    "💬 Agent 通信",
    "📋 运行记录",
])

with tab1:
    _chart(
        create_agent_sankey,
        events,
        stages,
        empty_message="Agent 通信数据不足，无法生成流程图",
    )
    st.subheader("执行阶段时间线")
    status_labels = {
        "success": "🟢 成功",
        "running": "🟡 运行中",
        "failed": "🔴 失败",
        "skipped": "⚪ 跳过",
        "pending": "⚪ 等待",
    }
    for stage in sorted(stages, key=lambda item: item.sequence):
        title = (
            f"{status_labels.get(stage.status, stage.status)} "
            f"{stage.agent_name} · {stage.stage_name}"
        )
        with st.expander(title):
            st.write(f"模型：{stage.model_name or '无'}")
            st.write(
                f"耗时：{stage.elapsed_seconds:.3f} 秒"
                if stage.elapsed_seconds is not None
                else "耗时：进行中"
            )
            st.write(f"Token：{stage.total_tokens:,}")
            st.write(f"时间：{stage.started_at} → {stage.ended_at or '进行中'}")
            if stage.output_summary:
                st.write(f"输出摘要：{stage.output_summary}")
            if stage.error_message:
                st.error(stage.error_message)

    if st.button(
        "▶ 回放 Agent 执行过程",
        disabled=st.session_state["monitor_replay_active"],
    ):
        st.session_state["monitor_replay_active"] = True
        placeholder = st.empty()
        progress = st.progress(0)
        ordered_stages = sorted(stages, key=lambda item: item.sequence)
        for index, stage in enumerate(ordered_stages, 1):
            placeholder.info(f"[运行中] {stage.stage_name}")
            time.sleep(min(max((stage.elapsed_seconds or 0) * 0.08, 0.25), 1.2))
            placeholder.success(
                f"[完成] {stage.stage_name} | "
                f"耗时 {stage.elapsed_seconds or 0:.2f}s | Token {stage.total_tokens}"
            )
            progress.progress(index / len(ordered_stages))
        st.session_state["monitor_replay_active"] = False
        st.success("Agent 执行过程回放完成。")

    _chart(create_agent_duration_bar, stages)
    _chart(create_agent_time_pie, stages)

with tab2:
    left, right = st.columns([3, 2])
    with left:
        _chart(create_model_token_bar, model_calls)
        _chart(create_input_output_token_bar, model_calls)
    with right:
        _chart(create_agent_token_pie, stages)
        _chart(create_call_type_pie, model_calls)

    sort_by = st.selectbox("调用明细排序", ["Total Tokens", "耗时（秒）"])
    call_rows = [{
        "Agent": call.agent_name,
        "Model": call.model_name,
        "Call Type": call.call_type,
        "Status": call.status,
        "Input Tokens": call.input_tokens,
        "Output Tokens": call.output_tokens,
        "Total Tokens": call.total_tokens,
        "耗时（秒）": call.elapsed_seconds,
        "开始时间": call.started_at,
    } for call in model_calls]
    call_rows.sort(
        key=lambda row: row.get(sort_by) or 0,
        reverse=True,
    )
    st.dataframe(call_rows, width="stretch", hide_index=True)

with tab3:
    left, right = st.columns([11, 9])
    with left:
        _chart(create_source_hit_bar, retrieval_records)
        _chart(create_top_k_relevance_bar, retrieval_records)
    with right:
        _chart(create_source_type_pie, retrieval_records)

    retrieval_rows = [{
        "排名": record.rank,
        "文档标题": record.document_title,
        "来源": record.source_name,
        "来源类型": record.source_type,
        "检索得分": record.retrieval_score,
        "Rerank 得分": record.rerank_score,
        "用于生成": bool(record.used_in_answer),
        "发布时间": record.published_at,
        "来源 URL": record.source_url,
    } for record in retrieval_records]
    st.dataframe(
        retrieval_rows,
        width="stretch",
        hide_index=True,
        column_config={"来源 URL": st.column_config.LinkColumn("来源 URL")},
    )
    for record in retrieval_records:
        with st.expander(f"#{record.rank or '-'} {record.document_title or '未命名文档'}"):
            st.write(record.chunk_preview or "无 chunk 预览")

with tab4:
    row1_left, row1_right = st.columns(2)
    with row1_left:
        _chart(create_token_history_line, historical_runs)
    with row1_right:
        _chart(create_duration_history_line, historical_runs)
    row2_left, row2_right = st.columns(2)
    with row2_left:
        _chart(create_evidence_coverage_line, historical_runs)
    with row2_right:
        _chart(create_retrieval_history_line, historical_runs)

    history_rows = [{
        "Run ID": run.run_id[:8],
        "完整 Run ID": run.run_id,
        "用户问题": safe_summary(run.user_query, 80),
        "任务类型": run.task_type,
        "开始时间": run.started_at,
        "状态": run.status,
        "总耗时": run.total_elapsed_seconds,
        "总 Token": run.total_tokens,
        "LLM 调用": run.llm_call_count,
        "检索文档数": run.retrieved_documents,
        "证据覆盖率": run.evidence_coverage,
        "图片数": run.generated_image_count,
    } for run in historical_runs]
    selection = st.dataframe(
        history_rows,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="monitor_history_table",
        column_config={"完整 Run ID": None},
    )
    if selection.selection.rows:
        selected_index = selection.selection.rows[0]
        selected = history_rows[selected_index]["完整 Run ID"]
        if selected != st.session_state["monitor_selected_run_id"]:
            st.session_state["monitor_selected_run_id"] = selected
            st.query_params["run_id"] = selected
            st.rerun()

with tab5:
    for event in sorted(events, key=lambda item: item.sequence):
        with st.container(border=True):
            st.markdown(f"**{event.from_agent} → {event.to_agent}**")
            st.caption(f"类型：{event.event_type} · 时间：{event.created_at}")
            st.write(event.content_summary)
    st.dataframe(
        [dataclasses.asdict(event) for event in events],
        width="stretch",
        hide_index=True,
    )

with tab6:
    st.subheader("当前 Run 阶段信息")
    st.dataframe(
        [dataclasses.asdict(stage) for stage in stages],
        width="stretch",
        hide_index=True,
    )
    if current_run.status == "failed":
        st.subheader("错误信息")
        st.error(
            f"{current_run.error_stage or '未知阶段'}："
            f"{current_run.error_message or '无错误摘要'}"
        )

    export_payload = {
        "run": dataclasses.asdict(current_run),
        "stages": [dataclasses.asdict(stage) for stage in stages],
        "model_calls": [dataclasses.asdict(call) for call in model_calls],
        "retrieval_records": [
            dataclasses.asdict(record) for record in retrieval_records
        ],
        "agent_events": [dataclasses.asdict(event) for event in events],
    }
    buttons = st.columns(4)
    buttons[0].download_button(
        "下载 Run JSON",
        _json_bytes(export_payload),
        file_name=f"run_{selected_run_id}.json",
        mime="application/json",
    )
    buttons[1].download_button(
        "下载模型调用 CSV",
        _csv_bytes(model_calls),
        file_name=f"model_calls_{selected_run_id}.csv",
        mime="text/csv",
    )
    buttons[2].download_button(
        "下载检索记录 CSV",
        _csv_bytes(retrieval_records),
        file_name=f"retrieval_{selected_run_id}.csv",
        mime="text/csv",
    )
    buttons[3].download_button(
        "下载历史运行 CSV",
        _csv_bytes(historical_runs),
        file_name="runs_history.csv",
        mime="text/csv",
    )
