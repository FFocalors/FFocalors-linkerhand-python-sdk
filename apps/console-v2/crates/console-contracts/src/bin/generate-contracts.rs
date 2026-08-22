use console_contracts::{
    ActionRecording, AppError, CommandSource, ConnectionSnapshot, ConnectionState,
    DeviceCapabilities, DeviceConfig, DeviceModel, GraspPreset, Hand, JointTargetCommand, LogLevel,
    MessageType, OperationSnapshot, OperationState, RawRange, SidecarOperation, StructuredLogEntry,
    TelemetrySnapshot, Transport, VectorCapability, VisionPoseProposal, CURRENT_SCHEMA_VERSION,
    RAW_MAX, RAW_MIN,
};
use std::io::{self, Write};
use ts_rs::TS;

const HEADER: &str = "// GENERATED FILE. Do not edit; run `pnpm generate:contracts`.\n// Source: crates/console-contracts/src/lib.rs\n";

fn declaration<T: TS>() -> String {
    let declaration = T::decl();
    let declaration = declaration
        .lines()
        .map(str::trim_end)
        .collect::<Vec<_>>()
        .join("\n");
    format!("export {declaration}\n")
}

fn main() -> io::Result<()> {
    let mut output = String::from(HEADER);
    output.push_str(&format!(
        "export const CURRENT_SCHEMA_VERSION = {CURRENT_SCHEMA_VERSION} as const;\n"
    ));
    output.push_str(&format!("export const RAW_MIN = {RAW_MIN} as const;\n"));
    output.push_str(&format!("export const RAW_MAX = {RAW_MAX} as const;\n\n"));

    // Every declaration below is rendered from the Rust type's TS metadata.
    // Keep this list explicit so the public projection is reviewable while its
    // fields, serde names, and enum values remain owned by lib.rs.
    output.push_str(&declaration::<DeviceModel>());
    output.push_str(&declaration::<Hand>());
    output.push_str(&declaration::<Transport>());
    output.push_str(&declaration::<ConnectionState>());
    output.push_str(&declaration::<CommandSource>());
    output.push_str(&declaration::<OperationState>());
    output.push_str(&declaration::<LogLevel>());
    output.push_str(&declaration::<SidecarOperation>());
    output.push_str(&declaration::<MessageType>());
    output.push_str(&declaration::<RawRange>());
    output.push_str(&declaration::<VectorCapability>());
    output.push_str(&declaration::<DeviceConfig>());
    output.push_str(&declaration::<DeviceCapabilities>());
    output.push_str(&declaration::<AppError>());
    output.push_str(&declaration::<ConnectionSnapshot>());
    output.push_str(&declaration::<JointTargetCommand>());
    output.push_str(&declaration::<TelemetrySnapshot>());
    output.push_str(&declaration::<OperationSnapshot>());
    output.push_str(&declaration::<StructuredLogEntry>());
    output.push_str(&declaration::<ActionRecording>());
    output.push_str(&declaration::<VisionPoseProposal>());
    output.push_str(&declaration::<GraspPreset>());

    // ts-rs v10 cannot emit an unconstrained generic declaration. This is the
    // only intentionally thin wrapper; its field names/types are still tested
    // against WireEnvelope<T>'s serde JSON in console-contracts.
    output.push_str(
        "export interface WireEnvelope<T> { schemaVersion: number; messageType: MessageType; requestId: string; sequence: number; monotonicTimeMs: number; operation: SidecarOperation; payload: T }\n",
    );

    io::stdout().write_all(output.as_bytes())
}
