"""Static safety checks for regressions that runtime tests may miss."""

from __future__ import annotations

import shutil
import subprocess

import pytest


def test_ruff_f821_gate():
    """Undefined-name regressions (F821) must fail fast in test flow."""
    ruff_bin = shutil.which("ruff")
    if not ruff_bin:
        pytest.skip("ruff is not installed in current environment")

    command = [ruff_bin, "check", "--select", "F821", "src", "tests"]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    output = (completed.stdout + "\n" + completed.stderr).strip()
    assert completed.returncode == 0, output
