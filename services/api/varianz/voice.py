from __future__ import annotations

import httpx

from .config import Settings


class TranscriptionUnavailable(RuntimeError):
    def __init__(self, code: str, status_code: int = 503):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class SpeechUnavailable(RuntimeError):
    pass


async def transcribe_audio(
    content: bytes,
    filename: str,
    content_type: str,
    settings: Settings,
) -> dict:
    if not settings.openai_api_key:
        raise TranscriptionUnavailable("openai_not_configured")
    try:
        async with httpx.AsyncClient(timeout=settings.openai_timeout_seconds) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                files={"file": (filename, content, content_type)},
                data={
                    "model": settings.openai_transcription_model,
                    "response_format": "json",
                    "prompt": (
                        "Varianz greenhouse operations: Wageningen, heating, electricity, "
                        "carbon dioxide, irrigation, drainage, humidity deficit, setpoints."
                    ),
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {400, 422}:
            raise TranscriptionUnavailable("invalid_audio", 422) from exc
        if status == 413:
            raise TranscriptionUnavailable("audio_too_large", 413) from exc
        if status == 429:
            raise TranscriptionUnavailable("transcription_rate_limited", 429) from exc
        if status in {401, 403}:
            raise TranscriptionUnavailable("openai_auth_error") from exc
        if status == 404:
            raise TranscriptionUnavailable("transcription_model_unavailable") from exc
        raise TranscriptionUnavailable("openai_transcription_unavailable") from exc
    except httpx.TimeoutException as exc:
        raise TranscriptionUnavailable("transcription_timeout", 504) from exc
    except httpx.RequestError as exc:
        raise TranscriptionUnavailable("openai_connection_unavailable") from exc
    try:
        text = str(response.json().get("text", "")).strip()
    except (ValueError, AttributeError) as exc:
        raise TranscriptionUnavailable("invalid_transcription_response") from exc
    if not text:
        raise TranscriptionUnavailable("empty_transcription")
    return {"text": text, "model": settings.openai_transcription_model}


async def synthesize_speech(text: str, language: str, settings: Settings) -> dict:
    if not settings.openai_api_key:
        raise SpeechUnavailable("openai_not_configured")
    try:
        async with httpx.AsyncClient(timeout=settings.openai_timeout_seconds) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_speech_model,
                    "voice": settings.openai_voice,
                    "input": text,
                    "response_format": "mp3",
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SpeechUnavailable("openai_speech_error") from exc
    except httpx.RequestError as exc:
        raise SpeechUnavailable("openai_connection_unavailable") from exc
    if not response.content:
        raise SpeechUnavailable("empty_speech")
    return {
        "audio": response.content,
        "content_type": "audio/mpeg",
        "model": settings.openai_speech_model,
        "voice": settings.openai_voice,
        "language": language,
    }
