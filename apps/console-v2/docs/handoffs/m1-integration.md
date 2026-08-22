# M1 contract integration handoff

## Integration point

- Branch: `codex/v2-rewrite`
- Integration base: `643a502` (`docs(console-v2): record browser visual acceptance`)
- Contract-freeze source branch: `codex/v2-m1-contract-freeze`
- Contract-freeze source tip integrated before this handoff: `3814134`
- Cherry-picked integration tip before this handoff: `5d7481f`
- The existing browser visual-acceptance commit and its content remain in the branch history.

The freeze commits were cherry-picked in source order: `9e8334e`, `6a768e6`,
`22c9137`, `b2986c6`, `e38ac31`, `2e7897a`, `3fed195`, `3814134`.
Their integration hashes are respectively `6d6d5f8`, `8e3a62c`, `2f71b44`,
`f612a4a`, `2b486a4`, `d9bb5c0`, `600eb70`, and `5d7481f`.

## What is integrated

Rust `console-contracts` is the sole public domain source. `ts-rs` derives the
checked-in TypeScript projection; `pnpm check:contracts` runs the Rust generator
and detects drift. The tagged CAN/RS485 transport, strict sidecar envelope,
normalized joint vectors, raw vector mapper, telemetry/error DTOs, model fixture,
software stop/unlock barrier, UI facade Ports, and the documented generic
`WireEnvelope<T>` wrapper are all included.

The handoff preserves the existing UI visual acceptance work. No new product
feature or contract semantic change was introduced during integration.

The pre-freeze integration record remains: the earlier runtime commits were
`384012f`, `6083f3c`, `9413c08`; sidecar commits were `2e61ae6`, `697c8e4`,
`7e60db9`, `40fb464`, `c60caca`, `8515f95`; and UI-shell commits were
`f5aefd6`, `73b4e19`, `fbdd1e3`. Its `.gitignore` add/add conflict retained
Rust `target/` and frontend build/cache ignores; no runtime, sidecar, UI, or
visual-acceptance source was discarded.

## Verification

From `apps/console-v2` on `codex/v2-rewrite`:

- `cargo test --workspace` passed.
- `cargo clippy --workspace --all-targets -- -D warnings` passed.
- `python -m pytest -q` in `sidecar/linkerhand-bridge` passed.
- `pnpm check:contracts` passed after regenerating the checked-in projection and refreshing the Git index; the generated file content hash matches HEAD.
- `pnpm typecheck` passed.
- `pnpm lint` passed.
- `pnpm test` passed: 3 files / 4 tests.
- `pnpm build` passed.

The earlier handoff also verified `cargo fmt --all -- --check`, `pnpm
install --frozen-lockfile`, `cargo check -p linkerhand-console`, and the
sidecar suite through the Python 3.12 test runner.

The Rust/ts-rs build emits a non-fatal note that `skip_serializing_if` is not
parsed by the metadata helper. The explicit `#[ts(...)]` override, Rust serde
tests, and checked-in projection regression protect the resulting `AppError`
shape. This is a generator limitation, not an integration mismatch.

## Post-handoff checks

The integration worktree is clean after the handoff commit. Future changes to
public DTOs or serde names must update Rust metadata first, run
`pnpm generate:contracts`, and keep `pnpm check:contracts` in CI.

Known remaining gaps are unchanged: the Tauri shell is still an assembly
skeleton, the UI uses mock runtime data, and build/test outputs remain ignored
(`dist`, `node_modules`, Python caches, Rust `target`, and TypeScript build
info).
