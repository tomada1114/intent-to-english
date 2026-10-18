from __future__ import annotations

from dataclasses import replace

import pytest

from intent_to_english.core import flow
from intent_to_english.core.coaching import (
    BlankOff,
    Feedback,
    Fix,
    Piece,
    PieceGiven,
    ReadingQuestion,
    RetryAccepted,
    WrapUp,
)
from intent_to_english.core.errors import InvalidInputError
from intent_to_english.core.models import (
    Action,
    FixTag,
    HintInput,
    NoInput,
    PracticeTarget,
    ReadingInput,
    RestateInput,
    RestateMode,
    Session,
    SessionStatus,
    Stage,
    TextInput,
    TurnEnd,
    TurnState,
)

EXPECTED = {
    "opening": {"open", "ask", "end"},
    "intent": {"intent", "english_direct", "restate", "ask", "end"},
    "english": {
        "english",
        "hint",
        "show_answer",
        "restate",
        "rewrite_intent",
        "ask",
        "end",
    },
    "reading_check": {"reading", "restate", "rewrite_intent", "ask", "end"},
    "retry": {
        "retry",
        "show_answer",
        "skip",
        "restate",
        "rewrite_intent",
        "ask",
        "end",
    },
    "answer_shown": {"typed_copy", "skip", "restate", "rewrite_intent", "ask", "end"},
    "partner_turn": {"partner_reply", "ask", "end"},
    "check_in": {"partner_reply", "ask", "end"},
    "ended": {"wrap_up"},
}


@pytest.mark.parametrize("stage", list(Stage), ids=lambda s: s.value)
@pytest.mark.parametrize("action", list(Action), ids=lambda a: a.value)
def test_allowed_actions_obeys_every_action_stage_pair(
    stage, action, fixed_now, nth_id
):
    session = Session(nth_id(1), fixed_now, turn_state=TurnState(intent="意図"))

    status = {Stage.ENDED: SessionStatus.ENDED}.get(stage, SessionStatus.IN_PROGRESS)
    ended_at = {Stage.ENDED: fixed_now}.get(stage)
    session = replace(session, status=status, ended_at=ended_at, stage=stage)
    assert (action in flow.allowed_actions(session)) == (
        action.value in EXPECTED[stage.value]
    )


@pytest.mark.parametrize(
    "action",
    [
        Action.INTENT,
        Action.ENGLISH_DIRECT,
        Action.ENGLISH,
        Action.RETRY,
        Action.TYPED_COPY,
        Action.REWRITE_INTENT,
        Action.PRACTICE_AGAIN,
        Action.ASK,
    ],
)
def test_check_input_accepts_limit_and_rejects_one_past_without_echo(action):
    limit = 500 if action is Action.ASK else 1000
    assert flow.check_input(action, TextInput("日" * limit)) == TextInput("日" * limit)
    with pytest.raises(
        InvalidInputError, match=f"limit {limit}, length {limit + 1}"
    ) as caught:
        flow.check_input(action, TextInput("日" * (limit + 1)))
    assert "日" not in str(caught.value)
    with pytest.raises(InvalidInputError, match="length 0"):
        flow.check_input(action, TextInput("   "))
    with pytest.raises(InvalidInputError, match="kind"):
        flow.check_input(action, NoInput())


def test_check_input_hint_checks_gap_and_optional_partial_english():
    assert flow.check_input(Action.HINT, HintInput("日" * 200)) == HintInput("日" * 200)
    with pytest.raises(InvalidInputError, match="gap"):
        flow.check_input(Action.HINT, HintInput("日" * 201))
    with pytest.raises(InvalidInputError, match="partial_english"):
        flow.check_input(Action.HINT, HintInput("gap", "x" * 1001))


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        pytest.param(3, Stage.CHECK_IN, id="third"),
        pytest.param(4, Stage.PARTNER_TURN, id="fourth"),
        pytest.param(6, Stage.CHECK_IN, id="sixth"),
    ],
)
def test_turn_done_pauses_at_each_third_reply(count, expected):
    assert flow.after_turn_done(count) is expected


def test_turn_state_guards_practice_and_intent_rewrite(fixed_now, nth_id):

    feedback = Feedback(
        "直してみよう",
        (Fix(1, "I", "Actually, I", "自然に", FixTag.IMPROVEMENT),),
        "I stayed home.",
        "(①) ____ stayed home.",
        "穴を埋めよう",
    )
    session = Session(nth_id(1), fixed_now, stage=Stage.INTENT)
    assert Action.PRACTICE_AGAIN not in flow.allowed_actions(session)
    practising = replace(
        session, turn_state=TurnState(practice=PracticeTarget(1, "家にいた", feedback))
    )
    assert Action.PRACTICE_AGAIN in flow.allowed_actions(practising)
    assert Action.REWRITE_INTENT not in flow.allowed_actions(
        replace(session, stage=Stage.RETRY)
    )
    assert Action.REWRITE_INTENT in flow.allowed_actions(
        replace(session, stage=Stage.RETRY, turn_state=TurnState(intent="家にいた"))
    )


def test_feedback_and_retry_transitions_end_or_choose_a_known_stage():

    assert (
        flow.after_feedback(ReadingQuestion("leave", ("去る", "住む")))
        is Stage.READING_CHECK
    )
    assert flow.after_feedback(Feedback("いいですね")) is TurnEnd.NO_FIX_NEEDED
    feedback = Feedback(
        "直してみよう",
        (Fix(1, "I", "Actually, I", "自然に", FixTag.IMPROVEMENT),),
        "I stayed home.",
        "(①) ____ stayed home.",
        "穴を埋めよう",
    )
    assert flow.after_feedback(feedback) is Stage.RETRY
    assert flow.after_retry(RetryAccepted("いいね"), 1) is TurnEnd.ACCEPTED
    assert flow.after_retry(BlankOff((1,), "最初だけ"), 1) is Stage.RETRY
    assert flow.after_retry(BlankOff((1,), "最初だけ"), 2) is TurnEnd.PIECE_GIVEN
    assert (
        flow.after_retry(PieceGiven((Piece(1, "Actually, I"),), "続けよう"), 2)
        is TurnEnd.PIECE_GIVEN
    )


def test_nontext_action_inputs_are_normalized_and_wrong_kinds_rejected():

    assert flow.check_input(Action.OPEN, NoInput()) == NoInput()
    assert flow.check_input(Action.READING, ReadingInput(" 去る ")) == ReadingInput(
        "去る"
    )
    assert flow.check_input(
        Action.RESTATE, RestateInput(RestateMode.SHORTER)
    ) == RestateInput(RestateMode.SHORTER)
    with pytest.raises(InvalidInputError, match="kind"):
        flow.check_input(Action.OPEN, TextInput("private input"))


def test_reading_input_has_no_text_action_length_limit():
    assert flow.check_input(Action.READING, ReadingInput("読" * 1001)) == ReadingInput(
        "読" * 1001
    )


def test_wrap_up_is_no_input_and_only_allowed_when_an_ended_session_is_due(
    fixed_now, nth_id
):
    due = Session(
        nth_id(1),
        fixed_now,
        ended_at=fixed_now,
        status=SessionStatus.ENDED,
        stage=Stage.ENDED,
    )
    assert flow.allowed_actions(due) == (Action.WRAP_UP,)
    assert flow.check_input(Action.WRAP_UP, NoInput()) == NoInput()
    assert flow.allowed_actions(replace(due, wrap_up=WrapUp(items=()))) == ()
    assert Action.WRAP_UP not in flow.allowed_actions(Session(nth_id(2), fixed_now))
