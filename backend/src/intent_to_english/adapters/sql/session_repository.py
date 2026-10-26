"""Atomic SQL persistence for conversation sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Integer, bindparam, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from intent_to_english.adapters.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_before,
    session_page_of,
)
from intent_to_english.adapters.sql import session_values as values
from intent_to_english.adapters.sql.tables import (
    model_calls,
    sessions,
    submission_cancellations,
    submissions,
    timeline_entries,
)
from intent_to_english.core import errors, models

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from intent_to_english.core.models import (
        ModelCallRecord,
        Page,
        Session,
        SessionSummary,
        Stage,
        StoredSession,
        Submission,
        TimelineEntry,
    )


_SESSION = (
    select(sessions).where(sessions.c.id == bindparam("session_id")).with_for_update()
)
_FIRST_PAGE = (
    select(sessions)
    .order_by(sessions.c.id.desc())
    .limit(bindparam("count", type_=Integer))
)
_NEXT_PAGE = _FIRST_PAGE.where(sessions.c.id < bindparam("before"))
_PREVIOUS_OPENER = (
    select(sessions.c.opener)
    .where(
        sessions.c.id < bindparam("session_id"),
        sessions.c.opener.is_not(None),
        sessions.c.opener != "",
    )
    .order_by(sessions.c.id.desc())
    .limit(1)
)
_ENTRIES = (
    select(timeline_entries)
    .where(timeline_entries.c.session_id == bindparam("session_id"))
    .order_by(timeline_entries.c.seq)
)
_ENTRY_IDS = select(timeline_entries.c.id).where(
    timeline_entries.c.id.in_(bindparam("ids", expanding=True))
)
_LAST_SUBMISSION = (
    select(submissions)
    .where(submissions.c.session_id == bindparam("session_id"))
    .order_by(submissions.c.created_at.desc(), submissions.c.id.desc())
    .limit(1)
)
_PENDING = (
    select(submissions)
    .where(
        submissions.c.session_id == bindparam("session_id"),
        submissions.c.status == "pending",
    )
    .limit(1)
)
_SUBMISSION = select(submissions).where(submissions.c.id == bindparam("submission_id"))
_INSERT_SESSION = insert(sessions)
_INSERT_SUBMISSION = insert(submissions)
_INSERT_ENTRY = insert(timeline_entries)
_INSERT_CALL = insert(model_calls)
_UPDATE_SESSION = update(sessions).where(sessions.c.id == bindparam("session_id"))
_UPDATE_PENDING = update(submissions).where(
    submissions.c.id == bindparam("submission_id"), submissions.c.status == "pending"
)
_CANCEL = (
    update(submissions)
    .where(
        submissions.c.session_id == bindparam("target_session_id"),
        submissions.c.base_version == bindparam("version"),
        submissions.c.status == "pending",
        func.coalesce(submissions.c.attempt_id, submissions.c.id)
        == bindparam("target_attempt_id"),
    )
    .values(status="cancelled", finished_at=bindparam("finished_at"))
)
_ATTEMPT = select(submissions.c.id).where(
    submissions.c.session_id == bindparam("session_id"),
    func.coalesce(submissions.c.attempt_id, submissions.c.id)
    == bindparam("attempt_id"),
)
_CANCELLATION = select(submission_cancellations.c.attempt_id).where(
    submission_cancellations.c.session_id == bindparam("session_id"),
    submission_cancellations.c.base_version == bindparam("base_version"),
    submission_cancellations.c.attempt_id == bindparam("attempt_id"),
)
_INSERT_CANCELLATION = insert(submission_cancellations)

_CALLS = (
    select(model_calls)
    .where(model_calls.c.session_id == bindparam("session_id"))
    .order_by(model_calls.c.created_at, model_calls.c.id)
)


class SqlSessionRepository:
    """Keep every state transition within one database transaction."""

    def __init__(self, engine: AsyncEngine) -> None:
        """Borrow the caller's migrated engine; the caller owns disposal."""
        self._engine = engine

    async def create(self, session: Session) -> StoredSession:
        """Create once, without overwriting an existing session."""
        try:
            async with self._engine.begin() as connection:
                await connection.execute(
                    _INSERT_SESSION, values.session_values(session)
                )
        except IntegrityError as error:
            if not _duplicate_id(error, "sessions"):
                raise
            message = "A session with this id is already stored"
            raise ValueError(message) from error
        return models.StoredSession(session)

    async def get(self, session_id: UUID) -> StoredSession:
        """Read one consistent snapshot under the session's transition lock."""
        async with self._engine.begin() as connection:
            session = await _require_session(connection, session_id)
            return await _snapshot(connection, session)

    async def list_page(self, cursor: str | None, limit: int) -> Page[SessionSummary]:
        """Page newest UUIDs first using the same opaque cursor as memory."""
        if limit < 1:
            raise errors.InvalidCursorError(INVALID_CURSOR_MESSAGE)
        before = decode_before(cursor) if cursor is not None else None
        async with self._engine.connect() as connection:
            result = await connection.execute(
                _FIRST_PAGE if before is None else _NEXT_PAGE,
                {"count": limit + 1, "before": before},
            )
            rows = result.mappings().all()
        summaries = [
            models.SessionSummary(
                row["id"],
                row["started_at"],
                models.SessionStatus(row["status"]),
                row["finished_replies"],
                row["opener"],
            )
            for row in rows
        ]
        return session_page_of(summaries, limit)

    async def previous_opener(self, session_id: UUID) -> str | None:
        """Find the newest earlier nonempty opener."""
        async with self._engine.connect() as connection:
            return await connection.scalar(_PREVIOUS_OPENER, {"session_id": session_id})

    async def begin_submission(
        self,
        submission: Submission,
        allowed_stages: frozenset[Stage],
        interrupted_before: datetime,
    ) -> None:
        """Check everything before atomically superseding and inserting."""
        try:
            async with self._engine.begin() as connection:
                session = await _require_session(connection, submission.session_id)
                if session.version != submission.base_version:
                    raise errors.StaleSessionError
                pending_row = (
                    (await connection.execute(_PENDING, {"session_id": session.id}))
                    .mappings()
                    .one_or_none()
                )
                pending = (
                    values.submission_from(pending_row)
                    if pending_row is not None
                    else None
                )
                live = (
                    pending is not None
                    and pending.boot_id == submission.boot_id
                    and pending.created_at >= interrupted_before
                )
                if live and submission.action is not models.Action.END:
                    raise errors.ActionInProgressError
                if (
                    session.status is models.SessionStatus.ENDED
                    and submission.action is not models.Action.WRAP_UP
                ):
                    raise errors.SessionEndedError
                if session.stage not in allowed_stages:
                    raise errors.ActionNotAllowedError(submission.action, session.stage)
                existing = await connection.scalar(
                    _SUBMISSION, {"submission_id": submission.id}
                )
                if existing is not None:
                    message = "A submission with this id is already stored"
                    raise ValueError(message)
                identity = {
                    "session_id": session.id,
                    "base_version": submission.base_version,
                    "attempt_id": submission.correlation_id,
                }
                if await connection.scalar(_CANCELLATION, identity) is not None:
                    raise errors.ActionCancelledError
                if await connection.scalar(_ATTEMPT, identity) is not None:
                    raise errors.AttemptAlreadyUsedError
                if pending is not None:
                    await connection.execute(
                        _UPDATE_PENDING,
                        {
                            "submission_id": pending.id,
                            "status": "cancelled" if live else "failed",
                            "failure_code": None if live else "interrupted",
                            "finished_at": submission.created_at,
                        },
                    )
                await connection.execute(
                    _INSERT_SUBMISSION, values.submission_values(submission)
                )
        except IntegrityError as error:
            detail = str(error.orig)
            if (
                "uq_submissions_session_id_base_version_active" in detail
                or "submissions.session_id, submissions.base_version" in detail
            ):
                raise errors.ActionInProgressError from error
            raise

    async def finish_submission(
        self,
        submission_id: UUID,
        session: Session,
        entries: tuple[TimelineEntry, ...],
        finished_at: datetime,
    ) -> StoredSession:
        """Append and advance only while the original submission is pending."""
        try:
            async with self._engine.begin() as connection:
                current = await _require_session(connection, session.id)
                submission = await _require_submission(connection, submission_id)
                if submission.status is not models.SubmissionStatus.PENDING:
                    raise errors.ActionCancelledError
                if (
                    submission.session_id != current.id
                    or session.version != current.version + 1
                ):
                    message = "Invalid session version in timeline completion"
                    raise ValueError(message)
                stored = await _snapshot(connection, current)
                await _check_entries(connection, session, stored.entries, entries)
                if entries:
                    await connection.execute(
                        _INSERT_ENTRY, [values.entry_values(entry) for entry in entries]
                    )
                columns = values.session_values(session)
                del columns["id"]
                await connection.execute(
                    _UPDATE_SESSION, {"session_id": session.id, **columns}
                )
                await connection.execute(
                    _UPDATE_PENDING,
                    {
                        "submission_id": submission_id,
                        "status": "completed",
                        "finished_at": finished_at,
                    },
                )
                return await _snapshot(connection, session)
        except IntegrityError as error:
            if not (
                _duplicate_id(error, "timeline_entries")
                or "timeline_entries.session_id, timeline_entries.seq"
                in str(error.orig)
                or "uq_timeline_entries_session_id" in str(error.orig)
            ):
                raise
            message = "Entries must extend the timeline without duplicates"
            raise ValueError(message) from error

    async def fail_submission(
        self, submission_id: UUID, failure_code: str, finished_at: datetime
    ) -> None:
        """Fail only pending work, never replacing a cancellation or completion."""
        async with self._engine.begin() as connection:
            submission = await _require_submission(connection, submission_id)
            await _require_session(connection, submission.session_id)
            await connection.execute(
                _UPDATE_PENDING,
                {
                    "submission_id": submission_id,
                    "status": "failed",
                    "failure_code": failure_code,
                    "finished_at": finished_at,
                },
            )

    async def cancel_submission(
        self,
        session_id: UUID,
        base_version: int,
        attempt_id: UUID,
        finished_at: datetime,
    ) -> bool:
        """Serialize admission and exact cancellation, including an early cancel."""
        async with self._engine.begin() as connection:
            session = await _require_session(connection, session_id)
            if session.version != base_version:
                return False
            identity = {
                "session_id": session_id,
                "base_version": base_version,
                "attempt_id": attempt_id,
            }
            if await connection.scalar(_CANCELLATION, identity) is None:
                await connection.execute(
                    _INSERT_CANCELLATION, {**identity, "created_at": finished_at}
                )
            result = await connection.execute(
                _CANCEL,
                {
                    "target_session_id": session_id,
                    "target_attempt_id": attempt_id,
                    "version": base_version,
                    "finished_at": finished_at,
                },
            )
            return result.rowcount > 0

    async def record_model_call(self, record: ModelCallRecord) -> None:
        """Persist every billed attempt independently of action completion."""
        try:
            async with self._engine.begin() as connection:
                await connection.execute(_INSERT_CALL, values.call_values(record))
        except IntegrityError as error:
            if not _duplicate_id(error, "model_calls"):
                raise
            message = "A model call with this id is already stored"
            raise ValueError(message) from error

    async def model_calls(self, session_id: UUID) -> tuple[ModelCallRecord, ...]:
        """Read calls in timestamp and id order, including cancelled work."""
        async with self._engine.connect() as connection:
            rows = (
                (await connection.execute(_CALLS, {"session_id": session_id}))
                .mappings()
                .all()
            )
        return tuple(values.call_from(row) for row in rows)


def _duplicate_id(error: IntegrityError, table: str) -> bool:
    detail = str(error.orig)
    return f"{table}.id" in detail or f'"pk_{table}"' in detail


async def _require_session(connection: AsyncConnection, session_id: UUID) -> Session:
    row = (
        (await connection.execute(_SESSION, {"session_id": session_id}))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise errors.SessionNotFoundError(session_id)
    return values.session_from(row)


async def _require_submission(
    connection: AsyncConnection, submission_id: UUID
) -> Submission:
    row = (
        (await connection.execute(_SUBMISSION, {"submission_id": submission_id}))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise KeyError(submission_id)
    return values.submission_from(row)


async def _snapshot(connection: AsyncConnection, session: Session) -> StoredSession:
    rows = (
        (await connection.execute(_ENTRIES, {"session_id": session.id}))
        .mappings()
        .all()
    )
    last = (
        (await connection.execute(_LAST_SUBMISSION, {"session_id": session.id}))
        .mappings()
        .one_or_none()
    )
    return models.StoredSession(
        session,
        tuple(values.entry_from(row) for row in rows),
        values.submission_from(last) if last is not None else None,
    )


async def _check_entries(
    connection: AsyncConnection,
    session: Session,
    stored: tuple[TimelineEntry, ...],
    entries: tuple[TimelineEntry, ...],
) -> None:
    expected = tuple(range(len(stored) + 1, len(stored) + len(entries) + 1))
    ids = [entry.id for entry in entries]
    duplicate = (
        bool(ids) and (await connection.scalar(_ENTRY_IDS, {"ids": ids})) is not None
    )
    if (
        tuple(entry.seq for entry in entries) != expected
        or any(entry.session_id != session.id for entry in entries)
        or len(set(ids)) != len(ids)
        or duplicate
    ):
        message = "Entries must extend the timeline without duplicates"
        raise ValueError(message)
