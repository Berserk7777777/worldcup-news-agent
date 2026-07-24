import base64
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from openai import OpenAI

from schemas import StageUsage
from utils import sanitize_error_message, strip_json_code_fence


class ConfigurationError(Exception):
    pass


class ModelOutputError(Exception):
    pass


class ImageGenerationError(Exception):
    pass


class SiliconFlowClient:
    def __init__(self, settings):
        if not settings.api_key:
            raise ConfigurationError("缺少SILICONFLOW_API_KEY")
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.request_timeout,
            max_retries=0,
        )

    def call_json_model(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> tuple[dict, StageUsage]:
        request = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if not getattr(self.settings, "llm_enable_thinking", False):
            request["extra_body"] = {"enable_thinking": False}
        try:
            response = self.client.chat.completions.create(**request)
        except Exception as error:
            message = str(error).lower()
            unsupported_thinking = (
                "enable_thinking" in message
                and ("not support" in message or "20015" in message)
            )
            if not unsupported_thinking or "extra_body" not in request:
                raise
            request.pop("extra_body", None)
            response = self.client.chat.completions.create(**request)
        if not response.choices:
            raise ModelOutputError("模型返回空choices")
        content = response.choices[0].message.content
        if not content:
            raise ModelOutputError("模型返回空内容")
        try:
            data = json.loads(strip_json_code_fence(content))
        except json.JSONDecodeError as error:
            excerpt = sanitize_error_message(Exception(content[:300]), self.settings.api_key)
            raise ModelOutputError(f"模型返回非法JSON：{excerpt}") from error
        usage = response.usage
        return data, StageUsage(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
        )

    def stream_chat(
        self,
        model: str,
        history: list[dict],
    ):
        messages = [{
            "role": "system",
            "content": (
                "你是一个以2026世界杯为主要专业领域的中文智能助手，也能正常"
                "进行日常对话、解释概念和回答一般问题。回答自然、直接、简洁。"
                "对于可能变化的实时赛事事实，如果对话中没有可靠来源，应明确"
                "说明暂时无法核实，不得编造。"
            ),
        }]
        messages.extend([
            {"role": item.get("role", ""), "content": item.get("content", "")}
            for item in history[-9:]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ])
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=1200,
            stream=True,
            extra_body={"enable_thinking": False},
        )
        for chunk in response:
            if not chunk.choices:
                continue
            content = getattr(chunk.choices[0].delta, "content", None)
            if content:
                yield content

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding 输入不能为空")
        response = self.client.embeddings.create(
            model=self.settings.embedding_model,
            input=texts,
            encoding_format="float",
        )
        return [
            list(item.embedding)
            for item in sorted(response.data, key=lambda item: item.index)
        ]

    def summarize_to_chinese(self, title: str, content: str) -> str:
        response = self.client.chat.completions.create(
            model=self.settings.chat_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是世界杯资料编辑。将外文原文概括为150至250字中文摘要，"
                        "保留可核实的人名、球队、比赛、日期和数据，不添加原文没有"
                        "的信息。只输出摘要正文。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"标题：{title}\n\n原文：{content[:8000]}",
                },
            ],
            temperature=0.1,
            max_tokens=500,
            stream=False,
            extra_body={"enable_thinking": False},
        )
        if not response.choices or not response.choices[0].message.content:
            raise ModelOutputError("中文摘要模型未返回内容")
        return response.choices[0].message.content.strip()

    def build_search_query(self, topic: str) -> str:
        response = self.client.chat.completions.create(
            model=self.settings.chat_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "把用户的中文世界杯新闻主题转换成一行简短英文搜索关键词。"
                        "保留球员、球队、比赛阶段、年份和用户需要的具体事实类型，"
                        "例如 goals、assists、match report、records。不要回答问题，"
                        "不要解释，不要使用引号或标点。"
                    ),
                },
                {"role": "user", "content": topic[:500]},
            ],
            temperature=0,
            max_tokens=80,
            stream=False,
            extra_body={"enable_thinking": False},
        )
        if not response.choices or not response.choices[0].message.content:
            raise ModelOutputError("实时搜索词模型未返回内容")
        return re.sub(r"\s+", " ", response.choices[0].message.content).strip()

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str = "recording.wav",
        content_type: str = "audio/wav",
    ) -> str:
        try:
            response = requests.post(
                f"{self.settings.base_url.rstrip('/')}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                files={"file": (filename, audio_bytes, content_type)},
                data={"model": self.settings.asr_model},
                timeout=self.settings.request_timeout,
            )
            response.raise_for_status()
            text = response.json().get("text", "").strip()
        except (requests.RequestException, ValueError) as error:
            raise ModelOutputError(
                sanitize_error_message(error, self.settings.api_key)
            ) from error
        if not text:
            raise ModelOutputError("语音识别接口未返回文字")
        return text

    def synthesize_speech(
        self,
        text: str,
        output_path: Path,
        voice: str = "",
        speed: float = 1.0,
    ) -> None:
        if not text.strip():
            raise ValueError("语音合成文本不能为空")
        model = self.settings.tts_model
        selected_voice = voice or self.settings.tts_voice
        try:
            response = requests.post(
                f"{self.settings.base_url.rstrip('/')}/audio/speech",
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "voice": selected_voice,
                    "input": text,
                    "response_format": "mp3",
                    "speed": min(2.0, max(0.5, float(speed))),
                },
                timeout=self.settings.request_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise ModelOutputError(
                "语音合成失败："
                + sanitize_error_message(error, self.settings.api_key)
            ) from error
        content_type = response.headers.get("Content-Type", "").lower()
        if "json" in content_type:
            detail = sanitize_error_message(
                Exception(response.text[:500]), self.settings.api_key
            )
            raise ModelOutputError(f"语音合成未返回音频：{detail}")
        if not response.content:
            raise ModelOutputError("语音合成接口返回了空音频")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)

    def analyze_image(
        self,
        image_bytes: bytes,
        content_type: str,
        user_prompt: str,
    ) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = self.client.chat.completions.create(
            model=self.settings.vision_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是体育新闻图片资料编辑。客观描述图片中的可见人物、"
                        "场景、文字和事件线索；明确区分可见事实与推测，不得把"
                        "无法确认的身份、时间、地点或比赛结果写成事实。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"用户的新闻需求：{user_prompt or '根据图片创作世界杯新闻'}。"
                                "请提取可供新闻策划参考的图片信息。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{encoded}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            temperature=0.1,
            max_tokens=800,
            stream=False,
        )
        if not response.choices or not response.choices[0].message.content:
            raise ModelOutputError("图片理解接口未返回内容")
        return response.choices[0].message.content.strip()

    def generate_image(
        self, model: str, prompt: str, negative_prompt: str, image_size: str
    ) -> tuple[str, int | None]:
        try:
            response = requests.post(
                f"{self.settings.base_url.rstrip('/')}/images/generations",
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "image_size": image_size,
                    "batch_size": 1,
                },
                timeout=self.settings.request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise ImageGenerationError(
                sanitize_error_message(error, self.settings.api_key)
            ) from error
        images = payload.get("images") or []
        if not images or not images[0].get("url"):
            raise ImageGenerationError("图片接口未返回有效images")
        return images[0]["url"], payload.get("seed", images[0].get("seed"))

    def download_image(self, image_url: str, output_path: Path) -> None:
        try:
            response = requests.get(image_url, timeout=self.settings.request_timeout)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            url_suffix = Path(urlparse(image_url).path).suffix.lower()
            if not content_type.startswith("image/") and url_suffix not in {
                ".png", ".jpg", ".jpeg", ".webp"
            }:
                raise ImageGenerationError("下载内容不是可识别的图片")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
            temp_path.write_bytes(response.content)
            temp_path.replace(output_path)
        except (requests.RequestException, OSError) as error:
            raise ImageGenerationError(
                sanitize_error_message(error, self.settings.api_key)
            ) from error
