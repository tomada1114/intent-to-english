"""The reported mode belongs to the injected process container."""

from __future__ import annotations

from dataclasses import replace
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from intent_to_english.api.app import create_app
from intent_to_english.settings import Settings


@pytest.mark.parametrize("mode", ["fixed", "anthropic"])
def test_meta_reads_the_supplied_container_mode(make_container, mode):
    container = replace(make_container(), model_mode=mode)
    with TestClient(create_app(container=container)) as client:
        response = client.get("/api/meta")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"model_mode": mode}


def test_meta_with_auto_and_key_selects_anthropic_without_model_requests():
    with TestClient(
        create_app(Settings(ANTHROPIC_API_KEY=SecretStr("dummy-key")))
    ) as client:
        response = client.get("/api/meta")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"model_mode": "anthropic"}
