# M1 integration handoff

- Branch: `codex/v2-rewrite`
- Base: `e2c087ee79cab97108eda83cdf6bc812aa18bce0`
- Integrated in order: runtime (`384012f`, `6083f3c`, `9413c08`), sidecar (`2e61ae6`, `697c8e4`, `7e60db9`, `40fb464`, `c60caca`, `8515f95`), UI shell (`f5aefd6`, `73b4e19`, `fbdd1e3`). Cherry-pick generated integration commits are visible in `git log`.
- Conflict: `apps/console-v2/.gitignore` was add/add. Retained Rust `/target/` plus frontend `node_modules/`, `dist/`, `coverage/`, `.vite/`, TypeScript build info, Vite timestamps, and logs. No runtime, sidecar, or UI source was discarded.

## Verification

- `cargo fmt --all -- --check` passed.
- `cargo test --workspace` passed: all Rust unit and doc tests, including app-runtime stop-all integration and bounded 100,000 log writes.
- `cargo clippy --workspace --all-targets -- -D warnings` passed.
- `uv run --with pytest --python 3.12 python -m pytest apps/console-v2/sidecar/linkerhand-bridge/tests` passed: 30 tests.
- In `apps/console-v2`, `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm lint`, `pnpm test`, and `pnpm build` passed. UI tests: 3 files / 4 tests.
- `cargo check -p linkerhand-console` passed.

## Known gaps

- Tauri shell remains an assembly skeleton and the UI still uses mock runtime data; no semantic contract changes were made during integration.
- Build/test outputs are ignored (`dist`, `node_modules`, Python caches, Rust `target`, and TypeScript build info); they are not part of the integration commit.
