"""Read recorded requests without changing the practice database."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Uuid, bindparam, or_, select
from sqlalchemy.exc import OperationalError, ProgrammingError

from intent_to_english.adapters.sql.engine import make_read_engine
from intent_to_english.adapters.sql.session_values import call_from
from intent_to_english.adapters.sql.tables import UtcDateTime, model_calls

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intent_to_english.core.models import ModelCallRecord


class CallLogReadError(Exception):
    """The selected database cannot supply its migrated call log."""


_SESSION = bindparam("session_id", type_=Uuid)
_SINCE = bindparam("since", type_=UtcDateTime)
_READ_CALLS = (
    select(model_calls)
    .where(
        or_(_SESSION.is_(None), model_calls.c.session_id == _SESSION),
        or_(_SINCE.is_(None), model_calls.c.created_at >= _SINCE),
    )
    .order_by(model_calls.c.created_at, model_calls.c.id)
)


async def read_calls(
    url: str, session_id: UUID | None = None, since: datetime | None = None
) -> tuple[ModelCallRecord, ...]:
    """Load optional inclusive filters over one owned read-only connection."""
    engine = make_read_engine(url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                _READ_CALLS, {"session_id": session_id, "since": since}
            )
            return tuple(call_from(row) for row in result.mappings())
    except OperationalError, ProgrammingError:
        message = "Cannot read the model call log. Check the database URL and run `just backend db-upgrade`."
        raise CallLogReadError(message) from None
    finally:
        await engine.dispose()
