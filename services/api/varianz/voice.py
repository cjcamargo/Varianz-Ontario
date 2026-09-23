from __future__ import annotations

import httpx

from .config import Settings


class LiveSessionUnavailable(RuntimeError):
    def __init__(self, code: str, status_code: int = 503):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class SpeechUnavailable(RuntimeError):
    pass


def create_live_session(sdp: str, session: dict, settings: Settings) -> dict:
    """Open a GPT-Live WebRTC session server-side so the API key never reaches the browser."""
    if not settings.openai_api_key:
        raise LiveSessionUnavailable("openai_not_configured")
    try:
        with httpx.Client(timeout=settings.openai_timeout_seconds) as client:
            response = client.post(
                "https://api.openai.com/v1/live/sessions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"session": session, "transport": {"type": "webrtc", "sdp": sdp}},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {400, 422}:
            raise LiveSessionUnavailable("invalid_live_session_request", 422) from exc
        if status == 429:
            raise LiveSessionUnavailable("live_rate_limited", 429) from exc
        if status in {401, 403}:
            raise LiveSessionUnavailable("openai_auth_error") from exc
        if status == 404:
            raise LiveSessionUnavailable("live_model_unavailable") from exc
        raise LiveSessionUnavailable("openai_live_unavailable") from exc
    except httpx.TimeoutException as exc:
        raise LiveSessionUnavailable("live_session_timeout", 504) from exc
    except httpx.RequestError as exc:
        raise LiveSessionUnavailable("openai_connection_unavailable") from exc
    try:
        payload = response.json()
        answer = str(payload["transport"]["sdp"])
        live_id = str(payload.get("session", {}).get("id", ""))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LiveSessionUnavailable("invalid_live_session_response") from exc
    if not answer.strip():
        raise LiveSessionUnavailable("invalid_live_session_response")
    return {"sdp": answer, "live_session_id": live_id}


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
