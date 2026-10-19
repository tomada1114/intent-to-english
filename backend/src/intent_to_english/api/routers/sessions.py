"""Thin HTTP wrappers for the versioned conversation service."""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter

from intent_to_english.api.dependencies import ConversationServiceDep
from intent_to_english.api.schemas import (
    CancelSessionRequest,
    SessionActionBody,
    SessionPageResponse,
    SessionResponse,
    problem_responses,
)
from intent_to_english.core.models import SESSION_PAGE_LIMIT

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", status_code=HTTPStatus.CREATED, responses=problem_responses(422))
async def create_session(service: ConversationServiceDep) -> SessionResponse:
    """Create an opening session before any model request."""
    return SessionResponse.from_domain(await service.start())


@router.get("", responses=problem_responses(422))
async def list_sessions(
    service: ConversationServiceDep,
    cursor: str | None = None,
    limit: int = SESSION_PAGE_LIMIT,
) -> SessionPageResponse:
    """List one page of sessions, newest first."""
    return SessionPageResponse.from_domain(await service.list_page(cursor, limit))


@router.get("/{session_id}", responses=problem_responses(404, 422))
async def get_session(
    session_id: UUID, service: ConversationServiceDep
) -> SessionResponse:
    """Read a session's timeline and recoverable input."""
    return SessionResponse.from_domain(await service.get(session_id))


@router.post(
    "/{session_id}/actions", responses=problem_responses(404, 409, 422, 502, 503, 504)
)
async def perform_session_action(
    session_id: UUID, body: SessionActionBody, service: ConversationServiceDep
) -> SessionResponse:
    """Apply one action at the version the learner answered."""
    return SessionResponse.from_domain(await service.act(session_id, body.to_domain()))


@router.post(
    "/{session_id}/cancel",
    status_code=HTTPStatus.NO_CONTENT,
    responses=problem_responses(404, 422),
)
async def cancel_session_action(
    session_id: UUID, body: CancelSessionRequest, service: ConversationServiceDep
) -> None:
    """Cancel pending work at the supplied version, including an absent target."""
    await service.cancel(session_id, body.version)
