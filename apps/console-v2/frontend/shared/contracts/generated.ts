// GENERATED FILE. Do not edit; run `pnpm generate:contracts`.
// Source: crates/console-contracts/src/lib.rs
export const CURRENT_SCHEMA_VERSION = 1 as const;
export const RAW_MIN = 0 as const;
export const RAW_MAX = 255 as const;

export type DeviceModel = 'O6' | 'L6' | 'L7' | 'L10' | 'L20' | 'G20' | 'L21' | 'L25';
export type Hand = 'left' | 'right';
export type Transport = { type: 'can'; channel: string } | { type: 'rs485'; port: string; baudrate: number };
export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error';
export type CommandSource = 'manual' | 'preset' | 'playback' | 'loop' | 'vision' | 'rockPaperScissors' | 'grasp' | 'safety';
export type OperationState = 'idle' | 'running' | 'stopping' | 'locked' | 'paused' | 'completed' | 'cancelled' | 'error';
export type LogLevel = 'trace' | 'debug' | 'info' | 'warn' | 'error';
export type SidecarOperation = 'connect' | 'disconnect' | 'capabilities' | 'getTelemetry' | 'getPosition' | 'getCurrent' | 'getSpeed' | 'getTouch' | 'setPosition' | 'setSpeed' | 'setCurrent' | 'setTorque' | 'stop' | 'unlock' | 'close';
export type MessageType = 'request' | 'command' | 'response' | 'event' | 'error';

export interface RawRange { min: number; max: number }
export interface VectorCapability { length: number; available: boolean; range: RawRange }
export interface DeviceConfig { schemaVersion: number; deviceId: string; name: string; model: DeviceModel; hand: Hand; transport: Transport; autoReconnect: boolean }
export interface DeviceCapabilities { schemaVersion: number; deviceId: string; model: DeviceModel; hand: Hand; transport: Transport; jointCount: number; position: VectorCapability; speed: VectorCapability; current: VectorCapability; torque: VectorCapability; touch: VectorCapability; speedCommandLength: number; currentCommandLength: number | null; torqueCommandLength: number | null; supportedOperations: SidecarOperation[] }
export interface AppError { code: string; message: string; retryable: boolean; details?: unknown }
export interface ConnectionSnapshot { schemaVersion: number; deviceId: string; state: ConnectionState; attempt: number; lastError: AppError | null }
export interface JointTargetCommand { schemaVersion: number; commandId: string; source: CommandSource; positions: number[]; durationMs?: number | null; finalCommand: boolean }
export interface TelemetrySnapshot { schemaVersion: number; deviceId: string; sequence: number; monotonicTimeMs: number; positions: number[]; rawPosition: number[]; rawCurrent: number[]; rawSpeed: number[]; rawTouch: number[]; connected: boolean }
export interface OperationSnapshot { schemaVersion: number; operationId: string; kind: string; state: OperationState; progress: number; detail?: string | null }
export interface StructuredLogEntry { schemaVersion: number; id: string; monotonicTimeMs: number; level: LogLevel; event: string; message: string; fields: Record<string, unknown> }
export interface ActionRecording { schemaVersion: number; id: string; name: string; frames: JointTargetCommand[]; durationMs: number; steps: number; updatedAt: string }
export interface VisionPoseProposal { schemaVersion: number; id: string; label: string; confidence: number; positions: number[]; expiresAtMonotonicMs?: number | null }
export interface GraspPreset { id: string; name: string; description: string }
export interface WireEnvelope<T> { schemaVersion: number; messageType: MessageType; requestId: string; sequence: number; monotonicTimeMs: number; operation: SidecarOperation; payload: T }
