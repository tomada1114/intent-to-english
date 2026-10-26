"""Fixed-mode HTTP practice reaches every stage without a provider request."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http import HTTPStatus
from threading import Event
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient

from intent_to_english.adapters.models.fixed import FixedPartnerModel
from intent_to_english.api.app import create_app
from intent_to_english.settings import Settings


def test_session_flow_reaches_all_nine_stages(start_session, act_session, fixed_now):
    view = start_session()
    stages = {view["stage"]}

    def act(action, **fields):
        nonlocal view
        view = act_session(view, action, **fields)
        stages.add(view["stage"])
        return view

    act("open")
    act("restate", mode="shorter")
    assert view["stage"] == "intent"
    act("ask", text="どこから話すのですか")
    assert view["stage"] == "intent"
    act("intent", text="久しぶりに映画を見た")
    act("hint", gap="住みたい", partial_english="I want to")
    act("english", text="I want to leave in Canada")
    act("reading", reading="live")
    act("retry", text="I want to live in Canada")
    assert view["stage"] == "retry"
    assert view["entries"][-1]["payload"]["result"]["blanks"] == [1]
    act("retry", text="Actually, I want to live in Canada")
    act("partner_reply")
    act("english_direct", text="That sounds great!")
    act("partner_reply")
    act("intent", text="今日はゆっくりしました")
    act("show_answer")
    act("typed_copy", text="I had a relaxing day, so I feel good.")
    assert view["stage"] == "check_in"
    act("end")
    assert view["wrap_up"] is None
    assert view["allowed_actions"] == ["wrap_up"]
    assert datetime.fromisoformat(view["ended_at"]) == fixed_now
    view = act("wrap_up")
    assert len(view["wrap_up"]["items"]) == 2
    assert {item["phrase"] for item in view["wrap_up"]["items"]} == {
        "Actually, …",
        "I feel refreshed",
    }
    assert view["allowed_actions"] == []
    assert stages == {
        "opening",
        "intent",
        "english",
        "reading_check",
        "retry",
        "partner_turn",
        "answer_shown",
        "check_in",
        "ended",
    }


def test_retry_skip_and_practice_keep_the_finished_turn_context(
    start_session, act_session
):
    view = act_session(start_session(), "open")
    view = act_session(view, "english_direct", text="I went to the park.")
    view = act_session(view, "skip")
    assert view["stage"] == "partner_turn"
    view = act_session(view, "partner_reply")
    view = act_session(view, "practice_again", text="Actually, I went to the park.")
    assert view["stage"] == "intent"
    assert view["finished_replies"] == 1
    assert view["entries"][-1]["kind"] == "practice_result"
    assert view["entries"][-1]["payload"]["turn_index"] == 1
    assert "line" in view["entries"][-1]["payload"]["result"]


def test_second_retry_miss_serializes_the_given_piece(start_session, act_session):
    view = act_session(start_session(), "open")
    view = act_session(view, "english_direct", text="I went to the park.")
    view = act_session(view, "retry", text="I went to the park.")
    view = act_session(view, "retry", text="I went to the park.")
    assert view["stage"] == "partner_turn"
    result = view["entries"][-2]["payload"]["result"]
    assert result["pieces"] == [{"number": 1, "text": "Actually, I"}]
    assert "line" in result


@pytest.mark.parametrize("operation", ["cancel", "end"])
def test_cancel_or_end_supersedes_only_the_named_pending_action(
    conversation_container, operation
):
    attempt_id = str(uuid4())
    started = Event()
    release = Event()

    class HeldPartner(FixedPartnerModel):
        async def open(self, request, repair=None):
            started.set()
            await anyio.to_thread.run_sync(release.wait)
            return await super().open(request, repair)

    with TestClient(
        create_app(container=conversation_container(HeldPartner()))
    ) as client:
        view = client.post("/api/sessions").json()
        path = f"/api/sessions/{view['id']}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(
                client.post,
                path + "/actions",
                json={"attempt_id": attempt_id, "action": "open", "version": 0},
            )
            try:
                assert started.wait(timeout=5)
                assert (
                    client.get(path).json()["last_submission"]["attempt_id"]
                    == attempt_id
                )
                duplicate = client.post(
                    path + "/actions",
                    json={"attempt_id": str(uuid4()), "action": "open", "version": 0},
                )
                assert duplicate.status_code == HTTPStatus.CONFLICT
                assert duplicate.json()["code"] == "action_in_progress"
                assert (
                    client.post(
                        path + "/cancel", json={"attempt_id": attempt_id, "version": 99}
                    ).status_code
                    == HTTPStatus.NO_CONTENT
                )
                assert client.get(path).json()["last_submission"]["state"] == "pending"
                if operation == "end":
                    response = client.post(
                        path + "/actions",
                        json={
                            "attempt_id": str(uuid4()),
                            "action": "end",
                            "version": 0,
                        },
                    )
                    assert response.status_code == HTTPStatus.OK
                    assert response.json()["stage"] == "ended"
                    assert response.json()["wrap_up"] == {"items": []}
                else:
                    response = client.post(
                        path + "/cancel", json={"attempt_id": attempt_id, "version": 0}
                    )
                    assert response.status_code == HTTPStatus.NO_CONTENT
            finally:
                release.set()
            late = waiting.result(timeout=10)
        assert late.status_code == HTTPStatus.CONFLICT
        assert late.json() == {
            "request_id": late.headers["X-Request-ID"],
            "type": "about:blank",
            "title": "Conflict",
            "status": 409,
            "detail": "The action was cancelled",
            "code": "action_cancelled",
        }
        recovered = client.get(path).json()
        assert recovered["stage"] == ("ended" if operation == "end" else "opening")
        assert recovered["last_submission"] is None


def test_sql_session_reopens_partial_practice_and_preserves_wrap_up_states(
    migrated_sqlite_url,
):
    settings = Settings(
        database_url=migrated_sqlite_url, model_mode="fixed", OPENROUTER_API_KEY=None
    )

    def act(client, view, action, **fields):
        response = client.post(
            f"/api/sessions/{view['id']}/actions",
            json={
                "attempt_id": str(uuid4()),
                "action": action,
                "version": view["version"],
                **fields,
            },
        )
        assert response.status_code == HTTPStatus.OK, response.text
        return response.json()

    with TestClient(create_app(settings)) as first:
        view = first.post("/api/sessions").json()
        view = act(first, view, "open")
        view = act(first, view, "intent", text="気分がいいです")
        view = act(first, view, "english", text="I feel refreshing today.")
        assert view["stage"] == "retry"
    with TestClient(create_app(settings)) as reopened:
        assert reopened.get(f"/api/sessions/{view['id']}").json() == view
        view = act(reopened, view, "retry", text="I feel refreshed today.")
        assert view["stage"] == "partner_turn"
        ended = act(reopened, view, "end")
        assert ended["wrap_up"] is None
    with TestClient(create_app(settings)) as ended_client:
        assert ended_client.get(f"/api/sessions/{ended['id']}").json() == ended
        wrapped = act(ended_client, ended, "wrap_up")
        empty = ended_client.post("/api/sessions").json()
        empty = act(ended_client, empty, "end")
        assert empty["wrap_up"] == {"items": []}
    with TestClient(create_app(settings)) as final:
        assert final.get(f"/api/sessions/{wrapped['id']}").json() == wrapped
        assert final.get(f"/api/sessions/{empty['id']}").json() == empty


@pytest.mark.parametrize("suffix", ["actions", "cancel"])
def test_attempt_identity_is_required_before_any_action_response(
    client, start_session, suffix
):
    view = start_session()
    body: dict[str, object] = {"version": 0}
    if suffix == "actions":
        body["action"] = "open"
    response = client.post(f"/api/sessions/{view['id']}/{suffix}", json=body)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert response.json()["code"] == "request_invalid"
    assert response.json()["errors"][0]["loc"][-1] == "attempt_id"


def test_early_cancel_and_replay_leave_a_same_version_replacement_usable(
    client, start_session
):
    view = start_session()
    path = f"/api/sessions/{view['id']}"
    attempt_id = str(uuid4())
    cancelled = {"version": 0, "attempt_id": attempt_id}
    assert (
        client.post(path + "/cancel", json=cancelled).status_code
        == HTTPStatus.NO_CONTENT
    )
    refused = client.post(path + "/actions", json={"action": "open", **cancelled})
    assert refused.status_code == HTTPStatus.CONFLICT
    assert refused.json()["code"] == "action_cancelled"
    assert client.get(path).json() == view
    assert (
        client.post(path + "/cancel", json=cancelled).status_code
        == HTTPStatus.NO_CONTENT
    )
    replacement = client.post(
        path + "/actions",
        json={"action": "open", "version": 0, "attempt_id": str(uuid4())},
    )
    assert replacement.status_code == HTTPStatus.OK
    assert replacement.json()["version"] == 1
