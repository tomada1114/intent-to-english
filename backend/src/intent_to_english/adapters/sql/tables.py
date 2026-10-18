"""The SQL schema, declared once as Core ``Table`` metadata.

Alembic compares migrations against ``metadata`` (``backend/migrations/env.py``),
so a change here is followed by a revision (``just backend db-revision``). No
ORM class maps these tables: rows become core models inside the repositories.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, override

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
)

from intent_to_english.core.models import MAX_TITLE_LENGTH

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect

# Every constraint and index gets a predictable name, so a later migration can
# drop or alter it by name on every database.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator[datetime]):
    """A timezone-aware ``datetime`` stored as naive UTC.

    SQLite has no timezone-aware type and PostgreSQL's converts on the way
    in, so storing naive UTC behaves the same on both: an aware value is
    converted to UTC and stored without its offset, and a value read back has
    UTC attached. A naive value is refused rather than guessed at: it is a bug
    in a clock or a caller, as ``Todo`` treats it.
    """

    impl = DateTime
    cache_ok = True

    @override
    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Convert an aware value to naive UTC for storage.

        Raises:
            ValueError: If ``value`` is naive.
        """
        if value is None:
            return None
        if value.utcoffset() is None:
            msg = f"{value.isoformat()} must be timezone-aware to be stored"
            raise ValueError(msg)
        return value.astimezone(UTC).replace(tzinfo=None)

    @override
    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Attach UTC to the naive UTC value the database returns."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


metadata = MetaData(naming_convention=NAMING_CONVENTION)

todos = Table(
    "todos",
    metadata,
    # The application generates ids (UUIDv7, ascending in creation order);
    # pages read in id order.
    Column("id", Uuid, primary_key=True),
    Column("title", String(MAX_TITLE_LENGTH), nullable=False),
    Column("is_completed", Boolean, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("started_at", UtcDateTime, nullable=False),
    Column("ended_at", UtcDateTime),
    Column("status", String, nullable=False),
    Column("stage", String, nullable=False),
    Column("turn_index", Integer, nullable=False),
    Column("turn_state", JSON, nullable=False),
    Column("version", Integer, nullable=False),
    Column("finished_replies", Integer, nullable=False),
    Column("opener", Text),
    Column("wrap_up", JSON(none_as_null=True)),
)

timeline_entries = Table(
    "timeline_entries",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("session_id", Uuid, ForeignKey("sessions.id"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("turn_index", Integer, nullable=False),
    Column("kind", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    UniqueConstraint("session_id", "seq"),
)

submissions = Table(
    "submissions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("session_id", Uuid, ForeignKey("sessions.id"), nullable=False, index=True),
    Column("base_version", Integer, nullable=False),
    Column("action", String, nullable=False),
    Column("input", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("failure_code", String),
    Column("boot_id", Uuid, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("finished_at", UtcDateTime),
)
Index(
    "uq_submissions_session_id_base_version_active",
    submissions.c.session_id,
    submissions.c.base_version,
    unique=True,
    sqlite_where=submissions.c.status.in_(("pending", "completed")),
    postgresql_where=submissions.c.status.in_(("pending", "completed")),
)

model_calls = Table(
    "model_calls",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("session_id", Uuid, ForeignKey("sessions.id"), nullable=False, index=True),
    Column("submission_id", Uuid, ForeignKey("submissions.id"), nullable=False),
    Column("turn_index", Integer, nullable=False),
    Column("role", String, nullable=False),
    Column("task", String, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("provider", String, nullable=False),
    Column("model", String, nullable=False),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    # Decimal text preserves the provider's exact cost on SQLite as well as PostgreSQL.
    Column("cost", String),
    Column("latency_ms", Integer, nullable=False),
    Column("outcome", String, nullable=False),
    Column("violations", JSON, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
)
