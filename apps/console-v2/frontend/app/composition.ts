import type { ActionController, ActionControllerState } from '../features/actions';
import type { DeviceControlController } from '../features/device-control';
import type { GraspController, GraspControllerState } from '../features/smart-grasp';
import type { ConnectionSnapshot, ConsolePorts, JointTargetCommand, OperationSnapshot } from '../shared/contracts';
import { isTauriRuntime, tauriRuntime } from '../shared/contracts';
import { tauriRuntimeExtras } from '../shared/contracts/tauri-runtime';
import { mockRuntime } from '../shared/contracts/mock-runtime';

export type ConsoleComposition = ConsolePorts & {
  deviceController: DeviceControlController;
  actionController: ActionController;
  graspController: GraspController;
  simulator: boolean;
};

const simulatorConnection = (runtime: ConsolePorts, deviceId: string): ConnectionSnapshot => ({ schemaVersion: 1, deviceId, state: 'connected', attempt: 1, lastError: null });
const stateListeners = <T>() => {
  const listeners = new Set<(value: T) => void>();
  return { add: (listener: (value: T) => void) => { listeners.add(listener); return () => listeners.delete(listener); }, emit: (value: T) => listeners.forEach(listener => listener(value)) };
};

function deviceController(runtime: ConsolePorts, simulator: boolean): DeviceControlController {
  let connection: ConnectionSnapshot | undefined;
  const connections = stateListeners<ConnectionSnapshot>();
  const operations = stateListeners<OperationSnapshot>();
  const actionExtras = simulator ? undefined : tauriRuntimeExtras.actions;
  const device = runtime.device as ConsolePorts['device'] & Partial<{
    reconnect(): Promise<ConnectionSnapshot>;
    connect(): Promise<ConnectionSnapshot>;
    disconnect(): Promise<ConnectionSnapshot>;
    setSpeed(command: { values: number[]; finalCommand: boolean }): Promise<void>;
    setTorque(command: { values: number[]; finalCommand: boolean }): Promise<void>;
    subscribeConnection(listener: (snapshot: ConnectionSnapshot) => void): () => void;
    subscribeOperation(listener: (snapshot: OperationSnapshot) => void): () => void;
  }>;
  const refresh = async () => { connection = await device.getConnection(); connections.emit(connection); return connection; };
  const callConnection = async (action: 'connect' | 'disconnect' | 'reconnect') => {
    if (simulator) { connection = simulatorConnection(runtime, (await runtime.device.getConfig()).deviceId); if (action === 'disconnect') connection = { ...connection, state: 'disconnected' }; connections.emit(connection); return; }
    if (action === 'connect' && device.connect) connection = await device.connect();
    else if (action === 'disconnect' && device.disconnect) connection = await device.disconnect();
    else if (action === 'reconnect' && device.reconnect) connection = await device.reconnect();
    else connection = await refresh();
    connections.emit(connection);
  };
  return {
    connect: () => callConnection('connect'), disconnect: () => callConnection('disconnect'), reconnect: () => callConnection('reconnect'),
    subscribeConnection(listener) { const remove = connections.add(listener); const remote = device.subscribeConnection?.(listener); void refresh(); return () => { remove(); remote?.(); }; },
    setJointTarget: (command: JointTargetCommand) => runtime.device.setJointTarget(command),
    setSpeed: command => device.setSpeed ? device.setSpeed(command) : Promise.reject(new Error('速度控制器不可用')),
    setTorque: command => device.setTorque ? device.setTorque(command) : Promise.reject(new Error('扭矩控制器不可用')),
    startQuickAction: async (id) => { if (actionExtras) await actionExtras.play(id, { speed: 1, loopCount: 0 }); else await runtime.motion.runAction(id); operations.emit({ schemaVersion: 1, operationId: id, kind: 'quick-action', state: 'running', progress: 0, detail: '动作引擎执行中' }); },
    stopQuickAction: async () => { if (actionExtras) await actionExtras.stop(); else await runtime.motion.pause(); operations.emit({ schemaVersion: 1, operationId: 'quick-action', kind: 'quick-action', state: 'cancelled', progress: 0, detail: '已停止' }); },
    startLoop: async (id) => { if (actionExtras) await actionExtras.play(id, { speed: 1, loopCount: null }); else await runtime.motion.runAction(id); operations.emit({ schemaVersion: 1, operationId: id, kind: 'loop', state: 'running', progress: 0, detail: '循环由 actor 执行（安全上限 1000 次）' }); },
    stopLoop: async () => { if (actionExtras) await actionExtras.stop(); else await runtime.motion.pause(); operations.emit({ schemaVersion: 1, operationId: 'loop', kind: 'loop', state: 'cancelled', progress: 0, detail: '已停止' }); },
    subscribeOperation(listener) { const remove = operations.add(listener); const remote = device.subscribeOperation?.(listener); return () => { remove(); remote?.(); }; },
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
  let state: GraspControllerState = { phase: 'idle', tactileAvailable: false, rawTouch: null, degraded: false };
  const listeners = stateListeners<GraspControllerState>();
  const set = (next: GraspControllerState) => { state = next; listeners.emit(state); };
  const extras = simulator ? undefined : tauriRuntimeExtras.grasp;
  return {
    async calibrate() { if (extras) { await extras.calibrate(); return; } set({ ...state, phase: 'calibrating' }); },
    async completeCalibration() { if (extras) { await extras.completeCalibration(); return; } set({ ...state, phase: 'ready' }); },
    async approach() { if (extras) { await extras.approach(); return; } set({ ...state, phase: 'approach' }); },
    async startGrasp(_presetId, degraded) { if (extras) { await extras.startGrasp(degraded); return; } set({ ...state, phase: 'grasping', degraded }); },
    async release() { if (extras) { await extras.release(); return; } set({ ...state, phase: 'releasing' }); },
    async abort() { if (extras) { await extras.abort(); return; } set({ ...state, phase: 'aborted' }); },
    getState: async () => state,
    subscribe(listener) { const remove = listeners.add(listener); const remote = extras?.subscribe(listener); return () => { remove(); remote?.(); }; },
  };
}

export function createComposition(): ConsoleComposition {
  const simulator = !isTauriRuntime();
  const runtime = simulator ? mockRuntime : tauriRuntime;
  return { ...runtime, simulator, deviceController: deviceController(runtime, simulator), actionController: actionController(runtime, simulator), graspController: graspController(runtime, simulator) };
}
