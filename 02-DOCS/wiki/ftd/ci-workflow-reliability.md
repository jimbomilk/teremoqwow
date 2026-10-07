# CI workflow reliability

## Intent

Repair deterministic GitHub Actions setup failures separately from the player
configuration change, while preserving real QoS integration gates.

## Scope

- In: Python CI dependency/caching setup, TypeScript test runtime, missing
  dependencies in integration jobs, safe federation cleanup before registry
  startup, and disabling external-player probes in CI.
- Out: changing QoS thresholds or treating missing local media frames/latency
  samples as success; production deployment.

## Checklist

- [x] Remove Python pip caching without a dependency manifest; use Node 24 only
  for TypeScript tests while schema validation stays on Node 20. Verify YAML and
  rerun the relevant Python and TypeScript test commands.
- [x] Install Flask-Cors for DRM/Billing and JSON Schema for federation; guard
  registry cleanup before startup. Verify imports, shell syntax, and the
  prerequisite-error cleanup path.
- [x] Skip only external player/Tailscale probes in CI; retain local media
  checks. Record the local no-frame and latency failures as a separate blocker.
- [x] Add a safe regression test for missing federation prerequisites and run it
  in the Python CI job.
- [x] Assert that cleanup skips `kill` when `REGISTRY_PID` is absent and
  invokes the intercepted `kill` shim exactly once with each distinct sentinel
  `424242` and `7654321` when set; retain the existing CI test command.
- [x] Remove the guarded kill branch temporarily; prove the set-PID regression
  fails, restore the script byte-for-byte, and rerun both tests.

## Evidence

- Recorded GitHub Actions failures from CI logs (not re-executed locally):
  - Run `37234199271` (`setup-python`): `Error: No requirements.txt or pyproject.toml found` in the Python setup step.
  - Run `37234199271` (`Node 20`): the TypeScript test step failed with `ERR_UNKNOWN_FILE_EXTENSION` for `.ts` when the workflow invoked Node 20 directly.
  - Run `37234199284` (`integration`): DRM/Billing import step failed with `ModuleNotFoundError: No module named 'flask_cors'`.
  - Run `37234199284` (`federation cleanup`): prerequisite setup required `jsonschema`; the cleanup path then failed with `REGISTRY_PID: unbound variable`.
  - Run `37234199284` (`QoS`): recorded failures included `No frames captured` and the local `measure-e2e.sh` latency check failed.
- Reproducible CI checks:
  - The CI Python job selects 3.12; run the regression command and its six
    existing pytest commands:
    ```bash
    python3 -m pytest scripts/test_verify_federation_cleanup.py -q
    PYTHONPATH="comercial/auth:relay" python3 -m pytest comercial/auth/test_register_privilege_gate.py -v --tb=short
    PYTHONPATH="admin/api:relay:comercial/portal" python3 -m pytest admin/test_broadcast_redis.py admin/test_quick_test.py admin/test_overlays_api.py -v --tb=short
    PYTHONPATH="comercial/portal:relay" python3 -m pytest comercial/billing/test_security_g3.py -v --tb=short
    PYTHONPATH="relay" python3 -m pytest relay/test_mocha_validator_g4.py -v --tb=short
    python3 -m pytest overlays/test_templates.py -v --tb=short
    python3 -m pytest player/test_player_html.py -v --tb=short
    ```
    Workspace rerun (Python 3.14.4): 138 tests passed, one warning, zero failures.
  - Node 24; the two commands from `.github/workflows/ci.yml`:
    ```bash
    node player/src/moq-watch.test.ts
    node player/src/overlay-engine.test.ts
    ```
    Workspace rerun under Node 24.21.0: 23 and 13 tests passed, respectively.
  - Both workflow files parsed using PyYAML with:
    ```bash
    python3 -c 'import pathlib, yaml; files = [".github/workflows/ci.yml", ".github/workflows/integration-test.yml"]; [yaml.safe_load(pathlib.Path(path).read_text()) for path in files]; print(f"Parsed {len(files)} workflow files with PyYAML")'
    ```
  - `bash -n scripts/verify-federation.sh` passed.
  - `git diff --check` passed.
- Recorded integration checks:
  - `bash comercial/billing/test_drm_flow.sh` passed (5 checks).
  - `bash qos/scripts/test_integration_remote.sh` passed (9/9).
  - Imports for DRM/Billing and federation workflow dependencies passed. The
    exact import-check command was not retained in the run record.
  - The regression test was run against the unguarded cleanup first: it failed
    because cleanup emitted `REGISTRY_PID: unbound variable` after the expected
    prerequisite error (RED). In the follow-up, a temporary mutant replaced the
    guarded cleanup with `kill "$$"`; the unchanged command
    `python3 -m pytest scripts/test_verify_federation_cleanup.py -q` rejected it
    (1 failed at the no-kill assertion; the shim recorded `<485964>` and returned
    success). The mutated source was restored byte-for-byte. The same exact command
    passed after restoration (final rerun: `1 passed in 0.04s`). Temporary Python,
    Docker, and kill shims plus their logs were scoped to the test temporary directory.
    A temporary `BASH_ENV` disables Bash's `kill` builtin so the PATH shim records
    calls; no real process or container was targeted.
  - The added set-PID case runs the same prerequisite failure with
    `REGISTRY_PID=424242`; it asserts the Docker shim records only the existing
    `docker rm -f ...` cleanup, the kill shim records exactly `call:424242`, and
    no registry or relay startup messages occur. The missing-prerequisite exit
    precedes certificate handling, so the production `CERT_DIR` is untouched.
    With the guarded kill block temporarily removed, the suite reported
    `1 failed, 1 passed`; the set-PID test failed because the kill shim was not
    called. The script was restored byte-for-byte (SHA-256
    `c494316c17b99fb2cb563677ba85d40df5a1d196372439cff9544780c8290ca1`).
    The final exact CI command,
    `python3 -m pytest scripts/test_verify_federation_cleanup.py -q`, passed
    both tests.
    `git diff --check` passed.
    A second mutation replaced only `kill "$REGISTRY_PID"` with `kill "424242"`
    (mutant SHA-256 `558d043729d875c576bbbd1bae6e81fe5212e968de21b7cf2bff010669b6335c`).
    Running `python3 -m pytest scripts/test_verify_federation_cleanup.py -q`
    failed the `7654321` subtest as intended: expected `call:7654321`, received
    `call:424242`; pytest summary: `1 failed, 2 passed, 1 subtests passed in
    0.08s`. The original cleanup source was restored byte-for-byte, confirmed
    against SHA-256 `c494316c17b99fb2cb563677ba85d40df5a1d196372439cff9544780c8290ca1`.
    With the original source restored, the same test command passed:
    `2 passed, 2 subtests passed in 0.07s`. After updating this evidence, the
    final requested checks reported pytest `2 passed, 2 subtests passed in
    0.06s`; `git diff --check` and `git diff --cached --check` each exited 0
    with no output.
- The full local QoS integration run was not repeated because a pre-existing
  `moq-relay` container is in `Created` state and the integration network
  already exists. The GH run also reported genuine local failures: lip-sync
  captured no frames, and `measure-e2e.sh` failed latency. These failures remain
  unresolved; they were not skipped or converted to success by this change.

## Next

Investigate the QoS local no-frame and latency failures separately. Do not
weaken or skip those checks as part of this workflow reliability change.
