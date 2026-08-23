import { Channel, invoke, isTauri } from '@tauri-apps/api/core';
import type { AppError, ConsolePorts, DeviceCapabilities, DeviceConfig, JointTargetCommand, OperationSnapshot, TelemetrySnapshot } from './index';

/** Runtime wire events stay feature-agnostic; app composition maps them to feature-local state. */
export type TauriActionState = { state: 'idle' | 'recording' | 'recordingPaused' | 'playing' | 'paused' | 'completed' | 'cancelled' | 'error'; actionId?: string; progress: number; detail?: string };
export type TauriGraspPhase = 'idle' | 'calibrating' | 'ready' | 'approach' | 'closingCoarse' | 'closingFine' | 'preloading' | 'holding' | 'releasing' | 'aborted' | 'failed';
export type TauriGraspJointState = 'idle' | 'closingCoarse' | 'closingFine' | 'contactCandidate' | 'contactConfirmed' | 'frozen' | 'limitReached' | 'error';
export type TauriGraspState = { phase: TauriGraspPhase; failure?: { code: string; message: string }; tactileAvailable: boolean; rawTouch?: number[] | null; degraded: boolean; joints?: { index: number; state: TauriGraspJointState; contactScore: number }[] };

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
  motionCancelSource: (source: 'vision' | 'rockPaperScissors' | 'loop' | 'playback' | 'grasp', _reason?: string) => invoke<void>('motion_cancel_source', { source }),
  actions: {
    startRecording: (name: string) => invoke<void>('action_start_recording', { name }), pauseRecording: () => invoke<void>('action_pause_recording'), resumeRecording: () => invoke<void>('action_resume_recording'), finishRecording: () => invoke<void>('action_finish_recording'), cancelRecording: () => invoke<void>('action_cancel_recording'),
    play: (id: string, options: { speed: number; loopCount: number | null }) => invoke<void>('action_play', { id, speed: options.speed, loopEnabled: options.loopCount !== 0, loopCount: options.loopCount }), pause: () => invoke<void>('action_pause'), resume: () => invoke<void>('action_resume'), stop: () => invoke<void>('action_stop'),
    subscribe: (listener: (value: TauriActionState) => void) => subscribeChannel('action_subscribe', 'action_unsubscribe', listener),
  },
  grasp: {
    calibrate: () => invoke<void>('grasp_calibrate'), completeCalibration: () => invoke<void>('grasp_complete_calibration'), approach: () => invoke<void>('grasp_approach'), startGrasp: (preset: string, degraded: boolean) => invoke<void>('grasp_start', { preset, degraded }), release: () => invoke<void>('grasp_release'), abort: () => invoke<void>('grasp_abort'),
    subscribe: (listener: (value: TauriGraspState) => void) => subscribeChannel('grasp_subscribe', 'grasp_unsubscribe', listener),
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
    runAction: (id: string) => invoke<void>('action_play', { id, speed: 1, loopEnabled: false, loopCount: null }),
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
  grasp: { listPresets: () => invoke('grasp_presets'), runPreset: () => invoke<void>('grasp_start', { preset: 'cube', degraded: false }) },
  vision: { propose: () => unavailable('vision proposals'), sync: () => unavailable('vision sync') },
  logs: { list: (limit = 20) => invoke('logs_list', { limit: Math.min(limit, 512) }) },
};
