import streamlit as st

from background_jobs import get_job, start_knowledge_update_job
from config import load_settings
from knowledge_base import KnowledgeBase
from rag_sources import SOURCES
from ui import apply_newsroom_style, render_page_sidebar, render_topbar


st.set_page_config(
    page_title="世界杯知识库",
    page_icon=":material/database:",
    layout="wide",
)

apply_newsroom_style()
render_page_sidebar()
render_topbar("知识库")
st.caption("TRUSTED SOURCE LIBRARY")
st.title("世界杯知识库")
st.caption(
    "手动抓取可信白名单，清洗、去重、切分并调用硅基流动 Embedding API。"
    "数据库保存在 data/worldcup_knowledge.db。"
)

settings = load_settings()
database = KnowledgeBase()
status = database.status()

metrics = st.container(horizontal=True)
metrics.metric("文章", status["documents"])
metrics.metric("文本分段", status["chunks"])
metrics.metric("A级来源文章", status["level_a"])
metrics.metric("B级来源文章", status["level_b"])
st.caption(f"最后更新时间：{status['last_updated'] or '尚未更新'}")

st.session_state.setdefault("knowledge_update_job_id", "")
st.session_state.setdefault("knowledge_update_finalized", "")
current_job = (
    get_job(st.session_state.knowledge_update_job_id)
    if st.session_state.knowledge_update_job_id
    else None
)
running = bool(current_job and current_job["status"] == "running")

if st.button(
    "更新知识库",
    icon=":material/sync:",
    type="primary",
    disabled=running,
):
    missing = [
        name
        for name, value in {
            "SILICONFLOW_API_KEY": settings.api_key,
            "EMBEDDING_MODEL": settings.embedding_model,
            "CHAT_MODEL": settings.chat_model,
        }.items()
        if not value.strip()
    ]
    if missing:
        st.error("请先在 .env 中配置：" + "、".join(missing))
    else:
        st.session_state.knowledge_update_job_id = start_knowledge_update_job(settings)
        st.session_state.knowledge_update_finalized = ""
        st.rerun()


@st.fragment(run_every=1.0 if running else None)
def render_update_progress() -> None:
    job_id = st.session_state.knowledge_update_job_id
    if not job_id:
        return
    job = get_job(job_id)
    if not job:
        st.error("后台更新记录已失效，请重新更新。")
        return
    if job["status"] == "running":
        with st.status("知识库正在后台更新", expanded=True):
            for event in job["events"][-12:]:
                icon = {
                    "running": ":material/progress_activity:",
                    "completed": ":material/check_circle:",
                    "failed": ":material/error:",
                }.get(event["state"], ":material/info:")
                st.write(f"{icon} {event['message']}")
        st.caption("可以切换到其他页面，更新任务不会中断。")
        return
    if job["status"] == "failed":
        st.error(job["error"])
    else:
        if st.session_state.knowledge_update_finalized != job_id:
            st.session_state.knowledge_update_finalized = job_id
            st.rerun()
        result = job["result"]
        st.success("知识库更新完成")
        result_metrics = st.container(horizontal=True)
        result_metrics.metric("新增", result["new"])
        result_metrics.metric("更新", result["updated"])
        result_metrics.metric("跳过", result["skipped"])
        result_metrics.metric("失败", result["failed"])


render_update_progress()

st.divider()
st.subheader("中英文来源白名单")
st.dataframe(
    [
        {
            "等级": source.level,
            "来源": source.name,
            "语言": source.language,
            "主要用途": source.purpose,
            "入口": source.seed_url,
        }
        for source in SOURCES
    ],
    hide_index=True,
    width="stretch",
    column_config={"入口": st.column_config.LinkColumn("入口")},
)
