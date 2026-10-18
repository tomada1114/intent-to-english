"""The Coach's request and output vocabulary, independent of any provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from intent_to_english.core.models import MAX_FIXES, FixTag, Stage, check_text

if TYPE_CHECKING:
    from intent_to_english.core.models import ConversationLine


READING_OPTIONS = 2


@dataclass(frozen=True, slots=True)
class Fix:
    """One sentence-ordered change, numbered for its matching blank."""

    number: int
    original: str | None
    replacement: str
    reason: str
    tag: FixTag

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        if not 1 <= self.number <= MAX_FIXES:
            msg = "Fix number must be 1-20"
            raise ValueError(msg)
        check_text(self.replacement)
        check_text(self.reason)
        if self.original is not None:
            check_text(self.original)


@dataclass(frozen=True, slots=True)
class ReadingNote:
    """A slip interpreted before the English reaches the Partner."""

    written: str
    read_as: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.written)
        check_text(self.read_as)


@dataclass(frozen=True, slots=True)
class Feedback:
    """Feedback teaches only the gaps and preserves the learner sentence."""

    first_line: str
    fixes: tuple[Fix, ...] = ()
    sentence: str | None = None
    template: str | None = None
    request_line: str | None = None
    readings_noted: tuple[ReadingNote, ...] = ()

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.first_line)
        if not self.fixes and any(
            value is not None
            for value in (self.sentence, self.template, self.request_line)
        ):
            msg = (
                "Feedback with no fixes must have no sentence, template or request line"
            )
            raise ValueError(msg)
        if self.fixes:
            for value in (self.sentence, self.template, self.request_line):
                if value is None:
                    msg = "Feedback with fixes requires a sentence, template and request line"
                    raise ValueError(msg)
                check_text(value)


@dataclass(frozen=True, slots=True)
class ReadingQuestion:
    """A single question disambiguating the learner English."""

    word: str
    readings: tuple[str, str]

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.word)
        if (
            len(self.readings) != READING_OPTIONS
            or any(not value.strip() for value in self.readings)
            or self.readings[0] == self.readings[1]
        ):
            msg = "Two distinct nonempty readings are required"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ReadingChoice:
    """The chosen meaning available to the feedback task."""

    word: str
    chosen: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.word)
        check_text(self.chosen)


@dataclass(frozen=True, slots=True)
class Acknowledgment:
    """A Japanese acknowledgment with an optional Japanese build hint."""

    line: str
    build_hint: str | None = None

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.line)
        if self.build_hint is not None:
            check_text(self.build_hint)


@dataclass(frozen=True, slots=True)
class GapHint:
    """Help only for the gap the learner named."""

    hint: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.hint)


@dataclass(frozen=True, slots=True)
class EarlierHint:
    """An earlier gap and its hint in this intent."""

    gap: str
    hint: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.gap)
        check_text(self.hint)


@dataclass(frozen=True, slots=True)
class RetryAccepted:
    """The filled template now conveys the intended English."""

    line: str
    readings_noted: tuple[ReadingNote, ...] = ()

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.line)


@dataclass(frozen=True, slots=True)
class BlankOff:
    """A first retry needs only the named blanks rebuilt."""

    blanks: tuple[int, ...]
    hint: str
    readings_noted: tuple[ReadingNote, ...] = ()

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.hint)
        if not self.blanks or any(
            not 1 <= number <= MAX_FIXES for number in self.blanks
        ):
            msg = "Off blanks must have numbers 1-20"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Piece:
    """The requested phrase after the second retry."""

    number: int
    text: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.text)
        if not 1 <= self.number <= MAX_FIXES:
            msg = "Piece number must be 1-20"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PieceGiven:
    """A second retry ends with only the pieces still missing."""

    pieces: tuple[Piece, ...]
    line: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.line)
        if not self.pieces:
            msg = "At least one piece is required"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Answer:
    """A complete example only when the learner requests it."""

    example: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.example)


@dataclass(frozen=True, slots=True)
class CoachAnswer:
    """A side answer that does not advance the stage."""

    text: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.text)


@dataclass(frozen=True, slots=True)
class WrapUpItem:
    """One expression from the session worth taking away."""

    phrase: str
    note: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.phrase)
        check_text(self.note)


@dataclass(frozen=True, slots=True)
class WrapUp:
    """A session ending without a score or a level."""

    items: tuple[WrapUpItem, ...]


@dataclass(frozen=True, slots=True)
class AcknowledgeRequest:
    """Acknowledge the preserved Japanese intent."""

    intent: str
    conversation: tuple[ConversationLine, ...]

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.intent)


@dataclass(frozen=True, slots=True)
class GapHintRequest:
    """All context for a hint without reading the session."""

    intent: str
    gap: str
    partial_english: str
    earlier: tuple[EarlierHint, ...]
    conversation: tuple[ConversationLine, ...]

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.intent)
        check_text(self.gap)


@dataclass(frozen=True, slots=True)
class FeedbackRequest:
    """Judge the learner English against what they meant."""

    intent: str | None
    english: str
    reading: ReadingChoice | None
    earlier_english: tuple[str, ...]
    conversation: tuple[ConversationLine, ...]

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.english)


@dataclass(frozen=True, slots=True)
class CheckRetryRequest:
    """The same task checks a retry or one practice submission."""

    intent: str | None
    feedback: Feedback
    sentence: str
    submission_number: int
    conversation: tuple[ConversationLine, ...]

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.sentence)
        if self.submission_number not in (1, 2):
            msg = "Submission number must be 1 or 2"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ShowAnswerRequest:
    """A complete answer requested at English or retry."""

    stage: Stage
    intent: str | None
    english: str | None
    feedback: Feedback | None
    conversation: tuple[ConversationLine, ...]

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        if self.stage not in (Stage.ENGLISH, Stage.RETRY):
            msg = "An answer is available only at english or retry"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class AnswerQuestionRequest:
    """A side question may arrive even before the opener."""

    question: str
    stage: Stage
    intent: str | None
    english: str | None
    feedback: Feedback | None
    conversation: tuple[ConversationLine, ...]

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.question)


@dataclass(frozen=True, slots=True)
class WrapUpRequest:
    """The checked feedbacks and English needed for a wrap-up."""

    feedbacks: tuple[Feedback, ...]
    conversation: tuple[ConversationLine, ...]


type RetryResult = RetryAccepted | BlankOff | PieceGiven
