import dataclasses
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def strip_json_code_fence(text: str) -> str:
    cleaned = text.lstrip("\ufeff").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    return cleaned[start : end + 1] if start >= 0 and end >= start else cleaned


def validate_required_keys(data: dict, required_keys: list[str], stage_name: str) -> None:
    missing = [key for key in required_keys if key not in data]
    if missing:
        from siliconflow_client import ModelOutputError

        raise ModelOutputError(f"{stage_name}输出缺少字段：{', '.join(missing)}")


def count_non_whitespace_characters(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def extract_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>\"，。；、]+", text)
    return list(dict.fromkeys(url.rstrip(".,;，。；、)]}") for url in urls))


def requested_image_count(text: str, default: int | None = 1) -> int:
    normalized_default = default if default in {1, 2} else 1
    matches = re.findall(
        r"([一二两12])\s*(?:张|幅)(?:图片|图像|配图|照片)?"
        r"|([一二两12])\s*个\s*(?:图片|图像|配图|照片)",
        text,
    )
    if not matches:
        return normalized_default
    count = next(value for value in matches[-1] if value)
    return 2 if count in {"二", "两", "2"} else 1


def is_image_generation_request(text: str) -> bool:
    has_image = re.search(r"图片|图像|照片|海报|特写|配图", text)
    has_action = re.search(r"生成|制作|画|绘制|给出|来[一两二12]?(?:张|幅)", text)
    has_article = re.search(r"新闻|报道|文章|战报|稿件|新闻稿", text)
    return bool(has_image and has_action and not has_article)


def should_start_image_only_job(app_mode: str, text: str) -> bool:
    """Keep image-only routing out of the full news creation workflow."""
    return app_mode != "新闻创作" and is_image_generation_request(text)


def load_saved_result(run_name: str, base_dir: Path = Path("outputs")) -> tuple[Path, dict]:
    safe_name = Path(run_name).name
    run_dir = (base_dir.resolve() / safe_name).resolve()
    if run_dir.parent != base_dir.resolve():
        raise FileNotFoundError("无效的新闻记录")
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        raise FileNotFoundError("新闻记录不存在")
    return run_dir, json.loads(result_path.read_text(encoding="utf-8"))


def is_valid_article_length(text: str) -> bool:
    return 300 <= count_non_whitespace_characters(text) <= 500


def sanitize_error_message(error: Exception, api_key: str = "") -> str:
    message = str(error)
    if api_key:
        message = message.replace(api_key, "***")
    message = re.sub(r"(?i)Bearer\s+[^\s,;\"']+", "Bearer ***", message)
    if len(message) > 500:
        message = message[:500] + "…[已截断]"
    return message


def create_run_directory(base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for suffix in [""] + [f"_{i:02d}" for i in range(1, 100)]:
        run_dir = base_dir / f"{timestamp}{suffix}"
        try:
            run_dir.mkdir()
            return run_dir
        except FileExistsError:
            continue
    raise OSError("同一秒内创建的输出目录过多")


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return value


def save_run_results(
    run_dir: Path,
    user_input,
    settings,
    planner_result: dict,
    writer_result: dict,
    reviewer_result: dict,
    trace: list,
    images: list,
    metrics: dict,
    sources: list | None = None,
    midjourney_jobs: list | None = None,
) -> dict:
    safe_images = []
    for image in images:
        item = _plain(image).copy()
        if item.get("kind") != "source":
            item.pop("source_url", None)
        safe_images.append(item)
    result = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "user_input": _plain(user_input),
        "models": {
            "planner": settings.planner_model,
            "writer": settings.writer_model,
            "reviewer": settings.reviewer_model,
            "image": settings.image_backend_label,
        },
        "planner_result": planner_result,
        "writer_result": writer_result,
        "reviewer_result": reviewer_result,
        "trace": [_plain(item) for item in trace],
        "images": safe_images,
        "metrics": metrics,
        "sources": sources or [],
        "midjourney_jobs": [_plain(item) for item in (midjourney_jobs or [])],
    }
    (run_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def save_final_article_txt(run_dir: Path, reviewer_result: dict) -> Path:
    parts = [
        reviewer_result.get("final_article_label", ""),
        reviewer_result.get("final_title", ""),
        "",
        reviewer_result.get("final_article", ""),
    ]
    path = run_dir / "final_article.txt"
    path.write_text("\n".join(part for part in parts if part or part == ""), encoding="utf-8")
    return path


def save_creation_report_md(
    run_dir: Path,
    user_input,
    settings,
    planner_result: dict,
    writer_result: dict,
    reviewer_result: dict,
    trace: list,
    images: list,
    metrics: dict,
) -> Path:
    user = _plain(user_input)
    trace_rows = "\n".join(
        f"- {item.stage_name} | {item.model} | {item.status} | "
        f"{item.elapsed_seconds}s | {item.usage.total_tokens} tokens"
        for item in trace
    )
    image_rows = "\n".join(
        f"- **{item.name}**：{item.prompt}\n  - 负面提示词：{item.negative_prompt}"
        for item in images
    ) or "- 无"
    report = f"""# 2026世界杯新闻创作记录

## 用户需求

```json
{json.dumps(user, ensure_ascii=False, indent=2)}
```

## 使用模型

- 策划：{settings.planner_model}
- 写作：{settings.writer_model}
- 审校：{settings.reviewer_model}
- 图像：{settings.image_backend_label}

## 新闻策划

```json
{json.dumps(planner_result, ensure_ascii=False, indent=2)}
```

## 新闻初稿

### {writer_result.get('title', '')}

{writer_result.get('full_article', '')}

## 审校报告

{reviewer_result.get('review_summary', '')}

## 最终新闻稿

### {reviewer_result.get('final_title', '')}

{reviewer_result.get('final_article', '')}

## 图片提示词

{image_rows}

## 智能体执行轨迹

{trace_rows}

## 字数与Token统计

```json
{json.dumps(metrics, ensure_ascii=False, indent=2)}
```
"""
    path = run_dir / "creation_report.md"
    path.write_text(report, encoding="utf-8")
    return path
