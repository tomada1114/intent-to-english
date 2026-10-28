"""Request and response bodies: the API's wire format, kept apart from the domain.

A domain field can be renamed without breaking a client, because only the
``from_domain`` classmethods map one onto the other.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from intent_to_english.core import models as m

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemFieldError(BaseModel):
    """A request parsing failure, without raw input or server context."""

    loc: list[str | int]
    message: str
    type: str


class ProblemDetails(BaseModel):
    """RFC 9457 error body with a stable application code."""

    type: Literal["about:blank"] = "about:blank"
    title: str
    status: int
    detail: str
    code: str
    request_id: str
    errors: list[ProblemFieldError] | None = None


def status_phrase(status: int) -> str:
    """Keep valid extension statuses usable when the stdlib has no phrase."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Unknown Status"


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Register error models; the factory publishes their Problem media type.

    ``Any`` matches FastAPI's ``responses=`` declaration type.
    """
    return {
        status: {"model": ProblemDetails, "description": status_phrase(status)}
        for status in statuses
    }


class HealthResponse(BaseModel):
    """Body of ``GET /healthz``."""

    status: Literal["ok"] = "ok"


class _SessionWireModel(BaseModel):
    """Reject unmapped fields at the explicit conversation wire boundary."""

    model_config = ConfigDict(extra="forbid")


class _ActionRequest(_SessionWireModel):
    """Map a versioned wire action onto the core's input values."""

    action: str
    version: StrictInt
    attempt_id: UUID

    def _input(self) -> m.ActionInput:
        return m.NoInput()

    def to_domain(self) -> m.ActionRequest:
        """Leave normalization, lengths and stage rules to the core."""
        return m.ActionRequest(
            m.Action(self.action),
            self.version,
            self._input(),
            attempt_id=self.attempt_id,
        )


class _TextActionRequest(_ActionRequest):
    """Text stays unconstrained until the core applies this action's limit."""

    text: str

    def _input(self) -> m.ActionInput:
        return m.TextInput(self.text)


class _HintActionRequest(_ActionRequest):
    """The named gap and the learner's partial English."""

    gap: str
    partial_english: str = ""

    def _input(self) -> m.ActionInput:
        return m.HintInput(self.gap, self.partial_english)


class _ReadingActionRequest(_ActionRequest):
    """The core checks membership in the two offered readings."""

    reading: str

    def _input(self) -> m.ActionInput:
        return m.ReadingInput(self.reading)


class _RestateActionRequest(_ActionRequest):
    """The requested shorter or simpler wording."""

    mode: m.RestateMode

    def _input(self) -> m.ActionInput:
        return m.RestateInput(self.mode)


class OpenActionRequest(_ActionRequest):
    """Body for the open action."""

    action: Literal["open"]


class IntentActionRequest(_TextActionRequest):
    """Body for the intent action."""

    action: Literal["intent"]


class EnglishDirectActionRequest(_TextActionRequest):
    """Body for the english_direct action."""

    action: Literal["english_direct"]


class EnglishActionRequest(_TextActionRequest):
    """Body for the english action."""

    action: Literal["english"]


class HintActionRequest(_HintActionRequest):
    """Body for the hint action."""

    action: Literal["hint"]


class ReadingActionRequest(_ReadingActionRequest):
    """Body for the reading action."""

    action: Literal["reading"]


class RetryActionRequest(_TextActionRequest):
    """Body for the retry action."""

    action: Literal["retry"]


class ShowAnswerActionRequest(_ActionRequest):
    """Body for the show_answer action."""

    action: Literal["show_answer"]


class TypedCopyActionRequest(_TextActionRequest):
    """Body for the typed_copy action."""

    action: Literal["typed_copy"]


class SkipActionRequest(_ActionRequest):
    """Body for the skip action."""

    action: Literal["skip"]


class PartnerReplyActionRequest(_ActionRequest):
    """Body for the partner_reply action."""

    action: Literal["partner_reply"]


class RestateActionRequest(_RestateActionRequest):
    """Body for the restate action."""

    action: Literal["restate"]


class RewriteIntentActionRequest(_TextActionRequest):
    """Body for the rewrite_intent action."""

    action: Literal["rewrite_intent"]


class PracticeAgainActionRequest(_TextActionRequest):
    """Body for the practice_again action."""

    action: Literal["practice_again"]


class AskActionRequest(_TextActionRequest):
    """Body for the ask action."""

    action: Literal["ask"]


class EndActionRequest(_ActionRequest):
    """Body for the end action."""

    action: Literal["end"]


class WrapUpActionRequest(_ActionRequest):
    """Body for the wrap_up action."""

    action: Literal["wrap_up"]


type SessionActionBody = Annotated[
    OpenActionRequest
    | IntentActionRequest
    | EnglishDirectActionRequest
    | EnglishActionRequest
    | HintActionRequest
    | ReadingActionRequest
    | RetryActionRequest
    | ShowAnswerActionRequest
    | TypedCopyActionRequest
    | SkipActionRequest
    | PartnerReplyActionRequest
    | RestateActionRequest
    | RewriteIntentActionRequest
    | PracticeAgainActionRequest
    | AskActionRequest
    | EndActionRequest
    | WrapUpActionRequest,
    Field(discriminator="action"),
]


class CancelSessionRequest(_SessionWireModel):
    """The version and exact attempt identity to abandon, even before admission."""

    version: StrictInt
    attempt_id: UUID


class MetaResponse(_SessionWireModel):
    """The mode selected by the process container."""

    model_mode: Literal["fixed", "anthropic"]


class FixResponse(_SessionWireModel):
    """One numbered sentence-ordered fix."""

    number: int
    original: str | None
    replacement: str
    reason: str
    tag: m.FixTag


class ReadingNoteResponse(_SessionWireModel):
    """The written word and the interpretation used."""

    written: str
    read_as: str


class FeedbackResponse(_SessionWireModel):
    """The checked feedback and its optional retry template."""

    first_line: str
    fixes: list[FixResponse]
    sentence: str | None
    template: str | None
    request_line: str | None
    readings_noted: list[ReadingNoteResponse]


class RetryAcceptedResponse(_SessionWireModel):
    """A retry that conveys the intended English."""

    line: str
    readings_noted: list[ReadingNoteResponse]


class BlankOffResponse(_SessionWireModel):
    """The missing blanks and their larger hint."""

    blanks: list[int]
    hint: str
    readings_noted: list[ReadingNoteResponse]


class PieceResponse(_SessionWireModel):
    """One requested piece after the second retry."""

    number: int
    text: str


class PieceGivenResponse(_SessionWireModel):
    """The remaining pieces at the end of a retry."""

    pieces: list[PieceResponse]
    line: str


type RetryResultResponse = RetryAcceptedResponse | BlankOffResponse | PieceGivenResponse


class PartnerLinePayloadResponse(_SessionWireModel):
    """The PartnerLinePayload wire fields."""

    text: str
    has_question: bool
    line_kind: m.LineKind
    restate_mode: m.RestateMode | None


class IntentPayloadResponse(_SessionWireModel):
    """The IntentPayload wire fields."""

    text: str
    is_replacement: bool


class AcknowledgmentPayloadResponse(_SessionWireModel):
    """The AcknowledgmentPayload wire fields."""

    line: str
    build_hint: str | None


class EnglishPayloadResponse(_SessionWireModel):
    """The EnglishPayload wire fields."""

    text: str
    is_direct: bool


class HintRequestPayloadResponse(_SessionWireModel):
    """The HintRequestPayload wire fields."""

    gap: str
    partial_english: str


class GapHintPayloadResponse(_SessionWireModel):
    """The GapHintPayload wire fields."""

    hint: str


class ReadingQuestionPayloadResponse(_SessionWireModel):
    """The ReadingQuestionPayload wire fields."""

    word: str
    readings: tuple[str, str]


class ReadingChoicePayloadResponse(_SessionWireModel):
    """The ReadingChoicePayload wire fields."""

    word: str
    chosen: str


class FeedbackPayloadResponse(_SessionWireModel):
    """The FeedbackPayload wire fields."""

    intent: str | None
    feedback: FeedbackResponse


class RetryPayloadResponse(_SessionWireModel):
    """The RetryPayload wire fields."""

    sentence: str
    submission_number: int


class RetryResultPayloadResponse(_SessionWireModel):
    """The RetryResultPayload wire fields."""

    result: RetryResultResponse


class AnswerPayloadResponse(_SessionWireModel):
    """The AnswerPayload wire fields."""

    example: str


class TypedCopyPayloadResponse(_SessionWireModel):
    """The TypedCopyPayload wire fields."""

    text: str


class EmptyPayloadResponse(_SessionWireModel):
    """The EmptyPayload wire fields."""


class TurnDonePayloadResponse(_SessionWireModel):
    """The TurnDonePayload wire fields."""

    english: str
    end: m.TurnEnd


class QuestionPayloadResponse(_SessionWireModel):
    """The QuestionPayload wire fields."""

    text: str


class CoachAnswerPayloadResponse(_SessionWireModel):
    """The CoachAnswerPayload wire fields."""

    text: str


class CheckInAnswerPayloadResponse(_SessionWireModel):
    """The CheckInAnswerPayload wire fields."""

    answer: m.CheckInAnswer


class PracticePayloadResponse(_SessionWireModel):
    """The PracticePayload wire fields."""

    turn_index: int
    sentence: str


class PracticeResultPayloadResponse(_SessionWireModel):
    """The PracticeResultPayload wire fields."""

    turn_index: int
    result: RetryResultResponse


class _TimelineEntryResponse(_SessionWireModel):
    """The common identity and ordering of an append-only entry."""

    id: UUID
    session_id: UUID
    seq: int
    turn_index: int
    created_at: datetime


class PartnerLineEntryResponse(_TimelineEntryResponse):
    """A partner_line timeline entry."""

    kind: Literal["partner_line"]
    payload: PartnerLinePayloadResponse


class IntentEntryResponse(_TimelineEntryResponse):
    """A intent timeline entry."""

    kind: Literal["intent"]
    payload: IntentPayloadResponse


class AcknowledgmentEntryResponse(_TimelineEntryResponse):
    """A acknowledgment timeline entry."""

    kind: Literal["acknowledgment"]
    payload: AcknowledgmentPayloadResponse


class EnglishEntryResponse(_TimelineEntryResponse):
    """A english timeline entry."""

    kind: Literal["english"]
    payload: EnglishPayloadResponse


class HintRequestEntryResponse(_TimelineEntryResponse):
    """A hint_request timeline entry."""

    kind: Literal["hint_request"]
    payload: HintRequestPayloadResponse


class GapHintEntryResponse(_TimelineEntryResponse):
    """A gap_hint timeline entry."""

    kind: Literal["gap_hint"]
    payload: GapHintPayloadResponse


class ReadingQuestionEntryResponse(_TimelineEntryResponse):
    """A reading_question timeline entry."""

    kind: Literal["reading_question"]
    payload: ReadingQuestionPayloadResponse


class ReadingChoiceEntryResponse(_TimelineEntryResponse):
    """A reading_choice timeline entry."""

    kind: Literal["reading_choice"]
    payload: ReadingChoicePayloadResponse


class FeedbackEntryResponse(_TimelineEntryResponse):
    """A feedback timeline entry."""

    kind: Literal["feedback"]
    payload: FeedbackPayloadResponse


class RetryEntryResponse(_TimelineEntryResponse):
    """A retry timeline entry."""

    kind: Literal["retry"]
    payload: RetryPayloadResponse


class RetryResultEntryResponse(_TimelineEntryResponse):
    """A retry_result timeline entry."""

    kind: Literal["retry_result"]
    payload: RetryResultPayloadResponse


class AnswerEntryResponse(_TimelineEntryResponse):
    """A answer timeline entry."""

    kind: Literal["answer"]
    payload: AnswerPayloadResponse


class TypedCopyEntryResponse(_TimelineEntryResponse):
    """A typed_copy timeline entry."""

    kind: Literal["typed_copy"]
    payload: TypedCopyPayloadResponse


class SkipEntryResponse(_TimelineEntryResponse):
    """A skip timeline entry."""

    kind: Literal["skip"]
    payload: EmptyPayloadResponse


class TurnDoneEntryResponse(_TimelineEntryResponse):
    """A turn_done timeline entry."""

    kind: Literal["turn_done"]
    payload: TurnDonePayloadResponse


class QuestionEntryResponse(_TimelineEntryResponse):
    """A question timeline entry."""

    kind: Literal["question"]
    payload: QuestionPayloadResponse


class CoachAnswerEntryResponse(_TimelineEntryResponse):
    """A coach_answer timeline entry."""

    kind: Literal["coach_answer"]
    payload: CoachAnswerPayloadResponse


class CheckInEntryResponse(_TimelineEntryResponse):
    """A check_in timeline entry."""

    kind: Literal["check_in"]
    payload: EmptyPayloadResponse


class CheckInAnswerEntryResponse(_TimelineEntryResponse):
    """A check_in_answer timeline entry."""

    kind: Literal["check_in_answer"]
    payload: CheckInAnswerPayloadResponse


class PracticeEntryResponse(_TimelineEntryResponse):
    """A practice timeline entry."""

    kind: Literal["practice"]
    payload: PracticePayloadResponse


class PracticeResultEntryResponse(_TimelineEntryResponse):
    """A practice_result timeline entry."""

    kind: Literal["practice_result"]
    payload: PracticeResultPayloadResponse


type TimelineEntryResponse = Annotated[
    PartnerLineEntryResponse
    | IntentEntryResponse
    | AcknowledgmentEntryResponse
    | EnglishEntryResponse
    | HintRequestEntryResponse
    | GapHintEntryResponse
    | ReadingQuestionEntryResponse
    | ReadingChoiceEntryResponse
    | FeedbackEntryResponse
    | RetryEntryResponse
    | RetryResultEntryResponse
    | AnswerEntryResponse
    | TypedCopyEntryResponse
    | SkipEntryResponse
    | TurnDoneEntryResponse
    | QuestionEntryResponse
    | CoachAnswerEntryResponse
    | CheckInEntryResponse
    | CheckInAnswerEntryResponse
    | PracticeEntryResponse
    | PracticeResultEntryResponse,
    Field(discriminator="kind"),
]


class NoInputResponse(_SessionWireModel):
    """An action without learner input."""


class TextInputResponse(_SessionWireModel):
    """Recoverable learner text."""

    text: str


class HintInputResponse(_SessionWireModel):
    """A recoverable gap request."""

    gap: str
    partial_english: str


class ReadingInputResponse(_SessionWireModel):
    """A recoverable reading choice."""

    reading: str


class RestateInputResponse(_SessionWireModel):
    """A recoverable restatement request."""

    mode: m.RestateMode


type ActionInputResponse = (
    NoInputResponse
    | TextInputResponse
    | HintInputResponse
    | ReadingInputResponse
    | RestateInputResponse
)


class LastSubmissionResponse(_SessionWireModel):
    """Pending or recoverable input with opaque correlation identity."""

    attempt_id: UUID
    state: m.LastSubmissionState
    action: m.Action
    input: ActionInputResponse
    failure_code: str | None


class WrapUpItemResponse(_SessionWireModel):
    """An expression encountered during this session."""

    phrase: str
    note: str


class WrapUpResponse(_SessionWireModel):
    """An empty list differs from a wrap-up that is still due."""

    items: list[WrapUpItemResponse]


class SessionResponse(_SessionWireModel):
    """The complete public session view, independent of internal working state."""

    id: UUID
    status: m.SessionStatus
    stage: m.Stage
    version: int
    turn_index: int
    finished_replies: int
    started_at: datetime
    ended_at: datetime | None
    allowed_actions: list[m.Action]
    entries: list[TimelineEntryResponse]
    last_submission: LastSubmissionResponse | None
    wrap_up: WrapUpResponse | None

    @classmethod
    def from_domain(cls, view: m.SessionView) -> SessionResponse:
        """Revalidate the recursive domain snapshot into explicit wire models."""
        return cls.model_validate(asdict(view))


class SessionSummaryResponse(_SessionWireModel):
    """One row of the newest-first session list."""

    id: UUID
    started_at: datetime
    status: m.SessionStatus
    finished_replies: int
    opener: str | None


class SessionPageResponse(_SessionWireModel):
    """One bounded page and its opaque continuation cursor."""

    items: list[SessionSummaryResponse]
    next_cursor: str | None

    @classmethod
    def from_domain(cls, page: m.Page[m.SessionSummary]) -> SessionPageResponse:
        """Map a domain page without exposing its repository representation."""
        return cls.model_validate(asdict(page))
