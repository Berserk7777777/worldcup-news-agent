import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Settings:
    api_key: str = ""
    base_url: str = "https://api.siliconflow.cn/v1"
    planner_model: str = ""
    writer_model: str = ""
    reviewer_model: str = ""
    image_model: str = ""
    image_provider: str = "siliconflow"
    ttapi_image_api_key: str = ""
    ttapi_image_api_key_header: str = "TT-API-KEY"
    ttapi_base_url: str = "https://api.ttapi.io"
    ttapi_get_u_images: bool = False
    ttapi_imagine_path: str = "/midjourney/v1/imagine"
    ttapi_fetch_path: str = "/midjourney/v1/fetch"
    ttapi_action_path: str = "/midjourney/v1/action"
    ttapi_fetch_method: str = "GET"
    ttapi_action_field: str = "action"
    ttapi_request_timeout_seconds: float = 30.0
    ttapi_poll_interval_seconds: float = 5.0
    ttapi_poll_timeout_seconds: float = 300.0
    chat_model: str = "Qwen/Qwen3.5-9B"
    llm_enable_thinking: bool = False
    vision_model: str = "Qwen/Qwen3-VL-32B-Instruct"
    asr_model: str = "FunAudioLLM/SenseVoiceSmall"
    embedding_model: str = "BAAI/bge-m3"
    image_size: str = "1024x1024"
    request_timeout: int = 120

    @property
    def image_backend_label(self) -> str:
        if self.image_provider == "ttapi":
            return "MidJourney via TTAPI"
        return self.image_model


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def load_settings() -> Settings:
    load_dotenv()
    try:
        timeout = int(os.getenv("REQUEST_TIMEOUT", "120"))
    except ValueError:
        timeout = 120
    return Settings(
        api_key=os.getenv("SILICONFLOW_API_KEY", ""),
        base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        planner_model=os.getenv("PLANNER_MODEL", ""),
        writer_model=os.getenv("WRITER_MODEL", ""),
        reviewer_model=os.getenv("REVIEWER_MODEL", ""),
        image_model=os.getenv("IMAGE_MODEL", ""),
        image_provider=os.getenv("IMAGE_PROVIDER", "siliconflow").strip().lower(),
        ttapi_image_api_key=os.getenv("TTAPI_IMAGE_API_KEY", ""),
        ttapi_image_api_key_header=os.getenv(
            "TTAPI_IMAGE_API_KEY_HEADER", "TT-API-KEY"
        ),
        ttapi_base_url=os.getenv(
            "TTAPI_IMAGE_BASE_URL",
            os.getenv("TTAPI_BASE_URL", "https://api.ttapi.io"),
        ).rstrip("/"),
        ttapi_get_u_images=_env_bool("TTAPI_GET_U_IMAGES", False),
        ttapi_imagine_path=os.getenv(
            "TTAPI_IMAGINE_PATH", "/midjourney/v1/imagine"
        ),
        ttapi_fetch_path=os.getenv("TTAPI_FETCH_PATH", "/midjourney/v1/fetch"),
        ttapi_action_path=os.getenv("TTAPI_ACTION_PATH", "/midjourney/v1/action"),
        ttapi_fetch_method=os.getenv("TTAPI_FETCH_METHOD", "GET").upper(),
        ttapi_action_field=os.getenv("TTAPI_ACTION_FIELD", "action"),
        ttapi_request_timeout_seconds=_env_float(
            "TTAPI_REQUEST_TIMEOUT_SECONDS", 30
        ),
        ttapi_poll_interval_seconds=_env_float("TTAPI_POLL_INTERVAL_SECONDS", 5),
        ttapi_poll_timeout_seconds=_env_float("TTAPI_POLL_TIMEOUT_SECONDS", 300),
        chat_model=os.getenv("CHAT_MODEL", "Qwen/Qwen3.5-9B"),
        llm_enable_thinking=_env_bool("SILICONFLOW_ENABLE_THINKING", False),
        vision_model=os.getenv("VISION_MODEL", "Qwen/Qwen3-VL-32B-Instruct"),
        asr_model=os.getenv("ASR_MODEL", "FunAudioLLM/SenseVoiceSmall"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
        image_size=os.getenv("IMAGE_SIZE", "1024x1024"),
        request_timeout=timeout,
    )


def get_missing_configs(settings: Settings) -> list[str]:
    fields = {
        "SILICONFLOW_API_KEY": settings.api_key,
        "PLANNER_MODEL": settings.planner_model,
        "WRITER_MODEL": settings.writer_model,
        "REVIEWER_MODEL": settings.reviewer_model,
        "EMBEDDING_MODEL": settings.embedding_model,
    }
    if settings.image_provider == "ttapi":
        fields["TTAPI_IMAGE_API_KEY"] = settings.ttapi_image_api_key
    else:
        fields["IMAGE_MODEL"] = settings.image_model
    return [name for name, value in fields.items() if not value.strip()]
