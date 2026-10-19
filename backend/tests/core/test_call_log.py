from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from intent_to_english.core import models as m
from intent_to_english.core.call_log import summarize


def test_empty_log_has_no_summary_rows():
    assert summarize(()) == ()


def test_summary_groups_and_sorts_role_model_and_task(make_model_call):
    records = []
    keys = [
        (m.ModelRole.PARTNER, "z-model", m.ModelTask.REPLY),
        (m.ModelRole.COACH, "b-model", m.ModelTask.FEEDBACK),
        (m.ModelRole.PARTNER, "a-model", m.ModelTask.RESTATE),
        (m.ModelRole.PARTNER, "a-model", m.ModelTask.OPEN),
    ]
    for role, model, task in keys:
        record = make_model_call()
        call = replace(
            record.call,
            role=role,
            task=task,
            usage=replace(record.call.usage, model=model),
        )
        records.append(replace(record, call=call))

    rows = summarize(records)

    assert [(row.role, row.model, row.task) for row in rows] == sorted(keys)
    assert all(row.calls == 1 for row in rows)


def test_every_outcome_and_repair_is_counted_as_its_own_call(make_model_call):
    records = []
    for outcome in m.CallOutcome:
        record = make_model_call()
        records.append(
            replace(
                record,
                call=replace(
                    record.call,
                    outcome=outcome,
                    attempt=2 if outcome is m.CallOutcome.REPAIRED else 1,
                ),
            )
        )

    (row,) = summarize(records)

    assert row.calls == 6
    assert dict(row.outcomes) == dict.fromkeys(m.CallOutcome, 1)


@pytest.mark.parametrize(
    ("count", "p50", "p95"), [(1, 1, 1), (20, 10, 19)], ids=["one-call", "nearest-rank"]
)
def test_summary_latency_uses_nearest_rank(make_model_call, count, p50, p95):
    records = []
    for latency in range(1, count + 1):
        record = make_model_call()
        records.append(
            replace(
                record,
                call=replace(
                    record.call, usage=replace(record.call.usage, latency_ms=latency)
                ),
            )
        )

    (row,) = summarize(records)

    assert row.latency_p50_ms == p50
    assert row.latency_p95_ms == p95


def test_missing_accounting_is_distinct_from_reported_zero_and_sums_exactly(
    make_model_call,
):
    records = []
    for inputs, outputs, cost in [
        (None, None, None),
        (0, 0, Decimal(0)),
        (5, None, Decimal("0.123456789012345678901234567890")),
    ]:
        record = make_model_call()
        usage = replace(
            record.call.usage, input_tokens=inputs, output_tokens=outputs, cost=cost
        )
        records.append(replace(record, call=replace(record.call, usage=usage)))

    (row,) = summarize(records)

    assert row.input_tokens == 5
    assert row.output_tokens == 0
    assert row.cost == Decimal("0.123456789012345678901234567890")
    (empty,) = summarize((make_model_call(),))
    assert empty.input_tokens is None
    assert empty.output_tokens is None
    assert empty.cost is None
