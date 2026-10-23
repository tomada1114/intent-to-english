from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from decimal import Decimal

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from intent_to_english.adapters.models import openrouter, prompts
from intent_to_english.adapters.models.openrouter import (
    OpenRouterPartnerModel,
    build_openrouter_models,
)
from intent_to_english.api.app import APP_TITLE
from intent_to_english.composition import ResourceClosers
from intent_to_english.core import coaching, partner
from intent_to_english.core import models as m
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


async def test_coach_acknowledge_returns_the_core_value_with_usage():
    def answer(messages, info):
        return ModelResponse(
            [TextPart('{"line":"いいですね!","build_hint":null}')],
            usage=RequestUsage(input_tokens=12, output_tokens=8),
        )

    adapter = openrouter.OpenRouterCoachModel("coach", FunctionModel(answer))

    result = await adapter.acknowledge(coaching.AcknowledgeRequest("散歩した", ()))

    assert isinstance(result, m.Parsed)
    assert result.output == coaching.Acknowledgment("いいですね!")
    assert result.usage.input_tokens == 12


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
    coach: openrouter.OpenRouterCoachModel | None = None
    client: AsyncOpenAI | None = None
    options: dict[str, object] = field(default_factory=dict)

    async def respond(self, request):
        self.requests.append(request)
        message = "PRIVATE-PROVIDER-TEXT"
        if self.case == "timeout":
            raise httpx2.ReadTimeout(message, request=request)
        if self.case == "connection":
            raise httpx2.ConnectError(message, request=request)
        if self.case in {"400", "429", "500"}:
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
    state.adapter, state.coach = build_openrouter_models(
        "explicit-key",
        ("anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"),
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
    ("case", "error_type", "status"),
    [
        ("400", ModelUnavailableError, 400),
        ("429", ModelRateLimitedError, 429),
        ("500", ModelUnavailableError, 500),
        ("connection", ModelUnavailableError, None),
        ("timeout", ModelTimeoutError, None),
    ],
    ids=["400", "429", "500", "connection", "timeout"],
)
async def test_provider_failure_carries_only_the_http_status(
    wire, case, error_type, status
):
    state, _ = wire
    state.case = case

    with override_allow_model_requests(True), pytest.raises(error_type) as caught:
        await state.adapter.open(partner.OpenRequest(None))

    assert caught.value.status == status
    assert "PRIVATE-PROVIDER-TEXT" not in str(caught.value)


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


COACH_FEEDBACK = coaching.Feedback("意図は伝わっています")
COACH_CASES = [
    (
        "acknowledge",
        coaching.AcknowledgeRequest("散歩した", ()),
        {"line": "いいですね!", "build_hint": None},
        coaching.Acknowledgment("いいですね!"),
    ),
    (
        "gap_hint",
        coaching.GapHintRequest("散歩した", "散歩", "I", (), ()),
        {"hint": "walk が使えます。"},
        coaching.GapHint("walk が使えます。"),
    ),
    (
        "feedback",
        coaching.FeedbackRequest("散歩した", "I walked.", None, (), ()),
        {"kind": "feedback", "feedback": {"first_line": "意図は伝わっています"}},
        COACH_FEEDBACK,
    ),
    (
        "feedback",
        coaching.FeedbackRequest(None, "I want to leave in Canada.", None, (), ()),
        {
            "kind": "reading_question",
            "word": "leave",
            "readings": ["leave", "live"],
        },
        coaching.ReadingQuestion("leave", ("leave", "live")),
    ),
    (
        "check_retry",
        coaching.CheckRetryRequest(None, COACH_FEEDBACK, "I walked.", 1, ()),
        {
            "result": {
                "kind": "accepted",
                "line": "伝わりました。",
                "readings_noted": [{"written": "starting", "read_as": "studying"}],
            }
        },
        coaching.RetryAccepted(
            "伝わりました。", (coaching.ReadingNote("starting", "studying"),)
        ),
    ),
    (
        "check_retry",
        coaching.CheckRetryRequest(None, COACH_FEEDBACK, "I walk.", 1, ()),
        {"result": {"kind": "blank_off", "blanks": [1], "hint": "過去形です。"}},
        coaching.BlankOff((1,), "過去形です。"),
    ),
    (
        "check_retry",
        coaching.CheckRetryRequest(None, COACH_FEEDBACK, "I walk.", 2, ()),
        {
            "result": {
                "kind": "piece_given",
                "pieces": [{"number": 1, "text": "walked"}],
                "line": "この表現で伝わります。",
            }
        },
        coaching.PieceGiven((coaching.Piece(1, "walked"),), "この表現で伝わります。"),
    ),
    (
        "show_answer",
        coaching.ShowAnswerRequest(m.Stage.ENGLISH, "散歩した", None, None, ()),
        {"example": "I walked."},
        coaching.Answer("I walked."),
    ),
    (
        "answer_question",
        coaching.AnswerQuestionRequest(
            "過去形は?", m.Stage.ENGLISH, "散歩した", None, None, ()
        ),
        {"text": "walked です。"},
        coaching.CoachAnswer("walked です。"),
    ),
    (
        "wrap_up",
        coaching.WrapUpRequest((COACH_FEEDBACK,), ()),
        {"items": [{"phrase": "walk", "note": "散歩の話で使いました。"}]},
        coaching.WrapUp((coaching.WrapUpItem("walk", "散歩の話で使いました。"),)),
    ),
]


@pytest.mark.parametrize(
    ("task", "task_request", "payload", "expected"),
    COACH_CASES,
    ids=[f"{case[0]}-{i}" for i, case in enumerate(COACH_CASES)],
)
@pytest.mark.parametrize("invalid", [False, True], ids=["valid", "invalid"])
async def test_coach_tasks_convert_and_preserve_prompts_and_usage(
    task, task_request, payload, expected, invalid
):
    calls = []

    def answer(messages, info):
        calls.append((messages, info))
        return ModelResponse(
            [TextPart("{}" if invalid else json.dumps(payload))],
            usage=RequestUsage(input_tokens=9, output_tokens=7),
            provider_details={"cost": 0.002},
        )

    adapter = openrouter.OpenRouterCoachModel(
        "coach-id", FunctionModel(answer), lambda: 1.0
    )
    repair = m.Repair((m.Violation(m.CheckId.SCHEMA, "Repair marker"),))
    result = await getattr(adapter, task)(task_request, repair)
    assert result.usage == m.Usage("openrouter", "coach-id", 9, 7, Decimal("0.002"), 0)
    assert len(calls) == 1
    messages, info = calls[0]
    rendered = getattr(prompts, f"render_{task}")(task_request, repair)
    assert messages[0].instructions == rendered.instructions
    assert messages[0].parts[-1].content == rendered.user_prompt
    assert "Repair marker" in rendered.instructions
    assert info.model_request_parameters.function_tools == []
    assert info.model_request_parameters.output_object.json_schema["type"] == "object"
    assert isinstance(result, m.ParseFailure) if invalid else result.output == expected


# Anthropic's native structured outputs answer these with a 400, which the adapter
# reports as model_unavailable: unions must be anyOf, and arrays allow only
# minItems 0 or 1, so lengths are checked after parsing instead.
UNSUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {"oneOf", "discriminator", "prefixItems", "maxItems"}
)
SCHEMA_TASKS = [("partner", task, task_request) for task, task_request in REQUESTS] + [
    ("coach", case[0], case[1]) for case in COACH_CASES
]


def _unsupported_schema_paths(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in UNSUPPORTED_SCHEMA_KEYWORDS or (key == "minItems" and value > 1):
                yield f"{path}.{key}"
            yield from _unsupported_schema_paths(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _unsupported_schema_paths(item, f"{path}[{index}]")


@pytest.mark.parametrize(
    ("role", "task", "task_request"),
    SCHEMA_TASKS,
    ids=[f"{case[0]}-{case[1]}-{i}" for i, case in enumerate(SCHEMA_TASKS)],
)
async def test_task_output_schema_uses_only_native_structured_output_features(
    role, task, task_request
):
    sent = []

    def answer(messages, info):
        sent.append(info.model_request_parameters.output_object.json_schema)
        return ModelResponse([TextPart("{}")])

    adapter_type = (
        OpenRouterPartnerModel if role == "partner" else openrouter.OpenRouterCoachModel
    )
    await getattr(adapter_type("model", FunctionModel(answer)), task)(task_request)

    assert len(sent) == 1
    assert list(_unsupported_schema_paths(sent[0])) == []


@pytest.mark.parametrize(
    "readings",
    [["leave"], ["leave", "live", "love"], ["leave", "leave"]],
    ids=["one", "three", "duplicate"],
)
async def test_coach_reading_question_rejects_invalid_options_with_usage(readings):
    def answer(messages, info):
        return ModelResponse(
            [
                TextPart(
                    json.dumps(
                        {
                            "kind": "reading_question",
                            "word": "leave",
                            "readings": readings,
                        }
                    )
                )
            ],
            usage=RequestUsage(input_tokens=2, output_tokens=3),
        )

    adapter = openrouter.OpenRouterCoachModel("coach", FunctionModel(answer))
    result = await adapter.feedback(
        coaching.FeedbackRequest(None, "I want to leave.", None, (), ())
    )
    assert isinstance(result, m.ParseFailure)
    assert result.usage.output_tokens == 3


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
    ids=["timeout", "connection", "429", "500", "200-no-status", "200-status"],
)
async def test_coach_provider_errors_use_the_same_safe_mapping(
    wire, case, error_type, caplog
):
    state, _ = wire
    state.case = case
    with (
        override_allow_model_requests(True),
        pytest.raises(error_type, match="Model") as caught,
    ):
        await state.coach.acknowledge(coaching.AcknowledgeRequest("散歩した", ()))
    assert caught.value.model == "anthropic/claude-sonnet-5.5"
    assert caught.value.latency_ms == 250
    assert "PRIVATE-PROVIDER-TEXT" not in str(caught.value)
    assert "PRIVATE-PROVIDER-TEXT" not in caplog.text
    assert len(state.requests) == 1


async def test_coach_preserves_content_failure_for_the_core_repair():
    def answer(messages, info):
        return ModelResponse([TextPart('{"line":"いいですね","build_hint":"Use I"}')])

    adapter = openrouter.OpenRouterCoachModel("coach", FunctionModel(answer))
    task_request = coaching.AcknowledgeRequest("散歩", ())
    result = await adapter.acknowledge(task_request)
    assert isinstance(result, m.Parsed)
    assert (
        coaching.check_acknowledgment(task_request, result.output)[0].check
        is m.CheckId.BUILD_HINT_LATIN
    )


async def test_coach_feedback_preserves_fixes_and_interpreted_slips():
    payload = {
        "kind": "feedback",
        "feedback": {
            "first_line": "意図は伝わっています",
            "fixes": [
                {
                    "number": 1,
                    "original": "walk",
                    "replacement": "walked",
                    "reason": "過去の話です",
                    "tag": "miss",
                }
            ],
            "sentence": "I walk.",
            "template": "I (①) ____.",
            "request_line": "文全体を言い直してください。",
            "readings_noted": [{"written": "starting", "read_as": "studying"}],
        },
    }

    def answer(messages, info):
        return ModelResponse([TextPart(json.dumps(payload))])

    result = await openrouter.OpenRouterCoachModel(
        "coach", FunctionModel(answer)
    ).feedback(coaching.FeedbackRequest("散歩した", "I walk.", None, (), ()))
    assert isinstance(result, m.Parsed)
    assert result.output == coaching.Feedback(
        "意図は伝わっています",
        (coaching.Fix(1, "walk", "walked", "過去の話です", m.FixTag.MISS),),
        "I walk.",
        "I (①) ____.",
        "文全体を言い直してください。",
        (coaching.ReadingNote("starting", "studying"),),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "feedback"},
        {
            "kind": "feedback",
            "feedback": {"first_line": "確認"},
            "word": "leave",
            "readings": ["leave", "live"],
        },
        {
            "kind": "reading_question",
            "word": "leave",
            "readings": ["leave", "live"],
            "feedback": {"first_line": "確認"},
        },
        {
            "kind": "feedback",
            "feedback": {
                "first_line": "確認",
                "fixes": [
                    {
                        "number": 0,
                        "original": None,
                        "replacement": "walk",
                        "reason": "確認",
                        "tag": "miss",
                    }
                ],
                "sentence": "I",
                "template": "(①) ____",
                "request_line": "確認",
            },
        },
    ],
    ids=["missing-payload", "mixed-feedback", "mixed-question", "invalid-fix"],
)
async def test_coach_feedback_rejects_inconsistent_core_payloads(payload):
    def answer(messages, info):
        return ModelResponse(
            [TextPart(json.dumps(payload))],
            usage=RequestUsage(input_tokens=3, output_tokens=4),
        )

    result = await openrouter.OpenRouterCoachModel(
        "coach", FunctionModel(answer)
    ).feedback(coaching.FeedbackRequest(None, "I walk.", None, (), ()))
    assert isinstance(result, m.ParseFailure)
    assert result.usage.input_tokens == 3


@pytest.mark.parametrize(
    "result",
    [
        {"kind": "accepted", "blanks": [1], "hint": "過去形です。"},
        {"kind": "blank_off", "line": "伝わりました。"},
        {"kind": "done", "line": "伝わりました。"},
    ],
    ids=["accepted-with-blank-off-fields", "blank-off-with-accepted-fields", "unknown"],
)
async def test_coach_retry_rejects_a_kind_without_its_own_fields(result):
    def answer(messages, info):
        return ModelResponse(
            [TextPart(json.dumps({"result": result}))],
            usage=RequestUsage(input_tokens=3, output_tokens=4),
        )

    outcome = await openrouter.OpenRouterCoachModel(
        "coach", FunctionModel(answer)
    ).check_retry(coaching.CheckRetryRequest(None, COACH_FEEDBACK, "I walk.", 1, ()))
    assert isinstance(outcome, m.ParseFailure)
    assert outcome.usage.output_tokens == 4
