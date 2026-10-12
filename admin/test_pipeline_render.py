"""Lanza los tests de la UI Pipeline (node:test). La lógica está en test_pipeline_render.test.mjs."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

MJS = Path(__file__).resolve().parent / "test_pipeline_render.test.mjs"
MJS_PAGE = Path(__file__).resolve().parent / "test_pipeline_page.test.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node no instalado")
@pytest.mark.parametrize("mjs", [MJS, MJS_PAGE], ids=lambda p: p.name)
def test_node_ui_tests_pass(mjs):
    p = subprocess.run(["node", "--test", str(mjs)], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout[-4000:] + p.stderr[-2000:]
