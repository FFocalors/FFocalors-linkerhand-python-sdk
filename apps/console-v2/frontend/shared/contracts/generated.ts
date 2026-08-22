// GENERATED FILE. Do not edit; run `pnpm generate:contracts`.
// Source: crates/console-contracts/src/lib.rs
export const CURRENT_SCHEMA_VERSION = 1 as const;
export const RAW_MIN = 0 as const;
export const RAW_MAX = 255 as const;

export type DeviceModel = "O6" | "L6" | "L7" | "L10" | "L20" | "G20" | "L21" | "L25";
export type Hand = "left" | "right";
export type Transport = { "type": "can", channel: string, } | { "type": "rs485", port: string, baudrate: number, };
export type ConnectionState = "disconnected" | "connecting" | "connected" | "reconnecting" | "error";
export type CommandSource = "manual" | "preset" | "playback" | "loop" | "vision" | "rockPaperScissors" | "grasp" | "safety";
export type OperationState = "idle" | "running" | "stopping" | "locked" | "paused" | "completed" | "cancelled" | "error";
export type LogLevel = "trace" | "debug" | "info" | "warn" | "error";
export type SidecarOperation = "connect" | "disconnect" | "capabilities" | "getTelemetry" | "getPosition" | "getCurrent" | "getSpeed" | "getTouch" | "setPosition" | "setSpeed" | "setCurrent" | "setTorque" | "stop" | "unlock" | "close";
export type MessageType = "request" | "command" | "response" | "event" | "error";
export type RawRange = { min: number, max: number, };
export type VectorCapability = { length: number, available: boolean, range: RawRange, };
export type DeviceConfig = { schemaVersion: number, deviceId: string, name: string, model: DeviceModel, hand: Hand, transport: Transport, autoReconnect: boolean, };
export type DeviceCapabilities = { schemaVersion: number, deviceId: string, model: DeviceModel, hand: Hand, transport: Transport, jointCount: number, position: VectorCapability, speed: VectorCapability, current: VectorCapability, torque: VectorCapability, touch: VectorCapability, speedCommandLength: number, currentCommandLength: number | null, torqueCommandLength: number | null, supportedOperations: Array<SidecarOperation>, };
export type AppError = { code: string, message: string, retryable: boolean, details?: unknown, };
export type ConnectionSnapshot = { schemaVersion: number, deviceId: string, state: ConnectionState, attempt: number, lastError: AppError | null, };
export type JointTargetCommand = { schemaVersion: number, commandId: string, source: CommandSource,
/**
 * Complete joint vector in normalized `0.0..=1.0` position units.
 */
positions: Array<number>, durationMs?: number | null, finalCommand: boolean, };
export type TelemetrySnapshot = { schemaVersion: number, deviceId: string, sequence: number, monotonicTimeMs: number, positions: Array<number>, rawPosition: Array<number>, rawCurrent: Array<number>, rawSpeed: Array<number>, rawTouch: Array<number>, connected: boolean, };
export type OperationSnapshot = { schemaVersion: number, operationId: string, kind: string, state: OperationState, progress: number, detail?: string | null, };
export type StructuredLogEntry = { schemaVersion: number, id: string, monotonicTimeMs: number, level: LogLevel, event: string, message: string, fields: Record<string, unknown>, };
export type ActionRecording = { schemaVersion: number, id: string, name: string, frames: Array<JointTargetCommand>, durationMs: number, steps: number, updatedAt: string, };
export type VisionPoseProposal = { schemaVersion: number, id: string, label: string, confidence: number, positions: Array<number>, expiresAtMonotonicMs?: number | null, };
export type GraspPreset = { id: string, name: string, description: string, };
export interface WireEnvelope<T> { schemaVersion: number; messageType: MessageType; requestId: string; sequence: number; monotonicTimeMs: number; operation: SidecarOperation; payload: T }
