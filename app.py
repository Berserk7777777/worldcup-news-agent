import base64
import html
import json
from datetime import date
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import quote

import streamlit as st

from background_jobs import (
    get_job,
    start_chat_job,
    start_image_job,
    start_midjourney_action_job,
    start_news_job,
    start_news_video_job,
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
from official_feed import load_official_headlines
from schemas import UserInput
from ui import (
    apply_newsroom_style,
    render_brand,
    render_sidebar_user,
    render_topbar,
)
from utils import extract_urls, requested_image_count, should_start_image_only_job


st.set_page_config(
    page_title="世界杯新闻助手",
    page_icon=":material/sports_soccer:",
    layout="wide",
)

apply_newsroom_style()


APP_MODES = ["对话", "新闻创作"]
REPORTING_MODES = ["真实报道", "AI模拟报道"]
NEWS_TYPES = ["自动判断", "赛事战报", "球员人物特写", "赛场精彩瞬间", "赛况总结", "世界杯与城市经济", "其他"]
WRITING_STYLES = ["第一人称叙事", "自动判断", "正式体育新闻", "新媒体新闻报道", "人物故事", "城市观察", "简洁客观报道"]
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
    "writing_style": "第一人称叙事",
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


def activate_mode(mode: str) -> None:
    st.session_state.app_mode = mode
    st.session_state.previous_app_mode = mode


def announce_mode_change() -> None:
    previous = st.session_state.get("previous_app_mode")
    current = st.session_state.get("app_mode")
    if current not in APP_MODES:
        st.session_state.app_mode = previous if previous in APP_MODES else APP_MODES[0]
        return
    if previous not in APP_MODES:
        st.session_state.previous_app_mode = current
        return
    if previous == current:
        return
    continuing = any(
        item.get("mode") == previous
        and item.get("job_id")
        and (get_job(item["job_id"]) or {}).get("status") == "running"
        for item in st.session_state.messages
    )
    suffix = "，原任务将继续在后台运行" if continuing else ""
    st.session_state.messages = [
        item for item in st.session_state.messages if not item.get("notice")
    ]
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


def render_home_dashboard(history: list[dict]) -> None:
    st.html(
        '<div class="news-section-title"><strong>快捷工作台</strong>'
        "<span>选择一个任务立即开始</span></div>"
    )
    cards = st.columns(3)
    quick_actions = [
        ("match", "◎", "赛事档案", "查看官方赛果与历史资料", "打开赛事档案"),
        ("news", "✎", "新闻创作", "生成快讯、赛后报道与专题稿", "开始创作"),
        ("source", "▥", "分析参考资料", "管理可信来源与赛事资料", "打开知识库"),
    ]
    for column, (key, icon, title, copy, label) in zip(cards, quick_actions):
        with column.container(border=True, key=f"quick_{key}"):
            st.html(
                f'<div class="quick-icon">{icon}</div>'
                f'<div class="quick-title">{title}</div>'
                f'<div class="quick-copy">{copy}</div>'
            )
            if key == "match":
                if st.button(label, key="open_match_center", width="stretch"):
                    st.switch_page("pages/04_Match_Center.py")
            elif key == "source":
                if st.button(label, key="open_knowledge_base", width="stretch"):
                    st.switch_page("pages/01_Knowledge_Base.py")
            else:
                st.button(
                    label,
                    key=f"start_{key}",
                    width="stretch",
                    on_click=activate_mode,
                    args=("新闻创作",),
                )

    hot_news, recent_work = st.columns([3, 2], gap="large")
    with hot_news:
        st.html(
            '<div class="news-section-title"><strong>官方动态</strong>'
            "<span>FIFA 官网 · 15 分钟缓存</span></div>"
        )
        feed_mode = st.segmented_control(
            "资料时间",
            ["最新动态", "历史回看"],
            default="最新动态",
            key="home_feed_mode",
            label_visibility="collapsed",
        )
        before = ""
        if feed_mode == "历史回看":
            selected_date = st.date_input(
                "查看该日期及之前的资料",
                value=date(2026, 7, 19),
                min_value=date(2026, 6, 11),
                max_value=date.today(),
                key="home_archive_date",
            )
            before = selected_date.isoformat()
        if st.button(
            "刷新官方动态",
            icon=":material/refresh:",
            key="refresh_official_feed",
        ):
            load_official_headlines.clear()
            st.toast("正在重新同步 FIFA 官方资料")
            st.rerun()

        with st.spinner("正在同步 FIFA 官方资料", show_time=True):
            feed = load_official_headlines(before=before, limit=5)
        st.caption(
            f"数据模式：{feed['mode']}　·　获取时间：{feed['retrieved_at']}"
        )
        if not feed["items"]:
            st.info("暂无可展示资料。可先在知识库页面执行一次更新。")
        for index, item in enumerate(feed["items"]):
            with st.container(border=True, key=f"official_story_{index}"):
                story, action = st.columns([5, 1], vertical_alignment="center")
                story.markdown(f"**{item['title']}**")
                story.caption(
                    f"{item['source_name']}　·　"
                    f"{item.get('published_at') or '未标注发布日期'}"
                )
                action.link_button(
                    "原文",
                    item["url"],
                    icon=":material/open_in_new:",
                    width="stretch",
                )
    with recent_work:
        st.html(
            '<div class="news-section-title"><strong>最近工作</strong>'
            "<span>自动保存</span></div>"
        )
        with st.container(border=True):
            if history:
                rows = []
                for item in history[:4]:
                    href = f"./News_Detail?run={quote(item['run'])}"
                    rows.append(
                        '<div class="history-row">'
                        f'<a href="{href}">{html.escape(item["title"][:34])}</a>'
                        "<span>已完成　›</span></div>"
                    )
                st.html("".join(rows))
            else:
                st.caption("完成第一篇新闻后，工作记录会显示在这里。")
                st.page_link(
                    "pages/05_History.py",
                    label="查看历史记录",
                    icon=":material/history:",
                )


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
            render_news_video(result, run_dir)

    if run_dir:
        href = f"./News_Detail?run={quote(run_dir.name)}"
        st.html(f'<a class="result-link" href="{href}">打开完整新闻详情 →</a>')

    run_id = result.get("monitor_run_id")
    if run_id:
        st.caption(f"[查看本次智能体运行记录](./Agent_Monitor?run_id={run_id})")


def _video_file(video: dict, run_dir: Path, field: str) -> Path | None:
    raw_path = video.get(field, "")
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_file():
        return path
    matches = list((run_dir / "video").glob(f"*/{path.name}"))
    return matches[-1] if matches else None


def render_news_video(result: dict, run_dir: Path) -> None:
    st.divider()
    st.markdown("#### AI 新闻视频播报")
    video_job_id = result.get("_video_job_id")
    if video_job_id:
        video_job = get_job(video_job_id)
        if video_job and video_job["status"] == "running":
            with st.status("正在生成 AI 新闻视频", expanded=True):
                events = video_job.get("events", [])
                if not events:
                    st.write(":material/progress_activity: 正在准备播报稿")
                for event in events:
                    icon = {
                        "running": ":material/progress_activity:",
                        "completed": ":material/check_circle:",
                        "failed": ":material/error:",
                    }.get(event["state"], ":material/info:")
                    st.write(f"{icon} {event['message']}")
            return
        if video_job and video_job["status"] == "completed":
            updated = video_job["result"]
            result.clear()
            result.update(updated)
            st.rerun()
        if video_job:
            result["_video_error"] = video_job.get("error", "视频生成失败")
        else:
            result["_video_error"] = "视频后台任务记录已失效，请重新生成"
        result.pop("_video_job_id", None)

    if result.get("_video_error"):
        st.error(result["_video_error"])

    video = result.get("video") or {}
    video_path = _video_file(video, run_dir, "video_path")
    if video_path:
        st.video(str(video_path))
        st.caption(
            f"{video.get('aspect_ratio', '16:9')} · "
            f"{video.get('duration_seconds', 0):.1f} 秒 · "
            f"{video.get('image_count', 0)} 张新闻图片 · "
            f"{'Veo 比赛演绎' if video.get('visual_mode') == 'veo' else '新闻版式'}"
        )
        if video.get("veo_error"):
            st.warning(f"Veo 镜头未能生成，已使用新闻版式完成播报：{video['veo_error']}")
        downloads = st.container(horizontal=True)
        downloads.download_button(
            "下载 MP4",
            video_path.read_bytes(),
            file_name=f"ai_news_{run_dir.name}.mp4",
            mime="video/mp4",
            icon=":material/download:",
            on_click="ignore",
        )
        for label, field, filename, mime in [
            ("下载字幕", "subtitle_path", "subtitles.srt", "text/plain"),
            ("下载播报稿", "script_path", "broadcast_script.txt", "text/plain"),
            ("下载配音", "audio_path", "narration.mp3", "audio/mpeg"),
        ]:
            path = _video_file(video, run_dir, field)
            if path:
                downloads.download_button(
                    label,
                    path.read_bytes(),
                    file_name=filename,
                    mime=mime,
                    on_click="ignore",
                )

    with st.expander(
        "重新生成视频" if video_path else "生成 AI 新闻视频",
        icon=":material/movie:",
    ):
        st.caption("使用 AI 配音和同步字幕。Veo 比赛镜头为 AI 生成赛事情景演绎，不代表真实比赛录像。")
        form_key = f"news-video-{run_dir.name}"
        with st.form(form_key):
            row = st.container(horizontal=True)
            aspect_ratio = row.segmented_control(
                "画面比例",
                ["16:9", "9:16"],
                default="16:9",
                key=f"video-aspect-{run_dir.name}",
            )
            duration_label = row.segmented_control(
                "播报时长",
                ["30秒", "60秒", "完整"],
                default="60秒",
                key=f"video-duration-{run_dir.name}",
            )
            speed = st.slider(
                "语速",
                min_value=0.75,
                max_value=1.25,
                value=1.0,
                step=0.05,
                key=f"video-speed-{run_dir.name}",
            )
            voice = st.text_input(
                "TTS 声音 ID",
                value=settings.tts_voice,
                key=f"video-voice-{run_dir.name}",
            )
            visual_options = ["新闻版式"]
            if settings.veo_available:
                visual_options.insert(0, "Veo 比赛演绎")
            else:
                st.info("配置 .env 中的 TTAPI_VIDEO_API_KEY 后，可使用 Veo 比赛演绎镜头。")
            visual_mode = st.segmented_control(
                "画面来源",
                visual_options,
                default=visual_options[0],
                key=f"video-visual-{run_dir.name}",
                help="先保留新闻图片轮播、配音和字幕，再在末尾追加一个 8 秒无声 Veo 情景片段。",
            )
            veo_model = "veo-3.1-fast"
            if visual_mode == "Veo 比赛演绎":
                veo_model = st.selectbox(
                    "Veo 模型",
                    ["veo-3.1-fast", "veo-3.1-quality", "veo-3.1-lite"],
                    key=f"veo-model-{run_dir.name}",
                )
            submitted = st.form_submit_button(
                "生成视频",
                type="primary",
                icon=":material/movie_creation:",
            )
        if submitted:
            duration = {"30秒": 30, "60秒": 60, "完整": 0}[duration_label]
            result["_video_job_id"] = start_news_video_job(
                settings,
                result,
                aspect_ratio or "16:9",
                duration,
                voice.strip(),
                float(speed),
                "veo" if visual_mode == "Veo 比赛演绎" else "newsroom",
                veo_model,
            )
            result.pop("_video_error", None)
            st.rerun()


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
        image_records = message.get("images") or (
            [message["image"]] if message.get("image") else []
        )
        if image_records:
            st.image(
                [item["bytes"] for item in image_records],
                caption=[item["name"] for item in image_records],
                width=260,
            )
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
        video_job_id = nested_result.get("_video_job_id")
        if video_job_id and (get_job(video_job_id) or {}).get("status") == "running":
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
        writing_style="第一人称叙事" if writing_style == "自动判断" else writing_style,
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
    render_brand()
    st.button(
        "新建工作",
        icon=":material/add:",
        on_click=reset_chat,
        type="primary",
        width="stretch",
    )
    st.page_link("app.py", label="首页", icon=":material/home:")
    st.button(
        "AI 对话",
        icon=":material/chat:",
        key="sidebar_chat",
        on_click=activate_mode,
        args=("对话",),
        width="stretch",
    )
    st.button(
        "新闻创作",
        icon=":material/edit_note:",
        key="sidebar_news",
        on_click=activate_mode,
        args=("新闻创作",),
        width="stretch",
    )
    st.page_link(
        "pages/04_Match_Center.py",
        label="赛事档案",
        icon=":material/sports_soccer:",
    )
    st.markdown("#### 最近记录")
    history = recent_runs()
    if history:
        for item in history[:3]:
            title = html.escape(item["title"][:28])
            href = f"./News_Detail?run={quote(item['run'])}"
            st.html(f'<a href="{href}" style="display:block;margin:.65rem 0;text-decoration:none">{title}</a>')
    else:
        st.caption("还没有生成过新闻")
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
    with st.expander("模型状态"):
        for label, model in [
            ("对话", settings.chat_model),
            ("策划", settings.planner_model),
            ("写作", settings.writer_model),
            ("审校", settings.reviewer_model),
            ("图片生成", settings.image_backend_label),
            ("图片理解", settings.vision_model),
            ("语音识别", settings.asr_model),
            ("语音合成", settings.tts_model),
        ]:
            st.write(f"{label}：{model or '未配置'}")
    render_sidebar_user()

has_conversation = any(not item.get("notice") for item in st.session_state.messages)
render_topbar("编辑部", configured=not get_missing_configs(settings))

if not has_conversation:
    hero, match = st.columns([1.15, 1], gap="large", vertical_alignment="center")
    with hero:
        st.html(
            """
<section class="news-hero fade-in">
  <div class="news-kicker">2026 World Cup AI newsroom</div>
  <h1>连接实时信息与历史档案，<br>生成<em>更准确</em>的新闻</h1>
  <p>同步官方动态，回看世界杯历史资料，生成比赛快讯与专业报道。上传事实材料、参考图片或直接录音，AI 编辑部会完成策划、写作与独立审校。</p>
</section>
"""
        )
    with match:
        st.html(
            """
<a class="tournament-card fade-in" href="./Match_Center">
  <div class="tournament-head">
    <span><b class="archive-badge">ARCHIVE</b>2026 FIFA WORLD CUP</span>
    <span>官方资料入口</span>
  </div>
  <div class="tournament-state">
    <span>赛事状态</span>
    <strong>已完结</strong>
    <p>2026 年 6 月 11 日 — 7 月 19 日</p>
  </div>
  <div class="tournament-actions"><span>赛程 · 赛果 · 官方报道 · 历史资料</span><span>进入赛事档案　›</span></div>
</a>
"""
        )
else:
    st.caption("2026 WORLD CUP AI NEWSROOM")
    st.markdown("## 新闻编辑工作台")

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

home_composer_slot = st.empty() if not has_conversation else None

if not has_conversation:
    render_home_dashboard(history)

@st.fragment(run_every=0.7 if has_running_job() else None)
def render_conversation() -> None:
    finished = False
    for message in st.session_state.messages:
        finished = render_message(message) or finished
    if finished:
        st.rerun()


current_mode_running = has_running_job(st.session_state.app_mode)

if home_composer_slot is not None:
    chat_input_parent = home_composer_slot.container()
else:
    chat_input_parent = nullcontext()
with chat_input_parent:
    render_conversation()
    if current_mode_running:
        st.caption(f"「{st.session_state.app_mode}」任务正在后台运行，可以切换到其他功能。")
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
    submission = st.chat_input(
        "输入你的问题" if st.session_state.app_mode == "对话" else "描述你要创作的新闻",
        accept_file="multiple",
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
    uploaded_images = []
    audio = None
elif submission:
    incoming_text = submission.text.strip()
    uploaded_images = list(submission.files)
    audio = submission.audio
else:
    incoming_text = ""
    uploaded_images = []
    audio = None

if suggested or submission:
    image_records = []
    image_payloads = []
    for uploaded_image in uploaded_images:
        image_bytes = uploaded_image.getvalue()
        image_record = {"name": uploaded_image.name, "bytes": image_bytes}
        image_records.append(image_record)
        image_payloads.append(
            {**image_record, "type": uploaded_image.type or "image/jpeg"}
        )
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
            "请描述这些参考图片。"
            if st.session_state.app_mode == "对话"
            else "请根据这些参考图片创作一篇2026世界杯相关新闻。"
        )
    st.session_state.messages.append(
        {
            "role": "user",
            "content": display_text,
            "images": image_records,
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
            images=image_payloads,
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
            images=image_payloads,
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
