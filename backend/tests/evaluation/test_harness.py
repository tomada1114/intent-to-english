from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from intent_to_english.adapters.models.fixed import FixedCoachModel, FixedPartnerModel
from intent_to_english.core import models as m
from intent_to_english.core import partner
from intent_to_english.core.errors import ModelTimeoutError, ModelUnavailableError
from intent_to_english.evaluation.__main__ import replace_summary
from intent_to_english.evaluation.cases import Case, load_cases
from intent_to_english.evaluation.expectations import Expectation
from intent_to_english.evaluation.harness import run_cases
from intent_to_english.evaluation.reports import RunMetadata

pytestmark = pytest.mark.anyio
METADATA = RunMetadata("2026-10-19", "coach/model", "partner/model", "abc123", False)


def opener(name="01-opener"):
    return Case(
        Path(f"{name}.toml"),
        m.ModelTask.OPEN,
        "requirements 3.11",
        partner.OpenRequest("Hi!"),
        {},
        (Expectation("differs_from", text="Hi!"),),
    )


async def test_checks_and_expectations_capture_both_real_attempts_without_double_call():
    class RepairingPartner(FixedPartnerModel):
        def __init__(self):
            self.repairs = []

        async def open(self, request, repair=None):
            del request
            self.repairs.append(repair)
            return m.Parsed(
                partner.PartnerLine("日本語" if repair is None else "How are you?"),
                m.Usage(
                    "test",
                    "partner/model",
                    10,
                    3,
                    Decimal("0.10"),
                    10 if repair is None else 20,
                ),
            )

    model = RepairingPartner()

    report = await run_cases((opener(),), model, FixedCoachModel(), METADATA)

    data = report.as_dict()
    assert len(model.repairs) == 2
    assert model.repairs[0] is None
    assert model.repairs[1].violations[0].check is m.CheckId.PARTNER_JAPANESE
    assert data["checks"]["partner_japanese"]["first"] == {
        "passed": 0,
        "total": 1,
        "rate": 0.0,
    }
    assert data["checks"]["partner_japanese"]["final"] == {
        "passed": 1,
        "total": 1,
        "rate": 1.0,
    }
    assert data["tasks"]["partner.open"]["calls"] == 2
    assert data["tasks"]["partner.open"]["outcomes"]["repaired"] == 1
    assert data["tasks"]["partner.open"]["cost_credits"] == "0.20"
    assert data["tasks"]["partner.open"]["latency_p50_ms"] == 10
    assert data["tasks"]["partner.open"]["latency_p95_ms"] == 20
    assert data["metadata"]["commit"] == "abc123"
    assert data["metadata"]["dirty"] is False


async def test_schema_failure_excludes_content_denominators_then_provider_error_continues():
    class FailingThenPassing(FixedPartnerModel):
        def __init__(self):
            self.calls = 0

        async def open(self, request, repair=None):
            self.calls += 1
            if self.calls == 1:
                return m.ParseFailure(
                    m.Usage("test", "model", None, None, None, 5), "Invalid schema"
                )
            if self.calls == 2:
                provider = "test"
                raise ModelTimeoutError(provider, "model", 60_000)
            return await super().open(request, repair)

    model = FailingThenPassing()

    report = await run_cases(
        (opener("01-fail"), opener("02-continue")), model, FixedCoachModel(), METADATA
    )

    data = report.as_dict()
    assert model.calls == 3
    assert data["cases"][0]["checks_first"]["schema"] is False
    assert data["cases"][0]["checks_first"]["partner_japanese"] is None
    assert data["cases"][0]["expectations_first"][0]["passed"] is None
    assert data["cases"][0]["checks_final"]["schema"] is None
    assert data["cases"][0]["error"] == "model_timeout"
    assert data["cases"][0]["error_status"] is None
    assert data["cases"][1]["error"] is None
    assert data["tasks"]["partner.open"]["outcomes"]["timeout"] == 1
    assert data["tasks"]["partner.open"]["cost_credits"] is None
    assert "credits" in report.render_markdown()
    assert '"coach_model": "coach/model"' in report.render_json()


async def test_provider_http_status_reaches_the_error_column_and_json():
    class Rejecting(FixedPartnerModel):
        async def open(self, request, repair=None):
            del request, repair
            provider = "openrouter"
            raise ModelUnavailableError(provider, "partner/model", 30, status=400)

    report = await run_cases(
        (opener("01-rejected"),), Rejecting(), FixedCoachModel(), METADATA
    )

    case = report.as_dict()["cases"][0]
    assert case["error"] == "model_unavailable"
    assert case["error_status"] == 400
    assert (
        "| 01-rejected | partner.open | provider_error | model_unavailable (HTTP 400) |"
        in report.render_markdown()
    )


async def test_all_seed_cases_render_reports_and_rewrite_only_temporary_readme(
    tmp_path,
):
    cases = load_cases(Path(__file__).resolve().parents[2] / "evals/cases")

    report = await run_cases(cases, FixedPartnerModel(), FixedCoachModel(), METADATA)

    assert len(cases) == 16
    assert all(case.source for case in cases)
    intent_note = cases[13].context["intent"]
    assert isinstance(intent_note, str)
    assert "札幌" in intent_note
    assert "札幌" not in repr(cases[13].request)
    markdown, machine = tmp_path / "report.md", tmp_path / "report.json"
    markdown.write_text(report.render_markdown())
    machine.write_text(report.render_json())
    readme = tmp_path / "README.md"
    text = "before\n<!-- eval-summary:start -->\nNo evaluation run yet.\n<!-- eval-summary:end -->\nafter\n"
    readme.write_text(replace_summary(text, report.task_table()))
    assert markdown.read_text().startswith("# Model evaluation")
    assert '"cases"' in machine.read_text()
    assert readme.read_text().startswith("before\n")
    assert readme.read_text().endswith("after\n")
    # Quality is a measured result here, never a fixed-adapter acceptance threshold.


@pytest.mark.parametrize(
    ("first_cost", "later_cost", "expected"),
    [
        (Decimal("0.00"), None, None),
        (Decimal("0.00"), Decimal("0.00"), "0.00"),
        (
            Decimal("0.123456789012345678901234567890"),
            Decimal(0),
            "0.123456789012345678901234567890",
        ),
    ],
    ids=["partial-cost-unknown", "reported-zero", "exact-decimal"],
)
async def test_task_percentiles_and_reported_cost_completeness(
    first_cost, later_cost, expected
):
    class TimedPartner(FixedPartnerModel):
        def __init__(self):
            self.calls = 0

        async def open(self, request, repair=None):
            self.calls += 1
            result = await super().open(request, repair)
            return m.Parsed(
                result.output,
                m.Usage(
                    "test",
                    "model",
                    None,
                    None,
                    first_cost if self.calls == 1 else later_cost,
                    self.calls,
                ),
            )

    report = await run_cases(
        tuple(opener(f"{n:02d}") for n in range(20)),
        TimedPartner(),
        FixedCoachModel(),
        METADATA,
    )

    task = report.as_dict()["tasks"]["partner.open"]
    assert task["latency_p50_ms"] == 10
    assert task["latency_p95_ms"] == 19
    assert task["cost_credits"] == expected
