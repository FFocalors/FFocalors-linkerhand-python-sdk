import { Channel, invoke, isTauri } from '@tauri-apps/api/core';
import type { AppError, ConsolePorts, DeviceCapabilities, DeviceConfig, JointTargetCommand, OperationSnapshot, TelemetrySnapshot } from './index';

const unsupported = (code: string, message: string): AppError => ({ code, message, retryable: false, details: null });
const unavailable = (name: string): Promise<never> => Promise.reject(unsupported('UNSUPPORTED', `${name} is not available in the runtime adapter`));

export const isTauriRuntime = () => isTauri();

/** Tauri 2 port implementation. Channel owns its callback and is detached on cleanup. */
export const tauriRuntime: ConsolePorts = {
  device: {
    getConfig: () => invoke<DeviceConfig>('config'),
    getCapabilities: () => invoke<DeviceCapabilities>('capabilities'),
    getConnection: () => invoke<Awaited<ReturnType<ConsolePorts['device']['getConnection']>>>('connection'),
    setJointTarget: (command: JointTargetCommand) => invoke<void>('set_joint_target', { command }),
    stopAll: () => invoke<void>('stop_all'),
    unlock: () => invoke<void>('unlock'),
  },
  motion: {
    getOperation: () => invoke<OperationSnapshot>('operation'),
    runAction: () => unavailable('action playback'),
    pause: () => unavailable('motion pause'),
  },
  telemetry: {
    read: () => invoke<TelemetrySnapshot>('telemetry_read'),
    subscribe(listener: (value: TelemetrySnapshot) => void) {
      const channel = new Channel<TelemetrySnapshot>(listener);
      let cancelled = false;
      let registered = false;
      const unsubscribe = () => invoke<void>('telemetry_unsubscribe', { channelId: channel.id }).catch(() => undefined);
      void invoke<void>('telemetry_subscribe', { channel }).then(() => {
        registered = true;
        if (cancelled) void unsubscribe();
      }).catch(() => { channel.onmessage = () => undefined; });
      return () => {
        cancelled = true;
        channel.onmessage = () => undefined;
        if (registered) void unsubscribe();
      };
    },
  },
  actions: { list: () => unavailable('action list'), delete: () => unavailable('action deletion') },
  grasp: { listPresets: () => unavailable('grasp presets'), runPreset: () => unavailable('grasp execution') },
  vision: { propose: () => unavailable('vision proposals'), sync: () => unavailable('vision sync') },
  logs: { list: () => unavailable('runtime logs') },
};
