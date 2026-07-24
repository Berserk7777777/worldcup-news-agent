import base64
import html
import json
from pathlib import Path
from urllib.parse import quote

import streamlit as st

from background_jobs import (
    get_job,
    start_chat_job,
    start_image_job,
    start_midjourney_action_job,
    start_news_job,
)
from config import get_missing_configs, load_settings
from midjourney_service import validate_reference_image_url
from news_images import (
    IMAGE_PLACEMENTS,
    IMAGE_USAGES,
    PLACEMENT_LABELS,
    uses_midjourney_reference,
    uses_source_image,
)
from schemas import UserInput
from utils import extract_urls, requested_image_count, should_start_image_only_job


st.set_page_config(
    page_title="世界杯新闻助手",
    page_icon=":material/sports_soccer:",
    layout="centered",
)

st.markdown(
    """
<style>
:root {
  --ink: #18352b;
  --muted: #68776f;
  --pitch: #0f6b4f;
  --lime: #d8e862;
  --paper: #fbfaf5;
  --line: rgba(24, 53, 43, 0.14);
}
.stApp {
  background:
    radial-gradient(circle at 12% 0%, rgba(216, 232, 98, .20), transparent 28rem),
    radial-gradient(circle at 92% 15%, rgba(15, 107, 79, .12), transparent 34rem),
    var(--paper);
}
.block-container {
  max-width: 860px;
  padding-top: 2rem;
  padding-bottom: 8rem;
}
h1, h2, h3 {
  color: var(--ink);
  font-family: Georgia, "Noto Serif SC", serif;
  letter-spacing: -.025em;
}
.hero {
  min-height: 310px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 2.5rem 0 1rem;
}
.hero-kicker {
  color: var(--pitch);
  font-size: .82rem;
  font-weight: 700;
  letter-spacing: .16em;
  text-transform: uppercase;
}
.hero h1 {
  margin: .65rem 0 .4rem;
  font-size: clamp(2.2rem, 7vw, 4.4rem);
  line-height: 1.02;
}
.hero p {
  color: var(--muted);
  font-size: 1.05rem;
  max-width: 35rem;
}
.result-cover {
  display: block;
  overflow: hidden;
  border-radius: 22px;
  border: 1px solid var(--line);
  box-shadow: 0 16px 44px rgba(24, 53, 43, .13);
  margin: .7rem 0 1rem;
}
.result-cover img {
  display: block;
  width: 100%;
  max-height: 430px;
  object-fit: cover;
  transition: transform .35s ease;
}
.result-cover:hover img { transform: scale(1.018); }
.result-link {
  display: inline-block;
  color: var(--pitch);
  font-weight: 700;
  text-decoration: none;
  margin: .35rem 0 .8rem;
}
.result-link:hover { text-decoration: underline; }
.mode-notice {
  width: fit-content;
  margin: .7rem auto;
  padding: .35rem .8rem;
  border-radius: 999px;
  background: rgba(15, 107, 79, .08);
  color: var(--muted);
  font-size: .82rem;
}
[data-testid="stChatMessage"] {
  width: fit-content;
  max-width: 92%;
  border: 0;
  background: transparent;
  padding: .35rem 0;
  box-shadow: none;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  margin-left: auto;
  padding: .75rem 1rem;
  border-radius: 22px 22px 6px 22px;
  background: #eaf1ff;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  margin-right: auto;
}
[data-testid="stChatMessageAvatarUser"] {
  display: none;
}
[data-testid="stChatMessageContent"] {
  min-width: 0;
}
[data-testid="stChatInput"] {
  border-color: rgba(15, 107, 79, .28);
  box-shadow: 0 12px 34px rgba(24, 53, 43, .11);
}
[data-testid="stSidebar"] {
  background: #173b30;
}
[data-testid="stSidebar"] * {
  color: #f4f1e7;
}
[data-testid="stSidebarNav"] { display: none; }
[data-testid="stSidebar"] .stButton button {
  background: var(--lime);
  color: #173b30;
  border: 0;
}
[data-testid="stSidebar"] .stButton button * { color: #173b30; }
[data-testid="stSidebar"] a:hover {
  color: var(--lime);
}
@media (max-width: 700px) {
  .block-container { padding-top: 1rem; }
  .hero { min-height: 260px; padding-top: 1rem; }
}
</style>
""",
    unsafe_allow_html=True,
)


APP_MODES = ["对话", "新闻创作"]
REPORTING_MODES = ["真实报道", "AI模拟报道"]
NEWS_TYPES = ["自动判断", "赛事战报", "球员人物特写", "赛场精彩瞬间", "赛况总结", "世界杯与城市经济", "其他"]
WRITING_STYLES = ["自动判断", "正式体育新闻", "新媒体新闻报道", "人物故事", "城市观察", "简洁客观报道"]
IMAGE_STYLES = ["体育新闻摄影", "赛事宣传海报", "城市纪实摄影", "电影感体育画面", "简洁新媒体头图"]
CHAT_SUGGESTIONS = {
    "你能做什么": "你能帮我做什么？",
    "了解2026世界杯": "请简单介绍一下2026世界杯。",
    "聊聊足球": "我们来聊聊足球吧。",
}
NEWS_SUGGESTIONS = {
    "主办城市经济": "写一篇关于2026世界杯对主办城市旅游和消费影响的新闻。",
    "球员人物故事": "根据我接下来提供的资料，写一篇2026世界杯球员人物特写。",
    "比赛战报": "帮我整理一篇2026世界杯比赛战报，请告诉我还需要补充哪些事实。",
}

for key, default in {
    "messages": [],
    "app_mode": "对话",
    "previous_app_mode": "对话",
    "workflow_result": None,
    "reporting_mode": "真实报道",
    "news_type": "自动判断",
    "audience": "普通球迷和关注世界杯的公众",
    "writing_style": "自动判断",
    "image_style": "体育新闻摄影",
    "image_count": 1,
    "image_usage": "图片作为新闻资料",
    "midjourney_reference_url": "",
    "midjourney_image_weight": 1.5,
    "source_image_caption": "",
    "source_image_credit": "",
    "source_image_url": "",
    "source_image_placement": "after_lead",
    "include_uploaded_image": True,
    "extra_facts": "",
    "news_task_active": False,
    "news_start_index": 0,
}.items():
    st.session_state.setdefault(key, default)

if st.session_state.get("image_count") not in {1, 2}:
    st.session_state.image_count = 1
if st.session_state.get("image_usage") not in IMAGE_USAGES:
    st.session_state.image_usage = IMAGE_USAGES[0]
if not isinstance(st.session_state.get("midjourney_image_weight"), (int, float)):
    st.session_state.midjourney_image_weight = 1.5
if st.session_state.get("source_image_placement") not in PLACEMENT_LABELS:
    st.session_state.source_image_placement = "after_lead"


def reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.workflow_result = None
    st.session_state.app_mode = "对话"
    st.session_state.previous_app_mode = "对话"
    st.session_state.news_task_active = False
    st.session_state.news_start_index = 0


def announce_mode_change() -> None:
    previous = st.session_state.previous_app_mode
    current = st.session_state.app_mode
    if previous == current:
        return
    continuing = any(
        item.get("mode") == previous
        and item.get("job_id")
        and (get_job(item["job_id"]) or {}).get("status") == "running"
        for item in st.session_state.messages
    )
    suffix = "，原任务将继续在后台运行" if continuing else ""
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": f"已由「{previous}」切换为「{current}」{suffix}",
            "mode": current,
            "notice": True,
        }
    )
    st.session_state.previous_app_mode = current


def recent_runs(limit: int = 8) -> list[dict]:
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
        records.append(
            {
                "run": run_dir.name,
                "title": reviewer.get("final_title") or payload.get("user_input", {}).get("topic") or run_dir.name,
            }
        )
        if len(records) >= limit:
            break
    return records


def image_path_for(item, run_dir: Path | None = None) -> Path | None:
    raw_path = item.local_path if hasattr(item, "local_path") else item.get("local_path", "")
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.exists():
        return path
    if run_dir:
        candidate = run_dir / path.name
        if candidate.exists():
            return candidate
    return None


def clickable_cover(path: Path, title: str, run_name: str) -> None:
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    href = f"./News_Detail?run={quote(run_name)}"
    st.html(
        f'<a class="result-cover" href="{href}" title="打开新闻详情">'
        f'<img src="data:{mime};base64,{encoded}" alt="{html.escape(title)}"></a>'
    )


def render_sources(factual_material: str, sources: list | None = None) -> None:
    if sources:
        st.markdown("**检索来源**")
        for index, source in enumerate(sources, 1):
            date = source.get("published_at") or "未标注日期"
            st.markdown(
                f"{index}. **{source.get('source_level', 'B')}级** "
                f"{source['source_name']}，《{source['document_title']}》，"
                f"{date}，[原始链接]({source['source_url']})"
            )
        return
    urls = extract_urls(factual_material)
    st.markdown("**来源**")
    if not urls:
        st.caption("当前材料未包含可点击的网址；接入 RAG 后将在这里显示检索来源。")
        return
    for index, url in enumerate(urls, 1):
        st.markdown(f"{index}. [打开原始来源]({url})")


def render_midjourney_jobs(result: dict) -> bool:
    jobs = result.get("midjourney_jobs", [])
    if not jobs:
        return False

    action_job_id = result.get("_midjourney_action_job_id")
    if action_job_id:
        action_job = get_job(action_job_id)
        if action_job and action_job["status"] == "running":
            with st.status("MidJourney 正在处理作者选择", expanded=True):
                events = action_job.get("events", [])
                if not events:
                    st.write(":material/progress_activity: 正在提交操作")
                for event in events:
                    icon = {
                        "running": ":material/progress_activity:",
                        "completed": ":material/check_circle:",
                        "failed": ":material/error:",
                    }.get(event["state"], ":material/info:")
                    st.write(f"{icon} {event['message']}")
            return True
        if action_job and action_job["status"] == "completed":
            updated = action_job["result"]
            result.clear()
            result.update(updated)
            st.rerun()
        if action_job:
            result["_midjourney_action_error"] = action_job.get("error", "操作失败")
        else:
            result["_midjourney_action_error"] = "后台任务记录已失效，请重新选择"
        result.pop("_midjourney_action_job_id", None)

    if result.get("_midjourney_action_error"):
        st.error(result["_midjourney_action_error"])

    st.markdown("#### MidJourney 图片选择")
    st.caption("作者可以直接选择 U1-U4 放大，或选择 V1-V4 生成对应构图的新四宫格。")
    for job_index, job in enumerate(result.get("midjourney_jobs", [])):
        with st.container(border=True):
            st.caption(f"任务 {job.get('job_id', '')} · {job.get('status', 'PENDING')}")
            final_media = job.get("final_image_local_path") or job.get("final_image_url")
            if final_media:
                st.image(final_media, caption="作者已确认的 MidJourney 图片", width="stretch")
                st.success(f"已完成 {job.get('requested_action') or '图片选择'}")
                continue

            candidates = job.get("candidates", [])
            allowed_labels = {f"U{i}" for i in range(1, 5)} | {
                f"V{i}" for i in range(1, 5)
            }
            available_actions = {
                str(item.get("label", "")).upper(): item
                for item in job.get("actions", [])
                if str(item.get("label", "")).upper() in allowed_labels
            }
            if candidates:
                columns = st.columns(2)
                for candidate_index, candidate in enumerate(candidates):
                    with columns[candidate_index % 2]:
                        media = candidate.get("local_path") or candidate.get("source_url")
                        if media:
                            st.image(
                                media,
                                caption=candidate.get("label", f"候选 {candidate_index + 1}"),
                                width="stretch",
                            )
                        if not available_actions and st.button(
                            "采用此候选",
                            key=f"accept-mj-{job.get('job_id')}-{candidate_index}",
                            icon=":material/check:",
                            width="stretch",
                        ):
                            result["_midjourney_action_job_id"] = start_midjourney_action_job(
                                settings,
                                result,
                                job_index,
                                f"ACCEPT_{candidate_index + 1}",
                            )
                            result.pop("_midjourney_action_error", None)
                            st.rerun()
            else:
                grid_media = job.get("grid_local_path") or job.get("grid_url")
                if grid_media:
                    st.image(grid_media, caption="MidJourney 四宫格", width="stretch")
                else:
                    st.info("TTAPI 已创建任务，暂未返回可显示的四宫格")

            if available_actions:
                st.caption("U：放大并作为最终候选；V：围绕对应象限生成下一组变体。")
                upscale_columns = st.columns(4)
                for index in range(1, 5):
                    label = f"U{index}"
                    if label not in available_actions:
                        continue
                    if upscale_columns[index - 1].button(
                        label,
                        key=f"mj-{job.get('job_id')}-{label}",
                        icon=":material/zoom_in:",
                        width="stretch",
                    ):
                        result["_midjourney_action_job_id"] = start_midjourney_action_job(
                            settings, result, job_index, label
                        )
                        result.pop("_midjourney_action_error", None)
                        st.rerun()
                variation_columns = st.columns(4)
                for index in range(1, 5):
                    label = f"V{index}"
                    if label not in available_actions:
                        continue
                    if variation_columns[index - 1].button(
                        label,
                        key=f"mj-{job.get('job_id')}-{label}",
                        icon=":material/auto_awesome:",
                        width="stretch",
                    ):
                        result["_midjourney_action_job_id"] = start_midjourney_action_job(
                            settings, result, job_index, label
                        )
                        result.pop("_midjourney_action_error", None)
                        st.rerun()
            elif not candidates:
                st.warning("当前 TTAPI 响应没有 U1-U4/V1-V4 Action ID，请核对 Fetch 响应字段。")
    return True


def render_result(result: dict) -> None:
    reviewer = result.get("reviewer_result", {})
    writer = result.get("writer_result", {})
    images = result.get("images", [])
    run_dir = Path(result["run_dir"]) if result.get("run_dir") else None
    title = reviewer.get("final_title") or writer.get("title") or "新闻生成未完成"
    article = reviewer.get("final_article") or writer.get("full_article", "")

    if result.get("stop_reason"):
        st.warning(result["stop_reason"])
    if result.get("missing_facts"):
        st.info("还需要补充：" + "；".join(result["missing_facts"]))

    has_midjourney = render_midjourney_jobs(result)

    if run_dir and images and not has_midjourney:
        cover = image_path_for(images[0], run_dir)
        if cover:
            clickable_cover(cover, title, run_dir.name)
            st.caption("点击图片打开新闻详情页")

    if article:
        label = reviewer.get("final_article_label")
        if label:
            st.badge(label, color="blue")
        st.subheader(title)
        st.markdown(article)
        stored_input = result.get("user_input")
        factual_material = stored_input.factual_material if hasattr(stored_input, "factual_material") else ""
        render_sources(factual_material, result.get("sources"))

    if run_dir:
        href = f"./News_Detail?run={quote(run_dir.name)}"
        st.html(f'<a class="result-link" href="{href}">打开完整新闻详情 →</a>')

    run_id = result.get("monitor_run_id")
    if run_id:
        st.caption(f"[查看本次智能体运行记录](./Agent_Monitor?run_id={run_id})")


def render_image_result(result: dict) -> None:
    run_dir = Path(result["run_dir"])
    st.badge("AI生成图片", color="orange")
    st.caption("以下图片由AI生成，仅用于创意展示，不代表真实赛事影像。")
    has_midjourney = render_midjourney_jobs(result)
    if not has_midjourney:
        for item in result.get("images", []):
            path = image_path_for(item, run_dir)
            if path:
                clickable_cover(path, item.get("name", "AI生成图片"), run_dir.name)
    href = f"./News_Detail?run={quote(run_dir.name)}"
    st.html(f'<a class="result-link" href="{href}">打开图片详情 →</a>')


def render_running_job(job: dict) -> None:
    with st.chat_message("assistant"):
        events = job.get("events", [])
        if job["kind"] == "chat":
            if events:
                st.caption(events[-1]["message"])
            if job["output"]:
                st.markdown(job["output"] + " ▌")
            else:
                st.caption("正在思考，切换功能不会中断本次回答。")
            return

        label = "图片正在后台生成" if job["kind"] == "image" else "新闻任务正在后台执行"
        with st.status(label, expanded=True):
            if not events:
                preparing = "正在准备图片生成" if job["kind"] == "image" else "正在准备新闻创作"
                st.write(f":material/progress_activity: {preparing}")
            for event in events:
                icon = {
                    "running": ":material/progress_activity:",
                    "completed": ":material/check_circle:",
                    "failed": ":material/error:",
                }.get(event["state"], ":material/info:")
                st.write(f"{icon} {event['message']}")
        st.caption("可以切换到对话或其他页面，本任务会继续执行。")


def finish_job_message(message: dict, job: dict) -> None:
    if job["status"] == "failed":
        message["content"] = job["error"]
    elif job["kind"] == "chat":
        message["content"] = job["output"] or "模型未返回内容，请重试。"
    elif job["kind"] == "image":
        message["content"] = ""
        message["image_result"] = job["result"]
    else:
        result = job["result"]
        message["content"] = (
            "请补充下面的信息，我会继续完成这篇新闻。"
            if result.get("missing_facts")
            else ""
        )
        message["result"] = result
        st.session_state.workflow_result = result
        st.session_state["current_run_id"] = result.get("monitor_run_id")
        st.session_state.news_task_active = bool(result.get("missing_facts"))
    message.pop("job_id", None)


def render_message(message: dict) -> bool:
    if message.get("notice"):
        st.html(f'<div class="mode-notice">{html.escape(message["content"])}</div>')
        return False

    job_id = message.get("job_id")
    if job_id:
        job = get_job(job_id)
        if job and job["status"] == "running":
            render_running_job(job)
            return False
        if job:
            finish_job_message(message, job)
        else:
            message["content"] = "后台任务记录已失效，请重新发送。"
            message.pop("job_id", None)

    with st.chat_message(message["role"]):
        if message.get("image"):
            st.image(message["image"]["bytes"], caption=message["image"]["name"], width=260)
        if message.get("content"):
            st.markdown(message["content"])
        if message.get("image_result"):
            render_image_result(message["image_result"])
        if message.get("result"):
            render_result(message["result"])
    return bool(job_id)


def has_running_job(mode: str | None = None) -> bool:
    for message in st.session_state.messages:
        if mode and message.get("mode") != mode:
            continue
        job_id = message.get("job_id")
        if job_id and (get_job(job_id) or {}).get("status") == "running":
            return True
        nested_result = message.get("result") or message.get("image_result") or {}
        action_job_id = nested_result.get("_midjourney_action_job_id")
        if action_job_id and (get_job(action_job_id) or {}).get("status") == "running":
            return True
    return False


def build_user_input() -> UserInput:
    task_messages = st.session_state.messages[st.session_state.news_start_index :]
    user_messages = [
        item
        for item in task_messages
        if item["role"] == "user" and item.get("mode") == "新闻创作"
    ]
    first_request = user_messages[0]["content"] if user_messages else ""
    request_text = "\n".join(item.get("content", "") for item in user_messages)
    facts = [st.session_state.extra_facts.strip()]
    for item in user_messages:
        facts.append(item.get("content", ""))
        if item.get("image_analysis"):
            facts.append("上传图片分析结果：\n" + item["image_analysis"])
    news_type = st.session_state.news_type
    writing_style = st.session_state.writing_style
    image_usage = st.session_state.image_usage
    return UserInput(
        reporting_mode=st.session_state.reporting_mode,
        topic=first_request[:200],
        news_type="其他" if news_type == "自动判断" else news_type,
        audience=st.session_state.audience.strip() or "普通球迷和关注世界杯的公众",
        writing_style="简洁客观报道" if writing_style == "自动判断" else writing_style,
        factual_material="\n\n".join(item for item in facts if item),
        image_style=st.session_state.image_style,
        image_count=requested_image_count(request_text, st.session_state.image_count),
        image_usage=image_usage,
        midjourney_reference_url=(
            st.session_state.midjourney_reference_url.strip()
            if uses_midjourney_reference(image_usage)
            else ""
        ),
        midjourney_image_weight=float(st.session_state.midjourney_image_weight),
        source_image_caption=st.session_state.source_image_caption.strip(),
        source_image_credit=st.session_state.source_image_credit.strip(),
        source_image_url=st.session_state.source_image_url.strip(),
        source_image_placement=st.session_state.source_image_placement,
        include_uploaded_image=bool(st.session_state.include_uploaded_image),
    )


def validate_input(user_input: UserInput, settings) -> list[str]:
    errors = []
    missing = get_missing_configs(settings)
    if missing:
        errors.append("请先在 .env 中配置：" + "、".join(missing))
    if settings.writer_model and settings.writer_model == settings.reviewer_model:
        errors.append("写作模型和审校模型必须不同")
    if not user_input.topic.strip():
        errors.append("请先描述你想创作的新闻")
    if uses_midjourney_reference(user_input.image_usage):
        if settings.image_provider != "ttapi":
            errors.append("MidJourney 参考图需要将 IMAGE_PROVIDER 配置为 ttapi")
        try:
            reference_url = validate_reference_image_url(
                user_input.midjourney_reference_url
            )
            if not reference_url:
                errors.append("请填写可公开访问的 MidJourney 参考图 HTTPS URL")
        except ValueError as error:
            errors.append(str(error))
    return errors


settings = load_settings()

with st.sidebar:
    st.markdown("## 世界杯新闻助手")
    st.button(
        "新建对话",
        icon=":material/add_comment:",
        on_click=reset_chat,
        width="stretch",
    )
    st.markdown("### 历史新闻")
    history = recent_runs()
    if history:
        for item in history:
            title = html.escape(item["title"][:28])
            href = f"./News_Detail?run={quote(item['run'])}"
            st.html(f'<a href="{href}" style="display:block;margin:.65rem 0;text-decoration:none">{title}</a>')
    else:
        st.caption("还没有生成过新闻")
    st.divider()
    st.page_link(
        "pages/01_Knowledge_Base.py",
        label="知识库管理",
        icon=":material/database:",
    )
    st.page_link(
        "pages/02_Agent_Monitor.py",
        label="运行监控",
        icon=":material/monitoring:",
    )
    with st.expander("模型状态"):
        for label, model in [
            ("对话", settings.chat_model),
            ("策划", settings.planner_model),
            ("写作", settings.writer_model),
            ("审校", settings.reviewer_model),
            ("图片生成", settings.image_backend_label),
            ("图片理解", settings.vision_model),
            ("语音识别", settings.asr_model),
        ]:
            st.write(f"{label}：{model or '未配置'}")

has_conversation = any(not item.get("notice") for item in st.session_state.messages)

if not has_conversation:
    st.html(
        """
<section class="hero">
  <div class="hero-kicker">2026 World Cup newsroom</div>
  <h1>你好，我是<br>世界杯新闻助手</h1>
  <p>可以聊世界杯和日常问题，也可以让我创作新闻。支持上传参考图片或直接录音，资料不足时我会继续询问。</p>
</section>
"""
    )
else:
    st.markdown("## 世界杯新闻助手")

st.segmented_control(
    "工作模式",
    APP_MODES,
    key="app_mode",
    selection_mode="single",
    label_visibility="collapsed",
    width="stretch",
    on_change=announce_mode_change,
)
if st.session_state.app_mode == "对话":
    st.caption("支持持续多轮对话，每轮消息调用一次快速聊天模型，并保留最近的对话上下文。")
    suggestions = CHAT_SUGGESTIONS
else:
    st.caption("启动新闻策划、写作、独立审校和配图流程。")
    suggestions = NEWS_SUGGESTIONS

if not has_conversation:
    suggested = st.pills(
        "可以这样开始",
        list(suggestions),
        selection_mode="single",
        label_visibility="collapsed",
        key=f"{st.session_state.app_mode}_suggestions",
    )
else:
    suggested = None

if st.session_state.app_mode == "新闻创作":
    with st.expander("高级设置", icon=":material/tune:"):
        row = st.container(horizontal=True)
        row.selectbox(
            "报道模式", REPORTING_MODES, key="reporting_mode", persist_state="session"
        )
        row.selectbox(
            "新闻类型", NEWS_TYPES, key="news_type", persist_state="session"
        )
        row.selectbox(
            "写作风格", WRITING_STYLES, key="writing_style", persist_state="session"
        )
        st.text_input("目标受众", key="audience", persist_state="session")
        image_row = st.container(horizontal=True)
        image_row.selectbox(
            "图片风格", IMAGE_STYLES, key="image_style", persist_state="session"
        )
        image_row.segmented_control(
            "图片数量", [1, 2], key="image_count", persist_state="session"
        )
        st.toggle(
            "将上传的真实图片加入成稿",
            key="include_uploaded_image",
            persist_state="session",
            help="开启后，上传图片会保存到本次新闻并可在详情页调整图注和位置。",
        )
        if settings.image_provider == "ttapi":
            st.segmented_control(
                "上传图片用途",
                IMAGE_USAGES,
                key="image_usage",
                selection_mode="single",
                width="stretch",
                persist_state="session",
            )
            if uses_source_image(st.session_state.image_usage):
                source_row = st.container(horizontal=True)
                source_row.text_input(
                    "真实图片图注",
                    key="source_image_caption",
                    placeholder="例如：球员在赛后向看台致意",
                    persist_state="session",
                )
                source_row.text_input(
                    "图片来源/摄影者",
                    key="source_image_credit",
                    placeholder="例如：FIFA / 摄影者姓名",
                    persist_state="session",
                )
                st.text_input(
                    "真实图片原始链接（可选）",
                    key="source_image_url",
                    placeholder="https://example.com/original-photo",
                    persist_state="session",
                )
                st.selectbox(
                    "真实图片插入位置",
                    options=list(IMAGE_PLACEMENTS.values()),
                    format_func=lambda value: PLACEMENT_LABELS[value],
                    key="source_image_placement",
                    persist_state="session",
                )
            if uses_midjourney_reference(st.session_state.image_usage):
                st.text_input(
                    "MidJourney 参考图 URL",
                    key="midjourney_reference_url",
                    placeholder="https://example.com/reference.jpg",
                    persist_state="session",
                )
                st.slider(
                    "参考图权重",
                    min_value=0.5,
                    max_value=2.0,
                    step=0.1,
                    key="midjourney_image_weight",
                    persist_state="session",
                )
        else:
            st.session_state.image_usage = IMAGE_USAGES[0]
        st.text_area(
            "补充事实材料",
            key="extra_facts",
            height=120,
            max_chars=8000,
            placeholder="可选：粘贴比赛数据、采访记录和来源网址。",
            persist_state="session",
        )

@st.fragment(run_every=0.7 if has_running_job() else None)
def render_conversation() -> None:
    finished = False
    for message in st.session_state.messages:
        finished = render_message(message) or finished
    if finished:
        st.rerun()


render_conversation()

current_mode_running = has_running_job(st.session_state.app_mode)
if current_mode_running:
    st.caption(f"「{st.session_state.app_mode}」任务正在后台运行，可以切换到其他功能。")

submission = st.chat_input(
    "输入你的问题" if st.session_state.app_mode == "对话" else "描述你要创作的新闻",
    accept_file=True,
    file_type=["jpg", "jpeg", "png", "webp"],
    accept_audio=True,
    audio_sample_rate=16000,
    max_chars=4000,
    max_upload_size=10,
    submit_mode="disable",
    disabled=current_mode_running,
)

if suggested and not submission:
    incoming_text = suggestions[suggested]
    uploaded_image = None
    audio = None
elif submission:
    incoming_text = submission.text.strip()
    uploaded_image = submission.files[0] if submission.files else None
    audio = submission.audio
else:
    incoming_text = ""
    uploaded_image = None
    audio = None

if suggested or submission:
    image_record = None
    image_payload = None
    if uploaded_image:
        image_bytes = uploaded_image.getvalue()
        image_record = {"name": uploaded_image.name, "bytes": image_bytes}
        image_payload = {
            **image_record,
            "type": uploaded_image.type or "image/jpeg",
        }
    audio_payload = (
        {
            "bytes": audio.getvalue(),
            "name": audio.name,
            "type": audio.type or "audio/wav",
        }
        if audio
        else None
    )
    if incoming_text:
        display_text = incoming_text
    elif audio:
        display_text = (
            "语音消息"
            if st.session_state.app_mode == "对话"
            else "请根据这段语音创作新闻。"
        )
    else:
        display_text = (
            "请描述这张参考图片。"
            if st.session_state.app_mode == "对话"
            else "请根据这张参考图片创作一篇2026世界杯相关新闻。"
        )
    st.session_state.messages.append(
        {
            "role": "user",
            "content": display_text,
            "image": image_record,
            "mode": st.session_state.app_mode,
        }
    )

    image_only = should_start_image_only_job(
        st.session_state.app_mode,
        display_text,
    )
    if image_only:
        image_config = (
            {"TTAPI_IMAGE_API_KEY": settings.ttapi_image_api_key}
            if settings.image_provider == "ttapi"
            else {
                "SILICONFLOW_API_KEY": settings.api_key,
                "IMAGE_MODEL": settings.image_model,
            }
        )
        missing = [name for name, value in image_config.items() if not value.strip()]
        if missing:
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "请先在 .env 中配置：" + "、".join(missing),
                    "mode": st.session_state.app_mode,
                }
            )
            st.rerun()
        if uses_midjourney_reference(st.session_state.image_usage):
            try:
                reference_url = validate_reference_image_url(
                    st.session_state.midjourney_reference_url
                )
                if not reference_url:
                    raise ValueError("请填写可公开访问的 MidJourney 参考图 HTTPS URL")
            except ValueError as error:
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": str(error),
                        "mode": st.session_state.app_mode,
                    }
                )
                st.rerun()
        job_id = start_image_job(
            settings,
            display_text,
            requested_image_count(display_text, st.session_state.image_count),
            (
                st.session_state.midjourney_reference_url.strip()
                if uses_midjourney_reference(st.session_state.image_usage)
                else ""
            ),
            "",
            float(st.session_state.midjourney_image_weight),
        )
    elif st.session_state.app_mode == "对话":
        chat_history = [
            {"role": item["role"], "content": item.get("content", "")}
            for item in st.session_state.messages
            if item.get("mode") == "对话" and not item.get("notice")
        ]
        job_id = start_chat_job(
            settings,
            chat_history,
            audio=audio_payload,
            image=image_payload,
        )
    else:
        if not st.session_state.news_task_active:
            st.session_state.news_task_active = True
            st.session_state.news_start_index = len(st.session_state.messages) - 1

        user_input = build_user_input()
        errors = validate_input(user_input, settings)
        if errors:
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "\n\n".join(errors),
                    "mode": "新闻创作",
                }
            )
            st.rerun()
        job_id = start_news_job(
            settings,
            user_input,
            audio=audio_payload,
            image=image_payload,
        )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": "",
            "mode": st.session_state.app_mode,
            "job_id": job_id,
        }
    )
    st.rerun()
