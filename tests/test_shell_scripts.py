#!/usr/bin/env python3
"""Run the shell-level tests in the pytest gate: launcher path resolution
(#52, #60, #138) and the install.sh --user end-to-end run (#138).

Run: python3 -m pytest tests/test_shell_scripts.py -q
"""

import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent


@pytest.mark.parametrize("script", ["test_launcher.sh", "test_install_user.sh"])
def test_shell_script(script):
    if not shutil.which("bash") or not shutil.which("tar"):
        pytest.skip("needs bash and tar")
    r = subprocess.run(["bash", str(TESTS / script)], capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-4000:]
