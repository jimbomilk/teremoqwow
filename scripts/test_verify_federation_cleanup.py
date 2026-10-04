import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
FEDERATION_SCRIPT = REPOSITORY_ROOT / "scripts" / "verify-federation.sh"


class FederationCleanupTest(unittest.TestCase):
    def _run_with_missing_prerequisites(self, registry_pid=None):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = pathlib.Path(temporary_directory)
            shim_directory = temporary_path / "bin"
            shim_directory.mkdir()
            docker_calls = temporary_path / "docker-calls"
            kill_calls = temporary_path / "kill-calls"
            bash_environment = temporary_path / "bash-environment"
            python3_shim = shim_directory / "python3"
            docker_shim = shim_directory / "docker"
            kill_shim = shim_directory / "kill"

            python3_shim.write_text(
                "#!/bin/sh\n"
                'if [ "$#" -eq 2 ] && [ "$1" = "-c" ] && '
                '[ "$2" = "import jwt, jsonschema" ]; then\n'
                "  exit 1\n"
                "fi\n"
                f"exec {shlex.quote(sys.executable)} \"$@\"\n"
            )
            docker_shim.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {shlex.quote(str(docker_calls))}\n"
            )
            kill_shim.write_text(
                "#!/bin/sh\n"
                f"printf 'call:%s\\n' \"$*\" >> {shlex.quote(str(kill_calls))}\n"
                "exit 0\n"
            )
            bash_environment.write_text("enable -n kill\n")
            python3_shim.chmod(0o755)
            docker_shim.chmod(0o755)
            kill_shim.chmod(0o755)

            environment = os.environ.copy()
            environment.pop("REGISTRY_PID", None)
            if registry_pid is not None:
                environment["REGISTRY_PID"] = registry_pid
            environment["PATH"] = f"{shim_directory}{os.pathsep}{environment['PATH']}"
            environment["BASH_ENV"] = str(bash_environment)

            result = subprocess.run(
                ["bash", str(FEDERATION_SCRIPT)],
                cwd=REPOSITORY_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

            output = result.stdout + result.stderr
            return (
                result,
                output,
                docker_calls.read_text().splitlines(),
                kill_calls.exists(),
                kill_calls.read_text().splitlines() if kill_calls.exists() else [],
            )

    def test_prerequisite_failure_cleans_up_without_starting_services(self):
        result, output, docker_calls, kill_calls_exist, _ = (
            self._run_with_missing_prerequisites()
        )

        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("PyJWT y jsonschema requeridos", output)
        self.assertNotIn("REGISTRY_PID: unbound variable", output)
        self.assertEqual(
            docker_calls,
            ["rm -f fed-relay-1 fed-relay-2 fed-publisher fed-subscriber"],
        )
        self.assertFalse(kill_calls_exist)
        self.assertNotIn("Arrancando registry_server.py", output)
        self.assertNotIn("Arrancando fed-relay-1", output)
        self.assertNotIn("Arrancando fed-relay-2", output)

    def test_prerequisite_failure_kills_registry_pid_without_starting_services(
        self,
    ):
        for registry_pid in ("424242", "7654321"):
            with self.subTest(registry_pid=registry_pid):
                result, output, docker_calls, kill_calls_exist, kill_calls = (
                    self._run_with_missing_prerequisites(registry_pid)
                )

                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn("PyJWT y jsonschema requeridos", output)
                self.assertEqual(
                    docker_calls,
                    ["rm -f fed-relay-1 fed-relay-2 fed-publisher fed-subscriber"],
                )
                self.assertTrue(kill_calls_exist)
                self.assertEqual(kill_calls, [f"call:{registry_pid}"])
                self.assertNotIn("Arrancando registry_server.py", output)
                self.assertNotIn("Arrancando fed-relay-1", output)
                self.assertNotIn("Arrancando fed-relay-2", output)


if __name__ == "__main__":
    unittest.main()
