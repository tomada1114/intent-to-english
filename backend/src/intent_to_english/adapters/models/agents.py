"""Provider-neutral PydanticAI role calls: task agents, the run wrapper and usage.

A provider module (``anthropic_provider.py``) supplies the model, its settings, its
failure mapping, refusal detection and cost through ``ProviderCalls``; nothing here
names a provider SDK, so another provider replaces only that module.
"""

from __future__ import annotations

import asyncio
from time import monotonic as system_monotonic
from typing import TYPE_CHECKING, Protocol

from pydantic_ai import Agent, NativeOutput, capture_run_messages
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse

from intent_to_english.adapters.models import prompts, schemas
from intent_to_english.adapters.models.schemas import PartnerLineOutput
from intent_to_english.core.errors import (
    ModelError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from intent_to_english.core.models import Parsed, ParseFailure, Repair, Usage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from decimal import Decimal

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model
    from pydantic_ai.settings import ModelSettings
    from pydantic_ai.usage import RequestUsage

    from intent_to_english.core import coaching, partner

CALL_TIMEOUT_SECONDS = 60
PARSE_FAILURE = "Model output did not match its schema"


class ProviderCalls(Protocol):
    """The provider-specific half of one role's calls."""

    @property
    def name(self) -> str:
        """The provider recorded in every call's usage and error."""

    @property
    def settings(self) -> ModelSettings:
        """The settings every call of this role sends, its timeout included."""

    def failure(self, error: ModelAPIError) -> tuple[type[ModelError], int | None]:
        """The core error for a failed request, and its HTTP status if any."""

    def refused(self, response: ModelResponse) -> bool:
        """Whether the provider refused to answer this request."""

    def cost(self, usage: RequestUsage) -> Decimal | None:
        """The call's cost from its reported tokens, or None without a known price."""


class _AgentCalls:
    """One call boundary for both roles: timeouts, parse failures and accounting."""

    def __init__(
        self,
        model_id: str,
        provider: ProviderCalls,
        monotonic: Callable[[], float],
    ) -> None:
        self._model_id = model_id
        self._provider = provider
        self._monotonic = monotonic

    async def _call[Output, Domain](
        self,
        agent: Agent[None, Output],
        prompt: prompts.Prompt,
        convert: Callable[[Output], Domain],
    ) -> Parsed[Domain] | ParseFailure:
        started = self._monotonic()
        with capture_run_messages() as messages:
            try:
                async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
                    result = await agent.run(
                        prompt.user_prompt,
                        instructions=prompt.instructions,
                        model_settings=self._provider.settings,
                    )
            except TimeoutError:
                raise ModelTimeoutError(
                    self._provider.name, self._model_id, self._elapsed(started)
                ) from None
            except ModelAPIError as error:
                kind, status = self._provider.failure(error)
                raise kind(
                    self._provider.name,
                    self._model_id,
                    self._elapsed(started),
                    status=status,
                ) from None
            except UnexpectedModelBehavior:
                # A refusal ends without a usable output (a ContentFilterError, or
                # text that fails validation); it is not repaired.
                self._raise_if_refused(messages, started)
                return ParseFailure(self._usage(messages, started), PARSE_FAILURE)
        self._raise_if_refused(messages, started)
        usage = self._usage(messages, started)
        try:
            output = convert(result.output)
        except ValueError:
            return ParseFailure(usage, PARSE_FAILURE)
        return Parsed(output, usage)

    def _raise_if_refused(
        self, messages: Sequence[ModelMessage], started: float
    ) -> None:
        response = _last_response(messages)
        if response is not None and self._provider.refused(response):
            raise ModelUnavailableError(
                self._provider.name, self._model_id, self._elapsed(started)
            )

    def _elapsed(self, started: float) -> int:
        return max(0, round((self._monotonic() - started) * 1000))

    def _usage(self, messages: Sequence[ModelMessage], started: float) -> Usage:
        response = _last_response(messages)
        return Usage(
            self._provider.name,
            self._model_id,
            response.usage.input_tokens if response else None,
            response.usage.output_tokens if response else None,
            self._provider.cost(response.usage) if response else None,
            self._elapsed(started),
        )


def _last_response(messages: Sequence[ModelMessage]) -> ModelResponse | None:
    return next((m for m in reversed(messages) if isinstance(m, ModelResponse)), None)


def _agent[Output](
    model: Model, output: type[Output], name: str
) -> Agent[None, Output]:
    """One retry-free task agent with native structured output and no tools."""
    agent = Agent(model, output_type=NativeOutput(output), retries=0, name=name)
    # Explicitly override even a host's Agent.instrument_all() default.
    agent.instrument = False
    return agent


class AgentPartnerModel(_AgentCalls):
    """The three Partner tasks over one model and task-specific agents."""

    def __init__(
        self,
        model_id: str,
        model: Model,
        provider: ProviderCalls,
        monotonic: Callable[[], float] = system_monotonic,
    ) -> None:
        """Build an independent, retry-free agent for each task once."""
        super().__init__(model_id, provider, monotonic)
        self._open = _agent(model, PartnerLineOutput, "partner_open")
        self._reply = _agent(model, PartnerLineOutput, "partner_reply")
        self._restate = _agent(model, PartnerLineOutput, "partner_restate")

    async def open(
        self, request: partner.OpenRequest, repair: Repair | None = None
    ) -> Parsed[partner.PartnerLine] | ParseFailure:
        """Call only the opener task, preserving its usage on parse failure."""
        return await self._call(
            self._open,
            prompts.render_open(request, repair),
            PartnerLineOutput.to_domain,
        )

    async def reply(
        self, request: partner.ReplyRequest, repair: Repair | None = None
    ) -> Parsed[partner.PartnerLine] | ParseFailure:
        """Reply to English context using the server's taking-turns flag."""
        return await self._call(
            self._reply,
            prompts.render_reply(request, repair),
            PartnerLineOutput.to_domain,
        )

    async def restate(
        self, request: partner.RestateRequest, repair: Repair | None = None
    ) -> Parsed[partner.PartnerLine] | ParseFailure:
        """Restate the current line without adding context to the role port."""
        return await self._call(
            self._restate,
            prompts.render_restate(request, repair),
            PartnerLineOutput.to_domain,
        )


class AgentCoachModel(_AgentCalls):
    """Seven Coach tasks over one model, without SDK retries or tools."""

    def __init__(
        self,
        model_id: str,
        model: Model,
        provider: ProviderCalls,
        monotonic: Callable[[], float] = system_monotonic,
    ) -> None:
        """Build task agents once, with native structured outputs."""
        super().__init__(model_id, provider, monotonic)
        self._acknowledge = _agent(
            model, schemas.AcknowledgmentOutput, "coach_acknowledge"
        )
        self._gap_hint = _agent(model, schemas.GapHintOutput, "coach_gap_hint")
        self._feedback = _agent(model, schemas.FeedbackOutput, "coach_feedback")
        self._check_retry = _agent(model, schemas.RetryOutput, "coach_check_retry")
        self._show_answer = _agent(model, schemas.AnswerOutput, "coach_show_answer")
        self._answer_question = _agent(
            model, schemas.CoachAnswerOutput, "coach_answer_question"
        )
        self._wrap_up = _agent(model, schemas.WrapUpOutput, "coach_wrap_up")

    async def acknowledge(
        self, request: coaching.AcknowledgeRequest, repair: Repair | None = None
    ) -> Parsed[coaching.Acknowledgment] | ParseFailure:
        """Run acknowledge with usage retained even on invalid output."""
        return await self._call(
            self._acknowledge,
            prompts.render_acknowledge(request, repair),
            schemas.AcknowledgmentOutput.to_domain,
        )

    async def gap_hint(
        self, request: coaching.GapHintRequest, repair: Repair | None = None
    ) -> Parsed[coaching.GapHint] | ParseFailure:
        """Run gap hint with usage retained even on invalid output."""
        return await self._call(
            self._gap_hint,
            prompts.render_gap_hint(request, repair),
            schemas.GapHintOutput.to_domain,
        )

    async def feedback(
        self, request: coaching.FeedbackRequest, repair: Repair | None = None
    ) -> Parsed[coaching.Feedback | coaching.ReadingQuestion] | ParseFailure:
        """Run feedback with usage retained even on invalid output."""
        return await self._call(
            self._feedback,
            prompts.render_feedback(request, repair),
            schemas.FeedbackOutput.to_domain,
        )

    async def check_retry(
        self, request: coaching.CheckRetryRequest, repair: Repair | None = None
    ) -> Parsed[coaching.RetryResult] | ParseFailure:
        """Run check retry with usage retained even on invalid output."""
        return await self._call(
            self._check_retry,
            prompts.render_check_retry(request, repair),
            schemas.RetryOutput.to_domain,
        )

    async def show_answer(
        self, request: coaching.ShowAnswerRequest, repair: Repair | None = None
    ) -> Parsed[coaching.Answer] | ParseFailure:
        """Run show answer with usage retained even on invalid output."""
        return await self._call(
            self._show_answer,
            prompts.render_show_answer(request, repair),
            schemas.AnswerOutput.to_domain,
        )

    async def answer_question(
        self, request: coaching.AnswerQuestionRequest, repair: Repair | None = None
    ) -> Parsed[coaching.CoachAnswer] | ParseFailure:
        """Run answer question with usage retained even on invalid output."""
        return await self._call(
            self._answer_question,
            prompts.render_answer_question(request, repair),
            schemas.CoachAnswerOutput.to_domain,
        )

    async def wrap_up(
        self, request: coaching.WrapUpRequest, repair: Repair | None = None
    ) -> Parsed[coaching.WrapUp] | ParseFailure:
        """Run wrap up with usage retained even on invalid output."""
        return await self._call(
            self._wrap_up,
            prompts.render_wrap_up(request, repair),
            schemas.WrapUpOutput.to_domain,
        )
