"""The Anthropic API behind PydanticAI's Anthropic model: everything provider-specific.

The client, the PydanticAI model and settings, the failure mapping, refusal
detection and the price table live here; ``agents.py`` holds the provider-neutral
task agents and run wrapper. Moving to Amazon Bedrock replaces this module and the
selection in ``composition.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus
from time import monotonic as system_monotonic
from typing import TYPE_CHECKING, Literal

from anthropic import APITimeoutError, AsyncAnthropic
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider

from intent_to_english.adapters.models.agents import (
    CALL_TIMEOUT_SECONDS,
    AgentCoachModel,
    AgentPartnerModel,
)
from intent_to_english.core.errors import (
    ModelError,
    ModelRateLimitedError,
    ModelTimeoutError,
    ModelUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.exceptions import ModelAPIError
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.usage import RequestUsage

    from intent_to_english.composition import ResourceClosers

# The SDK reads ANTHROPIC_LOG when imported and, at "debug", logs every request's
# options, the prompt and the learner's text included (anthropic 1.17.0
# _utils/_logs.py and _base_client.py). Nothing private reaches a log, so the SDK's
# loggers stay at WARNING whatever the environment asks.
for _sdk_logger in ("anthropic", "httpx2"):
    logging.getLogger(_sdk_logger).setLevel(logging.WARNING)

PROVIDER = "anthropic"
BASE_URL = "https://api.anthropic.com"
# Room for adaptive thinking at medium effort plus the JSON answer, and below
# PydanticAI's 21,333-token non-streaming cap: without an explicit value it sends
# the model's maximum output (128K) and streams the request behind the scenes
# (pydantic_ai/models/anthropic.py _default_max_tokens and _messages_create, 2.55.0).
# Efforts above high may think past it; the run then ends as a parse failure.
MAX_TOKENS = 16_000
type ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]

_PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class PriceTier:
    """USD per million tokens for prompts of at most ``up_to_input_tokens``."""

    up_to_input_tokens: int | None
    input_per_million: Decimal
    output_per_million: Decimal


# Base input and output prices, USD per million tokens, from
# https://platform.claude.com/docs/en/about-claude/pricing (observed 2026-10-28).
# Haiku 5.5 charges more for a prompt "over 100,000 tokens", counted over all input
# tokens including cache reads and writes, which PydanticAI's input_tokens already
# sums. Every input token is priced at the base rate: the adapter sends no cache
# control, so a change that adds caching must price cache tokens apart here.
# Thinking is billed as output and is already inside the reported output tokens.
PRICES: dict[str, tuple[PriceTier, ...]] = {
    "claude-sonnet-5-5": (PriceTier(None, Decimal("2.00"), Decimal("10.00")),),
    "claude-haiku-5-5": (
        PriceTier(100_000, Decimal("0.10"), Decimal("0.50")),
        PriceTier(None, Decimal("0.50"), Decimal("2.50")),
    ),
}


def cost(model_id: str, input_tokens: int, output_tokens: int) -> Decimal | None:
    """Price one call's reported tokens in USD; None for a model without a price."""
    tiers = PRICES.get(model_id)
    if tiers is None:
        return None
    tier = next(
        t
        for t in tiers
        if t.up_to_input_tokens is None or input_tokens <= t.up_to_input_tokens
    )
    return (
        input_tokens * tier.input_per_million + output_tokens * tier.output_per_million
    ) / _PER_MILLION


@dataclass(frozen=True, slots=True)
class AnthropicCalls:
    """One role's Anthropic settings, failure mapping, refusal check and price."""

    model_id: str
    reasoning_effort: ReasoningEffort = "medium"

    @property
    def name(self) -> str:
        """Every Anthropic call is recorded as provider ``anthropic``."""
        return PROVIDER

    @property
    def settings(self) -> AnthropicModelSettings:
        """The bounded request every call sends, with the role's effort."""
        return AnthropicModelSettings(
            timeout=CALL_TIMEOUT_SECONDS,
            max_tokens=MAX_TOKENS,
            anthropic_effort=self.reasoning_effort,
        )

    def failure(self, error: ModelAPIError) -> tuple[type[ModelError], int | None]:
        """Map PydanticAI's wrapping of an SDK failure, keeping only the status.

        PydanticAI raises ``ModelHTTPError`` for an ``anthropic.APIStatusError``
        and a plain ``ModelAPIError`` chained to an ``anthropic.APIConnectionError``
        otherwise; ``APITimeoutError`` subclasses the connection error, so it is
        checked first.
        """
        if isinstance(error, ModelHTTPError):
            if error.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                return ModelRateLimitedError, error.status_code
            return ModelUnavailableError, error.status_code
        if isinstance(error.__cause__, APITimeoutError):
            return ModelTimeoutError, None
        return ModelUnavailableError, None

    def refused(self, response: ModelResponse) -> bool:
        """Anthropic's ``refusal`` stop reason, which PydanticAI keeps in details."""
        details = response.provider_details or {}
        return details.get("finish_reason") == "refusal"

    def cost(self, usage: RequestUsage) -> Decimal | None:
        """The configured model's price over the response's reported tokens."""
        return cost(self.model_id, usage.input_tokens, usage.output_tokens)


def _build_client(api_key: str, resources: ResourceClosers) -> AsyncAnthropic:
    """One lazy client for both roles, its disposer registered exactly once.

    The explicit key and base URL keep ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN,
    ANTHROPIC_BASE_URL, profiles and Workload Identity Federation out of the
    request, and the explicit telemetry option keeps the SDK's own spans and
    trace propagation off, as PydanticAI's instrumentation is.
    """
    client = AsyncAnthropic(
        api_key=api_key,
        base_url=BASE_URL,
        max_retries=0,
        open_telemetry={"traces": False, "propagation": False},
    )
    # The SDK merges ANTHROPIC_CUSTOM_HEADERS into every request even when the
    # key and base URL are explicit, and has no option to turn that off; we set
    # no default headers of our own, so clearing them removes only the env's.
    client._custom_headers = {}  # noqa: SLF001 -- no public way to ignore ANTHROPIC_CUSTOM_HEADERS
    resources.push_async_callback(client.close)
    return client


@dataclass(frozen=True, slots=True)
class AnthropicRole:
    """One role's model id and its effort."""

    model_id: str
    reasoning_effort: ReasoningEffort = "medium"


def build_anthropic_models(
    api_key: str,
    roles: tuple[AnthropicRole, AnthropicRole],
    resources: ResourceClosers,
    *,
    monotonic: Callable[[], float] = system_monotonic,
) -> tuple[AgentPartnerModel, AgentCoachModel]:
    """Select the Partner's and the Coach's roles over one provider, without a request."""
    provider = AnthropicProvider(anthropic_client=_build_client(api_key, resources))
    partner_role, coach_role = roles
    return (
        AgentPartnerModel(
            partner_role.model_id,
            AnthropicModel(partner_role.model_id, provider=provider),
            AnthropicCalls(partner_role.model_id, partner_role.reasoning_effort),
            monotonic,
        ),
        AgentCoachModel(
            coach_role.model_id,
            AnthropicModel(coach_role.model_id, provider=provider),
            AnthropicCalls(coach_role.model_id, coach_role.reasoning_effort),
            monotonic,
        ),
    )
