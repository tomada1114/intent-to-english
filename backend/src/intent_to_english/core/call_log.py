"""Pure summaries of recorded model calls, independent of storage and entry points."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING

from intent_to_english.core.models import CallOutcome, sum_reported_costs

if TYPE_CHECKING:
    from collections.abc import Iterable
    from decimal import Decimal

    from intent_to_english.core.models import ModelCallRecord, ModelRole, ModelTask

OUTCOMES = (
    CallOutcome.OK,
    CallOutcome.REPAIRED,
    CallOutcome.INVALID_OUTPUT,
    CallOutcome.TIMEOUT,
    CallOutcome.RATE_LIMITED,
    CallOutcome.PROVIDER_ERROR,
)


@dataclass(frozen=True, slots=True)
class SummaryRow:
    """One immutable group with missing accounting kept separate from zero."""

    role: ModelRole
    model: str
    task: ModelTask
    calls: int
    outcomes: tuple[tuple[CallOutcome, int], ...]
    input_tokens: int | None
    output_tokens: int | None
    cost: Decimal | None
    latency_p50_ms: int
    latency_p95_ms: int
    http_statuses: tuple[tuple[CallOutcome, int, int], ...] = ()

    def __post_init__(self) -> None:
        """Reject a summary whose counts or percentiles cannot describe calls."""
        if self.calls < 1 or sum(count for _, count in self.outcomes) != self.calls:
            message = "Summary outcome counts must add up to its calls"
            raise ValueError(message)
        if self.latency_p50_ms < 0 or self.latency_p95_ms < self.latency_p50_ms:
            message = "Summary percentiles must be nonnegative and ordered"
            raise ValueError(message)


def summarize(records: Iterable[ModelCallRecord]) -> tuple[SummaryRow, ...]:
    """Group calls by role, model and task with provider-reported accounting."""
    grouped: dict[tuple[ModelRole, str, ModelTask], list[ModelCallRecord]] = (
        defaultdict(list)
    )
    for record in records:
        call = record.call
        grouped[call.role, call.usage.model, call.task].append(record)
    rows = []
    for (role, model, task), group in sorted(grouped.items()):
        latencies = sorted(record.call.usage.latency_ms for record in group)
        statuses = Counter(
            (record.call.outcome, record.call.status)
            for record in group
            if record.call.status is not None
        )
        rows.append(
            SummaryRow(
                role,
                model,
                task,
                len(group),
                tuple(
                    (kind, sum(record.call.outcome is kind for record in group))
                    for kind in OUTCOMES
                ),
                _tokens(record.call.usage.input_tokens for record in group),
                _tokens(record.call.usage.output_tokens for record in group),
                sum_reported_costs(record.call.usage.cost for record in group),
                latencies[ceil(len(group) * 0.50) - 1],
                latencies[ceil(len(group) * 0.95) - 1],
                tuple(
                    (kind, status, count)
                    for (kind, status), count in sorted(statuses.items())
                ),
            )
        )
    return tuple(rows)


def _tokens(values: Iterable[int | None]) -> int | None:
    reported = [value for value in values if value is not None]
    return sum(reported) if reported else None
