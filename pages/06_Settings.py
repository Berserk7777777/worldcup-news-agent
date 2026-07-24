import streamlit as st

from config import get_missing_configs, load_settings
from ui import apply_newsroom_style, render_page_sidebar, render_topbar


st.set_page_config(
    page_title="系统设置",
    page_icon=":material/settings:",
    layout="wide",
)
apply_newsroom_style()
render_page_sidebar()

settings = load_settings()
missing = get_missing_configs(settings)
render_topbar("系统设置", configured=not missing)

st.caption("NEWSROOM SETTINGS")
st.title("系统设置")
st.caption("检查模型连接，并设置当前浏览会话的编辑偏好。密钥不会在页面中显示。")

status, preferences = st.columns([3, 2], gap="large")
with status:
    st.subheader("模型与服务")
    rows = [
        ("快速对话", settings.chat_model),
        ("新闻策划", settings.planner_model),
        ("新闻写作", settings.writer_model),
        ("独立审校", settings.reviewer_model),
        ("图片生成", settings.image_backend_label),
        ("知识检索", settings.embedding_model),
    ]
    for label, model in rows:
        with st.container(border=True):
            left, right = st.columns([1, 3], vertical_alignment="center")
            left.markdown(f"**{label}**")
            right.code(model or "未配置", language=None)
    if missing:
        st.warning("仍需在 .env 中配置：" + "、".join(missing))
    else:
        st.success("全部必要服务已配置。", icon=":material/check_circle:")

with preferences:
    st.subheader("编辑偏好")
    st.toggle("自动保存创作记录", value=True, key="setting_auto_save")
    st.toggle("生成完成后显示通知", value=True, key="setting_notify")
    st.selectbox(
        "默认工作模式",
        ["AI 对话", "新闻创作"],
        key="setting_default_mode",
    )
    st.selectbox(
        "界面密度",
        ["舒适", "紧凑"],
        key="setting_density",
    )
    if st.button(
        "保存偏好",
        type="primary",
        icon=":material/save:",
        width="stretch",
    ):
        st.toast("偏好已保存到当前会话")

    if st.button(
        "重新检测配置",
        icon=":material/refresh:",
        width="stretch",
    ):
        st.toast("配置状态已刷新")
        st.rerun()
