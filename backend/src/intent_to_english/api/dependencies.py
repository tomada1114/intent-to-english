"""FastAPI dependencies that hand routes the services from the composition root."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import Depends, Request

from intent_to_english.core.services import ConversationService

if TYPE_CHECKING:
    from intent_to_english.composition import Container


def get_conversation_service(request: Request) -> ConversationService:
    """Read the conversation service owned by this application's container."""
    container: Container = request.app.state.container
    return container.conversations


ConversationServiceDep = Annotated[
    ConversationService, Depends(get_conversation_service)
]
"""The process-owned conversation service."""


def get_model_mode(request: Request) -> Literal["fixed", "anthropic"]:
    """Read the selected mode rather than inferring it from settings again."""
    container: Container = request.app.state.container
    return container.model_mode


ModelModeDep = Annotated[Literal["fixed", "anthropic"], Depends(get_model_mode)]
"""The mode selected by the injected container."""
