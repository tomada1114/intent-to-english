from __future__ import annotations

import json
from dataclasses import replace

import pytest

from intent_to_english.adapters.models.fixed import FixedCoachModel, FixedPartnerModel
from intent_to_english.composition import ModelPorts
from intent_to_english.evaluation import __main__ as cli
from intent_to_english.evaluation.reports import RunMetadata

ARGS = ["--commit", "test-head", "--dirty", "false"]
STEM = "2026-10-19_anthropic-claude-sonnet-5.5_anthropic-claude-haiku-5.5"
README = "before\n<!-- eval-summary:start -->\nNo evaluation run yet.\n<!-- eval-summary:end -->\nafter\n"


class ForbiddenPorts:
    async def forbidden(self, request, repair=None):
        del request, repair
        message = "A preflight refusal must not call any model"
        raise AssertionError(message)

    open = forbidden
    reply = forbidden
    restate = forbidden
    acknowledge = forbidden
    gap_hint = forbidden
    feedback = forbidden
    check_retry = forbidden
    show_answer = forbidden
    answer_question = forbidden
    wrap_up = forbidden


@pytest.fixture
def files(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(README)
    reports = tmp_path / "reports"
    return readme, reports, [*ARGS, "--readme", str(readme), "--reports", str(reports)]


def test_fixed_mode_refuses_before_any_call_or_write(files, capsys, monkeypatch):
    readme, reports, args = files
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("INTENT_TO_ENGLISH_MODEL_MODE", "fixed")

    assert cli.main(args) == 1

    error = capsys.readouterr().err
    assert "OPENROUTER_API_KEY" in error
    assert "INTENT_TO_ENGLISH_MODEL_MODE" in error
    assert readme.read_text() == README
    assert not reports.exists()


@pytest.fixture
def fake_live(monkeypatch, make_container):
    # The mode is fake: all ports remain offline. A failing preflight must not reach them.
    ports = make_container()
    forbidden = ForbiddenPorts()
    fake = replace(
        ports, model_mode="openrouter", models=ModelPorts(forbidden, forbidden)
    )
    monkeypatch.setattr(cli, "build_container", lambda _settings: fake, raising=False)
    monkeypatch.setattr(cli, "today_utc", lambda: "2026-10-19", raising=False)
    return fake


@pytest.mark.parametrize("suffix", ["md", "json"], ids=["markdown", "json"])
def test_existing_report_refuses_before_any_call(files, fake_live, suffix, capsys):
    readme, reports, args = files
    reports.mkdir()
    target = reports / f"{STEM}.{suffix}"
    target.write_text("KEEP")

    assert cli.main(args) == 1

    assert "exists" in capsys.readouterr().err
    assert target.read_text() == "KEEP"
    assert list(reports.iterdir()) == [target]
    assert readme.read_text() == README


@pytest.mark.parametrize(
    "content",
    [
        "missing",
        README + "<!-- eval-summary:start -->",
        README.replace("eval-summary:start", "eval-summary:end", 1),
        "<!-- eval-summary:end -->\n<!-- eval-summary:start -->",
    ],
    ids=["missing", "duplicate-start", "duplicate-end", "reversed"],
)
def test_bad_readme_markers_refuse_before_any_call(files, fake_live, content, capsys):
    readme, reports, args = files
    readme.write_text(content)

    assert cli.main(args) == 1

    assert "marker" in capsys.readouterr().err
    assert readme.read_text() == content
    assert not reports.exists()


def test_offline_fake_writes_both_reports_and_only_readme_summary(
    files, fake_live, monkeypatch
):
    readme, reports, args = files
    offline = replace(
        fake_live, models=ModelPorts(FixedPartnerModel(), FixedCoachModel())
    )
    monkeypatch.setattr(cli, "build_container", lambda _settings: offline)

    assert cli.main(args) == 0

    data = json.loads((reports / f"{STEM}.json").read_text())
    assert len(data["cases"]) == 16
    assert data["metadata"]["commit"] == "test-head"
    assert data["metadata"]["dirty"] is False
    assert (reports / f"{STEM}.md").read_text().startswith("# Model evaluation")
    assert readme.read_text().startswith("before\n<!-- eval-summary:start -->")
    assert readme.read_text().endswith("<!-- eval-summary:end -->\nafter\n")
    assert f"reports/{STEM}.md" in readme.read_text()


def test_invalid_usage_is_argparse_exit_two():
    with pytest.raises(SystemExit) as caught:
        cli.main(["--unknown"])

    assert caught.value.code == 2


def test_invalid_case_is_rejected_before_model_calls(
    files, fake_live, tmp_path, capsys
):
    readme, reports, args = files
    cases = tmp_path / "cases"
    cases.mkdir()
    source = (cli.BACKEND / "evals/cases/15-different-opener.toml").read_text()
    for number in range(10):
        text = (
            source.replace("previous_opener =", "unknown_opener =")
            if number == 0
            else source
        )
        (cases / f"{number:02d}.toml").write_text(text)

    assert cli.main([*args, "--cases", str(cases)]) == 1

    assert "request.unknown_opener" in capsys.readouterr().err
    assert not reports.exists()
    assert readme.read_text() == README


def test_evaluation_disables_database_before_building_container(
    files, monkeypatch, make_container, tmp_path
):
    seen = []
    database = tmp_path / "never-created.db"

    def build(settings):
        seen.append(settings.database_url)
        return make_container(settings)

    monkeypatch.setattr(cli, "build_container", build)
    monkeypatch.setenv(
        "INTENT_TO_ENGLISH_DATABASE_URL", f"sqlite+aiosqlite:///{database}"
    )
    monkeypatch.setenv("INTENT_TO_ENGLISH_MODEL_MODE", "fixed")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")

    assert cli.main(files[2]) == 1

    assert seen == [None]
    assert not database.exists()


def test_filename_preserves_a_plain_model_id_and_replaces_only_slashes():
    metadata = RunMetadata(
        "2026-10-19", "coach-no-slash", "provider/partner", "head", True
    )

    assert cli.report_stem(metadata) == "2026-10-19_coach-no-slash_provider-partner"
