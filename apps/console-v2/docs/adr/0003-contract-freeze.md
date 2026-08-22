# ADR 0003: Contract freeze and generated UI projection

Status: accepted  
Date: 2026-08-23

## Decision

`crates/console-contracts` is the only public domain-type source for Console V2. Its serde names are the wire names, and `generate-contracts` projects those types to the checked-in `frontend/shared/contracts/generated.ts`. `pnpm check:contracts` fails when the projection drifts.

The supported device set is exactly `O6`, `L6`, `L7`, `L10`, `L20`, `G20`, `L21`, and `L25`. Configuration carries `deviceId`, model, `hand`, a tagged CAN/RS485 transport, and `autoReconnect`. Public positions are normalized `0..=1`; raw SDK vectors are explicitly named `raw*` and remain `0..=255` at the sidecar seam. Conversion uses round/clamp with exact vector-length checks.

The canonical telemetry DTO does not invent temperature or aggregate current fields. It carries normalized positions and raw position/current/speed/touch vectors. Errors are `{code,message,retryable,details?}`. The strict envelope supports request/command/response/event/error and requires every transport field.

Sidecar `stop` is a software write barrier. It locks `set*` operations until explicit `unlock`; it is not a physical emergency stop. Runtime stop/unlock must fan out through Motion, Action, Grasp, Vision, and the internal sidecar port. UI-facing facade ports are separate from the internal sidecar dependency.

## Consequences

The UI must render normalized percentages and handle unavailable capabilities instead of assuming degrees, mA, or temperature. A future adapter owns normalized/raw conversion and model-specific lengths. Cross-language raw capability facts are snapshotted in `docs/contracts/raw-capabilities.json` and tested by Rust and Python.
