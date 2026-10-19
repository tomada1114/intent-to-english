"""Provider output schemas convert to framework-free core values."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from intent_to_english.core.partner import PartnerLine


class PartnerLineOutput(BaseModel):
    """A Partner line; content rules remain in the core's task checks."""

    model_config = ConfigDict(extra="forbid")
    line: str

    def to_domain(self) -> PartnerLine:
        """Apply core invariants after schema validation."""
        return PartnerLine(self.line)
