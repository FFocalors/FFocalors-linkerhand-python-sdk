# ADR 0004: Executable module boundaries and Windows CI

Status: accepted  
Date: 2026-08-23

## Decision

Console V2 keeps `app` as the frontend assembly layer. Features may depend on
themselves and shared/public contracts, but never on another feature. Shared
modules do not depend on product features or app assembly. Workers are kept at
the shared contract/runtime seam and may use only their own code, that seam,
or an explicit external package allowlist. These rules are checked by a
path-normalizing Node scanner so deep imports and Windows separators cannot
evade the check. ESLint repeats the same cross-feature/product restrictions as
editor feedback.

Rust business crates remain Tauri-free; `src-tauri` is the only Tauri owner.
The boundary check uses `cargo metadata` to check adapter direction and cycles.
The Python sidecar receives a lightweight import scan that rejects UI/feature
product-state imports.

The repository runs these checks and the complete frontend, Rust, sidecar,
contract, offline-asset, and build checks on Windows x64 in
`.github/workflows/console-v2.yml`. The workflow uses checked-in vision assets
and does not require hardware or download visual assets.

## Consequences

The module map is executable and has fixtures for both valid and invalid
imports. New shared or worker seams must be added to the checker allowlist
deliberately. This change modifies no public DTO, wire format, or generated
contract.
