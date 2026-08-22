import { Channel, invoke, isTauri } from '@tauri-apps/api/core';
import type { ActionControllerState } from '../../features/actions';
import type { GraspControllerState } from '../../features/smart-grasp';
import type { AppError, ConsolePorts, DeviceCapabilities, DeviceConfig, JointTargetCommand, OperationSnapshot, TelemetrySnapshot } from './index';

const unsupported = (code: string, message: string): AppError => ({ code, message, retryable: false, details: null });
const unavailable = (name: string): Promise<never> => Promise.reject(unsupported('UNSUPPORTED', `${name} is not available in the runtime adapter`));

export const isTauriRuntime = () => isTauri();

const subscribeChannel = <T>(subscribeCommand: string, unsubscribeCommand: string, listener: (value: T) => void) => {
  const channel = new Channel<T>(listener);
  let registered = false;
  let cancelled = false;
  const unsubscribe = () => invoke<void>(unsubscribeCommand, { channelId: channel.id }).catch(() => undefined);
  void invoke<void>(subscribeCommand, { channel }).then(() => { registered = true; if (cancelled) void unsubscribe(); }).catch(() => { channel.onmessage = () => undefined; });
  return () => { cancelled = true; channel.onmessage = () => undefined; if (registered) void unsubscribe(); };
};

export const tauriRuntimeExtras = {
  device: {
    connect: () => invoke<Awaited<ReturnType<ConsolePorts['device']['getConnection']>>>('connect'),
    disconnect: () => invoke<Awaited<ReturnType<ConsolePorts['device']['getConnection']>>>('disconnect'),
    reconnect: () => invoke<Awaited<ReturnType<ConsolePorts['device']['getConnection']>>>('reconnect'),
    setSpeed: (command: { values: number[]; finalCommand: boolean }) => invoke<void>('set_speed', { command }),
    setTorque: (command: { values: number[]; finalCommand: boolean }) => invoke<void>('set_torque', { command }),
    subscribeConnection: (listener: (value: Awaited<ReturnType<ConsolePorts['device']['getConnection']>>) => void) => subscribeChannel('connection_subscribe', 'connection_unsubscribe', listener),
    subscribeOperation: (listener: (value: OperationSnapshot) => void) => subscribeChannel('operation_subscribe', 'operation_unsubscribe', listener),
  },
  actions: {
    startRecording: (name: string) => invoke<void>('action_start_recording', { name }), pauseRecording: () => invoke<void>('action_pause_recording'), resumeRecording: () => invoke<void>('action_resume_recording'), finishRecording: () => invoke<void>('action_finish_recording'), cancelRecording: () => invoke<void>('action_cancel_recording'),
    play: (id: string, options: { speed: number; loopCount: number | null }) => invoke<void>('action_play', { id, speed: options.speed, loopCount: options.loopCount === null ? 1000 : options.loopCount }), pause: () => invoke<void>('action_pause'), resume: () => invoke<void>('action_resume'), stop: () => invoke<void>('action_stop'),
    subscribe: (listener: (value: ActionControllerState) => void) => subscribeChannel('action_subscribe', 'action_unsubscribe', listener),
  },
  grasp: {
    calibrate: () => invoke<void>('grasp_calibrate'), completeCalibration: () => invoke<void>('grasp_complete_calibration'), approach: () => invoke<void>('grasp_approach'), startGrasp: (degraded: boolean) => invoke<void>('grasp_start', { degraded }), release: () => invoke<void>('grasp_release'), abort: () => invoke<void>('grasp_abort'),
    subscribe: (listener: (value: GraspControllerState) => void) => subscribeChannel('grasp_subscribe', 'grasp_unsubscribe', listener),
  },
};

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
    runAction: (id: string) => invoke<void>('action_play', { id, speed: 1, loopCount: 0 }),
    pause: () => invoke<void>('action_pause'),
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
  actions: { list: () => invoke('action_list'), delete: (id: string) => invoke<void>('action_delete', { id }) },
  grasp: { listPresets: () => invoke('grasp_presets'), runPreset: () => invoke<void>('grasp_start', { degraded: false }) },
  vision: { propose: () => unavailable('vision proposals'), sync: () => unavailable('vision sync') },
  logs: { list: (limit = 20) => invoke('logs_list', { limit: Math.min(limit, 512) }) },
};
