import time
from pathlib import Path
from urllib.parse import urlparse

import requests


class TTAPIVeoError(RuntimeError):
    pass


class TTAPIVeoClient:
    """TTAPI adapter for asynchronous Gemini Video (Veo) jobs."""

    SUCCESS_STATES = {"SUCCESS", "COMPLETED", "DONE"}
    FAILURE_STATES = {"FAILED", "FAILURE", "ERROR", "CANCELLED", "TIMEOUT"}

    def __init__(self, settings):
        self.settings = settings
        if not settings.ttapi_video_api_key:
            raise TTAPIVeoError("尚未配置 TTAPI_VIDEO_API_KEY")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            self.settings.ttapi_video_api_key_header: self.settings.ttapi_video_api_key,
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.settings.ttapi_video_base_url.rstrip('/')}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = requests.request(
                method,
                self._url(path),
                headers=self._headers,
                timeout=(30, 90),
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            raise TTAPIVeoError(f"TTAPI Veo 请求失败：{error}") from error
        except ValueError as error:
            raise TTAPIVeoError("TTAPI Veo 返回内容不是 JSON") from error
        if not isinstance(payload, dict):
            raise TTAPIVeoError("TTAPI Veo 返回内容格式无效")
        if str(payload.get("status", "")).upper() in self.FAILURE_STATES:
            raise TTAPIVeoError(payload.get("message") or "TTAPI Veo 任务失败")
        return payload

    @staticmethod
    def _job_id(payload: dict) -> str:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        return str(data.get("jobId") or payload.get("jobId") or "").strip()

    def create_video(self, prompt: str, aspect_ratio: str, model: str) -> str:
        payload = self._request(
            "POST",
            self.settings.ttapi_video_generate_path,
            json={
                "prompt": prompt,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "resolution": "720p",
                "duration": "8",
            },
        )
        job_id = self._job_id(payload)
        if not job_id:
            raise TTAPIVeoError("TTAPI Veo 响应中未找到 jobId")
        return job_id

    def fetch(self, job_id: str) -> dict:
        return self._request(
            "GET", self.settings.ttapi_video_fetch_path, params={"jobId": job_id}
        )

    def poll_until_ready(self, job_id: str) -> tuple[str, dict]:
        deadline = time.monotonic() + self.settings.ttapi_video_poll_timeout_seconds
        while time.monotonic() < deadline:
            payload = self.fetch(job_id)
            status = str(payload.get("status", "")).upper()
            if status in self.FAILURE_STATES:
                raise TTAPIVeoError(payload.get("message") or "TTAPI Veo 任务失败")
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            video_url = str(data.get("video_url") or data.get("videoUrl") or "").strip()
            if status in self.SUCCESS_STATES and video_url:
                return video_url, payload
            time.sleep(self.settings.ttapi_poll_interval_seconds)
        raise TimeoutError(f"TTAPI Veo 任务 {job_id} 在规定时间内未完成")

    def download_video(self, video_url: str, output_path: Path) -> None:
        try:
            response = requests.get(video_url, timeout=(30, 180), allow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            suffix = Path(urlparse(video_url).path).suffix.lower()
            if not content_type.startswith("video/") and suffix not in {".mp4", ".webm", ".mov"}:
                raise TTAPIVeoError("TTAPI Veo 下载内容不是可识别的视频")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
        except requests.RequestException as error:
            raise TTAPIVeoError(f"TTAPI Veo 视频下载失败：{error}") from error

