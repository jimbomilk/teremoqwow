"""
Tests del HTML del player y su configuración de build de producción.

Run: python3 -m pytest player/test_player_html.py -v --tb=short
"""
import os
import pathlib
import re
import shlex
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import unittest

PLAYER_HTML = pathlib.Path(__file__).parent / "index.html"
WORKSPACE_ROOT = PLAYER_HTML.parent.parent


def _dockerfile_env_assignments(dockerfile: str, name: str) -> list[str]:
    continued = re.sub(r"\\[ \t]*\r?\n[ \t]*", " ", dockerfile)
    assignments = []
    for instruction in continued.splitlines():
        match = re.match(r"^\s*ENV\s+(.+)$", instruction, re.IGNORECASE)
        if not match:
            continue

        tokens = shlex.split(match.group(1))
        if not tokens:
            continue
        if "=" in tokens[0]:
            for token in tokens:
                key, separator, value = token.partition("=")
                if key == name and separator:
                    assignments.append(value)
        elif tokens[0] == name and len(tokens) > 1:
            assignments.append(" ".join(tokens[1:]))
    return assignments


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


class TestPlayerDevServer(unittest.TestCase):
    def test_bootstrap_module_is_served_from_root(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]

        base_url = f"http://127.0.0.1:{port}"
        vite_entry = PLAYER_HTML.parent / "node_modules" / "vite" / "bin" / "vite.js"
        process = subprocess.Popen(
            [
                "node",
                str(vite_entry),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ],
            cwd=PLAYER_HTML.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None:
                    self.fail(f"Vite dev server exited with status {process.returncode}")
                try:
                    with urllib.request.urlopen(base_url, timeout=1) as response:
                        html = response.read().decode("utf-8")
                    break
                except urllib.error.URLError:
                    if time.monotonic() >= deadline:
                        self.fail("Vite dev server did not start within 20 seconds")
                    time.sleep(0.1)

            module_refs = re.findall(
                r'<script\b(?=[^>]*\btype=["\']module["\'])[^>]*\bsrc=["\']([^"\']*bootstrap\.ts)["\'][^>]*>',
                html,
                re.IGNORECASE,
            )
            self.assertEqual(len(module_refs), 1, "Expected one bootstrap module script")
            self.assertEqual(module_refs[0], "/src/bootstrap.ts")

            with urllib.request.urlopen(
                urllib.parse.urljoin(base_url, module_refs[0]), timeout=5
            ) as response:
                self.assertEqual(response.status, 200)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            else:
                process.wait()


class TestPlayerProductionBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = os.environ.copy()
        env.update({
            "VITE_MOQ_RELAY_URL": "https://wow.teremoq.com:4443/anon",
            "VITE_RELAY_BROADCAST": "anon/live1",
            "VITE_MOQ_CERT_HASH": "",
        })
        subprocess.run(
            ["npm", "run", "build"],
            cwd=PLAYER_HTML.parent,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        cls.html = (PLAYER_HTML.parent / "dist" / "index.html").read_text()

    def test_production_html_works_below_player_prefix(self) -> None:
        asset_paths = re.findall(r'(?:src|href)="([^"]*/assets/[^"]+)"', self.html)
        self.assertTrue(asset_paths, "Built HTML does not reference any /assets/ files")
        self.assertTrue(
            all(path.startswith("./assets/") for path in asset_paths),
            f"Built assets must resolve relative to /player/: {asset_paths}",
        )
        self.assertIn('data-url="https://wow.teremoq.com:4443/anon"', self.html)
        self.assertIn('data-name="anon/live1"', self.html)
        self.assertIn('data-cert-hash=""', self.html)
        self.assertNotIn("%VITE_MOQ_CERT_HASH%", self.html)

    def _assert_dockerfile_env_contract(self, dockerfile: str) -> None:
        for name in (
            "VITE_MOQ_RELAY_URL",
            "VITE_RELAY_BROADCAST",
            "VITE_MOQ_CERT_HASH",
        ):
            assignments = _dockerfile_env_assignments(dockerfile, name)
            self.assertEqual(
                assignments,
                [f"${name}"],
                f"Dockerfile must assign {name} exactly once from its build ARG",
            )

    def test_production_build_arguments_match_webtransport(self) -> None:
        compose = (WORKSPACE_ROOT / "docker-compose.prod.yml").read_text()
        dockerfile = (PLAYER_HTML.parent / "Dockerfile").read_text()
        self.assertIn("VITE_MOQ_RELAY_URL: https://wow.teremoq.com:4443/anon", compose)
        self.assertIn('VITE_MOQ_CERT_HASH: ""', compose)
        self.assertIn("VITE_RELAY_BROADCAST: anon/live1", compose)
        self.assertIn("ARG VITE_MOQ_RELAY_URL=https://wow.teremoq.com:4443/anon", dockerfile)
        self.assertIn("ARG VITE_RELAY_BROADCAST=anon/live1", dockerfile)
        self.assertIn("ARG VITE_MOQ_CERT_HASH=", dockerfile)
        self._assert_dockerfile_env_contract(dockerfile)

    def test_dockerfile_env_assertions_reject_late_overrides(self) -> None:
        dockerfile = (PLAYER_HTML.parent / "Dockerfile").read_text()
        mutations = (
            "ENV VITE_MOQ_RELAY_URL wss://mutant.invalid/anon",
            "ENV VITE_MOQ_CERT_HASH %VITE_MOQ_CERT_HASH%",
            "ENV VITE_MOQ_RELAY_URL $VITE_MOQ_RELAY_URL extra",
            "ENV VITE_RELAY_BROADCAST=wrong",
            "ENV " + "\\" + "\n  VITE_MOQ_RELAY_URL wss://mutant.invalid/anon",
        )

        with tempfile.TemporaryDirectory(prefix="player-dockerfile-mutant-") as temp:
            copy = pathlib.Path(temp) / "Dockerfile"
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    copy.write_text(f"{dockerfile}\n{mutation}\n")
                    with self.assertRaises(AssertionError):
                        self._assert_dockerfile_env_contract(copy.read_text())


if __name__ == "__main__":
    unittest.main()
