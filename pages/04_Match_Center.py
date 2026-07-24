from datetime import date

import streamlit as st

from official_feed import load_official_headlines
from ui import apply_newsroom_style, render_page_sidebar, render_topbar


st.set_page_config(
    page_title="赛事档案",
    page_icon=":material/sports_soccer:",
    layout="wide",
)
apply_newsroom_style()
render_page_sidebar()
render_topbar("赛事档案")

st.caption("2026 WORLD CUP ARCHIVE")
st.title("赛事档案")
st.caption("世界杯已于 2026 年 7 月 19 日完结。这里仅展示 FIFA 官方动态和可核查的历史资料。")

view = st.segmented_control(
    "赛事视图",
    ["赛事概览", "历史资料", "球队入口", "官方入口"],
    default="赛事概览",
    label_visibility="collapsed",
)

if view == "赛事概览":
    overview, facts = st.columns([3, 2], gap="large")
    with overview:
        st.html(
            """
<a class="tournament-card" href="https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026">
  <div class="tournament-head">
    <span><b class="archive-badge">ARCHIVE</b>2026 FIFA WORLD CUP</span>
    <span>FIFA 官方</span>
  </div>
  <div class="tournament-state">
    <span>赛事状态</span>
    <strong>已完结</strong>
    <p>加拿大 · 墨西哥 · 美国</p>
  </div>
  <div class="tournament-actions"><span>2026.06.11 — 2026.07.19</span><span>打开 FIFA 赛事页　›</span></div>
</a>
"""
        )
    with facts:
        with st.container(border=True):
            st.subheader("赛事信息")
            st.markdown("**举办时间**　2026 年 6 月 11 日至 7 月 19 日")
            st.markdown("**举办地区**　加拿大、墨西哥、美国")
            st.markdown("**参赛规模**　48 支球队")
            st.caption("信息来源：FIFA 官方赛事页面")
            st.link_button(
                "查看完整赛程与赛果",
                "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/match-schedule-fixtures-results-teams-stadiums",
                icon=":material/open_in_new:",
                type="primary",
                width="stretch",
            )
            st.link_button(
                "查看最新官方报道",
                "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/news",
                icon=":material/article:",
                width="stretch",
            )

elif view == "历史资料":
    selected_date = st.date_input(
        "查看该日期及之前发布的资料",
        value=date(2026, 7, 19),
        min_value=date(2026, 6, 11),
        max_value=date.today(),
    )
    actions = st.container(horizontal=True, vertical_alignment="center")
    actions.caption("官方动态默认缓存 15 分钟，发布日期始终随内容展示。")
    if actions.button("重新同步", icon=":material/refresh:"):
        load_official_headlines.clear()
        st.toast("正在重新同步 FIFA 官方资料")
        st.rerun()

    with st.spinner("正在读取官方资料", show_time=True):
        feed = load_official_headlines(
            before=selected_date.isoformat(),
            limit=10,
        )
    st.caption(
        f"数据模式：{feed['mode']}　·　获取时间：{feed['retrieved_at']}"
    )
    if not feed["items"]:
        st.info("所选日期之前暂无本地或官方资料。")
    for index, item in enumerate(feed["items"]):
        with st.container(border=True, key=f"archive_item_{index}"):
            details, action = st.columns([5, 1], vertical_alignment="center")
            details.markdown(f"### {item['title']}")
            details.caption(
                f"{item['source_name']}　·　"
                f"{item.get('published_at') or '未标注发布日期'}"
            )
            action.link_button(
                "打开原文",
                item["url"],
                icon=":material/open_in_new:",
                width="stretch",
            )

elif view == "球队入口":
    teams = [
        ("阿根廷", "argentina"),
        ("巴西", "brazil"),
        ("法国", "france"),
        ("德国", "germany"),
        ("西班牙", "spain"),
        ("英格兰", "england"),
        ("加拿大", "canada"),
        ("墨西哥", "mexico"),
        ("美国", "usa"),
    ]
    columns = st.columns(3)
    for index, (name, slug) in enumerate(teams):
        with columns[index % 3].container(border=True):
            st.markdown(f"### {name}")
            st.caption("FIFA 官方球队档案、阵容、赛程与报道")
            st.link_button(
                "打开球队档案",
                "https://www.fifa.com/en/tournaments/mens/worldcup/"
                f"canadamexicousa2026/teams/{slug}",
                icon=":material/open_in_new:",
                width="stretch",
            )

else:
    links = [
        (
            "FIFA 2026 世界杯主页",
            "赛事概览、球队、视频与官方报道",
            "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026",
        ),
        (
            "完整赛程与赛果",
            "按日期查看正式比赛安排及结果",
            "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/match-schedule-fixtures-results-teams-stadiums",
        ),
        (
            "世界杯新闻中心",
            "FIFA 发布的最新赛事和赛后报道",
            "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/news",
        ),
    ]
    for title, copy, url in links:
        with st.container(border=True):
            content, action = st.columns([4, 1], vertical_alignment="center")
            content.markdown(f"### {title}")
            content.caption(copy)
            action.link_button(
                "访问官方页面",
                url,
                icon=":material/open_in_new:",
                width="stretch",
            )
