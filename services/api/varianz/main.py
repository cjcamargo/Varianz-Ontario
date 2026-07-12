from datetime import datetime
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .analytics import dashboard_snapshot
from .agent import AgentUnavailable, explain_dashboard
from .config import settings
from .dataset import load_replay_frame, quality_report
from .replay import ReplaySession

app = FastAPI(title="Varianz API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "Idempotency-Key"],
)
api = APIRouter(prefix="/api/v1")
sessions: dict[UUID, ReplaySession] = {}


class ReplayMutation(BaseModel):
    action: str
    expected_revision: int
    value: float | datetime | None = None


class AgentQuestion(BaseModel):
    question: str


@api.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}


@api.get("/demo/profile")
def demo_profile():
    return quality_report(settings.dataset_zip)


@api.post("/replay-sessions")
def create_replay_session():
    frame = load_replay_frame(settings.dataset_zip)
    session = ReplaySession.create(
        uuid4(), frame.observed_at.min().to_pydatetime(), frame.observed_at.max().to_pydatetime()
    )
    sessions[session.id] = session
    return session


@api.patch("/replay-sessions/{session_id}")
def update_replay_session(session_id: UUID, mutation: ReplayMutation):
    if session_id not in sessions:
        raise HTTPException(404, "replay_session_not_found")
    try:
        sessions[session_id] = sessions[session_id].mutate(
            mutation.action, mutation.expected_revision, value=mutation.value
        )
    except ValueError as exc:
        raise HTTPException(
            409 if str(exc) == "replay_revision_conflict" else 422, str(exc)
        ) from exc
    return sessions[session_id]


@api.get("/replay-sessions/{session_id}/snapshot")
def replay_snapshot(session_id: UUID):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "replay_session_not_found")
    cursor = session.effective_cursor()
    frame = load_replay_frame(settings.dataset_zip)
    visible = frame[frame.observed_at <= cursor].tail(1)
    values = (
        {}
        if visible.empty
        else {
            key: (None if value != value else value)
            for key, value in visible.iloc[0].items()
            if key != "observed_at"
        }
    )
    return {
        "session_id": session.id,
        "revision": session.revision,
        "cursor": cursor,
        "values": values,
    }


@api.get("/replay-sessions/{session_id}/dashboard")
def replay_dashboard(session_id: UUID):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "replay_session_not_found")
    return {
        "session_id": session.id,
        "revision": session.revision,
        "playing": session.playing,
        "speed": session.speed,
        **dashboard_snapshot(settings.dataset_zip, session.effective_cursor()),
    }


@api.post("/replay-sessions/{session_id}/agent/explain")
def agent_explain(session_id: UUID, request: AgentQuestion):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "replay_session_not_found")
    question = request.question.strip()
    if not 3 <= len(question) <= 1000:
        raise HTTPException(422, "question_length_out_of_range")
    evidence = dashboard_snapshot(settings.dataset_zip, session.effective_cursor())
    try:
        return explain_dashboard(question, evidence, settings)
    except AgentUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, "openai_upstream_error") from exc


app.include_router(api)
