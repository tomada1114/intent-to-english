from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from decimal import Decimal

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from intent_to_english.adapters.models import openrouter, prompts
from intent_to_english.adapters.models.openrouter import (
    OpenRouterPartnerModel,
    build_openrouter_partner,
)
from intent_to_english.api.app import APP_TITLE
from intent_to_english.composition import ResourceClosers
from intent_to_english.core import models as m
from intent_to_english.core import partner
from intent_to_english.core.errors import (
    ModelRateLimitedError,
    ModelTimeoutError,
    ModelUnavailableError,
)

pytestmark = pytest.mark.anyio

REQUESTS = [
    ("open", partner.OpenRequest(None)),
    (
        "reply",
        partner.ReplyRequest((m.ConversationLine(m.Speaker.LEARNER, "Hi!"),), False),
    ),
    ("restate", partner.RestateRequest((), "How is your day?", m.RestateMode.SHORTER)),
]


@pytest.mark.parametrize(
    ("task", "task_request"), REQUESTS, ids=["open", "reply", "restate"]
)
@pytest.mark.parametrize("repairing", [False, True], ids=["first", "repair"])
async def test_partner_task_uses_rendered_prompt_and_returns_usage(
    task, task_request, repairing
):
    calls = []

    def answer(messages, info):
        calls.append((messages, info))
        return ModelResponse(
            [TextPart('{"line":"Nice! What did you do?"}')],
            usage=RequestUsage(input_tokens=12, output_tokens=8),
            provider_details={"cost": 0.00125},
        )

    ticks = iter((10.0, 10.125))
    adapter = OpenRouterPartnerModel(
        "configured-model", FunctionModel(answer), lambda: next(ticks)
    )
    repair = (
        m.Repair((m.Violation(m.CheckId.PARTNER_JAPANESE, "Use English"),))
        if repairing
        else None
    )
    rendered = getattr(prompts, f"render_{task}")(task_request, repair)

    result = await getattr(adapter, task)(task_request, repair)

    assert result == m.Parsed(
        partner.PartnerLine("Nice! What did you do?"),
        m.Usage("openrouter", "configured-model", 12, 8, Decimal("0.00125"), 125),
    )
    assert len(calls) == 1
    messages, info = calls[0]
    assert messages[0].instructions == rendered.instructions
    assert messages[0].parts[-1].content == rendered.user_prompt
    assert info.model_settings["timeout"] == 60
    assert info.model_request_parameters.output_mode == "native"
    assert info.model_request_parameters.function_tools == []
    assert info.model_request_parameters.output_tools == []


@pytest.mark.parametrize(
    "text", ['{"line": 7}', '{"line":""}', "not json"], ids=["schema", "core", "json"]
)
async def test_invalid_partner_output_retains_usage_without_sdk_retry(text):
    calls = []

    def answer(messages, info):
        calls.append(messages)
        return ModelResponse(
            [TextPart(text)], usage=RequestUsage(input_tokens=4, output_tokens=3)
        )

    ticks = iter((1.0, 1.25))
    adapter = OpenRouterPartnerModel(
        "model", FunctionModel(answer), lambda: next(ticks)
    )

    result = await adapter.open(partner.OpenRequest(None))

    assert isinstance(result, m.ParseFailure)
    assert result.usage == m.Usage("openrouter", "model", 4, 3, None, 250)
    assert len(calls) == 1
    assert text not in result.detail


@dataclass
class Wire:
    case: str = "ok"
    requests: list[httpx2.Request] = field(default_factory=list)
    adapter: OpenRouterPartnerModel | None = None
    client: AsyncOpenAI | None = None
    options: dict[str, object] = field(default_factory=dict)

    async def respond(self, request):
        self.requests.append(request)
        message = "PRIVATE-PROVIDER-TEXT"
        if self.case == "timeout":
            raise httpx2.ReadTimeout(message, request=request)
        if self.case == "connection":
            raise httpx2.ConnectError(message, request=request)
        if self.case in {"429", "500"}:
            return httpx2.Response(
                int(self.case), json={"error": {"message": "PRIVATE-PROVIDER-TEXT"}}
            )
        if self.case == "error_without_status":
            return httpx2.Response(200, json={"choices": None, "error": None})
        if self.case == "error_with_status":
            return httpx2.Response(
                200, json={"error": {"code": 429, "message": "PRIVATE-PROVIDER-TEXT"}}
            )
        usage: dict[str, object] = {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        }
        if self.case != "no_cost":
            usage["cost"] = 0.0025
        content = (
            "invalid JSON PRIVATE-PROVIDER-TEXT"
            if self.case == "invalid"
            else '{"line":"Nice! What did you do?"}'
        )
        return httpx2.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "created": 1,
                "model": "anthropic/claude-haiku-5.5",
                "provider": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            },
        )


@pytest.fixture
async def wire(monkeypatch):
    state = Wire()
    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(state.respond))

    def make_client(**kwargs):
        state.options = kwargs
        state.client = AsyncOpenAI(**kwargs, http_client=http_client)
        return state.client

    monkeypatch.setattr(openrouter, "AsyncOpenAI", make_client)
    monkeypatch.setenv("OPENROUTER_API_KEY", "HOSTILE-KEY")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "HOSTILE-TITLE")
    monkeypatch.setenv("OPENROUTER_APP_URL", "https://hostile.invalid")
    resources = ResourceClosers()
    ticks = iter((2.0, 2.25))
    state.adapter = build_openrouter_partner(
        SecretStr("explicit-key"),
        "anthropic/claude-haiku-5.5",
        resources,
        app_title=APP_TITLE,
        monotonic=lambda: next(ticks),
    )
    resources.seal()
    yield state, resources
    await resources.drain(None, None, None)


async def test_suite_guard_refuses_real_model_before_transport(wire):
    state, _ = wire

    with pytest.raises(RuntimeError, match="ALLOW_MODEL_REQUESTS is False"):
        await state.adapter.open(partner.OpenRequest(None))

    assert state.requests == []


async def test_builder_pins_client_attribution_native_output_and_disposal(wire):
    state, resources = wire
    with override_allow_model_requests(True):
        result = await state.adapter.open(partner.OpenRequest(None))

    assert result.usage == m.Usage(
        "openrouter", "anthropic/claude-haiku-5.5", 12, 8, Decimal("0.0025"), 250
    )
    assert state.options == {
        "api_key": "explicit-key",
        "base_url": "https://openrouter.ai/api/v1",
        "max_retries": 0,
        "default_headers": {"X-OpenRouter-Title": APP_TITLE},
    }
    assert len(state.requests) == 1
    sent = state.requests[0]
    assert sent.headers["Authorization"] == "Bearer explicit-key"
    assert sent.headers["X-OpenRouter-Title"] == APP_TITLE
    assert "HTTP-Referer" not in sent.headers
    assert "HOSTILE" not in str(sent.headers)
    body = json.loads(sent.content)
    assert body["response_format"]["type"] == "json_schema"
    assert not {"tools", "tool_choice", "reasoning_effort", "reasoning"} & body.keys()
    assert not state.client.is_closed()
    await resources.drain(None, None, None)
    assert state.client.is_closed()


@pytest.mark.parametrize(
    ("case", "error_type"),
    [
        ("timeout", ModelTimeoutError),
        ("connection", ModelUnavailableError),
        ("429", ModelRateLimitedError),
        ("500", ModelUnavailableError),
        ("error_without_status", ModelUnavailableError),
        ("error_with_status", ModelRateLimitedError),
    ],
    ids=[
        "timeout-before-connection",
        "connection",
        "429",
        "500",
        "200-no-status",
        "200-status",
    ],
)
async def test_provider_failure_maps_without_retry_or_private_text(
    wire, case, error_type, caplog
):
    state, _ = wire
    state.case = case

    with (
        override_allow_model_requests(True),
        pytest.raises(error_type, match="Model") as caught,
    ):
        await state.adapter.open(partner.OpenRequest(None))

    assert caught.value.provider == "openrouter"
    assert caught.value.model == "anthropic/claude-haiku-5.5"
    assert caught.value.latency_ms == 250
    assert "PRIVATE-PROVIDER-TEXT" not in str(caught.value)
    assert "PRIVATE-PROVIDER-TEXT" not in caplog.text
    assert len(state.requests) == 1


@pytest.mark.parametrize(
    "case", ["no_cost", "invalid"], ids=["missing-cost", "parse-usage"]
)
async def test_real_provider_keeps_usage_when_cost_absent_or_output_invalid(wire, case):
    state, _ = wire
    state.case = case

    with override_allow_model_requests(True):
        result = await state.adapter.open(partner.OpenRequest(None))

    assert isinstance(result, m.ParseFailure if case == "invalid" else m.Parsed)
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 8
    assert result.usage.cost == (Decimal("0.0025") if case == "invalid" else None)
    assert len(state.requests) == 1


async def test_wall_clock_budget_expires_without_waiting_for_sdk(monkeypatch):
    async def slow(messages, info):
        await asyncio.sleep(1)
        return ModelResponse([TextPart('{"line":"Hi!"}')])

    monkeypatch.setattr(openrouter, "CALL_TIMEOUT_SECONDS", 0.01)
    ticks = iter((0.0, 0.025))
    adapter = OpenRouterPartnerModel("model", FunctionModel(slow), lambda: next(ticks))

    with pytest.raises(ModelTimeoutError, match="Model timeout") as caught:
        await adapter.open(partner.OpenRequest(None))

    assert caught.value.latency_ms == 25


async def test_parsed_japanese_remains_a_core_check_failure():
    def answer(messages, info):
        return ModelResponse([TextPart('{"line":"こんにちは"}')])

    adapter = OpenRouterPartnerModel("model", FunctionModel(answer))
    task_request = partner.OpenRequest(None)

    result = await adapter.open(task_request)

    assert isinstance(result, m.Parsed)
    assert (
        partner.check_open(task_request, result.output)[0].check
        is m.CheckId.PARTNER_JAPANESE
    )


async def test_unexpected_programming_error_propagates():
    def bug(messages, info):
        message = "unexpected adapter bug"
        raise RuntimeError(message)

    adapter = OpenRouterPartnerModel("model", FunctionModel(bug))

    with pytest.raises(RuntimeError, match="unexpected adapter bug"):
        await adapter.open(partner.OpenRequest(None))
