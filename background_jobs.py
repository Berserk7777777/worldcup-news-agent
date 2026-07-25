import copy
import dataclasses
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from knowledge_base import KnowledgeUpdater
from midjourney_service import (
    create_midjourney_candidates,
    persist_midjourney_state,
    run_midjourney_action,
)
from news_images import (
    normalize_image_record,
    persist_image_records,
    save_source_image,
    uses_midjourney_reference,
    uses_source_image,
)
from news_video_service import create_news_video, persist_video_result
from siliconflow_client import SiliconFlowClient
from ttapi_client import TTAPIMidJourneyClient
from utils import create_run_directory, sanitize_error_message
from workflow import run_news_workflow


_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="worldcup-agent")
_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}


def _create_job(kind: str) -> str:
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "output": "",
            "result": None,
            "error": "",
            "events": [],
        }
    return job_id


def _update(job_id: str, **values) -> None:
    with _LOCK:
        _JOBS[job_id].update(values)


def _append_output(job_id: str, text: str) -> None:
    with _LOCK:
        _JOBS[job_id]["output"] += text


def _append_event(job_id: str, stage: str, message: str, state: str) -> None:
    with _LOCK:
        _JOBS[job_id]["events"].append(
            {"stage": stage, "message": message, "state": state}
        )


def get_job(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return copy.copy(job) | {"events": list(job["events"])} if job else None


def _prepare_media(client, text, audio, images, event_callback):
    media_text = text
    image_analyses = []
    if audio:
        event_callback("语音识别", "正在识别语音", "running")
        transcript = client.transcribe_audio(
            audio["bytes"], audio["name"], audio["type"]
        )
        media_text = f"{media_text}\n\n语音补充：{transcript}" if media_text else transcript
        event_callback("语音识别", "语音识别完成", "completed")
    for index, image in enumerate(images or [], 1):
        event_callback("图片理解", f"正在读取参考图片 {index}/{len(images)}", "running")
        analysis = client.analyze_image(image["bytes"], image["type"], media_text)
        image_analyses.append(
            f"图片 {index}：{analysis}" if len(images) > 1 else analysis
        )
        event_callback("图片理解", f"参考图片 {index}/{len(images)} 分析完成", "completed")
    return media_text, "\n\n".join(image_analyses)


def start_chat_job(
    settings, history: list[dict], audio=None, image=None, images=None
) -> str:
    job_id = _create_job("chat")

    def run() -> None:
        try:
            client = SiliconFlowClient(settings)
            current_text = history[-1]["content"] if history else ""
            text, image_analysis = _prepare_media(
                client,
                current_text,
                audio,
                images if images is not None else ([image] if image else []),
                lambda stage, message, state: _append_event(
                    job_id, stage, message, state
                ),
            )
            prepared_history = [dict(item) for item in history]
            if prepared_history:
                prepared_history[-1]["content"] = text
                if image_analysis:
                    prepared_history[-1]["content"] += (
                        "\n\n参考图片分析：" + image_analysis
                    )
            for chunk in client.stream_chat(settings.chat_model, prepared_history):
                _append_output(job_id, chunk)
            _update(job_id, status="completed")
        except Exception as error:
            _update(
                job_id,
                status="failed",
                error=sanitize_error_message(error, settings.api_key),
            )

    _EXECUTOR.submit(run)
    return job_id


def start_image_job(
    settings,
    prompt: str,
    count: int | None,
    reference_image_url: str = "",
    reference_description: str = "",
    image_weight: float = 1.5,
) -> str:
    job_id = _create_job("image")
    normalized_count = count if count in {1, 2} else 1

    def run() -> None:
        try:
            image_provider = getattr(settings, "image_provider", "siliconflow")
            client = SiliconFlowClient(settings) if image_provider != "ttapi" else None
            run_dir = create_run_directory(Path("outputs"))
            images = []
            midjourney_jobs = []
            image_prompt = (
                f"{prompt}。AI模拟体育新闻摄影，主体清晰，真实光影，高细节，"
                "画面中不要出现文字或水印。"
            )
            negative_prompt = "文字，水印，标志，低清晰度，畸形肢体，重复人物"
            for index in range(normalized_count):
                _append_event(
                    job_id,
                    "图片生成",
                    f"正在生成第{index + 1}张图片",
                    "running",
                )
                if image_provider == "ttapi":
                    midjourney_job, generated = create_midjourney_candidates(
                        settings,
                        image_prompt,
                        negative_prompt,
                        run_dir,
                        f"midjourney_{index + 1}",
                        lambda stage, message, state: _append_event(
                            job_id, stage, message, state
                        ),
                        reference_image_url,
                        reference_description,
                        image_weight,
                    )
                    midjourney_jobs.append(
                        TTAPIMidJourneyClient.to_dict(midjourney_job)
                    )
                    images.extend(dataclasses.asdict(item) for item in generated)
                else:
                    if client is None:
                        raise RuntimeError("图片客户端未初始化")
                    url, seed = client.generate_image(
                        settings.image_model,
                        image_prompt,
                        negative_prompt,
                        settings.image_size,
                    )
                    image_path = run_dir / f"image_{index + 1}.png"
                    client.download_image(url, image_path)
                    images.append(
                        {
                            "image_id": f"ai_{index + 1}",
                            "kind": "ai",
                            "name": f"AI模拟图片 {index + 1}",
                            "caption": f"AI生成的新闻场景示意图 {index + 1}",
                            "credit": "",
                            "prompt": image_prompt,
                            "negative_prompt": negative_prompt,
                            "source_url": "",
                            "local_path": str(image_path),
                            "placement": "after_paragraph_2",
                            "selected": True,
                            "ai_disclosure": "AI生成示意图",
                            "seed": seed,
                            "error": "",
                        }
                    )
                _append_event(
                    job_id,
                    "图片生成",
                    f"第{index + 1}张图片生成完成",
                    "completed",
                )
            result = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "run_dir": str(run_dir),
                "user_input": {
                    "topic": prompt,
                    "news_type": "AI图片创作",
                    "factual_material": "本次结果为AI模拟图片，不代表真实赛事影像。",
                },
                "writer_result": {},
                "reviewer_result": {
                    "final_title": prompt[:80],
                    "final_article_label": "AI生成图片",
                    "review_summary": "纯图片生成任务，未作为真实新闻报道。",
                },
                "images": images,
                "midjourney_jobs": midjourney_jobs,
            }
            (run_dir / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _update(job_id, status="completed", result=result)
        except Exception as error:
            _update(
                job_id,
                status="failed",
                error=sanitize_error_message(error, settings.api_key),
            )

    _EXECUTOR.submit(run)
    return job_id


def start_midjourney_action_job(
    settings,
    result: dict,
    job_index: int,
    action_label: str,
) -> str:
    job_id = _create_job("midjourney_action")
    result_snapshot = copy.deepcopy(result)

    def run() -> None:
        try:
            updated_result = copy.deepcopy(result_snapshot)
            updated_result.pop("_midjourney_action_job_id", None)
            updated_result.pop("_midjourney_action_error", None)
            jobs = updated_result.get("midjourney_jobs", [])
            if job_index < 0 or job_index >= len(jobs):
                raise ValueError("MidJourney 任务编号无效")
            run_dir = Path(updated_result["run_dir"])
            previous_job_id = jobs[job_index]["job_id"]
            image_records = []
            negative_prompt = ""
            for item in updated_result.get("images", []):
                record = dataclasses.asdict(item) if dataclasses.is_dataclass(item) else dict(item)
                if record.get("provider_job_id") == previous_job_id:
                    negative_prompt = negative_prompt or record.get("negative_prompt", "")
                    continue
                image_records.append(record)

            prefix = f"midjourney_{job_index + 1}_{uuid.uuid4().hex[:8]}"
            updated_job, generated = run_midjourney_action(
                settings,
                jobs[job_index],
                action_label,
                run_dir,
                prefix,
                negative_prompt,
                lambda stage, message, state: _append_event(
                    job_id, stage, message, state
                ),
            )
            jobs[job_index] = TTAPIMidJourneyClient.to_dict(updated_job)
            image_records.extend(dataclasses.asdict(item) for item in generated)
            updated_result["images"] = image_records
            updated_result["midjourney_jobs"] = jobs
            persist_midjourney_state(run_dir, updated_result)
            _update(job_id, status="completed", result=updated_result)
        except Exception as error:
            _update(
                job_id,
                status="failed",
                error=sanitize_error_message(
                    error, settings.ttapi_image_api_key
                ),
            )

    _EXECUTOR.submit(run)
    return job_id


def start_news_video_job(
    settings,
    result: dict,
    aspect_ratio: str,
    target_seconds: int,
    voice: str,
    speed: float,
    visual_mode: str = "newsroom",
    veo_model: str = "veo-3.1-fast",
) -> str:
    job_id = _create_job("video")
    result_snapshot = copy.deepcopy(result)

    def run() -> None:
        try:
            updated_result = copy.deepcopy(result_snapshot)
            updated_result.pop("_video_job_id", None)
            updated_result.pop("_video_error", None)
            video = create_news_video(
                settings,
                updated_result,
                aspect_ratio=aspect_ratio,
                target_seconds=target_seconds,
                voice=voice,
                speed=speed,
                visual_mode=visual_mode,
                veo_model=veo_model,
                progress_callback=lambda stage, message, state: _append_event(
                    job_id, stage, message, state
                ),
            )
            updated_result["video"] = video
            persist_video_result(Path(updated_result["run_dir"]), video)
            _update(job_id, status="completed", result=updated_result)
        except Exception as error:
            _update(
                job_id,
                status="failed",
                error=sanitize_error_message(error, settings.api_key),
            )

    _EXECUTOR.submit(run)
    return job_id


def start_knowledge_update_job(settings) -> str:
    job_id = _create_job("knowledge")

    def run() -> None:
        try:
            updater = KnowledgeUpdater(
                settings,
                progress_callback=lambda stage, message, state: _append_event(
                    job_id, stage, message, state
                ),
            )
            result = updater.update()
            _update(job_id, status="completed", result=result)
        except Exception as error:
            _update(
                job_id,
                status="failed",
                error=sanitize_error_message(error, settings.api_key),
            )

    _EXECUTOR.submit(run)
    return job_id


def start_news_job(
    settings, user_input, audio=None, image=None, images=None
) -> str:
    job_id = _create_job("news")

    def run() -> None:
        try:
            client = SiliconFlowClient(settings)
            uploaded_images = images if images is not None else ([image] if image else [])
            text, image_analysis = _prepare_media(
                client,
                user_input.topic,
                audio,
                uploaded_images,
                lambda stage, message, state: _append_event(
                    job_id, stage, message, state
                ),
            )
            if audio:
                user_input.topic = text[:200]
                user_input.factual_material += "\n\n" + text
            if image_analysis:
                if uses_midjourney_reference(user_input.image_usage):
                    user_input.midjourney_reference_description = image_analysis
                if uses_source_image(user_input.image_usage):
                    user_input.factual_material += (
                        "\n\n上传图片分析结果：\n" + image_analysis
                    )
            result = run_news_workflow(
                user_input,
                settings,
                lambda stage, message, state: _append_event(
                    job_id, stage, message, state
                ),
            )
            if (
                uploaded_images
                and user_input.include_uploaded_image
                and result.get("run_dir")
            ):
                run_dir = Path(result["run_dir"])
                source_records = [
                    save_source_image(run_dir, uploaded_image, user_input, index)
                    for index, uploaded_image in enumerate(uploaded_images)
                ]
                generated_records = [
                    normalize_image_record(item, index)
                    for index, item in enumerate(result.get("images", []))
                ]
                result["images"] = [*source_records, *generated_records]
                persist_image_records(run_dir, result["images"])
            result["user_input"] = user_input
            _update(job_id, status="completed", result=result)
        except Exception as error:
            _update(
                job_id,
                status="failed",
                error=sanitize_error_message(error, settings.api_key),
            )

    _EXECUTOR.submit(run)
    return job_id
