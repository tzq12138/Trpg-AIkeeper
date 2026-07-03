"""STT (Speech-to-Text) provider layer — pluggable disabled / mock / http implementations."""

import logging
import tempfile
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {
    "audio/webm", "audio/webm;codecs=opus", "audio/mp4", "audio/aac",
    "audio/webm; codecs=opus", "audio/ogg", "audio/wav", "audio/mpeg",
}
MAX_AUDIO_BYTES = 8 * 1024 * 1024  # 8MB
MAX_DURATION_SECONDS = 30


class BaseSttProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, mime_type: str) -> dict:
        """Return {'transcribedText': str, 'confidence': float|None} or {'error': str}"""
        ...


class DisabledSttProvider(BaseSttProvider):
    def __init__(self):
        super().__init__()

    async def transcribe(self, audio_bytes: bytes, mime_type: str) -> dict:
        return {"error": "STT not configured. Set STT_PROVIDER=mock or STT_PROVIDER=http."}


class MockSttProvider(BaseSttProvider):
    async def transcribe(self, audio_bytes: bytes, mime_type: str) -> dict:
        # Simulate processing delay
        import asyncio
        await asyncio.sleep(0.3)
        return {
            "transcribedText": f"[测试转写] 这是模拟的语音转写结果。音频大小 {len(audio_bytes)} 字节，格式 {mime_type}。",
            "confidence": 0.95,
        }


class HttpSttProvider(BaseSttProvider):
    def __init__(self, url: str, api_key: str = "", model: str = ""):
        self.url = url
        self.api_key = api_key
        self.model = model

    async def transcribe(self, audio_bytes: bytes, mime_type: str) -> dict:
        # Write audio to temp file for multipart upload
        suffix = _mime_to_suffix(mime_type)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name

            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with httpx.AsyncClient(timeout=30) as client:
                with open(tmp_path, "rb") as f:
                    files = {"audio": (f"recording{suffix}", f, mime_type)}
                    form_data = {}
                    if self.model:
                        form_data["model"] = self.model
                    resp = await client.post(
                        self.url, headers=headers, files=files, data=form_data,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return _normalize_http_response(data)
        except Exception as e:
            logger.warning("HTTP STT failed: %s", e)
            return {"error": f"STT HTTP service error: {e}"}
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def _mime_to_suffix(mime: str) -> str:
    mime_lower = mime.lower()
    if "webm" in mime_lower:
        return ".webm"
    if "mp4" in mime_lower:
        return ".mp4"
    if "aac" in mime_lower:
        return ".aac"
    if "ogg" in mime_lower:
        return ".ogg"
    if "wav" in mime_lower:
        return ".wav"
    if "mpeg" in mime_lower or "mp3" in mime_lower:
        return ".mp3"
    return ".webm"


def _normalize_http_response(data: dict) -> dict:
    """Normalize common STT HTTP API response formats."""
    # OpenAI Whisper API format
    if "text" in data:
        return {"transcribedText": data["text"], "confidence": data.get("confidence")}
    # Generic format
    if "transcribedText" in data:
        return data
    if "transcript" in data:
        return {"transcribedText": data["transcript"]}
    if "result" in data:
        return {"transcribedText": str(data["result"])}
    # Fallback
    return {"transcribedText": str(data), "confidence": None}


def get_stt_provider(settings=None) -> BaseSttProvider:
    """Factory: load provider from environment or settings object."""
    provider_name = os.getenv("STT_PROVIDER", "disabled")
    if settings and hasattr(settings, 'stt_provider'):
        provider_name = settings.stt_provider

    if provider_name == "mock":
        return MockSttProvider()
    if provider_name == "http":
        url = os.getenv("STT_HTTP_URL", "")
        if settings and hasattr(settings, 'stt_http_url'):
            url = settings.stt_http_url
        api_key = os.getenv("STT_HTTP_API_KEY", "")
        if settings and hasattr(settings, 'stt_http_api_key'):
            api_key = settings.stt_http_api_key
        model = os.getenv("STT_MODEL", "")
        if url:
            return HttpSttProvider(url, api_key, model)
        return DisabledSttProvider()
    return DisabledSttProvider()
