from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from intent_to_english.adapters.memory import InMemorySessionRepository
from intent_to_english.core import coaching, partner
from intent_to_english.core.services import ConversationService

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    import anyio

    from intent_to_english.core.models import Parsed, ParseFailure, Repair


@dataclass
class ScriptedCall[Request, Output]:
    outputs: list[Parsed[Output] | ParseFailure | Exception] = field(
        default_factory=list
    )
    requests: list[tuple[Request, Repair | None]] = field(default_factory=list)
    started: anyio.Event | None = None
    release: anyio.Event | None = None

    async def __call__(
        self, request: Request, repair: Repair | None = None
    ) -> Parsed[Output] | ParseFailure:
        self.requests.append((request, repair))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


class ScriptedPartnerModel:
    def __init__(self):
        self.open_call = ScriptedCall[partner.OpenRequest, partner.PartnerLine]()
        self.reply_call = ScriptedCall[partner.ReplyRequest, partner.PartnerLine]()
        self.restate_call = ScriptedCall[partner.RestateRequest, partner.PartnerLine]()

    async def open(
        self, request: partner.OpenRequest, repair: Repair | None = None
    ) -> Parsed[partner.PartnerLine] | ParseFailure:
        return await self.open_call(request, repair)

    async def reply(
        self, request: partner.ReplyRequest, repair: Repair | None = None
    ) -> Parsed[partner.PartnerLine] | ParseFailure:
        return await self.reply_call(request, repair)

    async def restate(
        self, request: partner.RestateRequest, repair: Repair | None = None
    ) -> Parsed[partner.PartnerLine] | ParseFailure:
        return await self.restate_call(request, repair)


class ScriptedCoachModel:
    def __init__(self):
        self.acknowledge_call = ScriptedCall[
            coaching.AcknowledgeRequest, coaching.Acknowledgment
        ]()
        self.gap_hint_call = ScriptedCall[coaching.GapHintRequest, coaching.GapHint]()
        self.feedback_call = ScriptedCall[
            coaching.FeedbackRequest, coaching.Feedback | coaching.ReadingQuestion
        ]()
        self.check_retry_call = ScriptedCall[
            coaching.CheckRetryRequest, coaching.RetryResult
        ]()
        self.show_answer_call = ScriptedCall[
            coaching.ShowAnswerRequest, coaching.Answer
        ]()
        self.answer_question_call = ScriptedCall[
            coaching.AnswerQuestionRequest, coaching.CoachAnswer
        ]()
        self.wrap_up_call = ScriptedCall[coaching.WrapUpRequest, coaching.WrapUp]()

    async def acknowledge(
        self, request: coaching.AcknowledgeRequest, repair: Repair | None = None
    ) -> Parsed[coaching.Acknowledgment] | ParseFailure:
        return await self.acknowledge_call(request, repair)

    async def gap_hint(
        self, request: coaching.GapHintRequest, repair: Repair | None = None
    ) -> Parsed[coaching.GapHint] | ParseFailure:
        return await self.gap_hint_call(request, repair)

    async def feedback(
        self, request: coaching.FeedbackRequest, repair: Repair | None = None
    ) -> Parsed[coaching.Feedback | coaching.ReadingQuestion] | ParseFailure:
        return await self.feedback_call(request, repair)

    async def check_retry(
        self, request: coaching.CheckRetryRequest, repair: Repair | None = None
    ) -> Parsed[coaching.RetryResult] | ParseFailure:
        return await self.check_retry_call(request, repair)

    async def show_answer(
        self, request: coaching.ShowAnswerRequest, repair: Repair | None = None
    ) -> Parsed[coaching.Answer] | ParseFailure:
        return await self.show_answer_call(request, repair)

    async def answer_question(
        self, request: coaching.AnswerQuestionRequest, repair: Repair | None = None
    ) -> Parsed[coaching.CoachAnswer] | ParseFailure:
        return await self.answer_question_call(request, repair)

    async def wrap_up(
        self, request: coaching.WrapUpRequest, repair: Repair | None = None
    ) -> Parsed[coaching.WrapUp] | ParseFailure:
        return await self.wrap_up_call(request, repair)


@dataclass
class SettableClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


@dataclass
class ConversationHarness:
    service: ConversationService
    repository: InMemorySessionRepository
    partner: ScriptedPartnerModel
    coach: ScriptedCoachModel
    clock: SettableClock
    boot_id: UUID


@pytest.fixture
def make_conversation(fixed_now, new_id, nth_id):
    def make():
        repository = InMemorySessionRepository()
        partner_model = ScriptedPartnerModel()
        coach_model = ScriptedCoachModel()
        clock = SettableClock(fixed_now)
        boot_id = nth_id(9999)
        service = ConversationService(
            repository, partner_model, coach_model, clock, new_id, boot_id
        )
        return ConversationHarness(
            service, repository, partner_model, coach_model, clock, boot_id
        )

    return make
