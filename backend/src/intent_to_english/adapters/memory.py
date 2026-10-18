"""A process-local to-do repository, the default store and the tests' fake."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from typing import TYPE_CHECKING

from intent_to_english.adapters.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_after,
    decode_before,
    page_of,
    session_page_of,
)
from intent_to_english.core.errors import (
    ActionCancelledError,
    ActionInProgressError,
    ActionNotAllowedError,
    InvalidCursorError,
    SessionEndedError,
    SessionNotFoundError,
    StaleSessionError,
    TodoNotFoundError,
)
from intent_to_english.core.models import (
    Action,
    SessionStatus,
    SessionSummary,
    StoredSession,
    SubmissionStatus,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intent_to_english.core.models import (
        ModelCallRecord,
        Page,
        Session,
        Stage,
        Submission,
        TimelineEntry,
        Todo,
    )


class InMemoryTodoRepository:
    """Keep to-dos in a dict for the life of the process.

    Every method runs on the event loop and never awaits, so a read-modify-write
    of the dict cannot be interleaved with another task's: a duplicate-id check
    and the insert it guards happen as one step, and no lock is needed. An
    ``await`` added between reading and writing ``_todos`` would break that.
    """

    def __init__(self) -> None:
        """Start empty."""
        self._todos: dict[UUID, Todo] = {}

    async def add(self, todo: Todo) -> Todo:
        """Store a new to-do under its own id.

        Args:
            todo: The to-do to store.

        Returns:
            ``todo``, now stored.

        Raises:
            ValueError: If a to-do with this id is already stored; it is left
                unchanged.
        """
        if todo.id in self._todos:
            msg = f"A to-do with id {todo.id} is already stored"
            raise ValueError(msg)
        self._todos[todo.id] = todo
        return todo

    async def get(self, todo_id: UUID) -> Todo:
        """Fetch one to-do.

        Args:
            todo_id: The to-do to fetch.

        Returns:
            The stored to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        return self._require(todo_id)

    async def list_page(self, cursor: str | None, limit: int) -> Page[Todo]:
        """Fetch one page of to-dos in ascending id order.

        Args:
            cursor: ``None`` for the first page, else a ``next_cursor``.
            limit: The most to-dos the page holds.

        Returns:
            The page, with a cursor when more to-dos follow it.

        Raises:
            InvalidCursorError: If ``cursor`` is not one this store issued.
        """
        ids = sorted(self._todos)
        start = 0 if cursor is None else bisect_right(ids, decode_after(cursor))
        fetched = [self._todos[todo_id] for todo_id in ids[start : start + limit + 1]]
        return page_of(fetched, limit)

    async def update(self, todo: Todo) -> Todo:
        """Replace the stored to-do that has ``todo.id``.

        Args:
            todo: The new value.

        Returns:
            ``todo``, now stored.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        self._require(todo.id)
        self._todos[todo.id] = todo
        return todo

    async def delete(self, todo_id: UUID) -> None:
        """Remove one to-do.

        Args:
            todo_id: The to-do to remove.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        self._require(todo_id)
        del self._todos[todo_id]

    def _require(self, todo_id: UUID) -> Todo:
        """Return the stored to-do or raise ``TodoNotFoundError``."""
        try:
            return self._todos[todo_id]
        except KeyError:
            raise TodoNotFoundError(todo_id) from None


class InMemorySessionRepository:
    """Atomic event-loop storage: no method awaits between checking and writing."""

    def __init__(self) -> None:
        """Keep immutable values; every read returns an independent snapshot."""
        self._sessions: dict[UUID, Session] = {}
        self._entries: dict[UUID, tuple[TimelineEntry, ...]] = {}
        self._submissions: dict[UUID, Submission] = {}
        self._calls: dict[UUID, ModelCallRecord] = {}

    def _require_session(self, session_id: UUID) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFoundError(session_id) from None

    def _snapshot(self, session: Session) -> StoredSession:
        submissions = [
            s for s in self._submissions.values() if s.session_id == session.id
        ]
        last = max(submissions, key=lambda s: (s.created_at, s.id), default=None)
        return StoredSession(session, self._entries[session.id], last)

    async def create(self, session: Session) -> StoredSession:
        """Refuse duplicate ids without replacing any stored value."""
        if session.id in self._sessions:
            msg = "A session with this id is already stored"
            raise ValueError(msg)
        self._sessions[session.id] = session
        self._entries[session.id] = ()
        return self._snapshot(session)

    async def get(self, session_id: UUID) -> StoredSession:
        """Read the session, its timeline and its latest submission atomically."""
        return self._snapshot(self._require_session(session_id))

    async def list_page(self, cursor: str | None, limit: int) -> Page[SessionSummary]:
        """List newest ids first with an opaque descending cursor."""
        if limit < 1:
            raise InvalidCursorError(INVALID_CURSOR_MESSAGE)
        before = decode_before(cursor) if cursor is not None else None
        sessions = [
            s
            for s in sorted(self._sessions.values(), key=lambda s: s.id, reverse=True)
            if before is None or s.id < before
        ]
        summaries = [
            SessionSummary(s.id, s.started_at, s.status, s.finished_replies, s.opener)
            for s in sessions[: limit + 1]
        ]
        return session_page_of(summaries, limit)

    async def previous_opener(self, session_id: UUID) -> str | None:
        """Ignore sessions without an opener when looking back."""
        earlier = [
            s
            for s in self._sessions.values()
            if s.id < session_id and s.opener is not None
        ]
        previous = max(earlier, key=lambda s: s.id, default=None)
        return previous.opener if previous is not None else None

    async def begin_submission(
        self,
        submission: Submission,
        allowed_stages: frozenset[Stage],
        interrupted_before: datetime,
    ) -> None:
        """Check the complete precondition sequence before changing any state."""
        session = self._require_session(submission.session_id)
        if session.version != submission.base_version:
            raise StaleSessionError
        pending = next(
            (
                s
                for s in self._submissions.values()
                if s.session_id == session.id and s.status is SubmissionStatus.PENDING
            ),
            None,
        )
        is_live = (
            pending is not None
            and pending.boot_id == submission.boot_id
            and pending.created_at >= interrupted_before
        )
        if is_live and submission.action is not Action.END:
            raise ActionInProgressError
        if (
            session.status is SessionStatus.ENDED
            and submission.action is not Action.WRAP_UP
        ):
            raise SessionEndedError
        if session.stage not in allowed_stages:
            raise ActionNotAllowedError(submission.action, session.stage)
        if submission.id in self._submissions:
            msg = "A submission with this id is already stored"
            raise ValueError(msg)
        if pending is not None:
            self._submissions[pending.id] = replace(
                pending,
                status=SubmissionStatus.CANCELLED
                if is_live
                else SubmissionStatus.FAILED,
                failure_code=None if is_live else "interrupted",
                finished_at=submission.created_at,
            )
        self._submissions[submission.id] = submission

    async def finish_submission(
        self,
        submission_id: UUID,
        session: Session,
        entries: tuple[TimelineEntry, ...],
        finished_at: datetime,
    ) -> StoredSession:
        """Reject late output and invalid timeline extensions before any write."""
        submission = self._submissions[submission_id]
        if submission.status is not SubmissionStatus.PENDING:
            raise ActionCancelledError
        current = self._require_session(submission.session_id)
        if session.id != current.id or session.version != current.version + 1:
            msg = "Invalid session version in timeline completion"
            raise ValueError(msg)
        stored = self._entries[session.id]
        ids = {e.id for values in self._entries.values() for e in values}
        expected = tuple(range(len(stored) + 1, len(stored) + len(entries) + 1))
        if (
            tuple(e.seq for e in entries) != expected
            or any(e.session_id != session.id or e.id in ids for e in entries)
            or len({e.id for e in entries}) != len(entries)
        ):
            msg = "Entries must extend the timeline without duplicates"
            raise ValueError(msg)
        self._entries[session.id] = stored + entries
        self._sessions[session.id] = session
        self._submissions[submission_id] = replace(
            submission, status=SubmissionStatus.COMPLETED, finished_at=finished_at
        )
        return self._snapshot(session)

    async def fail_submission(
        self, submission_id: UUID, failure_code: str, finished_at: datetime
    ) -> None:
        """Failure never moves the stage and never overwrites a cancellation."""
        submission = self._submissions[submission_id]
        if submission.status is SubmissionStatus.PENDING:
            self._submissions[submission_id] = replace(
                submission,
                status=SubmissionStatus.FAILED,
                failure_code=failure_code,
                finished_at=finished_at,
            )

    async def cancel_submission(
        self, session_id: UUID, base_version: int, finished_at: datetime
    ) -> bool:
        """A stale cancel never affects the pending action at another version."""
        self._require_session(session_id)
        pending = next(
            (
                s
                for s in self._submissions.values()
                if s.session_id == session_id
                and s.base_version == base_version
                and s.status is SubmissionStatus.PENDING
            ),
            None,
        )
        if pending is not None:
            self._submissions[pending.id] = replace(
                pending, status=SubmissionStatus.CANCELLED, finished_at=finished_at
            )
        return pending is not None

    async def record_model_call(self, record: ModelCallRecord) -> None:
        """Keep billed attempts even if the action later fails or is cancelled."""
        if record.id in self._calls:
            msg = "A model call with this id is already stored"
            raise ValueError(msg)
        self._calls[record.id] = record

    async def model_calls(self, session_id: UUID) -> tuple[ModelCallRecord, ...]:
        """Return attempts in their recorded order."""
        return tuple(
            sorted(
                (c for c in self._calls.values() if c.session_id == session_id),
                key=lambda c: (c.created_at, c.id),
            )
        )
