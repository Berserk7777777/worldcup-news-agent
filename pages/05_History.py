import json
from pathlib import Path
from urllib.parse import quote

import streamlit as st

from ui import apply_newsroom_style, render_page_sidebar, render_topbar


st.set_page_config(
    page_title="历史记录",
    page_icon=":material/history:",
    layout="wide",
)
apply_newsroom_style()
render_page_sidebar()
render_topbar("历史记录")

st.caption("NEWSROOM ARCHIVE")
st.title("历史记录")
st.caption("查找已生成的新闻、创作结果和分析记录。")

query = st.text_input(
    "搜索记录",
    placeholder="输入新闻标题或创作主题",
    icon=":material/search:",
)

records = []
for run_dir in sorted(Path("outputs").glob("*"), reverse=True):
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        continue
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    reviewer = payload.get("reviewer_result", {})
    user_input = payload.get("user_input", {})
    title = reviewer.get("final_title") or user_input.get("topic") or run_dir.name
    if query and query.lower() not in title.lower():
        continue
    records.append(
        {
            "run": run_dir.name,
            "title": title,
            "type": user_input.get("news_type", "新闻"),
            "created": payload.get("created_at", run_dir.name),
        }
    )

if not records:
    st.info("没有找到历史记录。完成一次新闻创作后，结果会自动显示在这里。")
    if st.button("开始第一篇创作", type="primary", icon=":material/edit_note:"):
        st.session_state.app_mode = "新闻创作"
        st.session_state.previous_app_mode = "新闻创作"
        st.switch_page("app.py")
else:
    st.caption(f"共 {len(records)} 条记录")
    for index, record in enumerate(records):
        with st.container(border=True, key=f"history_{index}"):
            title, action = st.columns([5, 1], vertical_alignment="center")
            title.markdown(f"### {record['title']}")
            title.caption(f"{record['type']}　·　{record['created']}")
            action.link_button(
                "查看详情",
                url=f"./News_Detail?run={quote(record['run'])}",
                icon=":material/arrow_forward:",
                width="stretch",
            )
