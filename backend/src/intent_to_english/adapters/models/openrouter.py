"""PydanticAI Partner calls with explicit client ownership and accounting."""

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

from intent_to_english.adapters.models import prompts
from intent_to_english.adapters.models.schemas import PartnerLineOutput
from intent_to_english.core.errors import (
    ModelRateLimitedError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from intent_to_english.core.models import Parsed, ParseFailure, Repair, Usage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pydantic import SecretStr
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model

    from intent_to_english.composition import ResourceClosers
    from intent_to_english.core import partner

CALL_TIMEOUT_SECONDS = 60
PROVIDER = "openrouter"
PARSE_FAILURE = "Model output did not match its schema"


class OpenRouterPartnerModel:
    """The three Partner tasks over one model and task-specific agents."""

    def __init__(
        self,
        model_id: str,
        model: Model,
        monotonic: Callable[[], float] = system_monotonic,
    ) -> None:
        """Build an independent, retry-free agent for each task once."""
        self._model_id = model_id
        self._monotonic = monotonic
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
        return await self._call(self._open, prompts.render_open(request, repair))

    async def reply(
        self, request: partner.ReplyRequest, repair: Repair | None = None
    ) -> Parsed[partner.PartnerLine] | ParseFailure:
        """Reply to English context using the server's taking-turns flag."""
        return await self._call(self._reply, prompts.render_reply(request, repair))

    async def restate(
        self, request: partner.RestateRequest, repair: Repair | None = None
    ) -> Parsed[partner.PartnerLine] | ParseFailure:
        """Restate the current line without adding context to the role port."""
        return await self._call(self._restate, prompts.render_restate(request, repair))

    async def _call(
        self, agent: Agent[None, PartnerLineOutput], prompt: prompts.Prompt
    ) -> Parsed[partner.PartnerLine] | ParseFailure:
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
            output = result.output.to_domain()
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


def build_openrouter_partner(
    api_key: SecretStr,
    model_id: str,
    resources: ResourceClosers,
    *,
    app_title: str,
    monotonic: Callable[[], float] = system_monotonic,
) -> OpenRouterPartnerModel:
    """Build one lazy explicit client and transfer its close callback to the owner."""
    client = AsyncOpenAI(
        api_key=api_key.get_secret_value(),
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        default_headers={"X-OpenRouter-Title": app_title},
    )
    resources.push_async_callback(client.close)
    provider = OpenRouterProvider(openai_client=client)
    return OpenRouterPartnerModel(
        model_id, OpenRouterModel(model_id, provider=provider), monotonic
    )
