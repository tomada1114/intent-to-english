"""The session page cursor the in-memory and SQL repositories share.

A cursor names the last id of the page before, so the next page of the
newest-first listing is every session with a smaller id. It is opaque to the
core and to clients: a store whose own paging token differs keeps that token
inside its adapter.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING
from uuid import UUID

from intent_to_english.core.errors import InvalidCursorError
from intent_to_english.core.models import Page

if TYPE_CHECKING:
    from collections.abc import Sequence

    from intent_to_english.core.models import SessionSummary

INVALID_CURSOR_MESSAGE = (
    "Invalid page cursor: pass the next_cursor of an earlier page, "
    "or no cursor for the first page"
)
_UUID_BYTES = 16


def encode_after(last_id: UUID) -> str:
    """Return the canonical token for ``last_id``, the last id of a page.

    Args:
        last_id: The last id of the page before.

    Returns:
        The 16 id bytes as URL-safe base64 without padding: 22 characters a
        client can pass in a query string unescaped.
    """
    return base64.urlsafe_b64encode(last_id.bytes).rstrip(b"=").decode("ascii")


def decode_after(cursor: str) -> UUID:
    """Return the id a cursor from ``encode_after`` names.

    Accepts exactly the strings ``encode_after`` returns, so one id has one
    cursor: no padding, no standard-alphabet characters, no stray bits.

    Args:
        cursor: A ``next_cursor`` a page returned.

    Returns:
        The id the page before ended on.

    Raises:
        InvalidCursorError: If ``encode_after`` could not have returned
            ``cursor``.
    """
    try:
        # A str with non-ASCII characters raises ValueError too.
        raw = base64.urlsafe_b64decode(cursor + "==")
    except ValueError:
        raise InvalidCursorError(INVALID_CURSOR_MESSAGE) from None
    if len(raw) != _UUID_BYTES:
        raise InvalidCursorError(INVALID_CURSOR_MESSAGE)
    last_id = UUID(bytes=raw)
    if encode_after(last_id) != cursor:
        raise InvalidCursorError(INVALID_CURSOR_MESSAGE)
    return last_id


_SESSION_CURSOR_PREFIX = "session:"


def encode_before(session_id: UUID) -> str:
    """Return the session cursor whose next page starts below ``session_id``.

    The prefix names the token's family, so a bare id token is never accepted.
    """
    return _SESSION_CURSOR_PREFIX + encode_after(session_id)


def decode_before(cursor: str) -> UUID:
    """Read only canonical session cursors, rejecting other token families."""
    if not cursor.startswith(_SESSION_CURSOR_PREFIX):
        raise InvalidCursorError(INVALID_CURSOR_MESSAGE)
    return decode_after(cursor.removeprefix(_SESSION_CURSOR_PREFIX))


def session_page_of(
    fetched: Sequence[SessionSummary], limit: int
) -> Page[SessionSummary]:
    """Build a newest-first page from at most limit plus one session rows."""
    items = tuple(fetched[:limit])
    cursor = encode_before(items[-1].id) if len(fetched) > limit else None
    return Page(items, cursor)
