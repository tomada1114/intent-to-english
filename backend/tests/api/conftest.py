"""Fixtures for driving the FastAPI app."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from intent_to_english.adapters.memory import InMemorySessionRepository
from intent_to_english.adapters.models.fixed import FixedCoachModel
from intent_to_english.api.app import create_app
from intent_to_english.composition import Container, ModelPorts
from intent_to_english.core.services import ConversationService


@pytest.fixture
def client(make_container):
    """A client on an app built through the composition root.

    It gets an empty in-memory store and the fixed clock, so a response's
    ``created_at`` is known exactly.
    """
    with TestClient(create_app(container=make_container())) as test_client:
        yield test_client


@pytest.fixture
def start_session(client):
    """Create conversation state through its HTTP entry point."""

    def start():
        response = client.post("/api/sessions")
        assert response.status_code == HTTPStatus.CREATED, response.text
        return response.json()

    return start


@pytest.fixture
def act_session(client):
    """Send the displayed version with an action and return its accepted view."""

    def act(view, action, **fields):
        response = client.post(
            f"/api/sessions/{view['id']}/actions",
            json={"action": action, "version": view["version"], **fields},
        )
        assert response.status_code == HTTPStatus.OK, response.text
        return response.json()

    return act


@pytest.fixture
def conversation_container(fixed_clock, new_id, nth_id):
    """Inject a scripted Partner through the real memory conversation service."""

    def build(partner):
        models = ModelPorts(partner, FixedCoachModel())
        return Container(
            models=models,
            conversations=ConversationService(
                InMemorySessionRepository(),
                models.partner,
                models.coach,
                fixed_clock,
                new_id,
                nth_id(900),
            ),
        )

    return build
