from __future__ import annotations

import httpx

from .config import Settings


class TranscriptionUnavailable(RuntimeError):
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
        raise TranscriptionUnavailable("openai_transcription_error") from exc
    except httpx.RequestError as exc:
        raise TranscriptionUnavailable("openai_connection_unavailable") from exc
    text = str(response.json().get("text", "")).strip()
    if not text:
        raise TranscriptionUnavailable("empty_transcription")
    return {"text": text, "model": settings.openai_transcription_model}
