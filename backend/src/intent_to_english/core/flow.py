"""The action rules; model outputs never choose a stage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from intent_to_english.core.coaching import (
    BlankOff,
    Feedback,
    ReadingQuestion,
    RetryAccepted,
    RetryResult,
)
from intent_to_english.core.errors import InvalidInputError
from intent_to_english.core.models import (
    Action,
    HintInput,
    NoInput,
    ReadingInput,
    RestateInput,
    RestateMode,
    Stage,
    TextInput,
    TurnEnd,
)

if TYPE_CHECKING:
    from intent_to_english.core.models import ActionInput, Session

MAX_TEXT_LENGTH = 1000
MAX_GAP_LENGTH = 200
MAX_QUESTION_LENGTH = 500
CHECK_IN_INTERVAL = 3

ACTION_STAGES: dict[Action, frozenset[Stage]] = {
    Action.OPEN: frozenset({Stage.OPENING}),
    Action.INTENT: frozenset({Stage.INTENT}),
    Action.ENGLISH_DIRECT: frozenset({Stage.INTENT}),
    Action.ENGLISH: frozenset({Stage.ENGLISH}),
    Action.HINT: frozenset({Stage.ENGLISH}),
    Action.READING: frozenset({Stage.READING_CHECK}),
    Action.RETRY: frozenset({Stage.RETRY}),
    Action.SHOW_ANSWER: frozenset({Stage.ENGLISH, Stage.RETRY}),
    Action.TYPED_COPY: frozenset({Stage.ANSWER_SHOWN}),
    Action.SKIP: frozenset({Stage.RETRY, Stage.ANSWER_SHOWN}),
    Action.PARTNER_REPLY: frozenset({Stage.PARTNER_TURN, Stage.CHECK_IN}),
    Action.RESTATE: frozenset(
        {
            Stage.INTENT,
            Stage.ENGLISH,
            Stage.READING_CHECK,
            Stage.RETRY,
            Stage.ANSWER_SHOWN,
        }
    ),
    Action.REWRITE_INTENT: frozenset(
        {Stage.ENGLISH, Stage.READING_CHECK, Stage.RETRY, Stage.ANSWER_SHOWN}
    ),
    Action.PRACTICE_AGAIN: frozenset({Stage.CHECK_IN, Stage.INTENT}),
    Action.ASK: frozenset(Stage) - {Stage.ENDED},
    Action.END: frozenset(Stage) - {Stage.ENDED},
    Action.WRAP_UP: frozenset({Stage.ENDED}),
}
TEXT_ACTIONS = frozenset(
    {
        Action.INTENT,
        Action.ENGLISH_DIRECT,
        Action.ENGLISH,
        Action.RETRY,
        Action.TYPED_COPY,
        Action.REWRITE_INTENT,
        Action.PRACTICE_AGAIN,
        Action.ASK,
    }
)


def allowed_actions(session: Session) -> tuple[Action, ...]:
    """Apply both stage rules and the current turn's extra guards."""
    allowed = {
        action for action, stages in ACTION_STAGES.items() if session.stage in stages
    }
    if session.wrap_up is not None:
        allowed.discard(Action.WRAP_UP)
    if session.turn_state.practice is None:
        allowed.discard(Action.PRACTICE_AGAIN)
    if session.turn_state.intent is None:
        allowed.discard(Action.REWRITE_INTENT)
    return tuple(action for action in Action if action in allowed)


def _text(value: str, field: str, limit: int, *, can_be_empty: bool = False) -> str:
    stripped = value.strip()
    if len(stripped) > limit or (not stripped and not can_be_empty):
        raise InvalidInputError(field, limit, len(stripped))
    return stripped


def check_input(action: Action, value: ActionInput) -> ActionInput:
    """Normalize once and reject a wrong input kind without echoing text."""
    result: ActionInput
    if action in TEXT_ACTIONS and isinstance(value, TextInput):
        limit = MAX_QUESTION_LENGTH if action is Action.ASK else MAX_TEXT_LENGTH
        result = TextInput(_text(value.text, "text", limit))
    elif action is Action.HINT and isinstance(value, HintInput):
        result = HintInput(
            _text(value.gap, "gap", MAX_GAP_LENGTH),
            _text(
                value.partial_english,
                "partial_english",
                MAX_TEXT_LENGTH,
                can_be_empty=True,
            ),
        )
    elif action is Action.READING and isinstance(value, ReadingInput):
        result = ReadingInput(_text(value.reading, "reading", len(value.reading)))
    elif (
        action is Action.RESTATE
        and isinstance(value, RestateInput)
        and isinstance(value.mode, RestateMode)
    ) or (
        action not in TEXT_ACTIONS | {Action.HINT, Action.READING, Action.RESTATE}
        and isinstance(value, NoInput)
    ):
        result = value
    else:
        field = "kind"
        raise InvalidInputError(field, 0, 0)
    return result


def after_feedback(output: Feedback | ReadingQuestion) -> Stage | TurnEnd:
    """Only a checked output determines which predefined branch follows."""
    result: Stage | TurnEnd
    if isinstance(output, ReadingQuestion):
        result = Stage.READING_CHECK
    elif output.fixes:
        result = Stage.RETRY
    else:
        result = TurnEnd.NO_FIX_NEEDED
    return result


def after_retry(result: RetryResult, submission_number: int) -> Stage | TurnEnd:
    """Allow one more attempt only after the first incomplete retry."""
    next_state: Stage | TurnEnd
    if isinstance(result, RetryAccepted):
        next_state = TurnEnd.ACCEPTED
    elif isinstance(result, BlankOff) and submission_number == 1:
        next_state = Stage.RETRY
    else:
        next_state = TurnEnd.PIECE_GIVEN
    return next_state


def after_turn_done(finished_replies: int) -> Stage:
    """Pause after each third finished reply, before the Partner speaks."""
    return (
        Stage.CHECK_IN
        if finished_replies % CHECK_IN_INTERVAL == 0
        else Stage.PARTNER_TURN
    )
