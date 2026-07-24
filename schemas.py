from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserInput:
    reporting_mode: str
    topic: str
    news_type: str
    audience: str
    writing_style: str
    factual_material: str
    image_style: str
    image_count: int
    image_usage: str = "图片作为新闻资料"
    midjourney_reference_url: str = ""
    midjourney_reference_description: str = ""
    midjourney_image_weight: float = 1.5
    source_image_caption: str = ""
    source_image_credit: str = ""
    source_image_url: str = ""
    source_image_placement: str = "after_lead"
    include_uploaded_image: bool = True


@dataclass
class StageUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class StageTrace:
    stage_name: str
    model: str
    purpose: str
    elapsed_seconds: float
    usage: StageUsage = field(default_factory=StageUsage)
    status: str = "completed"
    output_summary: str = ""


@dataclass
class GeneratedImage:
    name: str
    prompt: str
    negative_prompt: str
    source_url: str
    local_path: str
    seed: int | None = None
    error: str = ""
    provider_job_id: str = ""
    candidate_label: str = ""
    image_id: str = ""
    kind: str = "ai"
    caption: str = ""
    credit: str = ""
    placement: str = "after_paragraph_2"
    selected: bool = True
    ai_disclosure: str = "AI生成示意图"


@dataclass
class ImageAction:
    label: str
    action_id: str


@dataclass
class ImageCandidate:
    label: str
    source_url: str
    local_path: str = ""
    action_id: str = ""


@dataclass
class MidJourneyJob:
    job_id: str
    prompt: str
    status: str = "PENDING"
    message: str = ""
    requested_action: str = ""
    grid_url: str = ""
    grid_local_path: str = ""
    candidates: list[ImageCandidate] = field(default_factory=list)
    actions: list[ImageAction] = field(default_factory=list)
    final_image_url: str = ""
    final_image_local_path: str = ""
    provider_payload: dict[str, Any] = field(default_factory=dict)
