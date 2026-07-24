import json
import re
from pathlib import Path

import streamlit as st

from document_export import build_docx_bytes, build_pdf_bytes
from news_images import (
    IMAGE_PLACEMENTS,
    PLACEMENT_LABELS,
    image_caption,
    images_by_placement,
    normalize_image_record,
    persist_image_records,
    resolve_image_path,
)
from utils import extract_urls, load_saved_result


st.set_page_config(
    page_title="新闻详情",
    page_icon=":material/article:",
    layout="centered",
)

st.markdown(
    """
<style>
.stApp {
  background:
    radial-gradient(circle at 85% 0%, rgba(216, 232, 98, .18), transparent 30rem),
    #fbfaf5;
}
.block-container { max-width: 850px; padding-top: 2rem; }
[data-testid="stSidebarNav"] { display: none; }
h1, h2, h3 {
  color: #18352b;
  font-family: Georgia, "Noto Serif SC", serif;
  letter-spacing: -.025em;
}
.article-meta {
  color: #68776f;
  border-top: 1px solid rgba(24, 53, 43, .14);
  border-bottom: 1px solid rgba(24, 53, 43, .14);
  padding: .8rem 0;
  margin: 1rem 0 2rem;
}
</style>
""",
    unsafe_allow_html=True,
)

st.link_button(
    label="返回对话",
    url="/",
    icon=":material/arrow_back:",
    width="content",
)

run_name = st.query_params.get("run", "")
if isinstance(run_name, list):
    run_name = run_name[0] if run_name else ""

if not run_name:
    st.info("请从聊天结果或历史新闻中打开详情页。")
    st.stop()

try:
    run_dir, result = load_saved_result(run_name)
except (FileNotFoundError, OSError, json.JSONDecodeError) as error:
    st.error(str(error))
    st.stop()

reviewer = result.get("reviewer_result", {})
writer = result.get("writer_result", {})
user_input = result.get("user_input", {})
title = reviewer.get("final_title") or writer.get("title") or user_input.get("topic", "新闻详情")
article = reviewer.get("final_article") or writer.get("full_article", "")
label = reviewer.get("final_article_label", "")

st.caption("2026 WORLD CUP NEWSROOM")
st.title(title)
if label:
    st.badge(label, color="blue")
st.html(
    f'<div class="article-meta">生成时间：{result.get("created_at", "未知")}　'
    f'新闻类型：{user_input.get("news_type", "未指定")}</div>'
)

placed_images = images_by_placement(result, run_dir)


def render_images(placement: str) -> None:
    for image in placed_images.get(placement, []):
        st.image(
            str(image["path"]),
            caption=image_caption(image),
            width="stretch",
        )


render_images("cover")
if article:
    article_body = re.split(r"\n\s*来源：\s*\n", article, maxsplit=1)[0].strip()
    paragraphs = [item for item in re.split(r"\n{2,}", article_body) if item.strip()]
    if paragraphs and re.sub(r"\s+", "", paragraphs[0].lstrip("# ")) == re.sub(
        r"\s+", "", title
    ):
        paragraphs = paragraphs[1:]
    for index, paragraph in enumerate(paragraphs):
        st.markdown(paragraph)
        if index == 0:
            render_images("after_lead")
        if index == 1:
            render_images("after_paragraph_2")
    if not paragraphs:
        render_images("after_lead")
    if len(paragraphs) < 2:
        render_images("after_paragraph_2")
    render_images("gallery")
elif user_input.get("news_type") == "AI图片创作":
    st.info("本次为纯图片生成任务，图片均为AI模拟内容，不代表真实赛事影像。")
    render_images("after_lead")
    render_images("after_paragraph_2")
    render_images("gallery")
else:
    st.warning("这次运行没有生成可展示的新闻正文。")

video = result.get("video") or {}
video_path = Path(video.get("video_path", "")) if video.get("video_path") else None
if video_path and not video_path.is_file():
    candidates = list((run_dir / "video").glob(f"*/{video_path.name}"))
    video_path = candidates[-1] if candidates else None
if video_path and video_path.is_file():
    st.divider()
    st.subheader("AI 主播新闻视频")
    st.video(str(video_path))
    st.caption(
        f"{video.get('aspect_ratio', '16:9')} · "
        f"{video.get('duration_seconds', 0):.1f} 秒 · "
        "AI 配音与自动字幕"
    )

if result.get("images"):
    with st.expander("图文编排", icon=":material/imagesmode:"):
        st.caption("真实图片应填写来源或摄影者；AI 图片会在成稿中自动标注为“AI生成示意图”。")
        updated_records = []
        with st.form("image-layout-form"):
            for index, raw_image in enumerate(result.get("images", [])):
                image = normalize_image_record(raw_image, index)
                path = resolve_image_path(image, run_dir)
                if not path:
                    updated_records.append(image)
                    continue
                with st.container(border=True):
                    preview, fields = st.columns([1, 2], vertical_alignment="top")
                    preview.image(str(path), width="stretch")
                    image["selected"] = fields.toggle(
                        "纳入图文稿",
                        value=bool(image.get("selected", True)),
                        key=f"image-selected-{index}",
                    )
                    image["caption"] = fields.text_input(
                        "图注",
                        value=image.get("caption") or image.get("name", "新闻配图"),
                        key=f"image-caption-{index}",
                    )
                    placement_values = list(IMAGE_PLACEMENTS.values())
                    current_placement = image.get("placement", "gallery")
                    if current_placement not in placement_values:
                        current_placement = "gallery"
                    image["placement"] = fields.selectbox(
                        "插入位置",
                        options=placement_values,
                        index=placement_values.index(current_placement),
                        format_func=lambda value: PLACEMENT_LABELS[value],
                        key=f"image-placement-{index}",
                    )
                    if image.get("kind") == "source":
                        image["credit"] = fields.text_input(
                            "图片来源/摄影者",
                            value=image.get("credit", ""),
                            key=f"image-credit-{index}",
                        )
                        image["source_url"] = fields.text_input(
                            "图片原始链接",
                            value=image.get("source_url", ""),
                            key=f"image-source-url-{index}",
                        )
                    else:
                        fields.caption("类型：AI生成示意图")
                image.pop("path", None)
                updated_records.append(image)
            saved = st.form_submit_button(
                "保存图文编排",
                type="primary",
                icon=":material/save:",
            )
        if saved:
            persist_image_records(run_dir, updated_records)
            st.rerun()

st.divider()
st.subheader("来源")
sources = result.get("sources", [])
urls = extract_urls(user_input.get("factual_material", ""))
if sources:
    for index, source in enumerate(sources, 1):
        date = source.get("published_at") or "未标注日期"
        st.markdown(
            f"{index}. **{source.get('source_level', 'B')}级** "
            f"{source['source_name']}，《{source['document_title']}》，"
            f"{date}，[原始链接]({source['source_url']})"
        )
elif urls:
    for index, url in enumerate(urls, 1):
        st.markdown(f"{index}. [打开原始来源]({url})")
else:
    st.caption("当前事实材料未包含可点击网址。接入 RAG 后，检索来源将在这里集中展示。")

with st.expander("查看事实材料与审校说明"):
    st.markdown("**用户提供的事实材料**")
    st.text(user_input.get("factual_material", "未提供"))
    st.markdown("**审校结论**")
    st.write(reviewer.get("review_summary", "未生成审校结论"))
    unsupported = reviewer.get("unsupported_claims", [])
    if unsupported:
        st.markdown("**无依据声明**")
        for item in unsupported:
            st.markdown(f"- {item}")

st.subheader("下载成品")
try:
    pdf_data = build_pdf_bytes(result, run_dir)
    docx_data = build_docx_bytes(result, run_dir)
except Exception as error:
    st.error(f"文档生成失败：{error}")
else:
    columns = st.columns(3)
    columns[0].download_button(
        "下载 PDF（含图片）",
        pdf_data,
        file_name=f"worldcup_news_{run_name}.pdf",
        mime="application/pdf",
        icon=":material/picture_as_pdf:",
        type="primary",
        on_click="ignore",
        width="stretch",
    )
    columns[1].download_button(
        "下载 Word（含图片）",
        docx_data,
        file_name=f"worldcup_news_{run_name}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        icon=":material/description:",
        on_click="ignore",
        width="stretch",
    )
    text_path = run_dir / "final_article.txt"
    if text_path.exists():
        columns[2].download_button(
            "下载纯文本",
            text_path.read_bytes(),
            file_name="final_article.txt",
            mime="text/plain",
            icon=":material/text_snippet:",
            on_click="ignore",
            width="stretch",
        )

with st.expander("更多下载"):
    extra_files = [
        ("下载完整结果", "result.json", "application/json"),
        ("下载创作报告", "creation_report.md", "text/markdown"),
    ]
    with st.container(horizontal=True):
        for label_text, filename, mime in extra_files:
            path = run_dir / filename
            if path.exists():
                st.download_button(
                    label_text,
                    path.read_bytes(),
                    file_name=filename,
                    mime=mime,
                    on_click="ignore",
                )
        if video_path and video_path.is_file():
            st.download_button(
                "下载 AI 新闻视频",
                video_path.read_bytes(),
                file_name=f"ai_news_{run_name}.mp4",
                mime="video/mp4",
                icon=":material/movie:",
                on_click="ignore",
            )
