"""The Coach's request and output vocabulary, independent of any provider."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from intent_to_english.core.models import (
    MAX_FIXES,
    CheckId,
    FixTag,
    Stage,
    Violation,
    check_text,
)
from intent_to_english.core.text import has_latin_letter

if TYPE_CHECKING:
    from intent_to_english.core.models import ConversationLine


READING_OPTIONS = 2
_BLANK = re.compile(r"\(([①-⑳])\) ____")
_REMAINING_BLANK = re.compile(r"[①-⑳]|_{2,}")


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


def check_acknowledgment(
    _request: AcknowledgeRequest, output: Acknowledgment
) -> tuple[Violation, ...]:
    """Keep a build hint free of Latin letters."""
    if output.build_hint is not None and has_latin_letter(output.build_hint):
        return (
            Violation(
                CheckId.BUILD_HINT_LATIN, "A build hint must contain no Latin letters"
            ),
        )
    return ()


def check_gap_hint(_request: GapHintRequest, _output: GapHint) -> tuple[Violation, ...]:
    """Expose a uniform entry point without adding candidate checks."""
    return ()


def check_feedback(
    request: FeedbackRequest, output: Feedback | ReadingQuestion
) -> tuple[Violation, ...]:
    """Check numbered blanks and prevent a completed-sentence leak."""
    if isinstance(output, ReadingQuestion):
        if request.reading is not None:
            return (
                Violation(
                    CheckId.SCHEMA,
                    "A chosen reading must receive feedback, not another reading question",
                ),
            )
        return ()
    if not output.fixes:
        return ()
    return (
        _check_fix_numbers(output)
        + _check_blanks_filled(output)
        + _check_completed_sentence(output, output)
    )


def check_retry_result(
    request: CheckRetryRequest, output: RetryResult
) -> tuple[Violation, ...]:
    """A retry result must not repeat the whole filled sentence."""
    return _check_completed_sentence(request.feedback, output)


def check_show_answer(
    _request: ShowAnswerRequest, _output: Answer
) -> tuple[Violation, ...]:
    """The requested complete answer is exempt from the leak rule."""
    return ()


def check_answer_question(
    request: AnswerQuestionRequest, output: CoachAnswer
) -> tuple[Violation, ...]:
    """Check side answers against feedback only when it exists."""
    return (
        _check_completed_sentence(request.feedback, output)
        if request.feedback is not None
        else ()
    )


def check_wrap_up(_request: WrapUpRequest, _output: WrapUp) -> tuple[Violation, ...]:
    """Leave candidate wrap-up checks to a future requirement."""
    return ()


def _fill_feedback(feedback: Feedback) -> str:
    replacements = {fix.number: fix.replacement for fix in feedback.fixes}
    return _BLANK.sub(
        lambda match: replacements.get(ord(match[1]) - ord("①") + 1, match[0]),
        feedback.template or "",
    )


def _check_fix_numbers(feedback: Feedback) -> tuple[Violation, ...]:
    expected = tuple(range(1, len(feedback.fixes) + 1))
    numbers = tuple(fix.number for fix in feedback.fixes)
    blanks = tuple(
        ord(match[1]) - ord("①") + 1
        for match in _BLANK.finditer(feedback.template or "")
    )
    if numbers != expected or blanks != expected:
        return (
            Violation(
                CheckId.FIX_NUMBERS,
                f"Fixes and blanks must both ascend from 1 through {len(expected)} exactly once",
            ),
        )
    return ()


def _check_blanks_filled(feedback: Feedback) -> tuple[Violation, ...]:
    if _REMAINING_BLANK.search(_fill_feedback(feedback)):
        return (
            Violation(
                CheckId.BLANKS_FILLED, "Filling every fix must leave no blank marker"
            ),
        )
    return ()


def _normalize(text: str) -> str:
    return (
        re.sub(r"\s+", " ", text.casefold().replace("\u2019", "'"))
        .strip()
        .rstrip(".!?")
        .rstrip()
    )


def _text_fields(value: object) -> tuple[str, ...]:
    if isinstance(value, StrEnum):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, tuple):
        return tuple(text for item in value for text in _text_fields(item))
    if is_dataclass(value) and not isinstance(value, type):
        return tuple(
            text
            for field in fields(value)
            for text in _text_fields(getattr(value, field.name))
        )
    return ()


def _check_completed_sentence(
    feedback: Feedback, output: object
) -> tuple[Violation, ...]:
    if not feedback.fixes:
        return ()
    filled = _normalize(_fill_feedback(feedback))
    if filled and any(filled in _normalize(text) for text in _text_fields(output)):
        return (
            Violation(
                CheckId.COMPLETED_SENTENCE,
                "The completed sentence must appear in no output text field",
            ),
        )
    return ()
