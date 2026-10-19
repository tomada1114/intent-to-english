"""e2e/verify_persistence.py, the browser test's independent persistence check.

The Playwright spec runs it as a process of its own on the run's SQLite file,
after the screen has started a session and shown the Partner's opener. These
tests run it the same way, against migrated scratch files, so a check that
passed on a session the API only kept in memory, or on another database, fails
here.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest
from sqlalchemy import event

from intent_to_english import composition
from intent_to_english.adapters.sql.engine import make_engine
from intent_to_english.core import models as m
from intent_to_english.settings import ENV_PREFIX, Settings
from tests.settings_env import without_settings_env

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable
    from types import ModuleType

    from intent_to_english.composition import Container

E2E = Path(__file__).resolve().parents[2] / "e2e"
VERIFIER = E2E / "verify_persistence.py"
ENVIRONMENT_TS = E2E / "environment.ts"
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
# The first fixed opener (adapters/models/fixed.py), which a fresh database gets.
OPENER = "Hey! How's it going?"
E2E_VALUES: dict[str, object] = {
    "cors_origins": [],
    "log_level": "INFO",
    "log_format": "text",
    "openrouter_api_key": None,
    "model_mode": "fixed",
    "coach_model": "anthropic/claude-sonnet-5.5",
    "partner_model": "anthropic/claude-haiku-5.5",
}

pytestmark = pytest.mark.anyio


@pytest.fixture
def verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_persistence", VERIFIER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _verify(
    database_url: str, session_id: object, opener: str = OPENER, **env: str
) -> subprocess.CompletedProcess[bytes]:
    return await anyio.run_process(
        [sys.executable, str(VERIFIER), database_url, str(session_id), opener],
        check=False,
        env=without_settings_env(os.environ) | env,
    )


async def _stored(
    make_container: Callable[[Settings], Container],
    database_url: str | None,
    *,
    opened: bool = True,
    ended: bool = False,
) -> m.SessionView:
    container = make_container(Settings(database_url=database_url))
    view = await container.conversations.start()
    if opened:
        view = await container.conversations.act(
            view.id, m.ActionRequest(m.Action.OPEN, view.version)
        )
    if ended:
        view = await container.conversations.act(
            view.id, m.ActionRequest(m.Action.END, view.version)
        )
    await container.aclose()
    return view


async def test_verifier_session_at_intent_in_the_file_passes(
    make_container, migrated_sqlite_url
):
    view = await _stored(make_container, migrated_sqlite_url)
    path = migrated_sqlite_url.removeprefix("sqlite+aiosqlite:///")

    result = await _verify(migrated_sqlite_url, view.id)

    assert result.returncode == 0, result.stderr
    assert result.stdout.decode() == (
        f"session {view.id} is stored at intent in {path}\n"
    )


async def test_verifier_session_the_api_kept_in_memory_fails(
    make_container, migrated_sqlite_url
):
    # The API pointed at the in-memory store: the screen sees the session, and
    # survives nothing but a reload; the database file stays empty.
    view = await _stored(make_container, None)

    result = await _verify(migrated_sqlite_url, view.id)

    assert result.returncode == 1
    assert f"no session {view.id} is stored" in result.stderr.decode()


async def test_verifier_session_still_opening_fails(
    make_container, migrated_sqlite_url
):
    view = await _stored(make_container, migrated_sqlite_url, opened=False)

    result = await _verify(migrated_sqlite_url, view.id)

    assert result.returncode == 1
    assert "at opening, not intent" in result.stderr.decode()


async def test_verifier_ended_session_fails(make_container, migrated_sqlite_url):
    view = await _stored(make_container, migrated_sqlite_url, ended=True)

    result = await _verify(migrated_sqlite_url, view.id)

    assert result.returncode == 1
    assert "stored ended, not in_progress" in result.stderr.decode()


async def test_verifier_other_opener_fails(make_container, migrated_sqlite_url):
    view = await _stored(make_container, migrated_sqlite_url)

    result = await _verify(
        migrated_sqlite_url, view.id, opener="Hi! How was your weekend?"
    )

    assert result.returncode == 1
    assert f"with openers [{OPENER!r}]" in result.stderr.decode()


async def test_verifier_ignores_an_inherited_database_url(
    make_container, migrated_sqlite_url, tmp_path
):
    # The inherited variable names a database that holds the session; the run's
    # own, given as an argument, does not.
    view = await _stored(make_container, migrated_sqlite_url)
    empty = f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}"
    await anyio.run_process(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        env=without_settings_env(os.environ)
        | {
            f"{ENV_PREFIX}DATABASE_URL": empty,
            f"{ENV_PREFIX}CORS_ORIGINS": "",
            f"{ENV_PREFIX}LOG_LEVEL": "INFO",
            f"{ENV_PREFIX}LOG_FORMAT": "text",
        },
    )

    result = await _verify(
        empty, view.id, INTENT_TO_ENGLISH_DATABASE_URL=migrated_sqlite_url
    )

    assert result.returncode == 1
    assert f"no session {view.id} is stored" in result.stderr.decode()


async def test_verifier_missing_file_fails_without_creating_it(tmp_path):
    missing = tmp_path / "missing.db"

    result = await _verify(f"sqlite+aiosqlite:///{missing}", "0" * 32)

    assert result.returncode == 1
    assert "no database file" in result.stderr.decode()
    assert not missing.exists()


async def test_verifier_unmigrated_file_fails_as_unreadable(tmp_path):
    unmigrated = tmp_path / "unmigrated.db"
    unmigrated.touch()

    result = await _verify(f"sqlite+aiosqlite:///{unmigrated}", "0" * 32)

    assert result.returncode == 1
    assert f"could not read {unmigrated}" in result.stderr.decode()


async def test_verifier_other_database_url_is_a_usage_error():
    result = await _verify("postgresql+asyncpg://localhost/x", "0" * 32)

    assert result.returncode == 2
    assert "not a SQLite URL" in result.stderr.decode()


async def test_verifier_malformed_session_id_is_a_usage_error(tmp_path):
    result = await _verify(f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}", "not-a-uuid")

    assert result.returncode == 2
    assert "session_id" in result.stderr.decode()


async def test_verifier_find_session_closes_its_engine(
    verifier, make_container, migrated_sqlite_url, monkeypatch
):
    view = await _stored(make_container, migrated_sqlite_url)
    opened, disposed = [], []

    def recording_make_engine(url):
        engine = make_engine(url)
        opened.append(engine)
        event.listen(
            engine.sync_engine, "engine_disposed", lambda _: disposed.append(engine)
        )
        return engine

    monkeypatch.setattr(composition, "make_engine", recording_make_engine)

    found = await verifier.find_session(
        verifier.isolated_settings(migrated_sqlite_url), view.id
    )

    assert found is not None
    assert (found.id, found.stage) == (view.id, m.Stage.INTENT)
    assert len(opened) == 1
    assert disposed == opened


def test_verifier_settings_outrank_environment_and_dotenv(
    verifier, monkeypatch, tmp_path
):
    hostile = {
        "INTENT_TO_ENGLISH_DATABASE_URL": "sqlite+aiosqlite:////hostile/dev.db",
        "INTENT_TO_ENGLISH_CORS_ORIGINS": "https://hostile.example",
        "INTENT_TO_ENGLISH_LOG_LEVEL": "DEBUG",
        "INTENT_TO_ENGLISH_LOG_FORMAT": "json",
        "OPENROUTER_API_KEY": "dummy-hostile-key",
        "INTENT_TO_ENGLISH_MODEL_MODE": "auto",
        "INTENT_TO_ENGLISH_COACH_MODEL": "hostile/coach",
        "INTENT_TO_ENGLISH_PARTNER_MODEL": "hostile/partner",
    }
    dotenv = tmp_path / "scratch.env"
    dotenv.write_text(
        "".join(f"{k}={v}\n" for k, v in hostile.items()), encoding="utf-8"
    )
    # As if backend/.env held the hostile values, without touching that file.
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv)
    assert Settings().log_format == "json"
    for name, value in hostile.items():
        monkeypatch.setenv(name, value)
    url = f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}"

    settings = verifier.isolated_settings(url)

    assert settings.model_dump() == {"database_url": url, **E2E_VALUES}


def test_verifier_settings_set_every_settings_field(verifier, tmp_path):
    settings = verifier.isolated_settings(f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}")

    assert settings.model_fields_set == set(Settings.model_fields)


def test_e2e_settings_environment_names_every_settings_field():
    # environment.ts gives the API and this check every Settings field
    # explicitly; one it left out could come from backend/.env.
    source = ENVIRONMENT_TS.read_text(encoding="utf-8")
    body = re.search(r"function settingsEnvironment\(.*?\n\}", source, re.DOTALL)
    assert body is not None

    names = set(re.findall(r"\b([A-Z_]+):", body[0]))

    assert names == {
        field.validation_alias
        if isinstance(field.validation_alias, str)
        else f"{ENV_PREFIX}{name.upper()}"
        for name, field in Settings.model_fields.items()
    }
