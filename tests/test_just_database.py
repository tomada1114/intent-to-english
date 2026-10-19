"""Database recipe execution with a fake uv; no database or server is started."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _call_log_recipe(
    tmp_path: Path, url: str, *, invalid: bool = False
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Execute the public recipe with a resolver/runner fake and no settings reads."""
    (tmp_path / "backend").mkdir()
    (tmp_path / "justfile").write_text("mod backend\n", encoding="utf-8")
    (tmp_path / "backend/justfile").write_text(
        (REPO_ROOT / "backend/justfile").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "uv"
    fake.write_text(
        "#!/bin/sh\n"
        'case " $* " in *" -c "*)\n'
        '  if [ "$FAKE_INVALID" = 1 ]; then\n'
        '    printf "validation failed: %s\\n" "$FAKE_URL" >&2; exit 1\n'
        "  fi\n"
        '  printf "%s\\n" "$FAKE_URL"; exit 0 ;; esac\n'
        'printf "%s\\n" "$@" > "$FAKE_RECORD"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    record = tmp_path / "calls.txt"
    result = subprocess.run(
        ["just", "backend", "call-log", "--since", "2026-01-02 03:04:05"],  # noqa: S607 -- just is a required CI tool
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_URL": url,
            "FAKE_INVALID": "1" if invalid else "0",
            "FAKE_RECORD": str(record),
            "UV_NO_CACHE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result, record


def test_call_log_invalid_configuration_is_safe_before_cli(tmp_path: Path) -> None:
    result, record = _call_log_recipe(
        tmp_path, "bad://user:synthetic-password@host/database", invalid=True
    )
    assert result.returncode == 1
    assert "synthetic-password" not in result.stderr
    assert "just backend db-upgrade" in result.stderr
    assert result.stdout == ""
    assert not record.exists()


@pytest.mark.parametrize("postgres", [False, True], ids=["sqlite", "postgres"])
def test_call_log_recipe_preserves_driver_and_filter_arguments(
    tmp_path: Path, postgres: bool
) -> None:
    url = (
        "postgresql+asyncpg://localhost/test"
        if postgres
        else "sqlite+aiosqlite:///./var/dev.db"
    )
    result, record = _call_log_recipe(tmp_path, url)
    assert result.returncode == 0, result.stderr
    arguments = record.read_text(encoding="utf-8").splitlines()
    assert arguments[:2] == ["run", "--locked"]
    assert ("--extra" in arguments) is postgres
    assert arguments[-5:] == [
        "python",
        "-m",
        "intent_to_english.call_log",
        "--since",
        "2026-01-02 03:04:05",
    ]


@pytest.mark.parametrize("recipe", ["db-upgrade", "db-revision", "dev"])
@pytest.mark.parametrize("postgres", [False, True], ids=["sqlite", "postgres"])
def test_database_recipe_installs_driver_only_for_postgres(
    tmp_path: Path, recipe: str, postgres: bool
) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "uv"
    fake.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$FAKE_RECORD"\n'
        'case "$INTENT_TO_ENGLISH_DATABASE_URL" in\n'
        '  postgresql+asyncpg:*) case " $* " in\n'
        '    *" --extra postgres "*) exit 0 ;;\n'
        '    *) echo "missing asyncpg" >&2; exit 3 ;;\n'
        "  esac ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    record = tmp_path / "calls.txt"
    lines = (REPO_ROOT / "backend/justfile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{recipe} "))
    body = []
    for line in lines[start + 1 :]:
        if not line.startswith("    "):
            break
        if "uv run" in line:
            body.append(line.strip())
    assert len(body) == 1
    url = (
        "postgresql+asyncpg://localhost/intent_to_english_test"
        if postgres
        else "sqlite+aiosqlite:///./var/dev.db"
    )
    command = (
        body[0]
        .replace("{{ quote(url) }}", shlex.quote(url))
        .replace("{{ quote(MESSAGE) }}", shlex.quote("test revision"))
    )
    result = subprocess.run(  # noqa: S603 -- fixed shell argv, repository recipe and fixture URL
        ["sh", "-cu", command],  # noqa: S607 -- sh from PATH, as just runs each line
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_RECORD": str(record),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    args = record.read_text(encoding="utf-8").splitlines()
    assert args[:2] == ["run", "--locked"]
    assert ("--extra" in args) is postgres
