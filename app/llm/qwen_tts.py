from __future__ import annotations

import base64
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from app import config


@dataclass
class SpeechAudio:
    audio_base64: str
    content_type: str
    model: str
    voice: str


class QwenTTSClient:
    """Text-to-speech client using DashScope qwen_tts SDK."""

    def __init__(self) -> None:
        self.api_key = config.QWEN_API_KEY
        self.model = config.QWEN_TTS_MODEL
        self.voice = config.QWEN_TTS_VOICE
        self.response_format = config.QWEN_TTS_FORMAT

    @property
    def is_mock(self) -> bool:
        return config.FORCE_MOCK_LLM or not bool(self.api_key)

    def synthesize(self, text: str, voice: str | None = None) -> SpeechAudio:
        cleaned = _clean_tts_text(text)
        if not cleaned:
            raise ValueError("TTS text cannot be empty")
        if self.is_mock:
            raise RuntimeError("TTS requires DASHSCOPE_API_KEY or QWEN_API_KEY and FORCE_MOCK_LLM=0")

        selected_voice = (voice or self.voice).strip() or self.voice
        audio_bytes, content_type = self._call_dashscope_tts(cleaned, selected_voice)
        return SpeechAudio(
            audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
            content_type=content_type or _content_type_for_format(self.response_format),
            model=self.model,
            voice=selected_voice,
        )

    def _call_dashscope_tts(self, text: str, voice: str) -> tuple[bytes, str]:
        try:
            dashscope = _import_dashscope()
        except ImportError as exc:
            raise RuntimeError("请先安装 dashscope>=1.23.1：pip install -U dashscope") from exc

        try:
            response = dashscope.audio.qwen_tts.SpeechSynthesizer.call(
                model=self.model,
                api_key=self.api_key,
                text=text,
                voice=voice,
            )
        except Exception as exc:
            raise RuntimeError(f"TTS request failed: {exc}") from exc

        status_code = _lookup(response, "status_code")
        if status_code and int(status_code) >= 400:
            code = _lookup(response, "code") or ""
            message = _lookup(response, "message") or response
            raise RuntimeError(f"TTS request failed: {status_code} {code} {message}")

        audio_value = _find_audio_value(response)
        if audio_value is None:
            raise RuntimeError(f"TTS response has no audio data: {response}")
        return _audio_value_to_bytes(audio_value, _content_type_for_format(self.response_format))


def _clean_tts_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned[:6000]


def _import_dashscope() -> Any:
    base_site_packages = Path(sys.base_prefix) / "Lib" / "site-packages"
    if base_site_packages.exists():
        base_site_path = str(base_site_packages)
        if base_site_path not in sys.path:
            sys.path.append(base_site_path)

    import dashscope

    return dashscope


def _find_audio_value(response: Any) -> Any:
    candidates = [
        ("output", "audio", "data"),
        ("output", "audio", "url"),
        ("output", "audio_url"),
        ("output", "url"),
        ("audio", "data"),
        ("audio", "url"),
        ("audio_url",),
        ("url",),
    ]
    for path in candidates:
        value = _lookup_path(response, path)
        if value:
            return value
    return None


def _audio_value_to_bytes(value: Any, default_content_type: str) -> tuple[bytes, str]:
    if isinstance(value, bytes):
        return value, default_content_type
    if isinstance(value, bytearray):
        return bytes(value), default_content_type
    if not isinstance(value, str):
        raise RuntimeError(f"Unsupported TTS audio value: {type(value).__name__}")

    if value.startswith("http://") or value.startswith("https://"):
        try:
            response = requests.get(value, timeout=90)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"TTS audio download failed: {exc}") from exc
        return response.content, response.headers.get("content-type", default_content_type)

    if value.startswith("data:"):
        header, encoded = value.split(",", 1)
        content_type = header.split(";", 1)[0].replace("data:", "") or default_content_type
        try:
            return base64.b64decode(encoded), content_type
        except ValueError as exc:
            raise RuntimeError("TTS response contains invalid base64 audio data") from exc

    try:
        return base64.b64decode(value), default_content_type
    except ValueError as exc:
        raise RuntimeError("TTS response contains invalid base64 audio data") from exc


def _lookup_path(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for key in path:
        current = _lookup(current, key)
        if current is None:
            return None
    return current


def _lookup(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    if hasattr(value, key):
        return getattr(value, key)
    try:
        return value[key]
    except (KeyError, TypeError, IndexError):
        return None


def _content_type_for_format(audio_format: str) -> str:
    mapping = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "opus": "audio/opus",
        "aac": "audio/aac",
        "flac": "audio/flac",
    }
    return mapping.get((audio_format or "mp3").lower(), "audio/mpeg")
