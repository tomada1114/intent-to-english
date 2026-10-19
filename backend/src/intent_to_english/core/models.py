"""The to-do domain model, the rules every to-do obeys, and the page of a listing."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from intent_to_english.core.errors import InvalidPageLimitError, InvalidTodoError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime
    from uuid import UUID

    from intent_to_english.core.coaching import (
        Feedback,
        ReadingQuestion,
        RetryResult,
        WrapUp,
    )

MIN_TITLE_LENGTH = 1
MAX_TITLE_LENGTH = 200
# Template defaults: an app changes the constants, and every entry point follows.
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100


def sum_reported_costs(values: Iterable[Decimal | None]) -> Decimal | None:
    """Sum reported credits exactly, keeping an entirely unknown cost absent."""
    reported = [value for value in values if value is not None]
    if not reported:
        return None
    if any(not value.is_finite() for value in reported):
        message = "Reported costs must be finite"
        raise ValueError(message)
    # Preserve every decimal place and the possible carry across requests.
    fraction_digits = max(0, -min(int(value.as_tuple().exponent) for value in reported))
    integer_digits = max(1, *(value.adjusted() + 1 for value in reported))
    with localcontext() as context:
        context.prec = max(
            context.prec, integer_digits + fraction_digits + len(str(len(reported))) + 1
        )
        return sum(reported, Decimal())


def normalize_title(raw_title: str) -> str:
    """Strip a title and enforce its length rule.

    The rule lives here, not in an API request model, so every entry point
    rejects the same titles with the same message.

    Args:
        raw_title: The title as the user typed it.

    Returns:
        The title without surrounding whitespace.

    Raises:
        InvalidTodoError: If the stripped title is empty or too long.
    """
    title = raw_title.strip()
    if not MIN_TITLE_LENGTH <= len(title) <= MAX_TITLE_LENGTH:
        msg = (
            f"Title must be {MIN_TITLE_LENGTH}-{MAX_TITLE_LENGTH} characters "
            f"after stripping whitespace, got {len(title)}"
        )
        raise InvalidTodoError(msg)
    return title


def check_page_limit(limit: int) -> None:
    """Enforce how many items one page may hold.

    The rule lives here, not in a route's query parameter, so every entry point
    rejects the same limits with the same message.

    Args:
        limit: The number of items a caller asked for.

    Raises:
        InvalidPageLimitError: If ``limit`` is below 1 or above ``MAX_PAGE_LIMIT``.
    """
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        msg = f"Page limit must be 1-{MAX_PAGE_LIMIT}, got {limit}"
        raise InvalidPageLimitError(msg)


@dataclass(frozen=True, slots=True)
class Todo:
    """A to-do, with the id the application gave it when it was created.

    Frozen so a change is always a new value handed back to the repository,
    never an in-place edit that a repository could silently miss.
    """

    id: UUID
    title: str
    created_at: datetime
    is_completed: bool = False

    def __post_init__(self) -> None:
        """Refuse to exist in a state no rule allows.

        Checked on every construction, because adapters rebuild to-dos from
        storage and ``dataclasses.replace`` builds new ones.

        Raises:
            InvalidTodoError: If the title is not already normalized, as
                ``normalize_title`` returns it.
            ValueError: If ``created_at`` is naive. That is a bug in a clock or
                an adapter, not bad user input, so it is not a domain error.
        """
        if normalize_title(self.title) != self.title:
            msg = "Title must not have surrounding whitespace; pass it through normalize_title"
            raise InvalidTodoError(msg)
        if self.created_at.utcoffset() is None:
            msg = (
                f"created_at must be timezone-aware, got {self.created_at.isoformat()}"
            )
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of a listing, and where the next one starts.

    Attributes:
        items: The page's items, in the order the listing promises.
        next_cursor: Opaque to every caller; pass it back to fetch the next
            page. ``None`` exactly when no stored item follows this page.
    """

    items: tuple[T, ...]
    next_cursor: str | None


SESSION_PAGE_LIMIT = 20
MAX_FIXES = 20
MAX_RETRIES = 2


class Stage(StrEnum):
    """The closed set of stage values shared by every layer."""

    OPENING = "opening"
    INTENT = "intent"
    ENGLISH = "english"
    READING_CHECK = "reading_check"
    RETRY = "retry"
    ANSWER_SHOWN = "answer_shown"
    PARTNER_TURN = "partner_turn"
    CHECK_IN = "check_in"
    ENDED = "ended"


class Action(StrEnum):
    """The closed set of action values shared by every layer."""

    OPEN = "open"
    INTENT = "intent"
    ENGLISH_DIRECT = "english_direct"
    ENGLISH = "english"
    HINT = "hint"
    READING = "reading"
    RETRY = "retry"
    SHOW_ANSWER = "show_answer"
    TYPED_COPY = "typed_copy"
    SKIP = "skip"
    PARTNER_REPLY = "partner_reply"
    RESTATE = "restate"
    REWRITE_INTENT = "rewrite_intent"
    PRACTICE_AGAIN = "practice_again"
    ASK = "ask"
    END = "end"
    WRAP_UP = "wrap_up"


class EntryKind(StrEnum):
    """The closed set of entrykind values shared by every layer."""

    PARTNER_LINE = "partner_line"
    INTENT = "intent"
    ACKNOWLEDGMENT = "acknowledgment"
    ENGLISH = "english"
    HINT_REQUEST = "hint_request"
    GAP_HINT = "gap_hint"
    READING_QUESTION = "reading_question"
    READING_CHOICE = "reading_choice"
    FEEDBACK = "feedback"
    RETRY = "retry"
    RETRY_RESULT = "retry_result"
    ANSWER = "answer"
    TYPED_COPY = "typed_copy"
    SKIP = "skip"
    TURN_DONE = "turn_done"
    QUESTION = "question"
    COACH_ANSWER = "coach_answer"
    CHECK_IN = "check_in"
    CHECK_IN_ANSWER = "check_in_answer"
    PRACTICE = "practice"
    PRACTICE_RESULT = "practice_result"


class SessionStatus(StrEnum):
    """The closed set of sessionstatus values shared by every layer."""

    IN_PROGRESS = "in_progress"
    ENDED = "ended"


class SubmissionStatus(StrEnum):
    """The closed set of submissionstatus values shared by every layer."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CallOutcome(StrEnum):
    """The closed set of calloutcome values shared by every layer."""

    OK = "ok"
    INVALID_OUTPUT = "invalid_output"
    REPAIRED = "repaired"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_ERROR = "provider_error"


class ModelRole(StrEnum):
    """The closed set of modelrole values shared by every layer."""

    PARTNER = "partner"
    COACH = "coach"


class ModelTask(StrEnum):
    """The closed set of modeltask values shared by every layer."""

    OPEN = "open"
    REPLY = "reply"
    RESTATE = "restate"
    ACKNOWLEDGE = "acknowledge"
    GAP_HINT = "gap_hint"
    FEEDBACK = "feedback"
    CHECK_RETRY = "check_retry"
    SHOW_ANSWER = "show_answer"
    ANSWER_QUESTION = "answer_question"
    WRAP_UP = "wrap_up"


class FixTag(StrEnum):
    """The closed set of fixtag values shared by every layer."""

    MISS = "miss"
    IMPROVEMENT = "improvement"


class RestateMode(StrEnum):
    """The closed set of restatemode values shared by every layer."""

    SHORTER = "shorter"
    SIMPLER = "simpler"


class CheckInAnswer(StrEnum):
    """The closed set of checkinanswer values shared by every layer."""

    CONTINUE = "continue"
    END = "end"


class TurnEnd(StrEnum):
    """The closed set of turnend values shared by every layer."""

    ACCEPTED = "accepted"
    SKIPPED = "skipped"
    ANSWER_TYPED = "answer_typed"
    NO_FIX_NEEDED = "no_fix_needed"
    PIECE_GIVEN = "piece_given"


class CheckId(StrEnum):
    """The closed set of checkid values shared by every layer."""

    SCHEMA = "schema"
    FIX_NUMBERS = "fix_numbers"
    BLANKS_FILLED = "blanks_filled"
    COMPLETED_SENTENCE = "completed_sentence"
    BUILD_HINT_LATIN = "build_hint_latin"
    PARTNER_JAPANESE = "partner_japanese"
    PARTNER_SENTENCES = "partner_sentences"
    PARTNER_QUESTIONS = "partner_questions"
    PARTNER_SHARE = "partner_share"


class LineKind(StrEnum):
    """The closed set of linekind values shared by every layer."""

    OPENER = "opener"
    REPLY = "reply"
    RESTATEMENT = "restatement"


class Speaker(StrEnum):
    """The closed set of speaker values shared by every layer."""

    PARTNER = "partner"
    LEARNER = "learner"


class LastSubmissionState(StrEnum):
    """The closed set of lastsubmissionstate values shared by every layer."""

    PENDING = "pending"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


def check_aware(value: datetime | None) -> None:
    """Reject a naive timestamp before an adapter can persist it."""
    if value is not None and value.utcoffset() is None:
        msg = "Timestamp must be timezone-aware"
        raise ValueError(msg)


def check_text(value: str) -> None:
    """Keep an empty string from representing a required model field."""
    if not value.strip():
        msg = "Text must not be empty"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class NoInput:
    """An action with no learner input."""


@dataclass(frozen=True, slots=True)
class TextInput:
    """Text supplied by the learner, checked by the action rule."""

    text: str


@dataclass(frozen=True, slots=True)
class HintInput:
    """The named gap and the English the learner already built."""

    gap: str
    partial_english: str = ""


@dataclass(frozen=True, slots=True)
class ReadingInput:
    """The reading the learner chose."""

    reading: str


@dataclass(frozen=True, slots=True)
class RestateInput:
    """How the Partner should restate its own line."""

    mode: RestateMode


@dataclass(frozen=True, slots=True)
class Usage:
    """Provider accounting for exactly one model request."""

    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cost: Decimal | None
    latency_ms: int

    def __post_init__(self) -> None:
        """Refuse structurally invalid values at every boundary."""
        if self.latency_ms < 0 or any(
            v is not None and v < 0
            for v in (self.input_tokens, self.output_tokens, self.cost)
        ):
            msg = "Usage values must be nonnegative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Violation:
    """A safe explanation of a check failure without learner text."""

    check: CheckId
    detail: str


@dataclass(frozen=True, slots=True)
class Repair:
    """The violations the second and final attempt must repair."""

    violations: tuple[Violation, ...]


@dataclass(frozen=True, slots=True)
class CallAttempt:
    """One model request, including a failed or repaired output."""

    role: ModelRole
    task: ModelTask
    attempt: int
    usage: Usage
    outcome: CallOutcome
    violations: tuple[Violation, ...] = ()

    def __post_init__(self) -> None:
        """Refuse structurally invalid values at every boundary."""
        if self.attempt not in (1, 2):
            msg = "Attempt must be 1 or 2"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    """An append-only accounting record independent of action success."""

    id: UUID
    session_id: UUID
    submission_id: UUID
    turn_index: int
    call: CallAttempt
    created_at: datetime

    def __post_init__(self) -> None:
        """Refuse structurally invalid values at every boundary."""
        check_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class Parsed[T]:
    """A parsed core value with the accounting of its request."""

    output: T
    usage: Usage


@dataclass(frozen=True, slots=True)
class ParseFailure:
    """Unparsable output retains accounting but never raw model text."""

    usage: Usage
    detail: str


@dataclass(frozen=True, slots=True)
class ConversationLine:
    """An English line the Partner said or heard."""

    speaker: Speaker
    text: str

    def __post_init__(self) -> None:
        """Refuse structurally invalid values at every boundary."""
        check_text(self.text)


@dataclass(frozen=True, slots=True)
class PracticeTarget:
    """The finished turn that can still be practised once more."""

    turn_index: int
    intent: str | None
    feedback: Feedback

    def __post_init__(self) -> None:
        """Only a finished turn with a fix can be a practice target."""
        if self.turn_index < 1 or not self.feedback.fixes:
            msg = "A practice target requires a positive turn index and a fix"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TurnState:
    """Only the working state the next action needs."""

    intent: str | None = None
    english: str | None = None
    feedback: Feedback | None = None
    retry_count: int = 0
    reading: ReadingQuestion | None = None
    shown_answer: str | None = None
    practice: PracticeTarget | None = None

    def __post_init__(self) -> None:
        """Refuse structurally invalid values at every boundary."""
        if not 0 <= self.retry_count <= MAX_RETRIES:
            msg = "Retry count must be 0-2"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Session:
    """The current state, replaced atomically when an action finishes."""

    id: UUID
    started_at: datetime
    ended_at: datetime | None = None
    status: SessionStatus = SessionStatus.IN_PROGRESS
    stage: Stage = Stage.OPENING
    turn_index: int = 1
    turn_state: TurnState = field(default_factory=TurnState)
    version: int = 0
    finished_replies: int = 0
    opener: str | None = None
    wrap_up: WrapUp | None = None

    def __post_init__(self) -> None:
        """Refuse structurally invalid values at every boundary."""
        check_aware(self.started_at)
        check_aware(self.ended_at)
        if (self.status is SessionStatus.ENDED) != (self.ended_at is not None):
            msg = "ended_at must be set exactly when a session is ended"
            raise ValueError(msg)
        if (self.status is SessionStatus.ENDED) != (self.stage is Stage.ENDED):
            msg = "Session status and stage must agree"
            raise ValueError(msg)
        if self.version < 0 or self.turn_index < 1 or self.finished_replies < 0:
            msg = "Session counters are outside their bounds"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PartnerLinePayload:
    """A Partner line with the metadata needed by both panes."""

    text: str
    has_question: bool
    line_kind: LineKind
    restate_mode: RestateMode | None = None


@dataclass(frozen=True, slots=True)
class IntentPayload:
    """The Japanese intention preserved before the English."""

    text: str
    is_replacement: bool = False


@dataclass(frozen=True, slots=True)
class AcknowledgmentPayload:
    """The Coach acknowledges the intent without giving English."""

    line: str
    build_hint: str | None = None


@dataclass(frozen=True, slots=True)
class EnglishPayload:
    """The learner English before feedback."""

    text: str
    is_direct: bool = False


@dataclass(frozen=True, slots=True)
class HintRequestPayload:
    """A hint request kept alongside the response."""

    gap: str
    partial_english: str


@dataclass(frozen=True, slots=True)
class GapHintPayload:
    """Help limited to the named gap."""

    hint: str


@dataclass(frozen=True, slots=True)
class ReadingQuestionPayload:
    """The two readings that change the feedback."""

    word: str
    readings: tuple[str, str]


@dataclass(frozen=True, slots=True)
class ReadingChoicePayload:
    """The reading the learner selected."""

    word: str
    chosen: str


@dataclass(frozen=True, slots=True)
class FeedbackPayload:
    """Checked feedback with its intent line."""

    intent: str | None
    feedback: Feedback


@dataclass(frozen=True, slots=True)
class RetryPayload:
    """The filled template, not a free rewrite."""

    sentence: str
    submission_number: int


@dataclass(frozen=True, slots=True)
class RetryResultPayload:
    """The checked retry result, including any reading notes."""

    result: RetryResult


@dataclass(frozen=True, slots=True)
class AnswerPayload:
    """A complete answer requested by the learner."""

    example: str


@dataclass(frozen=True, slots=True)
class TypedCopyPayload:
    """The shown answer typed once without another model call."""

    text: str


@dataclass(frozen=True, slots=True)
class SkipPayload:
    """An explicit skip, rendered with the fixed neutral line."""


@dataclass(frozen=True, slots=True)
class TurnDonePayload:
    """The final English the Partner receives for this turn."""

    english: str
    end: TurnEnd


@dataclass(frozen=True, slots=True)
class QuestionPayload:
    """A question only the Coach receives."""

    text: str


@dataclass(frozen=True, slots=True)
class CoachAnswerPayload:
    """The answer to a side question."""

    text: str


@dataclass(frozen=True, slots=True)
class CheckInPayload:
    """A pause after each third finished reply."""


@dataclass(frozen=True, slots=True)
class CheckInAnswerPayload:
    """The learner continues or ends at a check-in."""

    answer: CheckInAnswer


@dataclass(frozen=True, slots=True)
class PracticePayload:
    """A practice submission tied to its finished turn."""

    turn_index: int
    sentence: str


@dataclass(frozen=True, slots=True)
class PracticeResultPayload:
    """The practice result does not advance the conversation."""

    turn_index: int
    result: RetryResult


type ActionInput = NoInput | TextInput | HintInput | ReadingInput | RestateInput
type EntryPayload = (
    PartnerLinePayload
    | IntentPayload
    | AcknowledgmentPayload
    | EnglishPayload
    | HintRequestPayload
    | GapHintPayload
    | ReadingQuestionPayload
    | ReadingChoicePayload
    | FeedbackPayload
    | RetryPayload
    | RetryResultPayload
    | AnswerPayload
    | TypedCopyPayload
    | SkipPayload
    | TurnDonePayload
    | QuestionPayload
    | CoachAnswerPayload
    | CheckInPayload
    | CheckInAnswerPayload
    | PracticePayload
    | PracticeResultPayload
)

ENTRY_PAYLOAD_TYPES: Mapping[EntryKind, type[EntryPayload]] = MappingProxyType(
    {
        EntryKind.PARTNER_LINE: PartnerLinePayload,
        EntryKind.INTENT: IntentPayload,
        EntryKind.ACKNOWLEDGMENT: AcknowledgmentPayload,
        EntryKind.ENGLISH: EnglishPayload,
        EntryKind.HINT_REQUEST: HintRequestPayload,
        EntryKind.GAP_HINT: GapHintPayload,
        EntryKind.READING_QUESTION: ReadingQuestionPayload,
        EntryKind.READING_CHOICE: ReadingChoicePayload,
        EntryKind.FEEDBACK: FeedbackPayload,
        EntryKind.RETRY: RetryPayload,
        EntryKind.RETRY_RESULT: RetryResultPayload,
        EntryKind.ANSWER: AnswerPayload,
        EntryKind.TYPED_COPY: TypedCopyPayload,
        EntryKind.SKIP: SkipPayload,
        EntryKind.TURN_DONE: TurnDonePayload,
        EntryKind.QUESTION: QuestionPayload,
        EntryKind.COACH_ANSWER: CoachAnswerPayload,
        EntryKind.CHECK_IN: CheckInPayload,
        EntryKind.CHECK_IN_ANSWER: CheckInAnswerPayload,
        EntryKind.PRACTICE: PracticePayload,
        EntryKind.PRACTICE_RESULT: PracticeResultPayload,
    }
)


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """An immutable entry in the append-only session timeline."""

    id: UUID
    session_id: UUID
    seq: int
    turn_index: int
    kind: EntryKind
    payload: EntryPayload
    created_at: datetime

    def __post_init__(self) -> None:
        """Refuse structurally invalid values at every boundary."""
        check_aware(self.created_at)
        if type(self.payload) is not ENTRY_PAYLOAD_TYPES[self.kind]:
            msg = "Timeline kind and payload type must agree"
            raise ValueError(msg)
        if self.seq < 1 or self.turn_index < 1:
            msg = "Timeline counters must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """An action always names the version the learner answered."""

    action: Action
    version: int
    input: ActionInput = field(default_factory=NoInput)


@dataclass(frozen=True, slots=True)
class Submission:
    """An input stored before any model request begins."""

    id: UUID
    session_id: UUID
    base_version: int
    action: Action
    input: ActionInput
    boot_id: UUID
    created_at: datetime
    status: SubmissionStatus = SubmissionStatus.PENDING
    failure_code: str | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse structurally invalid values at every boundary."""
        check_aware(self.created_at)
        check_aware(self.finished_at)


@dataclass(frozen=True, slots=True)
class LastSubmission:
    """The pending or recoverable input shown after reopening."""

    state: LastSubmissionState
    action: Action
    input: ActionInput
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class StoredSession:
    """The repository snapshot consumed by a service."""

    session: Session
    entries: tuple[TimelineEntry, ...] = ()
    last_submission: Submission | None = None


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """One row of the newest-first listing."""

    id: UUID
    started_at: datetime
    status: SessionStatus
    finished_replies: int
    opener: str | None


@dataclass(frozen=True, slots=True)
class SessionView:
    """The complete view; the browser never chooses a stage."""

    id: UUID
    status: SessionStatus
    stage: Stage
    version: int
    turn_index: int
    finished_replies: int
    started_at: datetime
    ended_at: datetime | None
    allowed_actions: tuple[Action, ...]
    entries: tuple[TimelineEntry, ...]
    last_submission: LastSubmission | None
    wrap_up: WrapUp | None
