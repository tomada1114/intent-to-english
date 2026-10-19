"""FastAPI dependencies that hand routes the services from the composition root."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import Depends, Request

from intent_to_english.core.services import ConversationService, TodoService

if TYPE_CHECKING:
    from intent_to_english.composition import Container


def get_todo_service(request: Request) -> TodoService:
    """Hand a route the to-do service from the container ``create_app`` stored.

    Reading it from the app, not a module global, lets every ``create_app``
    call — one per test — own an independent store.

    Args:
        request: The current request, which carries its application.

    Returns:
        The application's ``TodoService``.
    """
    container: Container = request.app.state.container
    return container.todos


TodoServiceDep = Annotated[TodoService, Depends(get_todo_service)]
"""Declare a route parameter with this type to receive the ``TodoService``."""


def get_conversation_service(request: Request) -> ConversationService:
    """Read the conversation service owned by this application's container."""
    container: Container = request.app.state.container
    return container.conversations


ConversationServiceDep = Annotated[
    ConversationService, Depends(get_conversation_service)
]
"""The process-owned conversation service."""


def get_model_mode(request: Request) -> Literal["fixed", "openrouter"]:
    """Read the selected mode rather than inferring it from settings again."""
    container: Container = request.app.state.container
    return container.model_mode


ModelModeDep = Annotated[Literal["fixed", "openrouter"], Depends(get_model_mode)]
"""The mode selected by the injected container."""
