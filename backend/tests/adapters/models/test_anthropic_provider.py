from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import anthropic
import httpx2
import pytest
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.usage import RequestUsage

from intent_to_english.adapters.models import anthropic_provider
from intent_to_english.adapters.models.anthropic_provider import (
    AnthropicCalls,
    AnthropicRole,
    build_anthropic_models,
)
from intent_to_english.composition import ResourceClosers
from intent_to_english.core import coaching, partner
from intent_to_english.core import models as m
from intent_to_english.core.errors import (
    ModelRateLimitedError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from tests.adapters.models.test_agents import COACH_CASES, REQUESTS

if TYPE_CHECKING:
    from intent_to_english.adapters.models.agents import (
        AgentCoachModel,
        AgentPartnerModel,
    )

pytestmark = pytest.mark.anyio

PARTNER_ID = "claude-haiku-5-5"
COACH_ID = "claude-sonnet-5-5"
PRIVATE = "PRIVATE-PROVIDER-TEXT"
# Every variable the SDK reads for credentials, endpoint, or headers (anthropic
# 1.17.0 _client.py and lib/credentials): none may change a request.
HOSTILE_ENV = {
    "ANTHROPIC_API_KEY": "HOSTILE-ENV-KEY",
    "ANTHROPIC_AUTH_TOKEN": "HOSTILE-AUTH-TOKEN",
    "ANTHROPIC_BASE_URL": "https://hostile.invalid",
    "ANTHROPIC_PROFILE": "hostile",
    "ANTHROPIC_CUSTOM_HEADERS": "X-Hostile: 1\nAuthorization: Bearer HOSTILE",
    "ANTHROPIC_FEDERATION_RULE_ID": "fdrl_hostile",
    "ANTHROPIC_ORGANIZATION_ID": "00000000-0000-4000-8000-000000000000",
    "ANTHROPIC_SERVICE_ACCOUNT_ID": "svac_hostile",
    "ANTHROPIC_IDENTITY_TOKEN": "HOSTILE-IDENTITY-TOKEN",
    "ANTHROPIC_WORKSPACE_ID": "wrkspc_hostile",
    "ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE": "content",
}


def _message(content, stop_reason="end_turn", input_tokens=12, output_tokens=8):
    return httpx2.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": PARTNER_ID,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        },
    )


def _text(text):
    return [{"type": "text", "text": text}]


@dataclass
class Wire:
    case: str = "ok"
    requests: list[httpx2.Request] = field(default_factory=list)
    clients: list[anthropic.AsyncAnthropic] = field(default_factory=list)
    options: list[dict[str, object]] = field(default_factory=list)
    # Set by _build before any test calls them.
    partner: AgentPartnerModel = field(init=False)
    coach: AgentCoachModel = field(init=False)

    async def respond(self, request):
        self.requests.append(request)
        error = {"type": "error", "error": {"message": PRIVATE}}
        if self.case == "timeout":
            raise httpx2.ReadTimeout(PRIVATE, request=request)
        if self.case == "connection":
            raise httpx2.ConnectError(PRIVATE, request=request)
        if self.case.isdigit():
            return httpx2.Response(int(self.case), json=error)
        if self.case == "invalid":
            return _message(_text(f"invalid JSON {PRIVATE}"))
        if self.case == "refusal-empty":
            return _message([], "refusal")
        if self.case == "refusal-text":
            return _message(_text('{"li'), "refusal")
        if self.case == "refusal-parsed":
            return _message(_text('{"line":"Nice!"}'), "refusal")
        return _message(_text('{"line":"Nice! What did you do?"}'))

    def client(self, **kwargs):
        self.options.append(kwargs)
        transport = httpx2.MockTransport(self.respond)
        client = anthropic.AsyncAnthropic(
            **kwargs, http_client=anthropic.DefaultAsyncHttpxClient(transport=transport)
        )
        self.clients.append(client)
        return client


async def _build(state, monkeypatch, roles=None, ticks=(2.0, 2.25)):
    monkeypatch.setattr(anthropic_provider, "AsyncAnthropic", state.client)
    resources = ResourceClosers()
    clock = iter(ticks)
    state.partner, state.coach = build_anthropic_models(
        "explicit-key",
        roles or (AnthropicRole(PARTNER_ID), AnthropicRole(COACH_ID)),
        resources,
        monotonic=lambda: next(clock),
    )
    resources.seal()
    return resources


@pytest.fixture
async def wire(monkeypatch):
    for name in HOSTILE_ENV:
        monkeypatch.delenv(name, raising=False)
    state = Wire()
    resources = await _build(state, monkeypatch)
    yield state
    await resources.drain(None, None, None)


async def test_suite_guard_refuses_real_model_before_transport(wire):
    with pytest.raises(RuntimeError, match="ALLOW_MODEL_REQUESTS is False"):
        await wire.partner.open(partner.OpenRequest(None))

    assert wire.requests == []


async def test_builder_shares_one_retry_free_client_and_disposes_it_once(
    monkeypatch,
):
    state = Wire()
    resources = await _build(state, monkeypatch, ticks=(0.0, 0.0, 0.0, 0.0))

    with override_allow_model_requests(True):
        await state.partner.open(partner.OpenRequest(None))
        await state.coach.acknowledge(coaching.AcknowledgeRequest("散歩した", ()))

    assert len(state.clients) == 1
    assert state.options == [
        {
            "api_key": "explicit-key",
            "base_url": "https://api.anthropic.com",
            "max_retries": 0,
            "open_telemetry": {"traces": False, "propagation": False},
        }
    ]
    assert [json.loads(r.content)["model"] for r in state.requests] == [
        PARTNER_ID,
        COACH_ID,
    ]
    assert not state.clients[0].is_closed()
    await resources.drain(None, None, None)
    assert state.clients[0].is_closed()


async def test_request_sends_native_output_effort_and_bounded_tokens(wire):
    with override_allow_model_requests(True):
        result = await wire.partner.open(partner.OpenRequest(None))

    assert isinstance(result, m.Parsed)
    assert result.usage == m.Usage(
        "anthropic", PARTNER_ID, 12, 8, Decimal("0.0000052"), 250
    )
    assert len(wire.requests) == 1
    sent = wire.requests[0]
    assert str(sent.url) == "https://api.anthropic.com/v1/messages?beta=true"
    assert sent.headers["x-api-key"] == "explicit-key"
    assert "authorization" not in sent.headers
    assert sent.headers["x-stainless-retry-count"] == "0"
    body = json.loads(sent.content)
    assert body["max_tokens"] == 16_000
    assert body["stream"] is False
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "medium"
    assert not {"thinking", "tools", "tool_choice", "cache_control"} & body.keys()


async def _sent_request(monkeypatch):
    state = Wire()
    resources = await _build(state, monkeypatch)
    with override_allow_model_requests(True):
        await state.partner.open(partner.OpenRequest(None))
    await resources.drain(None, None, None)
    (sent,) = state.requests
    return str(sent.url), dict(sent.headers), json.loads(sent.content)


async def test_anthropic_environment_changes_no_request(monkeypatch, tmp_path):
    for name in [n for n in os.environ if n.upper().startswith("ANTHROPIC_")]:
        monkeypatch.delenv(name)
    clean = await _sent_request(monkeypatch)

    config_dir = tmp_path / "anthropic"
    (config_dir / "configs").mkdir(parents=True)
    profile = {"authentication": {"type": "api_key", "api_key": "HOSTILE-PROFILE"}}
    for name in ("hostile", "default"):
        (config_dir / "configs" / f"{name}.json").write_text(json.dumps(profile))
    (config_dir / "active_config").write_text("hostile")
    token_file = tmp_path / "identity-token"
    token_file.write_text("HOSTILE-IDENTITY-FILE")
    for name, value in HOSTILE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("ANTHROPIC_IDENTITY_TOKEN_FILE", str(token_file))

    hostile = await _sent_request(monkeypatch)

    assert hostile == clean
    assert "HOSTILE" not in json.dumps(hostile)


@pytest.mark.parametrize(
    ("effort", "role"),
    [("low", "partner"), ("max", "coach")],
    ids=["partner-low", "coach-max"],
)
async def test_role_effort_reaches_only_its_own_requests(monkeypatch, effort, role):
    state = Wire()
    roles = (
        AnthropicRole(PARTNER_ID, effort if role == "partner" else "medium"),
        AnthropicRole(COACH_ID, effort if role == "coach" else "medium"),
    )
    resources = await _build(state, monkeypatch, roles, ticks=(0.0,) * 4)

    with override_allow_model_requests(True):
        await state.partner.open(partner.OpenRequest(None))
        await state.coach.acknowledge(coaching.AcknowledgeRequest("散歩した", ()))
    await resources.drain(None, None, None)

    sent = [json.loads(r.content)["output_config"]["effort"] for r in state.requests]
    assert sent == ([effort, "medium"] if role == "partner" else ["medium", effort])


FAILURES = [
    ("timeout", ModelTimeoutError, None),
    ("connection", ModelUnavailableError, None),
    ("429", ModelRateLimitedError, 429),
    ("400", ModelUnavailableError, 400),
    ("500", ModelUnavailableError, 500),
    ("529", ModelUnavailableError, 529),
    ("refusal-empty", ModelUnavailableError, None),
    ("refusal-text", ModelUnavailableError, None),
    ("refusal-parsed", ModelUnavailableError, None),
]


@pytest.mark.parametrize("failure", FAILURES, ids=[case[0] for case in FAILURES])
@pytest.mark.parametrize("role", ["partner", "coach"])
async def test_provider_failure_maps_once_without_private_text(
    wire, failure, role, caplog
):
    case, error_type, status = failure
    wire.case = case
    call = (
        wire.partner.open(partner.OpenRequest(None))
        if role == "partner"
        else wire.coach.acknowledge(coaching.AcknowledgeRequest("散歩した", ()))
    )

    with (
        override_allow_model_requests(True),
        pytest.raises(error_type, match="Model") as caught,
    ):
        await call

    assert caught.value.provider == "anthropic"
    assert caught.value.model == (PARTNER_ID if role == "partner" else COACH_ID)
    assert caught.value.latency_ms == 250
    assert caught.value.status == status
    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in caplog.text
    assert len(wire.requests) == 1


async def test_invalid_output_keeps_usage_and_cost_for_the_repair(wire):
    wire.case = "invalid"

    with override_allow_model_requests(True):
        result = await wire.partner.open(partner.OpenRequest(None))

    assert isinstance(result, m.ParseFailure)
    assert result.usage == m.Usage(
        "anthropic", PARTNER_ID, 12, 8, Decimal("0.0000052"), 250
    )
    assert PRIVATE not in result.detail
    assert len(wire.requests) == 1


@pytest.mark.parametrize(
    ("model_id", "input_tokens", "output_tokens", "expected"),
    [
        ("claude-sonnet-5-5", 1_000_000, 1_000_000, Decimal("12.00")),
        ("claude-sonnet-5-5", 1_200, 300, Decimal("0.0054")),
        ("claude-haiku-5-5", 100_000, 1_000, Decimal("0.0105")),
        ("claude-haiku-5-5", 100_001, 1_000, Decimal("0.0525005")),
        ("claude-haiku-5-5", 0, 0, Decimal(0)),
        ("claude-opus-5-5", 1_000, 1_000, None),
    ],
    ids=["sonnet-million", "sonnet", "haiku-at-limit", "haiku-over", "zero", "unknown"],
)
def test_cost_is_usd_from_tokens_and_the_configured_price(
    model_id, input_tokens, output_tokens, expected
):
    usage = RequestUsage(input_tokens=input_tokens, output_tokens=output_tokens)

    assert AnthropicCalls(model_id).cost(usage) == expected


# Anthropic's structured outputs answer anything else with a 400, which the adapter
# reports as model_unavailable (https://platform.claude.com/docs/en/build-with-claude/
# structured-outputs, "JSON Schema limitations", observed 2026-10-28): objects need
# additionalProperties false, arrays allow only minItems 0 or 1, and no numeric or
# string-length constraint, so lengths are checked after parsing instead.
SUPPORTED_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "anyOf",
        "allOf",
        "$ref",
        "$defs",
        "definitions",
        "default",
        "format",
        "pattern",
        "minItems",
        "title",
        "description",
    }
)
SUPPORTED_FORMATS = frozenset(
    {
        "date-time",
        "time",
        "date",
        "duration",
        "email",
        "hostname",
        "uri",
        "ipv4",
        "ipv6",
        "uuid",
    }
)
SCHEMA_TASKS = [("partner", task, task_request) for task, task_request in REQUESTS] + [
    ("coach", case[0], case[1]) for case in COACH_CASES
]


def _subschemas(key, value, path):
    if key in {"properties", "$defs", "definitions"}:
        return [(child, f"{path}.{key}.{name}") for name, child in value.items()]
    if key in {"anyOf", "allOf"}:
        return [(child, f"{path}.{key}[{i}]") for i, child in enumerate(value)]
    if key == "items":
        return [(value, f"{path}.items")]
    return []


def _unsupported_schema_paths(node, path="$"):
    if not isinstance(node, dict):
        yield f"{path}: not a schema"
        return
    for key, value in node.items():
        for child, child_path in _subschemas(key, value, path):
            yield from _unsupported_schema_paths(child, child_path)
        if key not in SUPPORTED_KEYWORDS:
            yield f"{path}.{key}"
        elif key == "additionalProperties" and value is not False:
            yield f"{path}.additionalProperties"
        elif key == "minItems" and value not in {0, 1}:
            yield f"{path}.minItems"
        elif key == "format" and value not in SUPPORTED_FORMATS:
            yield f"{path}.format"
        elif key == "$ref" and not value.startswith("#"):
            yield f"{path}.$ref"
    if node.get("type") == "object" and node.get("additionalProperties") is not False:
        yield f"{path}: object without additionalProperties false"


@pytest.mark.parametrize(
    ("role", "task", "task_request"),
    SCHEMA_TASKS,
    ids=[f"{case[0]}-{case[1]}-{i}" for i, case in enumerate(SCHEMA_TASKS)],
)
async def test_every_task_sends_a_schema_inside_anthropic_structured_output(
    wire, role, task, task_request
):
    adapter = wire.partner if role == "partner" else wire.coach

    with override_allow_model_requests(True):
        await getattr(adapter, task)(task_request)

    (sent,) = wire.requests
    output_format = json.loads(sent.content)["output_config"]["format"]
    assert output_format["type"] == "json_schema"
    assert list(_unsupported_schema_paths(output_format["schema"])) == []
