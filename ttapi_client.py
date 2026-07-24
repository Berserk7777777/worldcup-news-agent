import dataclasses
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from config import Settings
from schemas import ImageAction, ImageCandidate, MidJourneyJob


class TTAPIError(RuntimeError):
    pass


class TTAPIMidJourneyClient:
    """TTAPI adapter for MidJourney Imagine, Fetch and U/V actions."""

    SUCCESS_STATES = {"SUCCESS", "SUCCEEDED", "COMPLETED", "DONE", "FINISHED"}
    FAILURE_STATES = {"FAIL", "FAILED", "ERROR", "CANCELLED", "CANCELED"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not settings.ttapi_image_api_key:
            raise TTAPIError("尚未配置 TTAPI_IMAGE_API_KEY")

    @property
    def headers(self) -> dict[str, str]:
        return {
            self.settings.ttapi_image_api_key_header: self.settings.ttapi_image_api_key,
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.settings.ttapi_base_url}/{path.lstrip('/')}"

    def _request_timeout(self) -> tuple[float, float]:
        read_timeout = max(
            1.0,
            float(getattr(self.settings, "ttapi_request_timeout_seconds", 30.0)),
        )
        return min(10.0, read_timeout), read_timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = requests.request(
                method,
                self._url(path),
                headers=self.headers,
                timeout=self._request_timeout(),
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError as error:
            detail = error.response.text[:500] if error.response is not None else str(error)
            status = error.response.status_code if error.response is not None else "unknown"
            raise TTAPIError(f"TTAPI 请求失败：HTTP {status}，{detail}") from error
        except (requests.RequestException, ValueError) as error:
            raise TTAPIError(f"TTAPI 请求失败：{error}") from error
        if not isinstance(payload, dict):
            raise TTAPIError("TTAPI 返回内容不是 JSON 对象")
        return payload

    def imagine(self, prompt: str) -> dict[str, Any]:
        return self._request(
            "POST",
            self.settings.ttapi_imagine_path,
            json={
                "prompt": prompt,
                "getUImages": self.settings.ttapi_get_u_images,
            },
        )

    def fetch(self, job_id: str) -> dict[str, Any]:
        payload = {"jobId": job_id}
        if self.settings.ttapi_fetch_method == "POST":
            return self._request("POST", self.settings.ttapi_fetch_path, json=payload)
        return self._request("GET", self.settings.ttapi_fetch_path, params=payload)

    def action(self, job_id: str, action_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            self.settings.ttapi_action_path,
            json={
                "jobId": job_id,
                self.settings.ttapi_action_field: action_id,
            },
        )

    @classmethod
    def _nodes(cls, payload: Any) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                nodes.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
        return nodes

    @staticmethod
    def _normalized(value: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

    @classmethod
    def _first_field(cls, payload: dict[str, Any], names: set[str]) -> Any:
        for node in cls._nodes(payload):
            for key, value in node.items():
                if cls._normalized(key) in names and value not in (None, ""):
                    return value
        return ""

    @classmethod
    def job_id_from(cls, payload: dict[str, Any]) -> str:
        value = cls._first_field(payload, {"jobid", "taskid"})
        if value:
            return str(value)
        for node in [payload, payload.get("data"), payload.get("result"), payload.get("output")]:
            if isinstance(node, dict) and node.get("id"):
                return str(node["id"])
        return ""

    @classmethod
    def status_from(cls, payload: dict[str, Any]) -> str:
        value = cls._first_field(payload, {"status", "state"}) or "PENDING"
        return str(value).upper()

    @classmethod
    def message_from(cls, payload: dict[str, Any]) -> str:
        value = cls._first_field(payload, {"message", "error", "description"})
        if isinstance(value, dict):
            return str(value.get("message") or value.get("detail") or value)
        return str(value or "")

    @classmethod
    def image_urls_from(cls, payload: dict[str, Any]) -> list[str]:
        values: list[Any] = []
        list_fields = {
            "imageurls", "images", "urls", "uimages", "uimageurls",
            "upscaledimages", "upscaledimageurls",
        }
        scalar_fields = {
            "imageurl", "image", "url", "gridurl", "gridimage",
            "resulturl", "outputurl", "imgurl", "img",
        }
        for node in cls._nodes(payload):
            for key, candidate in node.items():
                normalized = cls._normalized(key)
                if normalized in list_fields and isinstance(candidate, list):
                    values.extend(candidate)
                elif normalized in scalar_fields and candidate:
                    values.append(candidate)
        if not values:
            for node in cls._nodes(payload):
                for candidate in node.values():
                    if not isinstance(candidate, str):
                        continue
                    if not candidate.startswith(("http://", "https://")):
                        continue
                    if re.search(
                        r"(image|img|media|cdn|attachment)|\.(png|jpe?g|webp|avif)(?:\?|$)",
                        candidate,
                        re.IGNORECASE,
                    ):
                        values.append(candidate)
        result: list[str] = []
        for item in values:
            if isinstance(item, dict):
                item = item.get("url") or item.get("imageUrl") or item.get("image_url")
            if isinstance(item, str) and item.startswith(("http://", "https://")):
                if item not in result:
                    result.append(item)
        return result

    @classmethod
    def _action_label(cls, label: Any, action_id: Any) -> str:
        label_text = str(label or "").strip()
        compact = re.sub(r"[^A-Z0-9]", "", label_text.upper())
        match = re.search(r"([UV])([1-4])", compact)
        if match:
            return f"{match.group(1)}{match.group(2)}"

        action_text = str(action_id or "").lower()
        number_match = re.search(r"(?:^|::|_|-)([1-4])(?:$|::|_|-)", action_text)
        if not number_match:
            number_match = re.search(r"([1-4])$", action_text)
        if number_match and re.search(r"upsample|upscale", action_text):
            return f"U{number_match.group(1)}"
        if number_match and re.search(r"variation|vary", action_text):
            return f"V{number_match.group(1)}"
        return label_text

    @classmethod
    def actions_from(cls, payload: dict[str, Any]) -> list[ImageAction]:
        actions: list[ImageAction] = []
        seen: set[tuple[str, str]] = set()
        for node in cls._nodes(payload):
            for key, value in node.items():
                if cls._normalized(key) not in {"actions", "buttons", "components"}:
                    continue
                if not isinstance(value, list):
                    continue
                for item in value:
                    if not isinstance(item, str):
                        continue
                    label = cls._action_label(item, item)
                    if label and (label.upper(), item) not in seen:
                        seen.add((label.upper(), item))
                        actions.append(ImageAction(label=label, action_id=item))
        for node in cls._nodes(payload):
            action_id = (
                node.get("customId")
                or node.get("custom_id")
                or node.get("actionId")
                or node.get("action_id")
                or node.get("id")
                or node.get("value")
            )
            if not action_id:
                continue
            label = cls._action_label(
                node.get("label") or node.get("name") or node.get("emoji"),
                action_id,
            )
            if not label:
                continue
            key = (label.upper(), str(action_id))
            if key in seen:
                continue
            seen.add(key)
            actions.append(ImageAction(label=label, action_id=str(action_id)))
        return actions

    @classmethod
    def to_job(
        cls,
        payload: dict[str, Any],
        prompt: str,
        fallback_job_id: str = "",
        requested_action: str = "",
    ) -> MidJourneyJob:
        job_id = cls.job_id_from(payload) or fallback_job_id
        if not job_id:
            raise TTAPIError("TTAPI 响应中未找到 jobId")
        status = cls.status_from(payload)
        urls = cls.image_urls_from(payload)
        actions = cls.actions_from(payload)
        action_map = {item.label.upper(): item.action_id for item in actions}
        candidates: list[ImageCandidate] = []
        if len(urls) >= 4:
            for index, image_url in enumerate(urls[-4:], 1):
                candidates.append(
                    ImageCandidate(
                        label=f"候选 {index}",
                        source_url=image_url,
                        action_id=action_map.get(f"U{index}", ""),
                    )
                )
        grid_url = urls[0] if urls else ""
        requested = requested_action.upper()
        final_image_url = (
            grid_url
            if requested.startswith("U") and status in cls.SUCCESS_STATES and grid_url
            else ""
        )
        return MidJourneyJob(
            job_id=job_id,
            prompt=prompt,
            status=status,
            message=cls.message_from(payload),
            requested_action=requested_action,
            grid_url=grid_url,
            candidates=candidates,
            actions=actions,
            final_image_url=final_image_url,
            provider_payload=payload,
        )

    @staticmethod
    def to_dict(job: MidJourneyJob) -> dict[str, Any]:
        return dataclasses.asdict(job)

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> MidJourneyJob:
        return MidJourneyJob(
            job_id=payload["job_id"],
            prompt=payload.get("prompt", ""),
            status=payload.get("status", "PENDING"),
            message=payload.get("message", ""),
            requested_action=payload.get("requested_action", ""),
            grid_url=payload.get("grid_url", ""),
            grid_local_path=payload.get("grid_local_path", ""),
            candidates=[ImageCandidate(**item) for item in payload.get("candidates", [])],
            actions=[ImageAction(**item) for item in payload.get("actions", [])],
            final_image_url=payload.get("final_image_url", ""),
            final_image_local_path=payload.get("final_image_local_path", ""),
            provider_payload=payload.get("provider_payload", {}),
        )

    def create_job(self, prompt: str) -> MidJourneyJob:
        return self.to_job(self.imagine(prompt), prompt)

    def refresh_job(self, job: MidJourneyJob) -> MidJourneyJob:
        return self.to_job(
            self.fetch(job.job_id),
            job.prompt,
            fallback_job_id=job.job_id,
            requested_action=job.requested_action,
        )

    def submit_action(self, job: MidJourneyJob, action_label: str) -> MidJourneyJob:
        normalized = action_label.upper()
        matching = next(
            (item for item in job.actions if item.label.upper() == normalized),
            None,
        )
        if matching is None:
            available = ", ".join(item.label for item in job.actions) or "无"
            raise TTAPIError(
                f"TTAPI 响应中没有可用的 {normalized} Action ID；当前操作：{available}"
            )
        payload = self.action(job.job_id, matching.action_id)
        return self.to_job(
            payload,
            job.prompt,
            fallback_job_id=job.job_id,
            requested_action=normalized,
        )

    def is_ready(self, job: MidJourneyJob) -> bool:
        if job.status in self.FAILURE_STATES:
            return True
        if job.status not in self.SUCCESS_STATES:
            return False
        if job.requested_action.upper().startswith("U"):
            return bool(job.final_image_url)
        return bool(job.grid_url or job.candidates)

    def poll_until_ready(self, job: MidJourneyJob) -> MidJourneyJob:
        deadline = time.monotonic() + self.settings.ttapi_poll_timeout_seconds
        current = job
        while time.monotonic() < deadline:
            if self.is_ready(current):
                return current
            current = self.refresh_job(current)
            if current.status in self.FAILURE_STATES:
                raise TTAPIError(
                    current.message or f"TTAPI 任务失败：{current.status}"
                )
            if self.is_ready(current):
                return current
            time.sleep(self.settings.ttapi_poll_interval_seconds)
        raise TimeoutError(f"TTAPI 任务 {job.job_id} 在规定时间内未完成")

    def download_image(self, image_url: str, output_path: Path) -> None:
        try:
            response = requests.get(
                image_url,
                timeout=self._request_timeout(),
                allow_redirects=True,
            )
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            suffix = Path(urlparse(image_url).path).suffix.lower()
            if not content_type.startswith("image/") and suffix not in {
                ".png", ".jpg", ".jpeg", ".webp",
            }:
                raise TTAPIError("TTAPI 下载内容不是可识别的图片")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
            temp_path.write_bytes(response.content)
            temp_path.replace(output_path)
        except (requests.RequestException, OSError) as error:
            raise TTAPIError(f"TTAPI 图片下载失败：{error}") from error
