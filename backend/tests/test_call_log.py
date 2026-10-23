from __future__ import annotations

import asyncio
import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import make_url

from intent_to_english.adapters.sql.call_log import read_calls
from intent_to_english.call_log import main
from intent_to_english.core import models as m


def test_main_prints_empty_migrated_log(migrated_sqlite_url, capsys):
    assert main([]) == 0
    captured = capsys.readouterr()
    assert captured.out == "No model calls recorded.\n"
    assert captured.err == ""


def test_main_uses_default_database_and_prints_grouped_accounting(
    monkeypatch, capsys, make_model_call
):
    records = []
    seen = []
    for task, latency, outcome in [
        (m.ModelTask.REPLY, 900, m.CallOutcome.OK),
        (m.ModelTask.REPLY, 1200, m.CallOutcome.OK),
        (m.ModelTask.REPLY, 2000, m.CallOutcome.OK),
        (m.ModelTask.FEEDBACK, 20, m.CallOutcome.INVALID_OUTPUT),
        (m.ModelTask.FEEDBACK, 40, m.CallOutcome.REPAIRED),
    ]:
        record = make_model_call()
        role = m.ModelRole.PARTNER if task is m.ModelTask.REPLY else m.ModelRole.COACH
        call = replace(
            record.call,
            role=role,
            task=task,
            outcome=outcome,
            usage=m.Usage(
                "private-provider", "test/model", 10, 5, Decimal("0.10"), latency
            ),
        )
        records.append(replace(record, call=call))

    async def read(url, session_id=None, since=None):
        seen.append(url)
        return records

    monkeypatch.setattr("intent_to_english.call_log.read_calls", read)

    assert main([]) == 0

    output = capsys.readouterr().out
    assert seen == ["sqlite+aiosqlite:///./var/dev.db"]
    assert (
        "partner | test/model | reply | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 30 | 15 | 0.30 | 1200 | 2000"
        in output
    )
    assert (
        "coach | test/model | feedback | 2 | 0 | 1 | 1 | 0 | 0 | 0 | 20 | 10 | 0.20 | 20 | 40"
        in output
    )
    assert "private-provider" not in output


def test_invalid_database_configuration_is_not_echoed(monkeypatch, capsys):
    monkeypatch.setenv(
        "INTENT_TO_ENGLISH_DATABASE_URL", "bad://user:private-password@host/database"
    )
    assert main([]) == 1
    error = capsys.readouterr().err
    assert "just backend db-upgrade" in error
    assert "private-password" not in error


def test_connection_failure_is_actionable_without_exposing_driver_details(
    monkeypatch, capsys
):
    async def read(url, session_id=None, since=None):
        message = "private-driver-details"
        raise OSError(message)

    monkeypatch.setattr("intent_to_english.call_log.read_calls", read)
    assert main([]) == 1
    error = capsys.readouterr().err
    assert "just backend db-upgrade" in error
    assert "private-driver-details" not in error


def test_main_summarizes_without_changing_database_or_leaking_inputs(
    migrated_sqlite_url, seed_call_log, capsys, monkeypatch
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-key-never-print")
    asyncio.run(seed_call_log(migrated_sqlite_url))
    path = Path(make_url(migrated_sqlite_url).database or "")
    before = path.read_bytes()

    assert main([]) == 0

    captured = capsys.readouterr()
    assert "cost (credits)" in captured.out
    assert (
        "partner | test/model | reply | 4 | 4 | 0 | 0 | 0 | 0 | 0 | — | — | — | 0 | 0"
        in captured.out
    )
    assert "prompt" not in captured.out
    assert "submission" not in captured.out
    assert "private-key-never-print" not in captured.out
    assert captured.err == ""
    assert path.read_bytes() == before
    assert len(asyncio.run(read_calls(migrated_sqlite_url))) == 4


@pytest.mark.parametrize(
    "arguments",
    [["--session", "not-a-uuid"], ["--since", "yesterday"], ["--since", "2026-02-30"]],
    ids=["uuid", "date", "impossible-date"],
)
def test_invalid_filter_is_usage_error(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_no_matching_session_prints_empty(
    migrated_sqlite_url, seed_call_log, nth_id, capsys
):
    asyncio.run(seed_call_log(migrated_sqlite_url))
    assert main(["--session", str(nth_id(777))]) == 0
    assert capsys.readouterr().out == "No model calls recorded.\n"


@pytest.mark.parametrize("exists", [False, True], ids=["missing", "unmigrated"])
def test_missing_or_unmigrated_database_has_safe_actionable_error(
    tmp_path, monkeypatch, capsys, exists
):
    path = tmp_path / "empty.db"
    if exists:
        path.touch()
    monkeypatch.setenv("INTENT_TO_ENGLISH_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    assert main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "just backend db-upgrade" in captured.err
    assert path.exists() is exists
    if exists:
        assert path.read_bytes() == b""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-17", datetime(2026, 1, 17, 7, tzinfo=UTC)),
        ("2026-07-17T00:00:00", datetime(2026, 7, 17, 6, tzinfo=UTC)),
        ("2026-07-17T03:00:00+09:00", datetime(2026, 7, 16, 18, tzinfo=UTC)),
    ],
    ids=["local-midnight-winter", "local-summer-offset", "explicit-offset"],
)
def test_since_uses_historical_local_timezone(monkeypatch, capsys, value, expected):
    seen = []

    async def read(url, session_id=None, since=None):
        seen.append(since)
        return ()

    monkeypatch.setattr("intent_to_english.call_log.read_calls", read)
    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "America/Denver")
    time.tzset()
    try:
        assert main(["--since", value]) == 0
        assert seen == [expected]
    finally:
        if previous is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", previous)
        time.tzset()


def test_main_shows_http_status_breakdowns_in_existing_outcome_columns(
    monkeypatch, capsys, make_model_call
):
    records = []
    for outcome, status in [
        (m.CallOutcome.PROVIDER_ERROR, 400),
        (m.CallOutcome.PROVIDER_ERROR, 400),
        (m.CallOutcome.PROVIDER_ERROR, 503),
        (m.CallOutcome.PROVIDER_ERROR, None),
        (m.CallOutcome.RATE_LIMITED, 429),
        (m.CallOutcome.TIMEOUT, None),
        (m.CallOutcome.OK, None),
    ]:
        record = make_model_call()
        records.append(
            replace(record, call=replace(record.call, outcome=outcome, status=status))
        )

    async def read(_url, _session=None, _since=None):
        return records

    monkeypatch.setattr("intent_to_english.call_log.read_calls", read)

    assert main([]) == 0

    captured = capsys.readouterr()
    assert (
        "partner | test/model | reply | 7 | 1 | 0 | 0 | 1 | 1 (429: 1) | 4 (400: 2, 503: 1) |"
        in captured.out
    )
    assert "provider_error | input tokens" in captured.out
    assert captured.err == ""
