"""PydanticAI role calls with shared client ownership and accounting."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from http import HTTPStatus
from time import monotonic as system_monotonic
from typing import TYPE_CHECKING

from openai import APITimeoutError, AsyncOpenAI
from pydantic_ai import Agent, NativeOutput, capture_run_messages
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings

from intent_to_english.adapters.models import prompts, schemas
from intent_to_english.adapters.models.schemas import PartnerLineOutput
from intent_to_english.core.errors import (
    ModelRateLimitedError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from intent_to_english.core.models import Parsed, ParseFailure, Repair, Usage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model

    from intent_to_english.composition import ResourceClosers
    from intent_to_english.core import coaching, partner

CALL_TIMEOUT_SECONDS = 60
PROVIDER = "openrouter"
PARSE_FAILURE = "Model output did not match its schema"


class _OpenRouterCalls:
    """One call boundary for both roles: timeouts, parse failures and accounting."""

    def __init__(self, model_id: str, monotonic: Callable[[], float]) -> None:
        self._model_id = model_id
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
                        model_settings=ModelSettings(timeout=CALL_TIMEOUT_SECONDS),
                    )
            except TimeoutError:
                raise ModelTimeoutError(
                    PROVIDER, self._model_id, self._elapsed(started)
                ) from None
            except ModelHTTPError as error:
                kind = (
                    ModelRateLimitedError
                    if error.status_code == HTTPStatus.TOO_MANY_REQUESTS
                    else ModelUnavailableError
                )
                raise kind(PROVIDER, self._model_id, self._elapsed(started)) from None
            except ModelAPIError as error:
                connection_kind = (
                    ModelTimeoutError
                    if isinstance(error.__cause__, APITimeoutError)
                    else ModelUnavailableError
                )
                raise connection_kind(
                    PROVIDER, self._model_id, self._elapsed(started)
                ) from None
            except UnexpectedModelBehavior:
                return ParseFailure(self._usage(messages, started), PARSE_FAILURE)
        usage = self._usage(messages, started)
        try:
            output = convert(result.output)
        except ValueError:
            return ParseFailure(usage, PARSE_FAILURE)
        return Parsed(output, usage)

    def _elapsed(self, started: float) -> int:
        return max(0, round((self._monotonic() - started) * 1000))

    def _usage(self, messages: Sequence[ModelMessage], started: float) -> Usage:
        response = next(
            (m for m in reversed(messages) if isinstance(m, ModelResponse)), None
        )
        cost: object = (
            (response.provider_details or {}).get("cost") if response else None
        )
        reported_cost = (
            Decimal(str(cost)) if isinstance(cost, (int, float, str, Decimal)) else None
        )
        return Usage(
            PROVIDER,
            self._model_id,
            response.usage.input_tokens if response else None,
            response.usage.output_tokens if response else None,
            reported_cost,
            self._elapsed(started),
        )


class OpenRouterPartnerModel(_OpenRouterCalls):
    """The three Partner tasks over one model and task-specific agents."""

    def __init__(
        self,
        model_id: str,
        model: Model,
        monotonic: Callable[[], float] = system_monotonic,
    ) -> None:
        """Build an independent, retry-free agent for each task once."""
        super().__init__(model_id, monotonic)
        self._open = self._agent(model, "partner_open")
        self._reply = self._agent(model, "partner_reply")
        self._restate = self._agent(model, "partner_restate")

    @staticmethod
    def _agent(model: Model, name: str) -> Agent[None, PartnerLineOutput]:
        agent = Agent(
            model,
            output_type=NativeOutput(PartnerLineOutput),
            retries=0,
            name=name,
        )
        # Explicitly override even a host's Agent.instrument_all() default.
        agent.instrument = False
        return agent

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


class OpenRouterCoachModel(_OpenRouterCalls):
    """Seven Coach tasks over one model, without SDK retries or tools."""

    def __init__(
        self,
        model_id: str,
        model: Model,
        monotonic: Callable[[], float] = system_monotonic,
    ) -> None:
        """Build task agents once, with native structured outputs."""
        super().__init__(model_id, monotonic)
        self._acknowledge = Agent(
            model,
            output_type=NativeOutput(schemas.AcknowledgmentOutput),
            retries=0,
            name="coach_acknowledge",
        )
        self._acknowledge.instrument = False
        self._gap_hint = Agent(
            model,
            output_type=NativeOutput(schemas.GapHintOutput),
            retries=0,
            name="coach_gap_hint",
        )
        self._gap_hint.instrument = False
        self._feedback = Agent(
            model,
            output_type=NativeOutput(schemas.FeedbackOutput),
            retries=0,
            name="coach_feedback",
        )
        self._feedback.instrument = False
        self._check_retry = Agent(
            model,
            output_type=NativeOutput(schemas.RetryOutput),
            retries=0,
            name="coach_check_retry",
        )
        self._check_retry.instrument = False
        self._show_answer = Agent(
            model,
            output_type=NativeOutput(schemas.AnswerOutput),
            retries=0,
            name="coach_show_answer",
        )
        self._show_answer.instrument = False
        self._answer_question = Agent(
            model,
            output_type=NativeOutput(schemas.CoachAnswerOutput),
            retries=0,
            name="coach_answer_question",
        )
        self._answer_question.instrument = False
        self._wrap_up = Agent(
            model,
            output_type=NativeOutput(schemas.WrapUpOutput),
            retries=0,
            name="coach_wrap_up",
        )
        self._wrap_up.instrument = False

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


def _build_provider(
    api_key: str, resources: ResourceClosers, app_title: str
) -> OpenRouterProvider:
    """Give both roles one lazy client and register its disposer exactly once."""
    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        default_headers={"X-OpenRouter-Title": app_title},
    )
    resources.push_async_callback(client.close)
    return OpenRouterProvider(openai_client=client)


def build_openrouter_models(
    api_key: str,
    model_ids: tuple[str, str],
    resources: ResourceClosers,
    *,
    app_title: str,
    monotonic: Callable[[], float] = system_monotonic,
) -> tuple[OpenRouterPartnerModel, OpenRouterCoachModel]:
    """Select two model ids over one provider without making a network request."""
    provider = _build_provider(api_key, resources, app_title)
    partner_id, coach_id = model_ids
    return (
        OpenRouterPartnerModel(
            partner_id, OpenRouterModel(partner_id, provider=provider), monotonic
        ),
        OpenRouterCoachModel(
            coach_id, OpenRouterModel(coach_id, provider=provider), monotonic
        ),
    )
