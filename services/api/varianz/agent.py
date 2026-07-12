from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from .config import Settings

SYSTEM_INSTRUCTIONS = """You are Varianz, an operational-intelligence assistant for greenhouse operators.
Use only the supplied evidence. Never invent measurements, claim causality, promise savings, or imply that
you control equipment. Clearly distinguish observed, calculated, predicted, and simulated values. Keep the
answer concise and operational. Cite evidence keys in square brackets, for example [kpis.daily_heat_mj_m2].
If evidence is insufficient, say so. Respond in English."""


@dataclass(frozen=True)
class AgentResult:
    answer: str
    model: str
    response_id: str
    evidence_version: str


class AgentUnavailable(RuntimeError):
    pass


def _extract_output_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if direct:
        return str(direct)
    parts = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def explain_dashboard(question: str, evidence: dict, settings: Settings) -> AgentResult:
    if not settings.openai_api_key:
        raise AgentUnavailable("OPENAI_API_KEY is not configured")
    safe_evidence = {
        "cursor": evidence["cursor"],
        "kpis": evidence["kpis"],
        "latest": evidence["latest"],
        "baseline": evidence["baseline"],
        "alerts": evidence["alerts"],
        "definitions_version": evidence["definitions_version"],
    }
    body = {
        "model": settings.openai_model,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": f"Operator question: {question}\nEvidence JSON:\n{json.dumps(safe_evidence)}",
        "max_output_tokens": settings.openai_max_output_tokens,
        "store": False,
    }
    with httpx.Client(timeout=settings.openai_timeout_seconds) as client:
        response = client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=body,
        )
        response.raise_for_status()
    payload = response.json()
    text = _extract_output_text(payload)
    if not text:
        raise AgentUnavailable("OpenAI returned no output text")
    return AgentResult(
        text, settings.openai_model, payload.get("id", "unknown"), evidence["definitions_version"]
    )
