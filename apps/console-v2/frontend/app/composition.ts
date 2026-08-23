import type { ActionController, ActionControllerState } from '../features/actions';
import type { DeviceControlController } from '../features/device-control';
import type { GraspController, GraspControllerState } from '../features/smart-grasp';
import type { ConnectionSnapshot, ConsolePorts, JointTargetCommand, OperationSnapshot } from '../shared/contracts';
import { isTauriRuntime, tauriRuntime } from '../shared/contracts';
import { tauriRuntimeExtras } from '../shared/contracts/tauri-runtime';
import { mockRuntime } from '../shared/contracts/mock-runtime';
import { VisionRuntime } from '../shared/vision-runtime';
import { createRpsActionController, createVisionProposalController } from './controllers';
import { createSettingsController, createThemePort } from './settings';
import type { SettingsController, ThemePort } from '../features/settings';
import type { VisionProposalController, VisionRuntimeLike } from '../features/vision';
import type { RpsActionController } from '../features/rock-paper-scissors/types';
import VisionWorker from '../workers/vision-worker/index?worker&classic';

export type ConsoleComposition = ConsolePorts & {
  deviceController: DeviceControlController;
  actionController: ActionController;
  graspController: GraspController;
  simulator: boolean;
  visionRuntime: VisionRuntimeLike;
  visionProposalController: VisionProposalController;
  rpsActionController: RpsActionController;
  createRpsActionController: (capabilities: import('../shared/contracts').DeviceCapabilities) => RpsActionController;
  settingsController: SettingsController;
  themePort: ThemePort;
};

const simulatorConnection = (runtime: ConsolePorts, deviceId: string): ConnectionSnapshot => ({ schemaVersion: 1, deviceId, state: 'connected', attempt: 1, lastError: null });
const stateListeners = <T>() => {
  const listeners = new Set<(value: T) => void>();
  return { add: (listener: (value: T) => void) => { listeners.add(listener); return () => listeners.delete(listener); }, emit: (value: T) => listeners.forEach(listener => listener(value)) };
};

export function createDeviceController(runtime: ConsolePorts, simulator: boolean, extras?: typeof tauriRuntimeExtras.device): DeviceControlController {
  let connection: ConnectionSnapshot | undefined;
  const connections = stateListeners<ConnectionSnapshot>();
  const operations = stateListeners<OperationSnapshot>();
  const actionExtras = simulator ? undefined : tauriRuntimeExtras.actions;
  const device = runtime.device;
  const refresh = async () => { connection = await device.getConnection(); connections.emit(connection); return connection; };
  const callConnection = async (action: 'connect' | 'disconnect' | 'reconnect') => {
    if (simulator) { connection = simulatorConnection(runtime, (await runtime.device.getConfig()).deviceId); if (action === 'disconnect') connection = { ...connection, state: 'disconnected' }; connections.emit(connection); return; }
    if (action === 'connect' && extras) connection = await extras.connect();
    else if (action === 'disconnect' && extras) connection = await extras.disconnect();
    else if (action === 'reconnect' && extras) connection = await extras.reconnect();
    else connection = await refresh();
    connections.emit(connection);
  };
  return {
    connect: () => callConnection('connect'), disconnect: () => callConnection('disconnect'), reconnect: () => callConnection('reconnect'),
    subscribeConnection(listener) { const remove = connections.add(listener); const remote = extras?.subscribeConnection(listener); void refresh(); return () => { remove(); remote?.(); }; },
    setJointTarget: (command: JointTargetCommand) => runtime.device.setJointTarget(command),
    setSpeed: command => extras ? extras.setSpeed(command) : Promise.resolve(),
    setTorque: command => extras ? extras.setTorque(command) : Promise.resolve(),
    startQuickAction: async (id) => {
      if (actionExtras) { await actionExtras.play(id, { speed: 1, loopCount: 0 }); return; }
      await runtime.motion.runAction(id);
      operations.emit({ schemaVersion: 1, operationId: id, kind: 'quick-action', state: 'running', progress: 0, detail: '动作引擎执行中' });
      // Simulator completes a quick action shortly after starting so the UI resets.
      window.setTimeout(() => operations.emit({ schemaVersion: 1, operationId: id, kind: 'quick-action', state: 'completed', progress: 1, detail: '动作执行完成' }), 900);
    },
    stopQuickAction: async () => { if (actionExtras) await actionExtras.stop(); else await runtime.motion.pause(); operations.emit({ schemaVersion: 1, operationId: 'quick-action', kind: 'quick-action', state: 'cancelled', progress: 0, detail: '已停止' }); },
    startLoop: async (id) => { if (actionExtras) await actionExtras.play(id, { speed: 1, loopCount: null }); else await runtime.motion.runAction(id); operations.emit({ schemaVersion: 1, operationId: id, kind: 'loop', state: 'running', progress: 0, detail: '循环由 actor 执行，直到明确停止' }); },
    stopLoop: async () => { if (actionExtras) await actionExtras.stop(); else await runtime.motion.pause(); operations.emit({ schemaVersion: 1, operationId: 'loop', kind: 'loop', state: 'cancelled', progress: 0, detail: '已停止' }); },
    subscribeOperation(listener) { const remove = operations.add(listener); const remote = extras?.subscribeOperation(listener); return () => { remove(); remote?.(); }; },
  };
}

function actionController(runtime: ConsolePorts, simulator: boolean): ActionController {
  let state: ActionControllerState = { state: 'idle', progress: 0 };
  const listeners = stateListeners<ActionControllerState>();
  const set = (next: ActionControllerState) => { state = next; listeners.emit(state); };
  const extras = simulator ? undefined : tauriRuntimeExtras.actions;
  return {
    async startRecording(name) { if (extras) { await extras.startRecording(name); return; } set({ state: 'recording', progress: 0, detail: '浏览器模拟器录制中' }); },
    async pauseRecording() { if (extras) { await extras.pauseRecording(); return; } set({ ...state, state: 'recordingPaused' }); },
    async resumeRecording() { if (extras) { await extras.resumeRecording(); return; } set({ ...state, state: 'recording' }); },
    async finishRecording() { if (extras) { await extras.finishRecording(); return; } set({ state: 'idle', progress: 0 }); },
    async cancelRecording() { if (extras) { await extras.cancelRecording(); return; } set({ state: 'cancelled', progress: 0 }); },
    async play(actionId, options) { if (extras) { await extras.play(actionId, options); return; } set({ state: 'playing', actionId, progress: 0, detail: '浏览器模拟器执行中' }); },
    async pausePlayback() { if (extras) { await extras.pause(); return; } set({ ...state, state: 'paused' }); },
    async resumePlayback() { if (extras) { await extras.resume(); return; } set({ ...state, state: 'playing' }); },
    async stop() { if (extras) { await extras.stop(); return; } set({ state: 'cancelled', progress: 0 }); },
    getState: async () => state,
    subscribe(listener) { const remove = listeners.add(listener); const remote = extras?.subscribe(listener); return () => { remove(); remote?.(); }; },
  };
}

function graspController(runtime: ConsolePorts, simulator: boolean): GraspController {
  let state: GraspControllerState = {
    phase: 'idle',
    tactileAvailable: false,
    rawTouch: null,
    degraded: false,
    calibrated: false,
    joints: Array.from({ length: 6 }, (_, i) => ({
      index: i,
      name: ['拇指弯曲', '拇指横摆', '食指弯曲', '中指弯曲', '无名指弯曲', '小指弯曲'][i] ?? `J${i + 1}`,
      state: 'idle' as import('../features/smart-grasp').GraspJointState,
      contactScore: 0,
      load: 0,
      loadMax: 255,
    })),
    jointCount: 6,
  };
  const listeners = stateListeners<GraspControllerState>();
  const set = (next: Partial<GraspControllerState>) => { state = { ...state, ...next }; listeners.emit(state); };
  const extras = simulator ? undefined : tauriRuntimeExtras.grasp;
  return {
    async calibrate() {
      if (extras) { await extras.calibrate(); return; }
      // Simulate calibration: transition through calibrating → calibrated
      set({ phase: 'calibrating' });
      await new Promise(r => setTimeout(r, 1200));
      set({ phase: 'calibrated', calibrated: true });
    },
    async approach() {
      if (extras) { await extras.approach(); return; }
      set({ phase: 'approaching' });
      await new Promise(r => setTimeout(r, 600));
      // Move to ready for grasp
    },
    async startGrasp(_presetId, degraded) {
      if (extras) { await extras.startGrasp(degraded); return; }
      // 首次抓取强制要求先完成空载标定（标定结果仅会话内缓存）
      if (!state.calibrated) {
        set({ phase: 'failed', failure: { code: 'no_calibration', message: '未完成空载标定，请先执行标定后再开始抓取。' } });
        return;
      }
      // Simulate full grasp flow: coarse → fine → preload → holding → success
      set({ phase: 'closingCoarse', degraded });
      // Update joints to closingCoarse
      const coarseJoints = state.joints.map(j => ({ ...j, state: j.index === 1 ? 'frozen' as const : 'closingCoarse' as const, contactScore: 0, load: 20 + Math.floor(Math.random() * 15) }));
      set({ joints: coarseJoints });
      await new Promise(r => setTimeout(r, 800));

      set({ phase: 'closingFine' });
      const fineJoints = coarseJoints.map(j => ({ ...j, state: j.index === 1 ? 'frozen' as const : 'closingFine' as const, contactScore: 0.3 + Math.random() * 0.3, load: 40 + Math.floor(Math.random() * 20) }));
      set({ joints: fineJoints });
      await new Promise(r => setTimeout(r, 600));

      // Simulate contacts
      set({ phase: 'preloading' });
      const preloadJoints = fineJoints.map(j => {
        if (j.index === 1) return { ...j, state: 'frozen' as const };
        const contacted = Math.random() > 0.3;
        return {
          ...j,
          state: contacted ? 'contactConfirmed' as const : 'limitReached' as const,
          contactScore: contacted ? 0.85 + Math.random() * 0.15 : 0,
          load: contacted ? 80 + Math.floor(Math.random() * 40) : 30 + Math.floor(Math.random() * 10),
        };
      });
      set({ joints: preloadJoints });
      await new Promise(r => setTimeout(r, 400));

      set({ phase: 'holding' });
      await new Promise(r => setTimeout(r, 600));

      set({ phase: 'success' });
    },
    async release() {
      if (extras) { await extras.release(); return; }
      // 释放 = 急停：立即回到张开姿态，无分步延迟
      const resetJoints = state.joints.map(j => ({ ...j, state: 'idle' as const, contactScore: 0, load: 0 }));
      set({ phase: 'idle', joints: resetJoints });
    },
    async abort() {
      if (extras) { await extras.abort(); return; }
      set({ phase: 'aborted' });
      await new Promise(r => setTimeout(r, 300));
      set({ phase: 'idle' });
    },
    getState: async () => state,
    subscribe(listener) { const remove = listeners.add(listener); const remote = extras?.subscribe((s: any) => listener(s as GraspControllerState)); return () => { remove(); remote?.(); }; },
  };
}

export function createComposition(): ConsoleComposition {
  const simulator = !isTauriRuntime();
  const runtime = simulator
    ? {
      ...mockRuntime,
      actions: {
        ...mockRuntime.actions,
        list: async () => [{ schemaVersion: 1, id: 'builtin:neutral', name: '中性姿态', frames: [{ schemaVersion: 1, commandId: 'builtin:neutral:0', source: 'preset' as const, positions: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5], finalCommand: true }], durationMs: 50, steps: 1, updatedAt: '' }],
      },
    }
    : tauriRuntime;
  const visionRuntime = new VisionRuntime({}, { workerFactory: () => new VisionWorker() });
  const visionProposalController = createVisionProposalController(runtime, simulator);
  // In Tauri capabilities are loaded asynchronously by Shell. The app uses
  // O6 for the simulator and creates the RPS sink lazily with the authoritative
  // capability snapshot in Shell; this default sink remains disabled in a real
  // runtime until that snapshot is available.
  const createRps = (nextCapabilities: import('../shared/contracts').DeviceCapabilities) => createRpsActionController(runtime, nextCapabilities, simulator);
  const fallbackCapabilities = { schemaVersion: 1, deviceId: 'pending', model: 'O6' as const, hand: 'right' as const, transport: { type: 'can' as const, channel: 'pending' }, jointCount: 6, position: { length: 6, available: true, range: { min: 0, max: 255 } }, speed: { length: 6, available: true, range: { min: 0, max: 255 } }, current: { length: 6, available: true, range: { min: 0, max: 255 } }, torque: { length: 6, available: true, range: { min: 0, max: 255 } }, touch: { length: 0, available: false, range: { min: 0, max: 255 } }, speedCommandLength: 6, currentCommandLength: null, torqueCommandLength: 6, supportedOperations: ['setPosition' as const] };
  return { ...runtime, simulator, visionRuntime, visionProposalController, rpsActionController: createRps(fallbackCapabilities), createRpsActionController: createRps, settingsController: createSettingsController(runtime, simulator), themePort: createThemePort(), deviceController: createDeviceController(runtime, simulator, simulator ? undefined : tauriRuntimeExtras.device), actionController: actionController(runtime, simulator), graspController: graspController(runtime, simulator) };
}
