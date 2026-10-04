# Player production configuration

## Intent

Restore the production player at `/player/` by fixing its asset paths and the
WebTransport relay configuration.

## Scope

- In: player production asset base, relay URL and certificate-hash build value;
  focused regression tests and player documentation.
- Out: production deployment, relay/network operations and unrelated player changes.

## Checklist

- [x] Build player assets with paths that resolve below `/player/`; prove with
  the production build output.
- [x] Configure the production relay as an HTTPS WebTransport endpoint and
  avoid emitting an unresolved certificate-hash placeholder; prove with the
  built configuration.
- [x] Document the production player/relay behavior and run focused tests.

## Evidence

`npm --prefix player run build` completed successfully. Its HTML references
`./assets/...`, which resolves beneath `/player/`. `python3 -m pytest
player/test_player_html.py -q` passed (6 tests, 5 subtests); production output
assertions cover the HTTPS relay URL, `anon/live1`, an empty certificate hash,
and no unexpanded placeholder. The dev-server test confirms `/src/bootstrap.ts`
resolves at the root. Temporary mutations for production paths/config, Dockerfile
ENV overrides in both syntaxes, and a dev-only base prefix were rejected.
`git diff --check` passed. The refuter-tests agent verified the scoped diff
fingerprint and checks and reported zero findings. Correctness and security
refuters reported zero scoped findings but could not independently execute
checks or verify the fingerprint. Build emitted non-blocking dependency-comment
and chunk-size warnings. The deployed service has not been rebuilt or deployed.

## Next

Request authorization before publishing or deploying; production has not been
changed.
