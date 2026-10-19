"""Confirm, from a process of its own, that the browser's session is in the database.

``e2e/tests/conversation.spec.ts`` runs this once the screen has started a session
and the Partner's opener has arrived. A reload in the browser cannot tell a
database from an API that keeps sessions in memory; this process builds its own
container on the same SQLite file, so it sees only what the API stored there.

Every ``Settings`` field is passed explicitly and ``backend/.env`` is not read, so
neither an inherited ``INTENT_TO_ENGLISH_*`` variable nor the developer's dotenv file can
point it at another database. The container, and so its engine, is closed
before the process exits. Reading a session writes nothing.

Usage:
    uv run --locked python e2e/verify_persistence.py DATABASE_URL SESSION_ID OPENER

Exit status: 0 when a session with that id is stored in progress at ``intent``
with exactly one opener, and that opener is OPENER; 1 when it is missing or
differs, or the database cannot be read; 2 on a usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from intent_to_english.composition import build_container
from intent_to_english.core.errors import SessionNotFoundError
from intent_to_english.core.models import (
    EntryKind,
    LineKind,
    PartnerLinePayload,
    SessionStatus,
    Stage,
)
from intent_to_english.settings import (
    DEFAULT_COACH_MODEL,
    DEFAULT_PARTNER_MODEL,
    SQLITE_URL_PREFIX,
    Settings,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from intent_to_english.core.models import SessionView

USAGE_ERROR = 2


def isolated_settings(database_url: str) -> Settings:
    """Return Settings with every field set here and no dotenv file read.

    Keep the arguments equal to ``Settings``' fields: a field left out would be
    read from the environment or ``backend/.env``
    (``backend/tests/test_e2e_persistence.py`` fails when they disagree).
    """
    # Any is limited to BaseSettings' private constructor keyword, which
    # Pydantic's mypy plugin leaves out of Settings' signature.
    no_dotenv: dict[str, Any] = {"_env_file": None}
    return Settings(
        **no_dotenv,
        database_url=database_url,
        cors_origins=[],
        log_level="INFO",
        log_format="text",
        OPENROUTER_API_KEY=None,
        model_mode="fixed",
        coach_model=DEFAULT_COACH_MODEL,
        partner_model=DEFAULT_PARTNER_MODEL,
    )


async def find_session(settings: Settings, session_id: uuid.UUID) -> SessionView | None:
    """Return the stored session with ``session_id``, or None when there is none."""
    async with build_container(settings) as container:
        try:
            return await container.conversations.get(session_id)
        except SessionNotFoundError:
            return None


def _openers(view: SessionView) -> list[str]:
    return [
        entry.payload.text
        for entry in view.entries
        if entry.kind is EntryKind.PARTNER_LINE
        and isinstance(entry.payload, PartnerLinePayload)
        and entry.payload.line_kind is LineKind.OPENER
    ]


def _problem(
    session_id: uuid.UUID, opener: str, view: SessionView | None
) -> str | None:
    if view is None:
        return f"no session {session_id} is stored"
    if view.status is not SessionStatus.IN_PROGRESS:
        return f"session {session_id} is stored {view.status}, not in_progress"
    if view.stage is not Stage.INTENT:
        return f"session {session_id} is stored at {view.stage}, not intent"
    openers = _openers(view)
    if openers != [opener]:
        return (
            f"session {session_id} is stored with openers {openers!r}, not [{opener!r}]"
        )
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Check the database and report on stdout (stored) or stderr (anything else)."""
    parser = argparse.ArgumentParser(
        description="Confirm that the e2e flow's session is stored at intent."
    )
    parser.add_argument("database_url", help=f"{SQLITE_URL_PREFIX}<absolute path>")
    parser.add_argument("session_id", type=uuid.UUID)
    parser.add_argument("opener", help="the Partner's opener the screen showed")
    args = parser.parse_args(argv)
    database_url: str = args.database_url
    if not database_url.startswith(SQLITE_URL_PREFIX):
        sys.stderr.write(f"error: not a SQLite URL: {database_url!r}\n")
        return USAGE_ERROR
    # SQLite would create a missing file, and then report a missing table.
    path = Path(database_url.removeprefix(SQLITE_URL_PREFIX).partition("?")[0])
    if not path.is_file():
        sys.stderr.write(f"error: no database file at {path}\n")
        return 1
    try:
        view = asyncio.run(
            find_session(isolated_settings(database_url), args.session_id)
        )
    except Exception as error:  # any failure to read the database fails the check
        sys.stderr.write(f"error: could not read {path}: {error!r}\n")
        return 1
    problem = _problem(args.session_id, args.opener, view)
    if problem is not None:
        sys.stderr.write(f"error: {problem} in {path}\n")
        return 1
    sys.stdout.write(f"session {args.session_id} is stored at intent in {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
