import dataclasses
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


SOURCE_IMAGE_USAGE = "图片作为新闻资料"
REFERENCE_IMAGE_USAGE = "图片作为MidJourney参考图"
COMBINED_IMAGE_USAGE = "同时作为新闻资料和MidJourney参考图"
IMAGE_USAGES = [SOURCE_IMAGE_USAGE, REFERENCE_IMAGE_USAGE, COMBINED_IMAGE_USAGE]

IMAGE_PLACEMENTS = {
    "封面（标题下）": "cover",
    "导语后": "after_lead",
    "正文第2段后": "after_paragraph_2",
    "文末图片区": "gallery",
}
PLACEMENT_LABELS = {value: label for label, value in IMAGE_PLACEMENTS.items()}


def uses_source_image(image_usage: str) -> bool:
    return image_usage in {SOURCE_IMAGE_USAGE, COMBINED_IMAGE_USAGE}


def uses_midjourney_reference(image_usage: str) -> bool:
    return image_usage in {REFERENCE_IMAGE_USAGE, COMBINED_IMAGE_USAGE}


def _plain_image(image: Any) -> dict:
    if dataclasses.is_dataclass(image):
        return dataclasses.asdict(image)
    return dict(image)


def normalize_image_record(image: Any, index: int = 0) -> dict:
    record = _plain_image(image)
    kind = record.get("kind") or "ai"
    record["kind"] = kind
    if not record.get("image_id"):
        record["image_id"] = f"{kind}_{index + 1}"
    record.setdefault("caption", record.get("name", "新闻配图"))
    record.setdefault("credit", "")
    record.setdefault("source_url", "")
    if record.get("placement") not in PLACEMENT_LABELS:
        record["placement"] = (
            "after_lead" if kind == "source" else "after_paragraph_2"
        )
    if record.get("selected") is None:
        record["selected"] = True
    record.setdefault(
        "ai_disclosure",
        "" if kind == "source" else "AI生成示意图",
    )
    return record


def save_source_image(
    run_dir: Path, image: dict, user_input: Any, index: int = 0
) -> dict:
    image_bytes = image.get("bytes") or b""
    if not image_bytes:
        raise ValueError("上传的真实图片为空")

    image_number = index + 1
    output_path = run_dir / f"source_image_{image_number}.png"
    with Image.open(BytesIO(image_bytes)) as source:
        normalized = ImageOps.exif_transpose(source).convert("RGB")
        normalized.save(output_path, format="PNG", optimize=True)

    caption = getattr(user_input, "source_image_caption", "").strip()
    credit = getattr(user_input, "source_image_credit", "").strip()
    source_url = getattr(user_input, "source_image_url", "").strip()
    placement = getattr(user_input, "source_image_placement", "after_lead")
    if placement not in PLACEMENT_LABELS:
        placement = "after_lead"

    return {
        "image_id": f"source_{image_number}",
        "kind": "source",
        "name": image.get("name") or f"用户提供的真实图片 {image_number}",
        "caption": caption or f"用户提供的新闻资料图片 {image_number}",
        "credit": credit or "用户提供，版权信息待补充",
        "source_url": source_url,
        "local_path": str(output_path),
        "placement": placement,
        "selected": True,
        "ai_disclosure": "",
    }


def resolve_image_path(record: dict, run_dir: Path) -> Path | None:
    raw_path = record.get("local_path", "")
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_file():
        return path
    candidate = run_dir / path.name
    return candidate if candidate.is_file() else None


def publication_images(result: dict, run_dir: Path) -> list[dict]:
    records = []
    for index, image in enumerate(result.get("images", [])):
        record = normalize_image_record(image, index)
        if not record.get("selected", True):
            continue
        path = resolve_image_path(record, run_dir)
        if not path:
            continue
        record["path"] = path
        records.append(record)
    return records


def image_caption(record: dict) -> str:
    caption = (record.get("caption") or record.get("name") or "新闻配图").strip()
    if record.get("kind") == "source":
        credit = (record.get("credit") or "来源待补充").strip()
        source_url = (record.get("source_url") or "").strip()
        source_suffix = f"；原始链接：{source_url}" if source_url else ""
        return f"{caption}（图片来源：{credit}{source_suffix}）"
    disclosure = (record.get("ai_disclosure") or "AI生成示意图").strip()
    return f"{caption}（{disclosure}）"


def images_by_placement(result: dict, run_dir: Path) -> dict[str, list[dict]]:
    grouped = {placement: [] for placement in PLACEMENT_LABELS}
    for record in publication_images(result, run_dir):
        placement = record.get("placement", "gallery")
        grouped.setdefault(placement, []).append(record)
    return grouped


def persist_image_records(run_dir: Path, records: list[dict]) -> None:
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        return
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["images"] = records
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
