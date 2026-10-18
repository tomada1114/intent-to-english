"""English-only request values prevent Coach context reaching the Partner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from intent_to_english.core.models import CheckId, Violation, check_text
from intent_to_english.core.text import (
    count_questions,
    count_sentences,
    has_japanese_script,
)

if TYPE_CHECKING:
    from intent_to_english.core.models import ConversationLine, RestateMode


MAX_SENTENCES = 2


@dataclass(frozen=True, slots=True)
class PartnerLine:
    """A short English line, checked before it is stored."""

    text: str

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.text)


@dataclass(frozen=True, slots=True)
class OpenRequest:
    """The last opener permits variety without session context."""

    previous_opener: str | None


@dataclass(frozen=True, slots=True)
class ReplyRequest:
    """Only the English conversation and the taking-turns rule."""

    conversation: tuple[ConversationLine, ...]
    share: bool


@dataclass(frozen=True, slots=True)
class RestateRequest:
    """Restate only the Partner line the learner is answering."""

    conversation: tuple[ConversationLine, ...]
    line: str
    mode: RestateMode

    def __post_init__(self) -> None:
        """Reject structural inconsistencies before content checks run."""
        check_text(self.line)


def check_open(_request: OpenRequest, output: PartnerLine) -> tuple[Violation, ...]:
    """Check an opener without enforcing candidate style rules."""
    return _check_line(output)


def check_reply(request: ReplyRequest, output: PartnerLine) -> tuple[Violation, ...]:
    """Check a reply, including the server's taking-turns flag."""
    violations = _check_line(output)
    if request.share and count_questions(output.text):
        violations += (
            Violation(CheckId.PARTNER_SHARE, "A share must ask no question"),
        )
    return violations


def check_restate(
    _request: RestateRequest, output: PartnerLine
) -> tuple[Violation, ...]:
    """Apply the same language and length rules to a restatement."""
    return _check_line(output)


def _check_line(output: PartnerLine) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    if has_japanese_script(output.text):
        violations.append(
            Violation(
                CheckId.PARTNER_JAPANESE,
                "A Partner line must contain no Japanese script",
            )
        )
    sentences = count_sentences(output.text)
    if sentences > MAX_SENTENCES:
        violations.append(
            Violation(CheckId.PARTNER_SENTENCES, f"{sentences} sentences; at most 2")
        )
    questions = count_questions(output.text)
    if questions > 1:
        violations.append(
            Violation(CheckId.PARTNER_QUESTIONS, f"{questions} questions; at most 1")
        )
    return tuple(violations)
