export type DeviceModel = 'O6' | 'L7' | 'L12';
export type ConnectionState = 'connected' | 'connecting' | 'disconnected';
export type OperationState = 'idle' | 'running' | 'locked' | 'error';

export interface DeviceConfig { id: string; name: string; model: DeviceModel; address: string; }
export interface DeviceCapabilities { model: DeviceModel; jointCount: number; visionSync: boolean; tactile: boolean; }
export interface ConnectionSnapshot { state: ConnectionState; latencyMs: number; lastSeen: string; }
export interface JointTargetCommand { joint: string; value: number; }
export interface TelemetrySnapshot { timestamp: number; joints: Record<string, number>; currentMa: number; temperatureC: number; }
export interface OperationSnapshot { state: OperationState; label: string; progress: number; }
export interface StructuredLogEntry { id: string; time: string; level: 'info' | 'warn' | 'error'; message: string; source: string; }
export interface AppError { code: string; message: string; recoverable: boolean; }
export interface ActionRecording { id: string; name: string; durationMs: number; steps: number; updatedAt: string; }
export interface VisionPoseProposal { id: string; label: string; confidence: number; joints: Record<string, number>; }

export interface DevicePort { getConfig(): Promise<DeviceConfig>; getCapabilities(): Promise<DeviceCapabilities>; getConnection(): Promise<ConnectionSnapshot>; setJointTarget(command: JointTargetCommand): Promise<void>; stopAll(): Promise<void>; unlock(): Promise<void>; }
export interface MotionPort { getOperation(): Promise<OperationSnapshot>; runAction(id: string): Promise<void>; pause(): Promise<void>; }
export interface TelemetryPort { read(): Promise<TelemetrySnapshot>; subscribe(listener: (value: TelemetrySnapshot) => void): () => void; }
export interface ActionPort { list(): Promise<ActionRecording[]>; delete(id: string): Promise<void>; }
export interface GraspPort { listPresets(): Promise<{ id: string; name: string; description: string }[]>; runPreset(id: string): Promise<void>; }
export interface VisionPort { propose(source: 'vision' | 'rps'): Promise<VisionPoseProposal[]>; sync(proposal: VisionPoseProposal): Promise<void>; }
export interface LogPort { list(limit?: number): Promise<StructuredLogEntry[]>; }
export interface ConsolePorts { device: DevicePort; motion: MotionPort; telemetry: TelemetryPort; actions: ActionPort; grasp: GraspPort; vision: VisionPort; logs: LogPort; }
