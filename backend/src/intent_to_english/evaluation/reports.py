"""Stable JSON and Markdown reports over recorded evaluation attempts."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, NotRequired, TypedDict

from intent_to_english.core.models import CallOutcome, sum_reported_costs

if TYPE_CHECKING:
    from collections.abc import Iterable

    from intent_to_english.core.models import CallAttempt
    from intent_to_english.evaluation.cases import Case

type CheckValues = dict[str, bool | None]


class Rate(TypedDict):
    """Only applicable, observed values enter a rate's denominator."""

    passed: int
    total: int
    rate: float | None


class Comparison(TypedDict):
    """First-attempt and post-repair rates stay separate."""

    first: Rate
    final: Rate


class ExpectedResult(TypedDict):
    """One expectation result, preserving duplicates within a case."""

    kind: str
    passed: bool | None


class MetadataData(TypedDict):
    """The machine-readable source and configuration of one run."""

    date: str
    coach_model: str
    partner_model: str
    commit: str
    dirty: bool
    coach_reasoning_effort: str | None
    partner_reasoning_effort: str | None


class CaseData(TypedDict):
    """Case decisions and, on a failed final expectation, the parsed model output."""

    case: str
    source: str
    task: str
    error: str | None
    error_status: int | None
    outcomes: list[str]
    checks_first: CheckValues
    checks_final: CheckValues
    expectations_first: list[ExpectedResult]
    expectations_final: list[ExpectedResult]
    final_output: NotRequired[dict[str, object]]


class TaskData(TypedDict):
    """Accounting includes every actual request, including repairs and errors."""

    calls: int
    outcomes: dict[str, int]
    providers: list[str]
    models: list[str]
    cost_credits: str | None
    latency_p50_ms: int
    latency_p95_ms: int


class ReportData(TypedDict):
    """The public JSON report format."""

    metadata: MetadataData
    cases: list[CaseData]
    checks: dict[str, Comparison]
    expectations: dict[str, Comparison]
    tasks: dict[str, TaskData]


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """The UTC date, selected models, their efforts and source revision of one run."""

    date: str
    coach_model: str
    partner_model: str
    commit: str
    dirty: bool
    coach_reasoning_effort: str | None = None
    partner_reasoning_effort: str | None = None


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Decisions and call accounting retained for one case."""

    case: Case
    attempts: tuple[CallAttempt, ...]
    checks_first: CheckValues
    checks_final: CheckValues
    expectations_first: tuple[ExpectedResult, ...]
    expectations_final: tuple[ExpectedResult, ...]
    error: str | None
    error_status: int | None
    final_output: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class Report:
    """Render one run without changing its observations or billing again."""

    metadata: RunMetadata
    results: tuple[CaseResult, ...]

    def as_dict(self) -> ReportData:
        """Return the typed JSON boundary; Decimal credits stay decimal strings."""
        grouped: dict[str, list[CallAttempt]] = defaultdict(list)
        cases: list[CaseData] = []
        for result in self.results:
            task = result.case.task
            for attempt in result.attempts:
                grouped[f"{attempt.role.value}.{task.value}"].append(attempt)
            case_data = CaseData(
                case=result.case.path.stem,
                source=result.case.source,
                task=f"{result.attempts[0].role.value}.{task.value}",
                error=result.error,
                error_status=result.error_status,
                outcomes=[attempt.outcome.value for attempt in result.attempts],
                checks_first=dict(result.checks_first),
                checks_final=dict(result.checks_final),
                expectations_first=list(result.expectations_first),
                expectations_final=list(result.expectations_final),
            )
            if result.final_output is not None:
                case_data["final_output"] = result.final_output
            cases.append(case_data)
        meta = self.metadata
        return ReportData(
            metadata=MetadataData(
                date=meta.date,
                coach_model=meta.coach_model,
                partner_model=meta.partner_model,
                commit=meta.commit,
                dirty=meta.dirty,
                coach_reasoning_effort=meta.coach_reasoning_effort,
                partner_reasoning_effort=meta.partner_reasoning_effort,
            ),
            cases=cases,
            checks=_comparisons(cases, expectations=False),
            expectations=_comparisons(cases, expectations=True),
            tasks={
                task: _task_data(attempts) for task, attempts in sorted(grouped.items())
            },
        )

    def render_json(self) -> str:
        """Serialize decisions and selected parsed outputs without provider diagnostics."""
        return (
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )

    def render_markdown(self) -> str:
        """Render checks, expectations, task accounting and individual outcomes."""
        data = self.as_dict()
        meta = data["metadata"]
        lines = [
            "# Model evaluation",
            "",
            f"UTC date: {_cell(meta['date'])}",
            f"Coach: `{_cell(meta['coach_model'])}`; Partner: `{_cell(meta['partner_model'])}`",
            f"Reasoning effort: Coach {_effort(meta['coach_reasoning_effort'])}; Partner {_effort(meta['partner_reasoning_effort'])}",
            f"Commit: `{_cell(meta['commit'])}`; dirty: {str(meta['dirty']).lower()}",
            "",
            "Rates include applicable observed outputs only. A parse failure fails schema; content checks and expectations are N/A. Provider failures are N/A for output quality and remain counted in outcomes. Final means the last actual attempt, including a failed repair. Task cost is empty if any attempt has no reported cost.",
            "",
        ]
        for heading, key in (("Checks", "checks"), ("Expectations", "expectations")):
            comparisons = data["checks"] if key == "checks" else data["expectations"]
            lines.extend(
                [f"## {heading}", "", "| Rule | First | Final |", "| --- | --- | --- |"]
            )
            lines.extend(
                f"| {_cell(name)} | {_rate_cell(item['first'])} | {_rate_cell(item['final'])} |"
                for name, item in comparisons.items()
            )
            lines.append("")
        lines.extend(
            [
                "## Tasks",
                "",
                self.task_table(),
                "",
                "## Cases",
                "",
                "| Case | Task | Outcomes | Error |",
                "| --- | --- | --- | --- |",
            ]
        )
        lines.extend(
            f"| {_cell(case['case'])} | {_cell(case['task'])} | {', '.join(case['outcomes'])} | {_cell(_error(case))} |"
            for case in data["cases"]
        )
        return "\n".join(lines) + "\n"

    def task_table(self) -> str:
        """The same accounting table appears in the report and README summary."""
        outcomes = [item.value for item in CallOutcome]
        lines = [
            "| Task | Calls | "
            + " | ".join(outcomes)
            + " | Cost (credits) | p50 (ms) | p95 (ms) |",
            "| --- | --- | "
            + " | ".join("---" for _ in outcomes)
            + " | --- | --- | --- |",
        ]
        for task, item in self.as_dict()["tasks"].items():
            values = " | ".join(str(item["outcomes"][name]) for name in outcomes)
            lines.append(
                f"| {_cell(task)} | {item['calls']} | {values} | {item['cost_credits'] or ''} | {item['latency_p50_ms']} | {item['latency_p95_ms']} |"
            )
        return "\n".join(lines)


def _comparisons(cases: list[CaseData], *, expectations: bool) -> dict[str, Comparison]:
    first: dict[str, list[bool | None]] = defaultdict(list)
    final: dict[str, list[bool | None]] = defaultdict(list)
    for case in cases:
        if expectations:
            for item in case["expectations_first"]:
                first[item["kind"]].append(item["passed"])
            for item in case["expectations_final"]:
                final[item["kind"]].append(item["passed"])
        else:
            for key, value in case["checks_first"].items():
                first[key].append(value)
            for key, value in case["checks_final"].items():
                final[key].append(value)
    return {
        key: Comparison(first=_rate(first[key]), final=_rate(final[key]))
        for key in sorted(first.keys() | final.keys())
    }


def _rate(values: Iterable[bool | None]) -> Rate:
    observed = [value for value in values if value is not None]
    passed, total = sum(observed), len(observed)
    return Rate(passed=passed, total=total, rate=passed / total if total else None)


def _task_data(attempts: list[CallAttempt]) -> TaskData:
    latencies = sorted(item.usage.latency_ms for item in attempts)
    costs = [item.usage.cost for item in attempts]
    cost = (
        sum_reported_costs(costs) if all(value is not None for value in costs) else None
    )
    return TaskData(
        calls=len(attempts),
        outcomes={
            kind.value: sum(item.outcome is kind for item in attempts)
            for kind in CallOutcome
        },
        providers=sorted({item.usage.provider for item in attempts}),
        models=sorted({item.usage.model for item in attempts}),
        cost_credits=str(cost) if cost is not None else None,
        latency_p50_ms=latencies[ceil(len(latencies) * 0.50) - 1],
        latency_p95_ms=latencies[ceil(len(latencies) * 0.95) - 1],
    )


def _rate_cell(rate: Rate) -> str:
    return (
        f"{rate['passed']}/{rate['total']} ({rate['rate']:.1%})"
        if rate["rate"] is not None
        else "N/A"
    )


def _effort(effort: str | None) -> str:
    """An unset effort sends none, so the provider's default thinking applied."""
    return "provider default" if effort is None else f"`{_cell(effort)}`"


def _error(case: CaseData) -> str:
    """Name the provider's HTTP status beside the stable code when one was returned."""
    if case["error"] is None:
        return ""
    if case["error_status"] is None:
        return case["error"]
    return f"{case['error']} (HTTP {case['error_status']})"


def _cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")
