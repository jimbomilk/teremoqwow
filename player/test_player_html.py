"""
Tests E3-T4 — Player title dinámico + limpieza info técnica.

Run: python3 -m pytest player/test_player_html.py -v --tb=short
"""
import pathlib
import re
import subprocess
import unittest

PLAYER_HTML = pathlib.Path(__file__).parent / "index.html"
WORKSPACE_ROOT = PLAYER_HTML.parent.parent


def _run_node(script: str) -> str:
    """Execute a JS snippet with node (CJS mode) and return stdout stripped."""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(WORKSPACE_ROOT),
    )
    return result.stdout.strip()


class TestPlayerTitle(unittest.TestCase):
    def setUp(self) -> None:
        self.html = PLAYER_HTML.read_text()

    def _extract_title_script(self) -> str:
        """Extract the inline title-setting JS between the BEGIN/END_TITLE_SCRIPT markers."""
        match = re.search(
            r"<!-- BEGIN_TITLE_SCRIPT -->\s*<script>(.*?)</script>\s*<!-- END_TITLE_SCRIPT -->",
            self.html,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip()
        return ""

    def test_title_with_broadcast_param(self) -> None:
        """?broadcast=anon/live1  →  title = 'teremoqwow · live1'"""
        script = self._extract_title_script()
        self.assertNotEqual(script, "", "Title script not found in index.html")

        node_code = (
            "var location = { search: '?broadcast=anon%2Flive1' };\n"
            "var document = { title: '', body: { classList: { add: function(){} } } };\n"
            + script
            + "\nconsole.log(document.title);"
        )
        result = _run_node(node_code)
        self.assertEqual(result, "teremoqwow \u00b7 live1")

    def test_title_without_param(self) -> None:
        """No broadcast param  →  title = 'teremoqwow Player'"""
        script = self._extract_title_script()
        self.assertNotEqual(script, "", "Title script not found in index.html")

        node_code = (
            "var location = { search: '' };\n"
            "var document = { title: '', body: { classList: { add: function(){} } } };\n"
            + script
            + "\nconsole.log(document.title);"
        )
        result = _run_node(node_code)
        self.assertEqual(result, "teremoqwow Player")


if __name__ == "__main__":
    unittest.main()
