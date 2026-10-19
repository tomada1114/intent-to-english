"""Human-run evaluation; fixed mode refuses before any call or write.

Usage: python -m intent_to_english.evaluation --commit SHA --dirty true|false
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from intent_to_english.composition import build_container
from intent_to_english.evaluation.cases import load_cases
from intent_to_english.evaluation.harness import run_cases
from intent_to_english.evaluation.reports import RunMetadata
from intent_to_english.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Sequence

BACKEND = Path(__file__).resolve().parents[3]
START = "<!-- eval-summary:start -->"
END = "<!-- eval-summary:end -->"


@dataclass(frozen=True, slots=True)
class Options:
    """Typed arguments after argparse has validated the command boundary."""

    cases: Path
    reports: Path
    readme: Path
    commit: str
    dirty: bool


def main(argv: Sequence[str] | None = None) -> int:
    """Run the configured evaluation or return a refusal exit status."""
    parser = argparse.ArgumentParser(
        description="Run billed model evaluation; use just backend eval."
    )
    parser.add_argument("--commit", required=True)
    parser.add_argument("--dirty", choices=("true", "false"), required=True)
    parser.add_argument("--cases", type=Path, default=BACKEND / "evals/cases")
    parser.add_argument("--reports", type=Path, default=BACKEND / "evals/reports")
    parser.add_argument("--readme", type=Path, default=BACKEND.parent / "README.md")
    args = parser.parse_args(argv)
    options = Options(
        args.cases, args.reports, args.readme, args.commit, args.dirty == "true"
    )
    try:
        return asyncio.run(_execute(options, Settings()))
    except (OSError, ValueError) as error:
        sys.stderr.write(f"Evaluation refused or failed: {error}\n")
        return 1


async def _execute(options: Options, settings: Settings) -> int:
    # Evaluation uses the same model selection and ownership, with storage disabled.
    # No SQL driver, connection, schema or developer database is needed for port calls.
    memory_settings = settings.model_copy(update={"database_url": None})
    async with build_container(memory_settings) as container:
        if container.model_mode == "fixed":
            sys.stderr.write(
                "Evaluation requires live models: set OPENROUTER_API_KEY and INTENT_TO_ENGLISH_MODEL_MODE=auto. The selected mode is fixed.\n"
            )
            return 1
        metadata = RunMetadata(
            today_utc(),
            settings.coach_model,
            settings.partner_model,
            options.commit,
            options.dirty,
        )
        stem = report_stem(metadata)
        markdown, machine = (
            options.reports / f"{stem}.md",
            options.reports / f"{stem}.json",
        )
        for path in (markdown, machine):
            if path.exists():
                message = f"Report already exists: {path.name}"
                raise ValueError(message)
        _markers(options.readme.read_text(encoding="utf-8"))
        cases = load_cases(options.cases)
        report = await run_cases(
            cases, container.models.partner, container.models.coach, metadata
        )
        # Preserve outside edits made while a potentially long run was in progress.
        current_readme = options.readme.read_text(encoding="utf-8")
        link = quote(Path(os.path.relpath(markdown, options.readme.parent)).as_posix())
        block = f"Latest run: [{metadata.date}]({link})\n\n{report.task_table()}"
        updated = replace_summary(current_readme, block)
        markdown_text, json_text = report.render_markdown(), report.render_json()
        options.reports.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also prevents overwriting a concurrent run's result.
        with markdown.open("x", encoding="utf-8") as handle:
            handle.write(markdown_text)
        with machine.open("x", encoding="utf-8") as handle:
            handle.write(json_text)
        options.readme.write_text(updated, encoding="utf-8")
        sys.stdout.write(f"Wrote {markdown} and {machine}\n")
        return 0


def today_utc() -> str:
    """Name a report by its UTC run date."""
    return datetime.now(UTC).date().isoformat()


def report_stem(metadata: RunMetadata) -> str:
    """Keep model ids intact except for the specified slash replacement."""
    return f"{metadata.date}_{metadata.coach_model.replace('/', '-')}_{metadata.partner_model.replace('/', '-')}"


def replace_summary(text: str, block: str) -> str:
    """Rewrite only the one validated summary block."""
    start, end = _markers(text)
    return text[:start] + "\n" + block + "\n" + text[end:]


def _markers(text: str) -> tuple[int, int]:
    if (
        text.count(START) != 1
        or text.count(END) != 1
        or text.index(START) >= text.index(END)
    ):
        message = (
            "README must contain exactly one ordered start/end evaluation marker pair"
        )
        raise ValueError(message)
    return text.index(START) + len(START), text.index(END)


if __name__ == "__main__":
    raise SystemExit(main())
