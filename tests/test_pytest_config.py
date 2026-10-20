"""Both pytest configurations turn warnings into failures.

The root ``pyproject.toml`` runs the repository's own tests and
``backend/pyproject.toml`` the app's; each is its own pytest invocation.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("recipe", "expected"),
    [
        pytest.param("test", {"test_ordinary"}, id="local"),
        pytest.param("test-process", {"test_process"}, id="process"),
    ],
)
def test_test_recipe_selects_its_own_suite(
    tmp_path: Path, recipe: str, expected: set[str]
) -> None:
    just = shutil.which("just")
    assert just is not None, "the recipe selection check needs Just"
    shown = subprocess.run(  # noqa: S603 -- fixed recipe names, no shell
        [just, "--show", recipe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert shown.returncode == 0, shown.stderr
    command = shlex.split(shown.stdout.splitlines()[-1])
    selector = command[command.index("-m") + 1] if "-m" in command else ""
    test_file = tmp_path / "test_selection.py"
    test_file.write_text(
        "import pytest\n\n"
        "def test_ordinary(): pass\n\n"
        "@pytest.mark.process_integration\n"
        "def test_process(): pass\n",
        encoding="utf-8",
    )
    collected = subprocess.run(  # noqa: S603 -- fixture-only collection, no tests run
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(REPO_ROOT / "pyproject.toml"),
            "--rootdir",
            str(tmp_path),
            "-o",
            "markers=process_integration: fixture process test",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "-q",
            "-m",
            selector,
            str(test_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    selected = {
        line.rsplit("::", 1)[1]
        for line in collected.stdout.splitlines()
        if "::" in line
    }
    assert selected == expected


@pytest.mark.parametrize(
    "pyproject",
    [
        pytest.param(REPO_ROOT / "pyproject.toml", id="root"),
        pytest.param(REPO_ROOT / "backend" / "pyproject.toml", id="backend"),
    ],
)
def test_pytest_config_deprecation_warning_fails_the_run(tmp_path, pyproject):
    test_file = tmp_path / "test_warns.py"
    test_file.write_text(
        "import warnings\n"
        "\n"
        "def test_warns():\n"
        "    warnings.warn('old path', DeprecationWarning, stacklevel=1)\n",
        encoding="utf-8",
    )

    # A fresh interpreter: this run's own filters are already installed.
    result = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter and pytest
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(pyproject),
            "--rootdir",
            str(tmp_path),
            "-p",
            "no:cacheprovider",
            str(test_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "DeprecationWarning: old path" in result.stdout
