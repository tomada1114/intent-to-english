"""Build the one ``AsyncEngine`` the SQL repositories share."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import event, make_url
from sqlalchemy.ext.asyncio import create_async_engine

if TYPE_CHECKING:
    from sqlalchemy import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine
    from sqlalchemy.pool import ConnectionPoolEntry

# How long a SQLite connection waits for another connection's write lock
# before failing with "database is locked". The driver's default, 5 seconds,
# is short enough for a burst of concurrent writes on a loaded machine to
# exceed it.
SQLITE_BUSY_TIMEOUT_SECONDS = 30


def make_engine(url: str) -> AsyncEngine:
    """Return an engine for ``url`` that connects on first use.

    Opening nothing here is what lets ``build_container`` register
    ``engine.dispose`` without leaking a connection when a later step of the
    build fails. The caller owns the engine and must await ``dispose()`` on
    the event loop that used it; ``build_container`` registers that on the
    container's resources.

    Args:
        url: A SQLAlchemy URL for an async driver, as ``Settings`` validates
            it.

    Returns:
        The engine, pooling connections for the event loop that uses it.
    """
    connect_args: dict[str, Any] = {}
    if make_url(url).get_backend_name() == "sqlite":
        connect_args["timeout"] = SQLITE_BUSY_TIMEOUT_SECONDS
    try:
        engine = create_async_engine(url, connect_args=connect_args)
    except ModuleNotFoundError as exc:
        if make_url(url).drivername != "postgresql+asyncpg" or exc.name != "asyncpg":
            raise
        msg = "Install the 'postgres' extra to use a PostgreSQL database"
        raise RuntimeError(msg) from exc
    if engine.dialect.name == "sqlite":
        event.listen(engine.sync_engine, "connect", _sqlite_connect)
        event.listen(engine.sync_engine, "begin", _sqlite_begin)
    return engine


def _sqlite_connect(dbapi_connection: Any, _record: ConnectionPoolEntry) -> None:
    # The event exposes the driver's dynamic DBAPI facade, hence Any at this boundary.
    # SQLAlchemy owns BEGIN; otherwise SELECT and DDL escape the transaction.
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _sqlite_begin(connection: Connection) -> None:
    # Acquire the writer lock before reading, avoiding a read-to-write upgrade race.
    connection.exec_driver_sql("BEGIN IMMEDIATE")
