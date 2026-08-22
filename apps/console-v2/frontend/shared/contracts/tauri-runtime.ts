import type { ActionRecording, AppError, ConsolePorts, DeviceCapabilities, DeviceConfig, GraspPreset, JointTargetCommand, OperationSnapshot, StructuredLogEntry, TelemetrySnapshot, VisionPoseProposal } from './index';

type TauriInvoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
type TauriWindow = Window & { __TAURI_INTERNALS__?: { invoke?: TauriInvoke } };
const invoke = (): TauriInvoke => {
  const fn = (window as TauriWindow).__TAURI_INTERNALS__?.invoke;
  if (!fn) throw unsupported('TAURI_UNAVAILABLE', 'Tauri runtime is not installed');
  return fn;
};
const unsupported = (code: string, message: string): AppError => ({ code, message, retryable: false, details: null });
const unavailable = (name: string): Promise<never> => Promise.reject(unsupported('UNSUPPORTED', `${name} is not available in the runtime adapter`));

export const isTauriRuntime = () => typeof window !== 'undefined' && typeof (window as TauriWindow).__TAURI_INTERNALS__?.invoke === 'function';

/** Tauri 2 port implementation. Every supported method delegates to a typed
 * command; feature methods without a Rust facade fail explicitly. */
export const tauriRuntime: ConsolePorts = {
  device: {
    getConfig: () => invoke()<DeviceConfig>('config'),
    getCapabilities: () => invoke()<DeviceCapabilities>('capabilities'),
    getConnection: () => invoke<ReturnType<ConsolePorts['device']['getConnection']> extends Promise<infer T> ? T : never>('connection'),
    setJointTarget: (command: JointTargetCommand) => invoke<void>('set_joint_target', { command }),
    stopAll: () => invoke<void>('stop_all'),
    unlock: () => invoke<void>('unlock'),
  },
  motion: {
    getOperation: () => unavailable('motion operation'),
    runAction: () => unavailable('action playback'),
    pause: () => unavailable('motion pause'),
  },
  telemetry: {
    read: () => unavailable('telemetry read'),
    subscribe: () => () => undefined,
  },
  actions: {
    list: () => unavailable('action list'),
    delete: () => unavailable('action deletion'),
  },
  grasp: {
    listPresets: () => unavailable('grasp presets'),
    runPreset: () => unavailable('grasp execution'),
  },
  vision: {
    propose: () => unavailable('vision proposals'),
    sync: () => unavailable('vision sync'),
  },
  logs: { list: () => unavailable('runtime logs') },
};

// Keep DTO imports visible to the compiler for the adapter contract snapshot.
void (0 as unknown as ActionRecording[] | GraspPreset[] | OperationSnapshot | StructuredLogEntry[] | TelemetrySnapshot[] | VisionPoseProposal[]);
