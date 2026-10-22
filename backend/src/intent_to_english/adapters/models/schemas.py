"""Provider output schemas convert to framework-free core values."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from intent_to_english.core import coaching
from intent_to_english.core.models import FixTag
from intent_to_english.core.partner import PartnerLine


class PartnerLineOutput(BaseModel):
    """A Partner line; content rules remain in the core's task checks."""

    model_config = ConfigDict(extra="forbid")
    line: str

    def to_domain(self) -> PartnerLine:
        """Apply core invariants after schema validation."""
        return PartnerLine(self.line)


class CoachOutput(BaseModel):
    """Reject fields outside the task's structured output contract."""

    model_config = ConfigDict(extra="forbid")


class AcknowledgmentOutput(CoachOutput):
    """A short acknowledgment, with a Japanese-only build hint when needed."""

    line: str
    build_hint: str | None = None

    def to_domain(self) -> coaching.Acknowledgment:
        """Keep semantic checks in the core."""
        return coaching.Acknowledgment(self.line, self.build_hint)


class GapHintOutput(CoachOutput):
    """Help for only the learner's named gap."""

    hint: str

    def to_domain(self) -> coaching.GapHint:
        """Apply the core text invariant."""
        return coaching.GapHint(self.hint)


class FixOutput(CoachOutput):
    """One numbered replacement; null original represents a missing point."""

    number: int
    original: str | None
    replacement: str
    reason: str
    tag: FixTag

    def to_domain(self) -> coaching.Fix:
        """Validate numbering and required text through the core."""
        return coaching.Fix(
            self.number, self.original, self.replacement, self.reason, self.tag
        )


class ReadingNoteOutput(CoachOutput):
    """A transcription interpreted from context, never a pronunciation claim."""

    written: str
    read_as: str

    def to_domain(self) -> coaching.ReadingNote:
        """Apply the core's nonempty-text invariants."""
        return coaching.ReadingNote(self.written, self.read_as)


class FeedbackValue(CoachOutput):
    """Sentence-ordered fixes and their matching fill-in template."""

    first_line: str
    fixes: tuple[FixOutput, ...] = ()
    sentence: str | None = None
    template: str | None = None
    request_line: str | None = None
    readings_noted: tuple[ReadingNoteOutput, ...] = ()

    def to_domain(self) -> coaching.Feedback:
        """Let the core reject inconsistent feedback parts."""
        return coaching.Feedback(
            self.first_line,
            tuple(f.to_domain() for f in self.fixes),
            self.sentence,
            self.template,
            self.request_line,
            tuple(r.to_domain() for r in self.readings_noted),
        )


class FeedbackOutput(CoachOutput):
    """One top-level object, usable with NativeOutput's response_format.

    Readings stay an unbounded array: native structured output accepts no array
    length beyond minItems 1, so the pair is checked when converting instead.
    """

    kind: Literal["feedback", "reading_question"]
    feedback: FeedbackValue | None = None
    word: str | None = None
    readings: tuple[str, ...] | None = None

    def to_domain(self) -> coaching.Feedback | coaching.ReadingQuestion:
        """Require exactly the payload selected by kind."""
        if (
            self.kind == "feedback"
            and self.feedback is not None
            and self.word is None
            and self.readings is None
        ):
            return self.feedback.to_domain()
        if (
            self.kind == "reading_question"
            and self.feedback is None
            and self.word is not None
            and self.readings is not None
            and len(self.readings) == coaching.READING_OPTIONS
        ):
            first, second = self.readings
            return coaching.ReadingQuestion(self.word, (first, second))
        message = "Feedback kind requires its matching payload only"
        raise ValueError(message)


class RetryAcceptedOutput(CoachOutput):
    """A confirmation without repeating the complete filled sentence."""

    kind: Literal["accepted"]
    line: str
    readings_noted: tuple[ReadingNoteOutput, ...] = ()

    def to_domain(self) -> coaching.RetryAccepted:
        """Preserve the interpretations for the Partner's final English."""
        return coaching.RetryAccepted(
            self.line, tuple(r.to_domain() for r in self.readings_noted)
        )


class BlankOffOutput(CoachOutput):
    """A larger hint for the first submission's remaining blanks."""

    kind: Literal["blank_off"]
    blanks: tuple[int, ...]
    hint: str
    readings_noted: tuple[ReadingNoteOutput, ...] = ()

    def to_domain(self) -> coaching.BlankOff:
        """Validate the blank numbers at the core boundary."""
        return coaching.BlankOff(
            self.blanks, self.hint, tuple(r.to_domain() for r in self.readings_noted)
        )


class PieceOutput(CoachOutput):
    """Only a still-missing piece, never the whole sentence."""

    number: int
    text: str

    def to_domain(self) -> coaching.Piece:
        """Validate its number and content."""
        return coaching.Piece(self.number, self.text)


class PieceGivenOutput(CoachOutput):
    """The second submission ends with the pieces still missing."""

    kind: Literal["piece_given"]
    pieces: tuple[PieceOutput, ...]
    line: str

    def to_domain(self) -> coaching.PieceGiven:
        """Reject an empty set of pieces through the core."""
        return coaching.PieceGiven(tuple(p.to_domain() for p in self.pieces), self.line)


class RetryOutput(CoachOutput):
    """Wrap the kind-tagged result in one native-output object.

    A plain union keeps the schema's anyOf: a pydantic discriminator emits oneOf,
    which native structured output does not support. Each member's literal kind and
    forbidden extra fields still select exactly one.
    """

    result: RetryAcceptedOutput | BlankOffOutput | PieceGivenOutput

    def to_domain(self) -> coaching.RetryResult:
        """Convert the selected result without changing its meaning."""
        return self.result.to_domain()


class AnswerOutput(CoachOutput):
    """A complete example requested explicitly by the learner."""

    example: str

    def to_domain(self) -> coaching.Answer:
        """Apply the core text invariant."""
        return coaching.Answer(self.example)


class CoachAnswerOutput(CoachOutput):
    """A side answer that never moves the conversation stage."""

    text: str

    def to_domain(self) -> coaching.CoachAnswer:
        """Apply the core text invariant."""
        return coaching.CoachAnswer(self.text)


class WrapUpItemOutput(CoachOutput):
    """An expression and a brief Japanese note from this session."""

    phrase: str
    note: str

    def to_domain(self) -> coaching.WrapUpItem:
        """Apply the core text invariants."""
        return coaching.WrapUpItem(self.phrase, self.note)


class WrapUpOutput(CoachOutput):
    """The session's takeaways without grades or next actions."""

    items: tuple[WrapUpItemOutput, ...]

    def to_domain(self) -> coaching.WrapUp:
        """Preserve the ordered takeaways."""
        return coaching.WrapUp(tuple(item.to_domain() for item in self.items))
