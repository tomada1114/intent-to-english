from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import aiosqlite
import pytest
from sqlalchemy import make_url, text, update
from sqlalchemy.exc import DBAPIError

from intent_to_english.adapters.sql.call_log import CallLogReadError, read_calls
from intent_to_english.adapters.sql.engine import make_engine, make_read_engine
from intent_to_english.adapters.sql.tables import metadata, model_calls
from intent_to_english.core.models import CallOutcome

pytestmark = pytest.mark.anyio


async def test_sql_reader_restores_records_and_applies_both_inclusive_filters(
    migrated_sqlite_url, seed_call_log, nth_id, fixed_now
):
    records = await seed_call_log(migrated_sqlite_url)
    path = Path(make_url(migrated_sqlite_url).database or "")
    before = path.read_bytes()

    assert await read_calls(migrated_sqlite_url) == tuple(
        sorted(records, key=lambda record: (record.created_at, record.id))
    )
    assert await read_calls(migrated_sqlite_url, nth_id(100)) == records[:2]
    assert await read_calls(
        migrated_sqlite_url, since=fixed_now + timedelta(seconds=1)
    ) == (records[1], records[3])
    assert await read_calls(
        migrated_sqlite_url, nth_id(200), fixed_now + timedelta(seconds=1)
    ) == (records[3],)
    assert await read_calls(migrated_sqlite_url, nth_id(777)) == ()
    assert path.read_bytes() == before


async def test_reader_missing_database_creates_no_file(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(CallLogReadError, match="just backend db-upgrade"):
        await read_calls(f"sqlite+aiosqlite:///{path}")
    assert not path.exists()


async def test_missing_sqlite_file_is_rejected_before_starting_driver(
    tmp_path, monkeypatch
):
    def connect(*args, **kwargs):
        message = "A missing database must not start a driver worker"
        raise AssertionError(message)

    monkeypatch.setattr(aiosqlite, "connect", connect)
    with pytest.raises(CallLogReadError, match="just backend db-upgrade"):
        await read_calls(f"sqlite+aiosqlite:///{tmp_path / 'missing.db'}")


async def test_reader_existing_unmigrated_database_is_unchanged(tmp_path):
    path = tmp_path / "unmigrated.db"
    path.touch()
    with pytest.raises(CallLogReadError, match="just backend db-upgrade"):
        await read_calls(f"sqlite+aiosqlite:///{path}")
    assert path.read_bytes() == b""


async def test_sqlite_read_engine_refuses_writes_and_escapes_native_uri(
    migrated_sqlite_url, tmp_path
):
    original = Path(make_url(migrated_sqlite_url).database or "")
    copied = tmp_path / "call log #1.db"
    copied.write_bytes(original.read_bytes())
    for url in (
        f"sqlite+aiosqlite:///{copied}",
        f"sqlite+aiosqlite:///file:{quote(str(copied), safe='/')}?uri=true&mode=rw",
    ):
        engine = make_read_engine(url)
        try:
            async with engine.connect() as connection:
                assert await connection.scalar(text("PRAGMA query_only")) == 1
                with pytest.raises(DBAPIError, match="readonly"):
                    await connection.execute(text("DELETE FROM model_calls"))
        finally:
            await engine.dispose()
    assert copied.read_bytes() == original.read_bytes()


async def test_sqlite_literal_file_prefix_is_not_treated_as_a_uri(
    migrated_sqlite_url, tmp_path, monkeypatch
):
    original = Path(make_url(migrated_sqlite_url).database or "")
    copied = tmp_path / "file:literal.db"
    copied.write_bytes(original.read_bytes())
    monkeypatch.chdir(tmp_path)
    assert await read_calls("sqlite+aiosqlite:///file:literal.db") == ()
    assert not (tmp_path / "literal.db").exists()


@pytest.mark.parametrize(
    "options",
    ["uri=false&uri=false", "uri=true&uri=true", "uri=%20true%20"],
    ids=["repeated-false", "repeated-true", "whitespace-true"],
)
async def test_native_uri_flags_match_application_driver_coercion(
    migrated_sqlite_url, seed_call_log, options
):
    records = await seed_call_log(migrated_sqlite_url)
    path = Path(make_url(migrated_sqlite_url).database or "")
    native_url = f"sqlite+aiosqlite:///file:{quote(str(path), safe='/')}?{options}"
    writer = make_engine(native_url)
    try:
        async with writer.connect() as connection:
            assert (
                await connection.scalar(text("SELECT count(*) FROM model_calls")) == 4
            )
    finally:
        await writer.dispose()

    assert await read_calls(native_url) == tuple(
        sorted(records, key=lambda record: (record.created_at, record.id))
    )


@pytest.mark.postgres
async def test_postgres_reader_uses_typed_filters_and_read_only_transaction(
    migrated_postgres_url, seed_call_log, fixed_now, nth_id
):
    writer = make_engine(migrated_postgres_url)
    try:
        async with writer.begin() as connection:
            for table in (
                "submission_cancellations",
                "model_calls",
                "submissions",
                "timeline_entries",
                "sessions",
            ):
                await connection.execute(metadata.tables[table].delete())
        records = await seed_call_log(migrated_postgres_url)
        assert (
            await read_calls(migrated_postgres_url, nth_id(100), fixed_now)
            == records[:2]
        )
        assert len(await read_calls(migrated_postgres_url)) == 4
        reader = make_read_engine(migrated_postgres_url)
        try:
            async with reader.connect() as connection:
                assert (
                    await connection.scalar(text("SHOW transaction_read_only")) == "on"
                )
                with pytest.raises(DBAPIError, match="read-only"):
                    await connection.execute(text("DELETE FROM model_calls"))
        finally:
            await reader.dispose()
    finally:
        await writer.dispose()


async def test_sql_reader_restores_provider_http_status(
    migrated_sqlite_url, seed_call_log
):
    records = await seed_call_log(migrated_sqlite_url)
    engine = make_engine(migrated_sqlite_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                update(model_calls)
                .where(model_calls.c.id == records[0].id)
                .values(status=400, outcome="provider_error")
            )
    finally:
        await engine.dispose()

    restored = await read_calls(migrated_sqlite_url)

    expected = replace(
        records[0],
        call=replace(records[0].call, status=400, outcome=CallOutcome.PROVIDER_ERROR),
    )
    assert expected in restored
    assert len(restored) == 4
