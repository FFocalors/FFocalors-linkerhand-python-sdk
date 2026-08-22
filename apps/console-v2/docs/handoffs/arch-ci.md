# Architecture and Windows CI handoff

## Scope

This handoff adds engineering governance only: frontend/Rust/Python boundary
checks, matching ESLint restrictions, boundary fixtures, and a Windows x64 CI
workflow. Public contracts were not modified (`修改公共契约=否`).

## Checks

From `apps/console-v2`:

- `pnpm test:boundaries` proves legal and illegal feature, worker, sidecar, and
  Rust metadata fixtures.
- `pnpm check:boundaries` checks the real frontend tree, Python sidecar, and
  Rust workspace (`cargo metadata`).
- `.github/workflows/console-v2.yml` runs these checks with cargo fmt/test/
  clippy/check, sidecar pytest, pnpm frozen install, typecheck, lint, tests,
  contracts, offline assets, and frontend build on Windows x64.

The workflow uses the checked-in vision asset manifest. It does not require
hardware or invoke the vision asset downloader.

## Integration note

This work is isolated on `codex/v2-m5-arch-ci` from integration baseline
`e421e7a3d27a8ee31a1fa739603dbc3a7da50ba7`. No runtime behavior, DTO, or wire
contract changed.
