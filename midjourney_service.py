import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from config import Settings
from schemas import GeneratedImage, MidJourneyJob
from ttapi_client import TTAPIMidJourneyClient


ProgressCallback = Callable[[str, str, str], None] | None


def build_midjourney_prompt(
    prompt: str,
    negative_prompt: str,
    image_size: str,
    reference_image_url: str = "",
    reference_description: str = "",
    image_weight: float = 1.5,
) -> str:
    reference_url = validate_reference_image_url(reference_image_url)
    description = re.sub(r"\s+", " ", reference_description).strip()[:800]
    text_parts = [reference_url, description, prompt]
    text = re.sub(r"\s+", " ", " ".join(part for part in text_parts if part)).strip()
    if "--ar " not in text:
        ratio = "1:1"
        match = re.fullmatch(r"(\d+)x(\d+)", image_size.strip().lower())
        if match:
            width, height = int(match.group(1)), int(match.group(2))
            if width > height:
                ratio = "16:9"
            elif height > width:
                ratio = "9:16"
        text += f" --ar {ratio}"
    if "--style " not in text:
        text += " --style raw"
    if reference_url and "--iw " not in text:
        normalized_weight = min(2.0, max(0.5, float(image_weight or 1.5)))
        text += f" --iw {normalized_weight:g}"
    if "--no " not in text:
        exclusions = "text watermark logo caption typography"
        if negative_prompt:
            exclusions += " " + re.sub(r"[,，、]+", " ", negative_prompt)
        text += f" --no {exclusions}"
    return text


def validate_reference_image_url(value: str) -> str:
    url = value.strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("MidJourney 参考图必须使用可公开访问的 HTTPS URL")
    return url


def _notify(callback: ProgressCallback, message: str, state: str) -> None:
    if callback:
        callback("图片生成", message, state)


def materialize_midjourney_job(
    client: TTAPIMidJourneyClient,
    job: MidJourneyJob,
    run_dir: Path,
    prefix: str,
    negative_prompt: str,
) -> tuple[MidJourneyJob, list[GeneratedImage]]:
    images: list[GeneratedImage] = []
    if job.final_image_url:
        final_path = run_dir / f"{prefix}_final.png"
        client.download_image(job.final_image_url, final_path)
        job.final_image_local_path = str(final_path)
        images.append(
            GeneratedImage(
                name="MidJourney 最终图片",
                prompt=job.prompt,
                negative_prompt=negative_prompt,
                source_url=job.final_image_url,
                local_path=str(final_path),
                provider_job_id=job.job_id,
                candidate_label=job.requested_action,
                image_id=f"ai_{job.job_id}",
                caption="新闻场景示意图",
            )
        )
        return job, images

    if job.candidates:
        for index, candidate in enumerate(job.candidates, 1):
            candidate_path = run_dir / f"{prefix}_candidate_{index}.png"
            client.download_image(candidate.source_url, candidate_path)
            candidate.local_path = str(candidate_path)
            images.append(
                GeneratedImage(
                    name=f"MidJourney {candidate.label}",
                    prompt=job.prompt,
                    negative_prompt=negative_prompt,
                    source_url=candidate.source_url,
                    local_path=str(candidate_path),
                    provider_job_id=job.job_id,
                    candidate_label=candidate.label,
                    image_id=f"ai_{job.job_id}_{index}",
                    caption=f"MidJourney 候选 {candidate.label}",
                    selected=False,
                )
            )
        return job, images

    if job.grid_url:
        grid_path = run_dir / f"{prefix}_grid.png"
        client.download_image(job.grid_url, grid_path)
        job.grid_local_path = str(grid_path)
        images.append(
            GeneratedImage(
                name="MidJourney 四宫格",
                prompt=job.prompt,
                negative_prompt=negative_prompt,
                source_url=job.grid_url,
                local_path=str(grid_path),
                provider_job_id=job.job_id,
                candidate_label="GRID",
                image_id=f"ai_{job.job_id}_grid",
                caption="MidJourney 四宫格候选",
                selected=False,
            )
        )
    return job, images


def create_midjourney_candidates(
    settings: Settings,
    prompt: str,
    negative_prompt: str,
    run_dir: Path,
    prefix: str,
    progress_callback: ProgressCallback = None,
    reference_image_url: str = "",
    reference_description: str = "",
    image_weight: float = 1.5,
) -> tuple[MidJourneyJob, list[GeneratedImage]]:
    client = TTAPIMidJourneyClient(settings)
    final_prompt = build_midjourney_prompt(
        prompt,
        negative_prompt,
        settings.image_size,
        reference_image_url,
        reference_description,
        image_weight,
    )
    _notify(progress_callback, "正在提交 MidJourney Imagine 任务", "running")
    job = client.create_job(final_prompt)
    _notify(
        progress_callback,
        f"MidJourney 任务已提交（{job.job_id}），正在等待四宫格",
        "running",
    )
    job = client.poll_until_ready(job)
    _notify(progress_callback, "MidJourney 四宫格已生成", "completed")
    return materialize_midjourney_job(
        client, job, run_dir, prefix, negative_prompt
    )


def run_midjourney_action(
    settings: Settings,
    job_payload: dict,
    action_label: str,
    run_dir: Path,
    prefix: str,
    negative_prompt: str,
    progress_callback: ProgressCallback = None,
) -> tuple[MidJourneyJob, list[GeneratedImage]]:
    client = TTAPIMidJourneyClient(settings)
    job = client.from_dict(job_payload)
    normalized = action_label.upper()

    if normalized.startswith("ACCEPT_"):
        index = int(normalized.split("_", 1)[1]) - 1
        if index < 0 or index >= len(job.candidates):
            raise ValueError("候选图片编号无效")
        candidate = job.candidates[index]
        job.requested_action = f"候选 {index + 1}"
        job.final_image_url = candidate.source_url
        job.final_image_local_path = candidate.local_path
        image = GeneratedImage(
            name="MidJourney 最终图片",
            prompt=job.prompt,
            negative_prompt=negative_prompt,
            source_url=candidate.source_url,
            local_path=candidate.local_path,
            provider_job_id=job.job_id,
            candidate_label=job.requested_action,
            image_id=f"ai_{job.job_id}",
            caption="新闻场景示意图",
        )
        return job, [image]

    _notify(progress_callback, f"正在执行 {normalized}", "running")
    updated = client.submit_action(job, normalized)
    updated = client.poll_until_ready(updated)
    state_text = "最终图片" if normalized.startswith("U") else "新四宫格"
    _notify(progress_callback, f"{normalized} {state_text}已生成", "completed")
    return materialize_midjourney_job(
        client, updated, run_dir, prefix, negative_prompt
    )


def persist_midjourney_state(run_dir: Path, result: dict) -> None:
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        return
    stored = json.loads(result_path.read_text(encoding="utf-8"))
    stored["images"] = result.get("images", [])
    stored["midjourney_jobs"] = result.get("midjourney_jobs", [])
    result_path.write_text(
        json.dumps(stored, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
