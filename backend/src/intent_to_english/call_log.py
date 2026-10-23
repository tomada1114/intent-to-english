"""Summarize model calls without billing or changing the practice database.

Usage: python -m intent_to_english.call_log [--session UUID] [--since WHEN]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from intent_to_english.adapters.sql.call_log import CallLogReadError, read_calls
from intent_to_english.core.call_log import summarize
from intent_to_english.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from intent_to_english.core.call_log import SummaryRow
    from intent_to_english.core.models import CallOutcome


def _since(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError as error:
        message = "expected YYYY-MM-DD or an ISO 8601 datetime"
        raise argparse.ArgumentTypeError(message) from error


def _table(rows: Sequence[SummaryRow]) -> str:
    headers = "role | model | task | calls | ok | repaired | invalid_output | timeout | rate_limited | provider_error | input tokens | output tokens | cost (credits) | p50 (ms) | p95 (ms)"
    lines = [headers]
    for row in rows:
        values = (
            row.role.value,
            row.model,
            row.task.value,
            row.calls,
            *(_outcome_cell(row, kind, count) for kind, count in row.outcomes),
            row.input_tokens,
            row.output_tokens,
            row.cost,
            row.latency_p50_ms,
            row.latency_p95_ms,
        )
        lines.append(
            " | ".join("—" if value is None else str(value) for value in values)
        )
    return "\n".join(lines) + "\n"


def _outcome_cell(row: SummaryRow, kind: CallOutcome, count: int) -> str:
    """Keep outcome totals while showing the subset with a reported HTTP status."""
    statuses = ", ".join(
        f"{status}: {number}"
        for outcome, status, number in row.http_statuses
        if outcome is kind
    )
    return f"{count} ({statuses})" if statuses else str(count)


def main(argv: Sequence[str] | None = None) -> int:
    """Print recorded calls grouped by role, model and task."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=UUID)
    parser.add_argument("--since", type=_since)
    arguments = parser.parse_args(argv)
    session: UUID | None = arguments.session
    since: datetime | None = arguments.since
    try:
        url = Settings().database_url or "sqlite+aiosqlite:///./var/dev.db"
        records = asyncio.run(read_calls(url, session, since))
    except CallLogReadError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    except ValueError, RuntimeError, OSError:
        sys.stderr.write(
            "Cannot read the model call log. Check the database URL, the 'postgres' extra if needed, and run `just backend db-upgrade`.\n"
        )
        return 1
    rows = summarize(records)
    sys.stdout.write(_table(rows) if rows else "No model calls recorded.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
