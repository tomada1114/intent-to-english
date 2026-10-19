"""A process-local session repository, the default store and the tests' fake."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from intent_to_english.adapters.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_before,
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
    )


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
