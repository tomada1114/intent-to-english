"""The composition root: the one place adapters are wired into services.

The API gets its services from ``build_container`` and from nowhere else,
so swapping a repository is a change to this module only.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Self

from anyio import CancelScope
from anyio.lowlevel import checkpoint_if_cancelled

from intent_to_english.adapters.memory import InMemorySessionRepository
from intent_to_english.adapters.models.anthropic_provider import (
    AnthropicRole,
    build_anthropic_models,
)
from intent_to_english.adapters.models.fixed import FixedCoachModel, FixedPartnerModel
from intent_to_english.adapters.sql.engine import make_engine
from intent_to_english.adapters.sql.session_repository import SqlSessionRepository
from intent_to_english.core.services import ConversationService

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType
    from uuid import UUID

    from intent_to_english.core.ports import (
        Clock,
        CoachModel,
        IdFactory,
        PartnerModel,
        SessionRepository,
    )
    from intent_to_english.settings import Settings


@dataclass(slots=True)
class ResourceClosers:
    """Disposal callbacks for process resources, independent of their caller task.

    Register lazy resources during composition, before the Container is built.
    A callback must be safe on the resource's event loop in a separate task and
    context. Entered context managers, task groups, cancellation scopes and
    context-variable tokens belong to the scope that acquired them instead.
    Callback results cannot suppress a Container body exception.
    """

    _stack: AsyncExitStack = field(
        default_factory=AsyncExitStack, init=False, repr=False
    )
    _sealed: bool = field(default=False, init=False, repr=False)

    def push_async_callback[**P](
        self,
        callback: Callable[P, Awaitable[object]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> None:
        """Register a task-independent disposer, with its arguments, in LIFO order."""
        if self._sealed:
            message = "Register disposal callbacks before building the Container"
            raise RuntimeError(message)
        self._stack.push_async_callback(callback, *args, **kwargs)

    def seal(self) -> None:
        """Finish registration when resource ownership moves to the Container."""
        self._sealed = True

    async def drain(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Run every disposer; preserve cleanup failures and their body context."""
        await self._stack.__aexit__(exc_type, exc_value, traceback)


@dataclass(slots=True)
class _CleanupState:
    """Mutable ownership bookkeeping inside the otherwise frozen container."""

    task: asyncio.Task[None] | None = None


@dataclass(frozen=True, slots=True)
class ModelPorts:
    """The selected role ports shared by conversation and evaluation."""

    partner: PartnerModel
    coach: CoachModel


@dataclass(frozen=True, slots=True)
class Container:
    """The services an entry point may call, built once per process."""

    conversations: ConversationService = field(kw_only=True)
    models: ModelPorts = field(kw_only=True)
    model_mode: Literal["fixed", "anthropic"] = field(default="fixed", kw_only=True)
    _resources: ResourceClosers = field(
        default_factory=ResourceClosers, repr=False, compare=False
    )
    _cleanup: _CleanupState = field(
        default_factory=_CleanupState, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """Seal the callback registry and reject ownership of entered managers."""
        _seal_resources(self._resources)

    async def aclose(self) -> None:
        """Release every resource the composition root registered, at most once."""
        await self._close(None, None, None)

    async def __aenter__(self) -> Self:
        """Keep ownership until the surrounding context exits."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release owned resources without suppressing the body exception."""
        await self._close(exc_type, exc_value, traceback)

    async def _close(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Finish one drain on the owning loop, then propagate caller cancellation."""
        task = self._cleanup.task
        if task is not None and task.done():
            # ExitStack is already drained, including after a cleanup failure.
            await checkpoint_if_cancelled()
            return
        if task is None:
            task = asyncio.create_task(
                self._resources.drain(exc_type, exc_value, traceback),
                name="container-cleanup",
            )
            self._cleanup.task = task
        cancellation: asyncio.CancelledError | None = None
        # AnyIO scopes cancel every checkpoint. asyncio.wait does not forward
        # direct Task.cancel to the cleanup task or log its failure separately.
        with CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.wait({task})
                except asyncio.CancelledError as error:
                    cancellation = error
            task.result()
        if cancellation is not None:
            raise cancellation
        await checkpoint_if_cancelled()


def _seal_resources(resources: object) -> None:
    """Check ownership at runtime too, for callers outside the typed factory."""
    if not isinstance(resources, ResourceClosers):
        message = "Container accepts task-independent disposal callbacks in ResourceClosers only"
        raise TypeError(message)
    resources.seal()


def utc_now() -> datetime:
    """Return the current time in UTC; the production ``Clock``."""
    return datetime.now(tz=UTC)


def build_container(
    settings: Settings,
    clock: Clock = utc_now,
    new_id: IdFactory = uuid.uuid7,
    *,
    boot_id: UUID | None = None,
) -> Container:
    """Choose the adapters ``settings`` asks for and wire them into services.

    A plain function, not a coroutine: nothing here awaits, and a bad setting
    must still fail in ``create_app``, before any request is served. Being
    synchronous, it cannot await the cleanup of a partly built stack, so a build
    that raises leaves registered callbacks un-run. An adapter builder therefore
    registers cleanup with ``resources.push_async_callback(...)`` only for an
    object that opens nothing when constructed (an engine that connects on
    first use, say), so an error later in the build leaves nothing open.

    Args:
        settings: Selects the repository through ``database_url``.
        clock: Stamps new sessions and records; tests pass a fixed one.
        new_id: Gives new sessions and records their ids; ``uuid.uuid7``, whose
            ids ascend in creation order, unless a test passes a predictable
            factory.
        boot_id: One process identity; tests may inject it to check interruption.

    Returns:
        The services and their owned resources, ready for an entry point to
        call. Await ``aclose()``, or use it with ``async with``, when done.
    """
    resources = ResourceClosers()
    session_repository = _build_repository(settings, resources)
    models, model_mode = _build_models(settings, resources)
    conversations = ConversationService(
        session_repository,
        models.partner,
        models.coach,
        clock,
        new_id,
        boot_id if boot_id is not None else uuid.uuid7(),
    )
    return Container(
        conversations=conversations,
        models=models,
        model_mode=model_mode,
        _resources=resources,
    )


def _build_repository(
    settings: Settings, resources: ResourceClosers
) -> SessionRepository:
    """Return the SQL session repository on its own engine, or a memory store.

    The SQL repository's engine is the one resource the container owns: it
    connects on first use, so registering ``engine.dispose`` here leaves
    nothing open if the build fails later, under the rule ``build_container``
    states. The database must already be migrated; nothing here creates a
    table.
    """
    if settings.database_url is None:
        return InMemorySessionRepository()
    engine = make_engine(settings.database_url)
    resources.push_async_callback(engine.dispose)
    return SqlSessionRepository(engine)


def _build_models(
    settings: Settings, resources: ResourceClosers
) -> tuple[ModelPorts, Literal["fixed", "anthropic"]]:
    """Unwrap the key only at the composition boundary, after selecting live mode.

    The provider is chosen here alone: a Bedrock adapter would be one more branch
    building its own roles behind the same ports.
    """
    if settings.model_mode == "fixed" or settings.anthropic_api_key is None:
        return ModelPorts(FixedPartnerModel(), FixedCoachModel()), "fixed"
    partner, coach = build_anthropic_models(
        settings.anthropic_api_key.get_secret_value(),
        (
            AnthropicRole(settings.partner_model, settings.partner_reasoning_effort),
            AnthropicRole(settings.coach_model, settings.coach_reasoning_effort),
        ),
        resources,
    )
    return ModelPorts(partner, coach), "anthropic"
