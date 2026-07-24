from datetime import datetime

import streamlit as st


def apply_newsroom_style(max_width: int = 1480) -> None:
    st.html(
        f"""
<style>
:root {{
  --news-ink: #172724;
  --news-muted: #6f7772;
  --news-green: #0b2f2b;
  --news-green-2: #1c5a52;
  --news-gold: #c7a96b;
  --news-paper: #f4f0e8;
  --news-card: rgba(255, 255, 255, .72);
  --news-line: rgba(16, 42, 37, .12);
  --news-shadow: 0 14px 40px rgba(28, 49, 42, .08);
}}
.stApp {{
  background:
    radial-gradient(circle at 82% 8%, rgba(199, 169, 107, .12), transparent 28rem),
    radial-gradient(circle at 20% 72%, rgba(28, 90, 82, .06), transparent 32rem),
    var(--news-paper);
}}
[data-testid="stMainBlockContainer"] {{
  max-width: {max_width}px;
  padding: 1.2rem 2.2rem 7rem;
}}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{
  background:
    radial-gradient(circle at 20% 85%, rgba(199, 169, 107, .10), transparent 17rem),
    var(--news-green);
  border-right: 0;
}}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
  padding-top: 1.1rem;
}}
[data-testid="stSidebarNav"] {{ display: none; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(255, 255, 255, .12); }}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
  color: #f5f6ef;
}}
[data-testid="stSidebar"] a {{ color: #edf4ec; }}
[data-testid="stSidebar"] .stButton button {{
  border-color: rgba(255, 255, 255, .14);
  background: rgba(255, 255, 255, .06);
  color: #f7f7f2;
}}
[data-testid="stSidebar"] .stButton button:hover {{
  border-color: var(--news-gold);
  background: rgba(215, 239, 85, .12);
  color: var(--news-gold);
}}
[data-testid="stSidebar"] .stButton button[kind="primary"] {{
  background: var(--news-gold);
  color: var(--news-green);
  border-color: var(--news-gold);
}}
h1, h2, h3 {{
  color: var(--news-ink);
  letter-spacing: -.035em;
}}
.news-brand {{
  display: flex;
  align-items: center;
  gap: .8rem;
  padding: .35rem 0 1.25rem;
  color: white;
}}
.news-brand-mark {{
  display: grid;
  place-items: center;
  width: 2.8rem;
  height: 2.8rem;
  border: 2px solid var(--news-gold);
  border-radius: 50%;
  color: var(--news-gold);
  font-size: 1.35rem;
}}
.news-brand strong {{ display: block; font-size: 1.12rem; }}
.news-brand span {{
  color: var(--news-gold);
  font-size: .62rem;
  letter-spacing: .24em;
}}
.news-user {{
  margin-top: 1.2rem;
  padding: 1rem 0 .2rem;
  border-top: 1px solid rgba(255, 255, 255, .12);
  color: #f6f7ef;
}}
.news-user b {{ display: block; }}
.news-user span {{ color: #8ee6a5; font-size: .78rem; }}
.news-topbar {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  min-height: 3rem;
  margin-bottom: 1.35rem;
  padding: 0 6rem 1rem 0;
  border-bottom: 1px solid var(--news-line);
  color: #43524d;
  font-size: .84rem;
}}
.news-topbar-right {{ display: flex; gap: 1.3rem; align-items: center; }}
.news-status-dot {{
  display: inline-block;
  width: .52rem;
  height: .52rem;
  margin-right: .4rem;
  border-radius: 50%;
  background: #23a447;
  box-shadow: 0 0 0 4px rgba(35, 164, 71, .10);
}}
.news-status-dot.warning {{ background: #e59a23; }}
.news-hero {{
  padding: 2.1rem .2rem 1.5rem;
}}
.news-kicker {{
  color: #6d9b2e;
  font-size: .78rem;
  font-weight: 800;
  letter-spacing: .17em;
  text-transform: uppercase;
}}
.news-hero h1 {{
  margin: .8rem 0 .8rem;
  max-width: 47rem;
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: clamp(2.45rem, 4.6vw, 4.7rem);
  line-height: 1.08;
}}
.news-hero h1 em {{
  position: relative;
  color: inherit;
  font-style: normal;
  white-space: nowrap;
}}
.news-hero h1 em::after {{
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -.16rem;
  height: .38rem;
  border-radius: 50%;
  background: var(--news-gold);
  z-index: -1;
}}
.news-hero p {{
  max-width: 43rem;
  color: var(--news-muted);
  font-size: 1rem;
  line-height: 1.8;
}}
.tournament-card {{
  position: relative;
  display: block;
  min-height: 325px;
  overflow: hidden;
  padding: 1.55rem;
  border: 1px solid rgba(255,255,255,.14);
  border-radius: 26px;
  color: white !important;
  text-decoration: none !important;
  background:
    radial-gradient(circle at 82% 22%, rgba(199,169,107,.24), transparent 13rem),
    linear-gradient(150deg, #173f3a 0%, #0b2f2b 60%, #071f1d 100%);
  box-shadow: 0 22px 54px rgba(9, 40, 34, .18);
  transition: transform .2s ease, box-shadow .2s ease;
}}
.tournament-card::after {{
  content: "";
  position: absolute;
  right: -9%;
  bottom: -38%;
  width: 62%;
  height: 78%;
  border: 1px solid rgba(199,169,107,.22);
  border-radius: 50%;
}}
.tournament-card:hover {{
  transform: translateY(-4px);
  box-shadow: 0 27px 60px rgba(9, 40, 34, .24);
}}
.tournament-head, .tournament-state, .tournament-actions {{
  position: relative;
  z-index: 1;
}}
.tournament-head {{
  display: flex;
  justify-content: space-between;
  font-size: .78rem;
}}
.archive-badge {{
  display: inline-block;
  margin-right: .55rem;
  padding: .25rem .48rem;
  border-radius: 7px;
  color: #102a25;
  background: var(--news-gold);
  font-weight: 800;
}}
.tournament-state {{
  margin: 3.2rem 0 2.5rem;
}}
.tournament-state span {{
  display: block;
  color: #bfcac5;
  font-size: .75rem;
  letter-spacing: .12em;
}}
.tournament-state strong {{
  display: block;
  margin: .3rem 0 .4rem;
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 3.2rem;
}}
.tournament-state p {{ margin: 0; color: #d8dfdb; }}
.tournament-actions {{
  display: flex;
  justify-content: space-between;
  padding-top: 1rem;
  border-top: 1px solid rgba(255,255,255,.13);
  color: #dfe8e1;
  font-size: .78rem;
}}
.news-section-title {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 1.7rem 0 .8rem;
}}
.news-section-title strong {{ color: var(--news-ink); font-size: 1.05rem; }}
.news-section-title span {{ color: var(--news-muted); font-size: .78rem; }}
[class*="st-key-quick_"] [data-testid="stVerticalBlockBorderWrapper"] {{
  min-height: 175px;
  background: var(--news-card);
  border-color: var(--news-line);
  border-radius: 19px;
  box-shadow: var(--news-shadow);
  transition: transform .2s ease, border-color .2s ease;
}}
[class*="st-key-quick_"] [data-testid="stVerticalBlockBorderWrapper"]:hover {{
  transform: translateY(-4px);
  border-color: rgba(20, 90, 74, .32);
}}
.quick-icon {{
  display: grid;
  place-items: center;
  width: 2.55rem;
  height: 2.55rem;
  border-radius: 12px;
  color: var(--news-green);
  background: var(--news-gold);
  font-size: 1.2rem;
  font-weight: 800;
}}
.quick-title {{ margin: .75rem 0 .15rem; color: var(--news-ink); font-weight: 800; }}
.quick-copy {{ min-height: 2.5rem; color: var(--news-muted); font-size: .79rem; line-height: 1.55; }}
[data-testid="stChatInput"] {{
  border-color: rgba(20, 90, 74, .28);
  border-radius: 18px;
  box-shadow: 0 15px 45px rgba(28, 49, 42, .12);
}}
[data-testid="stChatMessage"] {{
  border-radius: 18px;
  border-color: var(--news-line);
  background: rgba(255,255,255,.62);
}}
.history-row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: .8rem 0;
  border-bottom: 1px solid var(--news-line);
}}
.history-row a {{
  color: var(--news-ink) !important;
  font-weight: 700;
  text-decoration: none !important;
}}
.history-row span {{ color: var(--news-muted); font-size: .78rem; }}
.fade-in {{ animation: newsroom-fade .3s ease both; }}
@keyframes newsroom-fade {{
  from {{ opacity: 0; transform: translateY(5px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
@media (max-width: 900px) {{
  [data-testid="stMainBlockContainer"] {{ padding: .8rem 1rem 6.5rem; }}
  .news-topbar-right span:nth-child(2) {{ display: none; }}
  .news-topbar {{ padding-right: 3.5rem; }}
  .news-hero {{ padding-top: .7rem; }}
  .tournament-card {{ min-height: 290px; }}
}}
</style>
"""
    )


def render_brand() -> None:
    st.html(
        """
<div class="news-brand">
  <div class="news-brand-mark">⚽</div>
  <div><strong>世界杯新闻助手</strong><span>AI NEWSROOM</span></div>
</div>
"""
    )


def render_topbar(_section: str, configured: bool = True) -> None:
    now = datetime.now().strftime("%Y年%m月%d日　%H:%M")
    status = "正常" if configured else "待配置"
    status_class = "" if configured else " warning"
    st.html(
        f"""
<div class="news-topbar fade-in">
  <span>▣　{now}</span>
  <div class="news-topbar-right">
    <span><i class="news-status-dot{status_class}"></i>模型状态：{status}</span>
    <span>◷　官方动态：15 分钟同步</span>
  </div>
</div>
"""
    )


def render_sidebar_user() -> None:
    st.html('<div class="news-user"><b>编辑部</b><span>● 在线</span></div>')


def render_page_sidebar() -> None:
    with st.sidebar:
        render_brand()
        st.page_link(
            "app.py",
            label="新建工作",
            icon=":material/add:",
        )
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
            "pages/02_Agent_Monitor.py",
            label="运行监控",
            icon=":material/monitoring:",
        )
        st.page_link(
            "pages/06_Settings.py",
            label="设置",
            icon=":material/settings:",
        )
        render_sidebar_user()
