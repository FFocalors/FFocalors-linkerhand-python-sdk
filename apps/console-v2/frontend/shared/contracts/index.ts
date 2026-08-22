export * from './generated';
import type { ActionRecording, AppError, ConnectionSnapshot, DeviceCapabilities, DeviceConfig, GraspPreset, JointTargetCommand, OperationSnapshot, StructuredLogEntry, TelemetrySnapshot, VisionPoseProposal } from './generated';

export interface DevicePort {
  getConfig(): Promise<DeviceConfig>;
  getCapabilities(): Promise<DeviceCapabilities>;
  getConnection(): Promise<ConnectionSnapshot>;
  setJointTarget(command: JointTargetCommand): Promise<void>;
  stopAll(): Promise<void>;
  unlock(): Promise<void>;
}
export interface MotionPort { getOperation(): Promise<OperationSnapshot>; runAction(id: string): Promise<void>; pause(): Promise<void> }
export interface TelemetryPort { read(): Promise<TelemetrySnapshot>; subscribe(listener: (value: TelemetrySnapshot) => void): () => void }
export interface ActionPort { list(): Promise<ActionRecording[]>; delete(id: string): Promise<void> }
export interface GraspPort { listPresets(): Promise<GraspPreset[]>; runPreset(id: string): Promise<void> }
export interface VisionPort { propose(source: 'vision' | 'rps'): Promise<VisionPoseProposal[]>; sync(proposal: VisionPoseProposal): Promise<void> }
export interface LogPort { list(limit?: number): Promise<StructuredLogEntry[]> }
export type ConsoleError = AppError;
export interface ConsolePorts { device: DevicePort; motion: MotionPort; telemetry: TelemetryPort; actions: ActionPort; grasp: GraspPort; vision: VisionPort; logs: LogPort }
export { isTauriRuntime, tauriRuntime } from './tauri-runtime';
