"""Fixtures shared by every layer's tests."""

from __future__ import annotations

import asyncio
import itertools
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pydantic_ai.models
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from intent_to_english.adapters.sql.engine import make_engine
from intent_to_english.adapters.sql.session_repository import SqlSessionRepository
from intent_to_english.composition import Container, build_container
from intent_to_english.core import models as m
from intent_to_english.settings import Settings
from tests.settings_env import without_settings_env

# FunctionModel is offline; only explicitly mocked transport tests lift this guard.
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False

FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
# Capture before the autouse settings-isolation fixture deletes INTENT_TO_ENGLISH_*.
POSTGRES_URL = os.environ.get("INTENT_TO_ENGLISH_TEST_POSTGRES_URL")


def _fixed_clock() -> datetime:
    return FIXED_NOW


def _nth_id(n: int) -> UUID:
    # A version-7, RFC 9562-variant layout with n in the low bits, so the ids
    # look like uuid.uuid7's and ascend with n.
    return UUID(f"01900000-0000-7000-8000-{n:012x}")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Run every ``anyio``-marked test on asyncio only.

    AnyIO's own fixture is module-scoped and parametrized over every installed
    backend; fixing it here keeps the run single-backend, and session scope
    lets a module- or session-scoped async fixture use it.
    """
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch):
    """Keep the developer's shell and dotenv file out of tests."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    cleaned = without_settings_env(os.environ)
    for name in set(os.environ) - cleaned.keys():
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fixed_now() -> datetime:
    """The instant ``fixed_clock`` always reads."""
    return FIXED_NOW


@pytest.fixture
def make_model_call(new_id, nth_id, fixed_now):
    """Build independent log records with one shared session/submission by default."""

    def make(call=None, **changes):
        if call is None:
            call = m.CallAttempt(
                m.ModelRole.PARTNER,
                m.ModelTask.REPLY,
                1,
                m.Usage("test", "test/model", None, None, None, 0),
                m.CallOutcome.OK,
            )
        record = m.ModelCallRecord(
            new_id(), nth_id(100), nth_id(101), 1, call, fixed_now
        )
        return replace(record, **changes)

    return make


@pytest.fixture
def seed_call_log(make_model_call, nth_id, fixed_now):
    """Persist a small log through the same public repository as the service."""

    async def seed(url):
        engine = make_engine(url)
        records = []
        try:
            repository = SqlSessionRepository(engine)
            for index in (100, 200):
                session = m.Session(nth_id(index), fixed_now)
                submission = m.Submission(
                    nth_id(index + 1),
                    session.id,
                    0,
                    m.Action.OPEN,
                    m.NoInput(),
                    nth_id(999),
                    fixed_now,
                )
                await repository.create(session)
                await repository.begin_submission(
                    submission, frozenset({m.Stage.OPENING}), fixed_now
                )
                for seconds in (0, 1):
                    record = make_model_call(
                        session_id=session.id,
                        submission_id=submission.id,
                        created_at=fixed_now + timedelta(seconds=seconds),
                    )
                    await repository.record_model_call(record)
                    records.append(record)
        finally:
            await engine.dispose()
        return tuple(records)

    return seed


@pytest.fixture
def fixed_clock():
    """A ``Clock`` that always reads ``fixed_now``, so timestamps are exact."""
    return _fixed_clock


@pytest.fixture
def nth_id():
    """Return the ``n``-th id ``new_id`` hands out, counting from 1."""
    return _nth_id


@pytest.fixture
def new_id():
    """An ``IdFactory`` handing out ``nth_id(1)``, ``nth_id(2)``, ... in turn.

    One counter per test, shared by every container ``make_container`` builds
    in it, so two containers on the same SQLite file never collide on an id.
    """
    counter = itertools.count(1)
    return lambda: _nth_id(next(counter))


@pytest.fixture
async def make_container(new_id, anyio_backend):
    """Build containers through the composition root with fixed time and ids.

    Defaults to the in-memory repository; pass ``Settings`` to choose another.
    Every container built is closed after the test, on the loop that ran it,
    so no SQL engine is left for garbage collection to warn about. Taking
    ``anyio_backend`` lets a plain ``def`` test use this async fixture too.
    Never hand a SQL container to a ``TestClient``: the client runs the app on
    a loop of its own, and the engine's pooled connections belong to one loop
    (use ``create_app(settings)`` there, which closes its own container).
    """
    built: list[Container] = []

    def _make(settings: Settings | None = None) -> Container:
        chosen = settings if settings is not None else Settings(database_url=None)
        container = build_container(chosen, clock=_fixed_clock, new_id=new_id)
        built.append(container)
        return container

    yield _make
    for container in reversed(built):
        await container.aclose()


@pytest.fixture
def sqlite_url(tmp_path):
    """The URL of a SQLite file in ``tmp_path`` that nothing has created yet."""
    return f"sqlite+aiosqlite:///{tmp_path / 'app.db'}"


@pytest.fixture
def alembic_config(sqlite_url, monkeypatch):
    """Alembic's own configuration, aimed at the ``sqlite_url`` file.

    ``migrations/env.py`` reads ``INTENT_TO_ENGLISH_DATABASE_URL`` as the command line
    does, so the variable stays set to ``sqlite_url`` for the whole test.
    env.py calls ``asyncio.run``: run a command only from a plain ``def``
    test or fixture, never inside a running event loop.
    """
    monkeypatch.setenv("INTENT_TO_ENGLISH_DATABASE_URL", sqlite_url)
    config = Config(ALEMBIC_INI)
    # pytest captures logging; alembic.ini's handlers would replace its own.
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture
def migrated_sqlite_url(alembic_config, sqlite_url):
    """``sqlite_url``, its file migrated to the head revision as the app needs."""
    command.upgrade(alembic_config, "head")
    return sqlite_url


@pytest.fixture(scope="session")
def migrated_postgres_url(request):
    """Migrate only when PostgreSQL tests were selected, once per session."""
    if not any(item.get_closest_marker("postgres") for item in request.session.items):
        return None
    if not POSTGRES_URL:
        pytest.fail(
            "INTENT_TO_ENGLISH_TEST_POSTGRES_URL must name a disposable PostgreSQL database"
        )

    async def migrate():
        engine = create_async_engine(POSTGRES_URL)
        try:
            async with engine.begin() as connection:
                config = Config(ALEMBIC_INI)
                config.attributes["configure_logging"] = False
                config.attributes["connection"] = connection.sync_connection
                await connection.run_sync(lambda _: command.upgrade(config, "head"))
        finally:
            await engine.dispose()

    asyncio.run(migrate())
    return POSTGRES_URL
