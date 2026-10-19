"""Observe actual port returns without adding requests or moving core checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from intent_to_english.core import models as m
from intent_to_english.core.errors import ModelError

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from intent_to_english.core import coaching as c
    from intent_to_english.core import partner as p
    from intent_to_english.core.ports import CoachModel, PartnerModel


@dataclass
class Observation:
    """One output slot per attempted call, including failures."""

    outputs: list[object | None] = field(default_factory=list)

    async def call[T](
        self, pending: Awaitable[m.Parsed[T] | m.ParseFailure]
    ) -> m.Parsed[T] | m.ParseFailure:
        """Preserve both the actual result and the task runner's error behavior."""
        try:
            result = await pending
        except ModelError:
            self.outputs.append(None)
            raise
        self.outputs.append(result.output if isinstance(result, m.Parsed) else None)
        return result


@dataclass(frozen=True, slots=True)
class ObservedPartner:
    """The Partner port with one observer shared by this case's attempts."""

    inner: PartnerModel
    observation: Observation

    async def open(
        self, request: p.OpenRequest, repair: m.Repair | None = None
    ) -> m.Parsed[p.PartnerLine] | m.ParseFailure:
        """Observe the opener call."""
        return await self.observation.call(self.inner.open(request, repair))

    async def reply(
        self, request: p.ReplyRequest, repair: m.Repair | None = None
    ) -> m.Parsed[p.PartnerLine] | m.ParseFailure:
        """Observe the reply call."""
        return await self.observation.call(self.inner.reply(request, repair))

    async def restate(
        self, request: p.RestateRequest, repair: m.Repair | None = None
    ) -> m.Parsed[p.PartnerLine] | m.ParseFailure:
        """Observe the restatement call."""
        return await self.observation.call(self.inner.restate(request, repair))


@dataclass(frozen=True, slots=True)
class ObservedCoach:
    """The Coach port with the same one-slot-per-call observation."""

    inner: CoachModel
    observation: Observation

    async def acknowledge(
        self, request: c.AcknowledgeRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.Acknowledgment] | m.ParseFailure:
        """Observe acknowledgment."""
        return await self.observation.call(self.inner.acknowledge(request, repair))

    async def gap_hint(
        self, request: c.GapHintRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.GapHint] | m.ParseFailure:
        """Observe a gap hint."""
        return await self.observation.call(self.inner.gap_hint(request, repair))

    async def feedback(
        self, request: c.FeedbackRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.Feedback | c.ReadingQuestion] | m.ParseFailure:
        """Observe feedback or its reading question."""
        return await self.observation.call(self.inner.feedback(request, repair))

    async def check_retry(
        self, request: c.CheckRetryRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.RetryResult] | m.ParseFailure:
        """Observe a retry or practice check."""
        return await self.observation.call(self.inner.check_retry(request, repair))

    async def show_answer(
        self, request: c.ShowAnswerRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.Answer] | m.ParseFailure:
        """Observe a requested answer."""
        return await self.observation.call(self.inner.show_answer(request, repair))

    async def answer_question(
        self, request: c.AnswerQuestionRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.CoachAnswer] | m.ParseFailure:
        """Observe a side question."""
        return await self.observation.call(self.inner.answer_question(request, repair))

    async def wrap_up(
        self, request: c.WrapUpRequest, repair: m.Repair | None = None
    ) -> m.Parsed[c.WrapUp] | m.ParseFailure:
        """Observe a wrap-up."""
        return await self.observation.call(self.inner.wrap_up(request, repair))
