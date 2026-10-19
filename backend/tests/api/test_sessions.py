"""The versioned conversation's HTTP contract and its safe failures."""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from intent_to_english.adapters.models.fixed import FixedPartnerModel
from intent_to_english.api.app import create_app
from intent_to_english.core import errors
from intent_to_english.core import models as m
from intent_to_english.core import partner as p


def test_create_session_returns_the_complete_opening_view(client, nth_id, fixed_now):
    response = client.post("/api/sessions")
    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body == {
        "id": str(nth_id(1)),
        "status": "in_progress",
        "stage": "opening",
        "version": 0,
        "turn_index": 1,
        "finished_replies": 0,
        "started_at": body["started_at"],
        "ended_at": None,
        "allowed_actions": ["open", "ask", "end"],
        "entries": [],
        "last_submission": None,
        "wrap_up": None,
    }
    assert datetime.fromisoformat(body["started_at"]) == fixed_now
    assert client.get(f"/api/sessions/{body['id']}").json() == body


def test_session_list_defaults_to_twenty_newest_first(client, start_session):
    created = [start_session() for _ in range(21)]
    response = client.get("/api/sessions")
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert [item["id"] for item in body["items"]] == [
        item["id"] for item in reversed(created[1:])
    ]
    assert body["items"][0] == {
        "id": created[-1]["id"],
        "started_at": created[-1]["started_at"],
        "status": "in_progress",
        "finished_replies": 0,
        "opener": None,
    }
    final = client.get("/api/sessions", params={"cursor": body["next_cursor"]}).json()
    assert [item["id"] for item in final["items"]] == [created[0]["id"]]
    assert final["next_cursor"] is None


@pytest.mark.parametrize("suffix", ["", "/actions", "/cancel"])
def test_unknown_session_returns_not_found(client, suffix):
    session_id = "00000000-0000-0000-0000-000000000000"
    path = f"/api/sessions/{session_id}{suffix}"
    response = (
        client.get(path)
        if not suffix
        else client.post(
            path,
            json={"action": "open", "version": 0}
            if suffix == "/actions"
            else {"version": 0},
        )
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "request_id": response.headers["X-Request-ID"],
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": f"Session {session_id} not found",
        "code": "session_not_found",
    }


@pytest.mark.parametrize(
    "case",
    [("intent", "", 1000), ("intent", "x" * 1001, 1000), ("ask", "x" * 501, 500)],
    ids=["empty-intent", "long-intent", "long-question"],
)
def test_action_text_limits_come_from_the_core(
    client, start_session, act_session, case
):
    action, text, limit = case
    view = act_session(start_session(), "open")
    response = client.post(
        f"/api/sessions/{view['id']}/actions",
        json={"action": action, "version": view["version"], "text": text},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert response.json() == {
        "request_id": response.headers["X-Request-ID"],
        "type": "about:blank",
        "title": "Unprocessable Content",
        "status": 422,
        "detail": f"Invalid text: limit {limit}, length {len(text)}",
        "code": "invalid_input",
    }
    assert client.get(f"/api/sessions/{view['id']}").json() == view


@pytest.mark.parametrize(
    ("body", "error_type"),
    [
        ({"action": "unknown", "version": 0}, "union_tag_invalid"),
        ({"action": "open"}, "missing"),
    ],
    ids=["unknown-action", "missing-version"],
)
def test_action_parser_rejects_an_unknown_action_or_missing_version(
    client, start_session, body, error_type
):
    view = start_session()
    response = client.post(f"/api/sessions/{view['id']}/actions", json=body)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    problem = response.json()
    assert problem["code"] == "request_invalid"
    assert problem["errors"][0]["type"] == error_type
    assert client.get(f"/api/sessions/{view['id']}").json() == view


def test_cancel_requires_version_and_is_idempotent_without_pending_work(
    client, start_session
):
    view = start_session()
    path = f"/api/sessions/{view['id']}/cancel"
    for version in (0, 0, 99):
        response = client.post(path, json={"version": version})
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.content == b""
    response = client.post(path, json={})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert response.json()["code"] == "request_invalid"
    assert response.json()["errors"] == [
        {"loc": ["body", "version"], "message": "Field required", "type": "missing"}
    ]
    assert client.get(f"/api/sessions/{view['id']}").json() == view


@pytest.mark.parametrize(
    "version", [False, "0", 0.0], ids=["boolean", "string", "float"]
)
@pytest.mark.parametrize("suffix", ["actions", "cancel"])
def test_version_is_an_integer_token_without_coercion(
    client, start_session, version, suffix
):
    view = start_session()
    body = {"version": version}
    if suffix == "actions":
        body["action"] = "open"
    response = client.post(f"/api/sessions/{view['id']}/{suffix}", json=body)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert response.json()["code"] == "request_invalid"
    assert client.get(f"/api/sessions/{view['id']}").json() == view


def test_non_uuid_session_path_is_a_request_problem(client):
    response = client.get("/api/sessions/not-a-uuid")
    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert response.json()["code"] == "request_invalid"
    assert response.json()["errors"][0]["loc"] == ["path", "session_id"]


def test_stale_action_does_not_change_the_session(client, start_session, act_session):
    initial = start_session()
    view = act_session(initial, "open")
    response = client.post(
        f"/api/sessions/{view['id']}/actions",
        json={
            "action": "intent",
            "version": initial["version"],
            "text": "散歩しました",
        },
    )
    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json() == {
        "request_id": response.headers["X-Request-ID"],
        "type": "about:blank",
        "title": "Conflict",
        "status": 409,
        "detail": "The session version has changed",
        "code": "stale_session",
    }
    assert client.get(f"/api/sessions/{view['id']}").json() == view


def test_action_stage_and_ended_guards_are_conflicts(
    client, start_session, act_session
):
    view = start_session()
    response = client.post(
        f"/api/sessions/{view['id']}/actions",
        json={"action": "english", "version": 0, "text": "Hello"},
    )
    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["code"] == "action_not_allowed"
    ended = act_session(view, "end")
    assert ended["wrap_up"] == {"items": []}
    for action, code in [("open", "session_ended"), ("wrap_up", "action_not_allowed")]:
        response = client.post(
            f"/api/sessions/{view['id']}/actions",
            json={"action": action, "version": ended["version"]},
        )
        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json()["code"] == code
    assert client.get(f"/api/sessions/{view['id']}").json() == ended


@pytest.mark.parametrize(
    "case",
    [
        (errors.ModelTimeoutError, HTTPStatus.GATEWAY_TIMEOUT, "model_timeout"),
        (
            errors.ModelRateLimitedError,
            HTTPStatus.SERVICE_UNAVAILABLE,
            "model_rate_limited",
        ),
        (errors.ModelUnavailableError, HTTPStatus.BAD_GATEWAY, "model_unavailable"),
        (None, HTTPStatus.BAD_GATEWAY, "model_output_invalid"),
    ],
    ids=["timeout", "rate-limited", "unavailable", "invalid-output"],
)
def test_model_failure_keeps_the_pending_input_and_uses_problem_details(
    conversation_container, caplog, case
):
    error_class, status, code = case
    calls = []
    failure = (
        error_class("private-provider", "private-model", 12) if error_class else None
    )

    class BadPartner(FixedPartnerModel):
        async def open(self, request, repair=None):
            calls.append((request, repair))
            if failure is not None:
                raise failure
            return m.Parsed(
                p.PartnerLine("こんにちは"),
                m.Usage("fixed", "fixed", None, None, None, 0),
            )

    container = conversation_container(BadPartner())
    with TestClient(create_app(container=container)) as client:
        created = client.post("/api/sessions")
        assert created.status_code == HTTPStatus.CREATED
        view = created.json()
        response = client.post(
            f"/api/sessions/{view['id']}/actions", json={"action": "open", "version": 0}
        )
        assert response.status_code == status
        expected_error = failure or errors.ModelOutputInvalidError(m.ModelTask.OPEN)
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json() == {
            "request_id": response.headers["X-Request-ID"],
            "type": "about:blank",
            "title": status.phrase,
            "status": status.value,
            "detail": str(expected_error),
            "code": code,
        }
        recovered = client.get(f"/api/sessions/{view['id']}").json()
        assert recovered["stage"] == "opening"
        assert recovered["version"] == 0
        assert recovered["entries"] == []
        assert recovered["last_submission"] == {
            "state": "failed",
            "action": "open",
            "input": {},
            "failure_code": code,
        }
    assert len(calls) == (1 if failure else 2)
    assert "private-provider" not in response.text + caplog.text
    assert "private-model" not in response.text + caplog.text
    assert "こんにちは" not in response.text + caplog.text


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 101}, {"cursor": "forged"}])
def test_session_page_rejects_bad_limits_and_cursors(client, query):
    response = client.get("/api/sessions", params=query)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert response.json()["code"] == (
        "invalid_cursor" if "cursor" in query else "invalid_page_limit"
    )


def test_wire_contract_has_seventeen_actions_and_twenty_one_entry_kinds(client):
    document = client.get("/openapi.json").json()
    path = "/api/sessions/{session_id}/actions"
    assert path in document["paths"]

    def resolve(schema):
        while "$ref" in schema:
            schema = document["components"]["schemas"][
                schema["$ref"].rsplit("/", 1)[-1]
            ]
        return schema

    body = resolve(
        document["paths"][path]["post"]["requestBody"]["content"]["application/json"][
            "schema"
        ]
    )
    assert body["discriminator"]["propertyName"] == "action"
    assert set(body["discriminator"]["mapping"]) == {
        action.value for action in m.Action
    }
    for schema in body["oneOf"]:
        action = resolve(schema)
        assert "version" in action["required"]
        assert all("maxLength" not in field for field in action["properties"].values())
    view = document["components"]["schemas"]["SessionResponse"]
    entry = resolve(view["properties"]["entries"]["items"])
    assert entry["discriminator"]["propertyName"] == "kind"
    assert set(entry["discriminator"]["mapping"]) == {
        kind.value for kind in m.EntryKind
    }
