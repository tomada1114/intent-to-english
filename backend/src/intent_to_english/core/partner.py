"""English-only request values prevent Coach context reaching the Partner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from intent_to_english.core.models import check_text

if TYPE_CHECKING:
    from intent_to_english.core.models import ConversationLine, RestateMode


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
