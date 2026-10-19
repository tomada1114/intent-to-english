from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from intent_to_english.core import models
from intent_to_english.core.coaching import Feedback, RetryAccepted
from intent_to_english.core.errors import InvalidTodoError
from intent_to_english.core.models import MAX_TITLE_LENGTH, Todo, normalize_title


@pytest.mark.parametrize(
    ("values", "expected"),
    [((), None), ((None, Decimal(0)), Decimal(0))],
    ids=["unknown", "reported-zero"],
)
def test_sum_reported_costs_preserves_unknown_and_zero(values, expected):
    assert models.sum_reported_costs(values) == expected


def test_sum_reported_costs_rejects_nonfinite_accounting():
    with pytest.raises(ValueError, match="must be finite"):
        models.sum_reported_costs((Decimal("NaN"),))


@pytest.mark.parametrize(
    ("raw_title", "expected"),
    [
        pytest.param("buy milk", "buy milk", id="plain"),
        pytest.param("  buy milk\n", "buy milk", id="surrounding-whitespace"),
        pytest.param("x", "x", id="one-character"),
        pytest.param("x" * MAX_TITLE_LENGTH, "x" * MAX_TITLE_LENGTH, id="max-length"),
        pytest.param("牛乳を買う 🥛", "牛乳を買う 🥛", id="unicode"),
        pytest.param(
            f" {'x' * MAX_TITLE_LENGTH} ",
            "x" * MAX_TITLE_LENGTH,
            id="max-length-after-strip",
        ),
    ],
)
def test_normalize_title_valid_title_returns_stripped_title(raw_title, expected):
    assert normalize_title(raw_title) == expected


@pytest.mark.parametrize(
    ("raw_title", "length"),
    [
        pytest.param("", 0, id="empty"),
        pytest.param(" \t\n ", 0, id="whitespace-only"),
        pytest.param("x" * (MAX_TITLE_LENGTH + 1), MAX_TITLE_LENGTH + 1, id="too-long"),
    ],
)
def test_normalize_title_out_of_range_raises_invalid_todo_error(raw_title, length):
    with pytest.raises(InvalidTodoError, match=rf"1-200 characters .* got {length}$"):
        normalize_title(raw_title)


@pytest.fixture
def make_model(nth_id, fixed_now):
    """Build a ``Todo``, which enforces its invariants on every construction."""

    def _make(title: str = "buy milk", created_at: datetime = fixed_now) -> Todo:
        return Todo(id=nth_id(1), title=title, created_at=created_at)

    return _make


def test_model_valid_fields_keeps_them(make_model, fixed_now):
    model = make_model("buy milk", fixed_now)

    assert (model.title, model.created_at) == ("buy milk", fixed_now)


@pytest.mark.parametrize(
    ("title", "pattern"),
    [
        pytest.param(" buy milk", r"surrounding whitespace", id="unstripped"),
        pytest.param("", r"got 0$", id="empty"),
        pytest.param("x" * (MAX_TITLE_LENGTH + 1), r"got 201$", id="too-long"),
    ],
)
def test_model_invalid_title_raises_invalid_todo_error(make_model, title, pattern):
    with pytest.raises(InvalidTodoError, match=pattern):
        make_model(title)


def test_model_naive_created_at_raises_value_error(make_model):
    naive = datetime.fromisoformat("2026-01-02T03:04:05")

    with pytest.raises(ValueError, match=r"must be timezone-aware"):
        make_model(created_at=naive)


def test_replace_with_invalid_title_raises_invalid_todo_error(nth_id, fixed_now):
    todo = Todo(id=nth_id(1), title="buy milk", created_at=fixed_now)

    with pytest.raises(InvalidTodoError, match=r"got 0$"):
        replace(todo, title="")


def test_session_new_values_start_at_opening_and_reject_invalid_dates(
    fixed_now, nth_id
):

    session = models.Session(id=nth_id(1), started_at=fixed_now)

    assert session.stage is models.Stage.OPENING
    assert session.version == 0
    assert session.turn_index == 1
    assert session.status is models.SessionStatus.IN_PROGRESS
    with pytest.raises(ValueError, match="timezone-aware"):
        models.Session(id=nth_id(1), started_at=fixed_now.replace(tzinfo=None))
    with pytest.raises(ValueError, match="ended_at"):
        replace(session, status=models.SessionStatus.ENDED, stage=models.Stage.ENDED)


def test_practice_target_requires_feedback_with_at_least_one_fix():
    with pytest.raises(ValueError, match="fix"):
        models.PracticeTarget(1, None, Feedback("いいですね"))


@pytest.mark.parametrize(
    "stage",
    [stage for stage in models.Stage if stage is not models.Stage.ENDED],
    ids=lambda stage: stage.value,
)
def test_active_session_refuses_an_end_timestamp(stage, fixed_now, nth_id):
    with pytest.raises(ValueError, match="ended_at"):
        models.Session(nth_id(1), fixed_now, stage=stage, ended_at=fixed_now)


@pytest.mark.parametrize(
    ("kind", "payload", "wrong"),
    [
        pytest.param(
            models.EntryKind.PARTNER_LINE,
            models.PartnerLinePayload("Hi!", False, models.LineKind.OPENER),
            models.SkipPayload(),
            id="partner-line",
        ),
        pytest.param(
            models.EntryKind.INTENT,
            models.IntentPayload("意図"),
            models.SkipPayload(),
            id="intent",
        ),
        pytest.param(
            models.EntryKind.ACKNOWLEDGMENT,
            models.AcknowledgmentPayload("いいですね"),
            models.SkipPayload(),
            id="acknowledgment",
        ),
        pytest.param(
            models.EntryKind.ENGLISH,
            models.EnglishPayload("English"),
            models.SkipPayload(),
            id="english",
        ),
        pytest.param(
            models.EntryKind.HINT_REQUEST,
            models.HintRequestPayload("gap", ""),
            models.SkipPayload(),
            id="hint-request",
        ),
        pytest.param(
            models.EntryKind.GAP_HINT,
            models.GapHintPayload("hint"),
            models.SkipPayload(),
            id="gap-hint",
        ),
        pytest.param(
            models.EntryKind.READING_QUESTION,
            models.ReadingQuestionPayload("word", ("one", "two")),
            models.SkipPayload(),
            id="reading-question",
        ),
        pytest.param(
            models.EntryKind.READING_CHOICE,
            models.ReadingChoicePayload("word", "one"),
            models.SkipPayload(),
            id="reading-choice",
        ),
        pytest.param(
            models.EntryKind.FEEDBACK,
            models.FeedbackPayload(None, Feedback("いいですね")),
            models.SkipPayload(),
            id="feedback",
        ),
        pytest.param(
            models.EntryKind.RETRY,
            models.RetryPayload("English", 1),
            models.SkipPayload(),
            id="retry",
        ),
        pytest.param(
            models.EntryKind.RETRY_RESULT,
            models.RetryResultPayload(RetryAccepted("いいですね")),
            models.SkipPayload(),
            id="retry-result",
        ),
        pytest.param(
            models.EntryKind.ANSWER,
            models.AnswerPayload("Example"),
            models.SkipPayload(),
            id="answer",
        ),
        pytest.param(
            models.EntryKind.TYPED_COPY,
            models.TypedCopyPayload("Example"),
            models.SkipPayload(),
            id="typed-copy",
        ),
        pytest.param(
            models.EntryKind.SKIP,
            models.SkipPayload(),
            models.CheckInPayload(),
            id="skip",
        ),
        pytest.param(
            models.EntryKind.TURN_DONE,
            models.TurnDonePayload("English", models.TurnEnd.ACCEPTED),
            models.SkipPayload(),
            id="turn-done",
        ),
        pytest.param(
            models.EntryKind.QUESTION,
            models.QuestionPayload("質問"),
            models.SkipPayload(),
            id="question",
        ),
        pytest.param(
            models.EntryKind.COACH_ANSWER,
            models.CoachAnswerPayload("答え"),
            models.SkipPayload(),
            id="coach-answer",
        ),
        pytest.param(
            models.EntryKind.CHECK_IN,
            models.CheckInPayload(),
            models.SkipPayload(),
            id="check-in",
        ),
        pytest.param(
            models.EntryKind.CHECK_IN_ANSWER,
            models.CheckInAnswerPayload(models.CheckInAnswer.CONTINUE),
            models.SkipPayload(),
            id="check-in-answer",
        ),
        pytest.param(
            models.EntryKind.PRACTICE,
            models.PracticePayload(1, "English"),
            models.SkipPayload(),
            id="practice",
        ),
        pytest.param(
            models.EntryKind.PRACTICE_RESULT,
            models.PracticeResultPayload(1, RetryAccepted("いいですね")),
            models.SkipPayload(),
            id="practice-result",
        ),
    ],
)
def test_timeline_kind_accepts_only_its_matching_payload(
    kind, payload, wrong, fixed_now, nth_id
):
    entry = models.TimelineEntry(nth_id(2), nth_id(1), 1, 1, kind, payload, fixed_now)
    assert entry.payload == payload
    with pytest.raises(ValueError, match="payload"):
        replace(entry, payload=wrong)
