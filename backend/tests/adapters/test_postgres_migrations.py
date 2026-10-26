"""Exercise the migrations through a shared async PostgreSQL connection."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from intent_to_english.adapters.sql.engine import make_engine
from intent_to_english.adapters.sql.tables import metadata
from tests.conftest import ALEMBIC_INI

if TYPE_CHECKING:
    from sqlalchemy import Connection

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]

APP_TABLES = {
    "sessions",
    "timeline_entries",
    "submissions",
    "model_calls",
    "submission_cancellations",
}
TODOS_REVISION = "f58f944d0d8e"
SESSIONS_REVISION = "de3f10d569ec"


def _tables(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def _todos_shape(connection: Connection) -> tuple[object, ...]:
    inspector = inspect(connection)
    columns = [
        (column["name"], str(column["type"]), column["nullable"])
        for column in inspector.get_columns("todos")
    ]
    primary_key = inspector.get_pk_constraint("todos")
    return (columns, primary_key["constrained_columns"], primary_key["name"])


async def test_postgres_migrations_upgrade_check_downgrade_upgrade(
    migrated_postgres_url,
):
    engine = make_engine(migrated_postgres_url)
    try:
        async with engine.begin() as connection:
            config = Config(ALEMBIC_INI)
            config.attributes["configure_logging"] = False
            config.attributes["connection"] = connection.sync_connection
            await connection.run_sync(lambda _: command.upgrade(config, "head"))
            await connection.run_sync(lambda _: command.check(config))
            assert await connection.run_sync(_tables) == {
                "alembic_version",
                *APP_TABLES,
            }
            await connection.run_sync(lambda _: command.downgrade(config, "base"))
            assert await connection.run_sync(_tables) == {"alembic_version"}
            await connection.run_sync(lambda _: command.upgrade(config, "head"))
            await connection.run_sync(lambda _: command.check(config))
            tables = await connection.run_sync(_tables)
            assert tables == {"alembic_version", *metadata.tables}
    finally:
        await engine.dispose()


async def test_postgres_drop_revision_downgrade_recreates_todos(
    migrated_postgres_url,
):
    engine = make_engine(migrated_postgres_url)
    try:
        async with engine.begin() as connection:
            config = Config(ALEMBIC_INI)
            config.attributes["configure_logging"] = False
            config.attributes["connection"] = connection.sync_connection
            await connection.run_sync(lambda _: command.downgrade(config, "base"))
            await connection.run_sync(lambda _: command.upgrade(config, TODOS_REVISION))
            created = await connection.run_sync(_todos_shape)
            await connection.run_sync(lambda _: command.upgrade(config, "head"))

            await connection.run_sync(
                lambda _: command.downgrade(config, SESSIONS_REVISION)
            )

            assert await connection.run_sync(_todos_shape) == created
            assert created[1:] == (["id"], "pk_todos")
            await connection.run_sync(lambda _: command.upgrade(config, "head"))
            assert await connection.run_sync(_tables) == {
                "alembic_version",
                *APP_TABLES,
            }
    finally:
        await engine.dispose()
