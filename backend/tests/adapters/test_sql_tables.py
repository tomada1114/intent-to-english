"""What the SQL schema stores, below what the repository contract can see."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import bindparam, insert, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import StatementError
from sqlalchemy.schema import CreateIndex

from intent_to_english.adapters.sql.engine import make_engine
from intent_to_english.adapters.sql.session_repository import SqlSessionRepository
from intent_to_english.adapters.sql.tables import UtcDateTime, metadata, sessions
from intent_to_english.core import coaching, models
from intent_to_english.core.errors import SessionNotFoundError

pytestmark = pytest.mark.anyio

TOKYO = timezone(timedelta(hours=9))
SESSION_ID = UUID("01900000-0000-7000-8000-000000000001")


@pytest.fixture
async def engine(tmp_path):
    built = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
    async with built.begin() as connection:
        await connection.run_sync(metadata.create_all)
    yield built
    await built.dispose()


def _row(started_at: datetime) -> dict[str, object]:
    return {
        "id": SESSION_ID,
        "started_at": started_at,
        "status": "in_progress",
        "stage": "opening",
        "turn_index": 1,
        "turn_state": {},
        "version": 0,
        "finished_replies": 0,
    }


async def test_utc_datetime_aware_value_is_stored_as_naive_utc(engine):
    async with engine.begin() as connection:
        await connection.execute(
            insert(sessions), _row(datetime(2026, 1, 2, 21, 4, 5, tzinfo=TOKYO))
        )
        stored = await connection.scalar(text("SELECT started_at FROM sessions"))

    assert stored == "2026-01-02 12:04:05.000000"


async def test_utc_datetime_read_back_is_the_same_instant_in_utc(engine):
    written = datetime(2026, 1, 2, 21, 4, 5, tzinfo=TOKYO)
    async with engine.begin() as connection:
        await connection.execute(insert(sessions), _row(written))
        read = await connection.scalar(select(sessions.c.started_at))

    assert read == written
    assert read.tzinfo is UTC


async def test_utc_datetime_naive_value_raises_and_stores_nothing(engine):
    naive = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC).replace(tzinfo=None)

    with pytest.raises(StatementError, match=r"must be timezone-aware"):
        async with engine.begin() as connection:
            await connection.execute(insert(sessions), _row(naive))

    async with engine.connect() as connection:
        assert await connection.scalar(select(sessions.c.id)) is None


async def test_utc_datetime_none_passes_through_both_ways(engine):
    # A nullable column of this type, ended_at, stores and reads NULL.
    async with engine.begin() as connection:
        await connection.execute(
            insert(sessions),
            _row(datetime(2026, 1, 2, tzinfo=UTC)) | {"ended_at": None},
        )
        read = await connection.scalar(select(sessions.c.ended_at))
        unbound = await connection.scalar(
            select(bindparam("nothing", None, type_=UtcDateTime))
        )

    assert read is None
    assert unbound is None


def test_metadata_names_constraints_by_the_naming_convention():
    assert sessions.primary_key.name == "pk_sessions"


def test_session_tables_have_the_documented_columns_and_nullability():
    expected = {
        "sessions": (
            "id started_at ended_at status stage turn_index turn_state version finished_replies opener wrap_up",
            {"ended_at", "opener", "wrap_up"},
        ),
        "timeline_entries": (
            "id session_id seq turn_index kind payload created_at",
            set(),
        ),
        "submissions": (
            "id session_id base_version action input status failure_code boot_id created_at finished_at",
            {"failure_code", "finished_at"},
        ),
        "model_calls": (
            "id session_id submission_id turn_index role task attempt provider model input_tokens output_tokens cost latency_ms outcome violations created_at",
            {"input_tokens", "output_tokens", "cost"},
        ),
    }
    for name, (columns, nullable) in expected.items():
        assert name in metadata.tables
        table = metadata.tables[name]
        assert set(table.c.keys()) == set(columns.split())
        assert {column.name for column in table.c if column.nullable} == nullable
        assert table.primary_key.name == f"pk_{name}"
        for column in table.c:
            if column.name.endswith("_at"):
                assert isinstance(column.type, UtcDateTime)


@pytest.mark.parametrize(
    "dialect", [sqlite.dialect(), postgresql.dialect()], ids=["sqlite", "postgresql"]
)
def test_submission_active_index_is_partial_on_both_dialects(dialect):
    assert "submissions" in metadata.tables
    indexes = metadata.tables["submissions"].indexes
    index = next(index for index in indexes if index.unique)
    ddl = str(CreateIndex(index).compile(dialect=dialect))
    assert "UNIQUE INDEX uq_submissions_session_id_base_version_active" in ddl
    assert "(session_id, base_version)" in ddl
    assert "WHERE status IN ('pending', 'completed')" in ddl


async def test_wrap_up_due_is_sql_null_and_empty_wrap_up_is_json(
    engine, fixed_now, nth_id
):
    repository = SqlSessionRepository(engine)
    await repository.create(models.Session(nth_id(1), fixed_now))
    await repository.create(
        models.Session(nth_id(2), fixed_now, wrap_up=coaching.WrapUp(()))
    )
    async with engine.connect() as connection:
        nulls = await connection.scalar(
            text("SELECT count(*) FROM sessions WHERE wrap_up IS NULL")
        )
        ready = await connection.scalar(
            text("SELECT wrap_up FROM sessions WHERE wrap_up IS NOT NULL")
        )
    assert nulls == 1
    assert ready == '{"items": []}'


async def test_session_survives_disposing_and_reopening_the_engine(
    engine, fixed_now, nth_id
):
    expected = models.Session(nth_id(1), fixed_now, opener="Hi!")
    await SqlSessionRepository(engine).create(expected)
    await engine.dispose()
    reopened = make_engine(str(engine.url))
    try:
        assert (
            await SqlSessionRepository(reopened).get(expected.id)
        ).session == expected
    finally:
        await reopened.dispose()


async def test_old_json_payloads_use_defaults_for_added_optional_fields(
    engine, fixed_now, nth_id
):
    repository = SqlSessionRepository(engine)
    session = models.Session(nth_id(1), fixed_now)
    await repository.create(session)
    async with engine.begin() as connection:
        await connection.execute(
            metadata.tables["sessions"].update().values(turn_state={})
        )
        await connection.execute(
            insert(metadata.tables["timeline_entries"]),
            {
                "id": nth_id(2),
                "session_id": session.id,
                "seq": 1,
                "turn_index": 1,
                "kind": "intent",
                "payload": {"text": "日本語"},
                "created_at": fixed_now,
            },
        )
    stored = await repository.get(session.id)
    assert stored.session.turn_state == models.TurnState()
    assert stored.entries[0].payload == models.IntentPayload("日本語", False)


async def test_sql_operations_reject_an_unknown_session_before_writing(
    engine, fixed_now, nth_id
):
    repository = SqlSessionRepository(engine)
    session = models.Session(nth_id(1), fixed_now)
    submission = models.Submission(
        nth_id(2),
        session.id,
        0,
        models.Action.OPEN,
        models.NoInput(),
        nth_id(99),
        fixed_now,
    )
    for operation in (
        lambda: repository.get(session.id),
        lambda: repository.begin_submission(
            submission, frozenset({models.Stage.OPENING}), fixed_now
        ),
        lambda: repository.finish_submission(submission.id, session, (), fixed_now),
        lambda: repository.cancel_submission(session.id, 0, fixed_now),
    ):
        with pytest.raises(SessionNotFoundError, match="not found"):
            await operation()
    assert (await repository.list_page(None, 20)).items == ()
