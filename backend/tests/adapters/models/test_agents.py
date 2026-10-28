from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from intent_to_english.adapters.models import agents, prompts
from intent_to_english.adapters.models.agents import AgentCoachModel, AgentPartnerModel
from intent_to_english.core import coaching, partner
from intent_to_english.core import models as m
from intent_to_english.core.errors import (
    ModelError,
    ModelRateLimitedError,
    ModelTimeoutError,
    ModelUnavailableError,
)

pytestmark = pytest.mark.anyio


@dataclass
class FakeProvider:
    """A provider half that records what the neutral wrapper asks of it."""

    name: str = "test-provider"
    settings: ModelSettings = field(
        default_factory=lambda: ModelSettings(timeout=agents.CALL_TIMEOUT_SECONDS)
    )
    price: Decimal | None = Decimal("0.0042")
    refuse: bool = False
    mapped: tuple[type[ModelError], int | None] = (ModelUnavailableError, None)
    failures: list[ModelAPIError] = field(default_factory=list)
    priced: list[RequestUsage] = field(default_factory=list)
    responses: list[ModelResponse] = field(default_factory=list)

    def failure(self, error):
        self.failures.append(error)
        return self.mapped

    def refused(self, response):
        self.responses.append(response)
        return self.refuse

    def cost(self, usage):
        self.priced.append(usage)
        return self.price


def partner_model(model_id, function, provider=None, monotonic=None):
    return AgentPartnerModel(
        model_id,
        FunctionModel(function),
        provider or FakeProvider(),
        *(() if monotonic is None else (monotonic,)),
    )


def coach_model(model_id, function, provider=None, monotonic=None):
    return AgentCoachModel(
        model_id,
        FunctionModel(function),
        provider or FakeProvider(),
        *(() if monotonic is None else (monotonic,)),
    )


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

    adapter = coach_model("coach", answer)

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
        )

    ticks = iter((10.0, 10.125))
    provider = FakeProvider()
    adapter = partner_model("configured-model", answer, provider, lambda: next(ticks))
    repair = (
        m.Repair((m.Violation(m.CheckId.PARTNER_JAPANESE, "Use English"),))
        if repairing
        else None
    )
    rendered = getattr(prompts, f"render_{task}")(task_request, repair)

    result = await getattr(adapter, task)(task_request, repair)

    assert result == m.Parsed(
        partner.PartnerLine("Nice! What did you do?"),
        m.Usage("test-provider", "configured-model", 12, 8, Decimal("0.0042"), 125),
    )
    assert [(u.input_tokens, u.output_tokens) for u in provider.priced] == [(12, 8)]
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
    adapter = partner_model(
        "model", answer, FakeProvider(price=None), lambda: next(ticks)
    )

    result = await adapter.open(partner.OpenRequest(None))

    assert isinstance(result, m.ParseFailure)
    assert result.usage == m.Usage("test-provider", "model", 4, 3, None, 250)
    assert len(calls) == 1
    assert text not in result.detail


async def test_wall_clock_budget_expires_without_waiting_for_sdk(monkeypatch):
    async def slow(messages, info):
        await asyncio.sleep(1)
        return ModelResponse([TextPart('{"line":"Hi!"}')])

    monkeypatch.setattr(agents, "CALL_TIMEOUT_SECONDS", 0.01)
    ticks = iter((0.0, 0.025))
    adapter = partner_model("model", slow, monotonic=lambda: next(ticks))

    with pytest.raises(ModelTimeoutError, match="Model timeout") as caught:
        await adapter.open(partner.OpenRequest(None))

    assert caught.value.latency_ms == 25


async def test_parsed_japanese_remains_a_core_check_failure():
    def answer(messages, info):
        return ModelResponse([TextPart('{"line":"こんにちは"}')])

    adapter = partner_model("model", answer)
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

    adapter = partner_model("model", bug)

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
        )

    adapter = coach_model("coach-id", answer, FakeProvider(), lambda: 1.0)
    repair = m.Repair((m.Violation(m.CheckId.SCHEMA, "Repair marker"),))
    result = await getattr(adapter, task)(task_request, repair)
    assert result.usage == m.Usage(
        "test-provider", "coach-id", 9, 7, Decimal("0.0042"), 0
    )
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

    adapter = coach_model("coach", answer)
    result = await adapter.feedback(
        coaching.FeedbackRequest(None, "I want to leave.", None, (), ())
    )
    assert isinstance(result, m.ParseFailure)
    assert result.usage.output_tokens == 3


async def test_coach_preserves_content_failure_for_the_core_repair():
    def answer(messages, info):
        return ModelResponse([TextPart('{"line":"いいですね","build_hint":"Use I"}')])

    adapter = coach_model("coach", answer)
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

    result = await coach_model("coach", answer).feedback(
        coaching.FeedbackRequest("散歩した", "I walk.", None, (), ())
    )
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

    result = await coach_model("coach", answer).feedback(
        coaching.FeedbackRequest(None, "I walk.", None, (), ())
    )
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

    outcome = await coach_model("coach", answer).check_retry(
        coaching.CheckRetryRequest(None, COACH_FEEDBACK, "I walk.", 1, ())
    )
    assert isinstance(outcome, m.ParseFailure)
    assert outcome.usage.output_tokens == 4


@pytest.mark.parametrize(
    ("mapped", "error"),
    [
        ((ModelRateLimitedError, 429), ModelHTTPError(429, "model", "PRIVATE-TEXT")),
        ((ModelUnavailableError, 529), ModelHTTPError(529, "model", "PRIVATE-TEXT")),
        ((ModelTimeoutError, None), ModelAPIError("model", "PRIVATE-TEXT")),
    ],
    ids=["rate-limited", "unavailable", "timeout"],
)
async def test_provider_failure_raises_the_core_error_the_provider_names(mapped, error):
    def fail(messages, info):
        raise error

    provider = FakeProvider(mapped=mapped)
    ticks = iter((3.0, 3.5))
    adapter = partner_model("model", fail, provider, lambda: next(ticks))

    with pytest.raises(mapped[0]) as caught:
        await adapter.open(partner.OpenRequest(None))

    assert provider.failures == [error]
    assert (caught.value.provider, caught.value.model) == ("test-provider", "model")
    assert (caught.value.latency_ms, caught.value.status) == (500, mapped[1])
    assert "PRIVATE-TEXT" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "response",
    [
        ModelResponse([TextPart('{"line":"Nice! What did you do?"}')]),
        ModelResponse([TextPart('{"li')]),
        ModelResponse([], finish_reason="content_filter"),
    ],
    ids=["parsed", "unparsed", "empty"],
)
async def test_refused_response_is_unavailable_and_never_a_parse_failure(response):
    calls = []

    def answer(messages, info):
        calls.append(messages)
        return response

    ticks = iter((1.0, 1.5))
    adapter = partner_model(
        "model", answer, FakeProvider(refuse=True), lambda: next(ticks)
    )

    with pytest.raises(ModelUnavailableError) as caught:
        await adapter.open(partner.OpenRequest(None))

    assert len(calls) == 1
    assert (caught.value.provider, caught.value.latency_ms) == ("test-provider", 500)
    assert caught.value.status is None


async def test_content_filter_without_a_provider_refusal_stays_a_parse_failure():
    def answer(messages, info):
        return ModelResponse(
            [],
            finish_reason="content_filter",
            usage=RequestUsage(input_tokens=5, output_tokens=0),
        )

    result = await partner_model("model", answer).open(partner.OpenRequest(None))

    assert isinstance(result, m.ParseFailure)
    assert result.usage.input_tokens == 5
