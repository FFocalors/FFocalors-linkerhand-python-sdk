import type { ActionController, ActionControllerState, PlaybackOptions, PosePreset, ProgrammedAction } from '../features/actions';
import type { DeviceControlController } from '../features/device-control';
import type { GraspController, GraspControllerState } from '../features/smart-grasp';
import type { ConnectionSnapshot, ConsolePorts, JointTargetCommand, OperationSnapshot } from '../shared/contracts';
import { isTauriRuntime, tauriRuntime } from '../shared/contracts';
import { tauriRuntimeExtras } from '../shared/contracts/tauri-runtime';
import { mockRuntime } from '../shared/contracts/mock-runtime';
import { createRpsActionController, createVisionProposalController } from './controllers';
import { createSettingsController, createThemePort } from './settings';
import type { SettingsController, ThemePort } from '../features/settings';
import type { VisionProposalController, VisionRuntimeLike } from '../features/vision';
import type { RpsActionController } from '../features/rock-paper-scissors/types';
import type { VisionLandmarkResult, VisionRuntimeSnapshot } from '../shared/vision-runtime';

const IDLE_VISION_SNAPSHOT: VisionRuntimeSnapshot = { state: 'idle', owner: null, cameraDeviceId: null, model: 'unloaded', frameSequence: 0, fps: null, droppedFrames: 0, inflight: 0, lastError: null };

/**
 * The camera runtime and its classic MediaPipe worker are loaded only when a
 * vision feature starts. Keeping this seam in the composition layer means the
 * safety stop path can continue to use one shared runtime without pulling the
 * worker or MediaPipe into the initial shell chunk.
 */
type VisionRuntimeLoader = () => Promise<VisionRuntimeLike>;

export class LazyVisionRuntime implements VisionRuntimeLike {
  private readonly loader: VisionRuntimeLoader;
  private delegate: VisionRuntimeLike | null = null;
  private loading: Promise<VisionRuntimeLike> | null = null;
  private disposed = false;
  private lifecycleGeneration = 0;
  private currentSnapshot = IDLE_VISION_SNAPSHOT;
  private readonly listeners = new Set<(snapshot: VisionRuntimeSnapshot) => void>();
  private readonly resultListeners = new Set<(result: VisionLandmarkResult) => void>();

  constructor(loader: VisionRuntimeLoader = LazyVisionRuntime.loadDefault) {
    this.loader = loader;
  }

  snapshot(): VisionRuntimeSnapshot { return this.currentSnapshot; }

  subscribe(listener: (snapshot: VisionRuntimeSnapshot) => void): () => void {
    this.listeners.add(listener);
    listener(this.currentSnapshot);
    return () => this.listeners.delete(listener);
  }

  onResult(listener: (result: VisionLandmarkResult) => void): () => void {
    this.resultListeners.add(listener);
    return () => this.resultListeners.delete(listener);
  }

  async start(video: HTMLVideoElement, source: 'vision' | 'rps', deviceId?: string): Promise<void> {
    if (this.disposed) throw new Error('视觉 Runtime 已释放');
    const generation = this.lifecycleGeneration;
    const runtime = await this.load();
    // dispose() can run while the dynamic imports are pending. Never start a
    // delegate that became available after its owner was disposed.
    if (this.disposed || generation !== this.lifecycleGeneration) throw new Error('视觉 Runtime 已释放');
    await runtime.start(video, source, deviceId);
  }

  async stop(): Promise<void> {
    const generation = this.lifecycleGeneration;
    if (this.loading) await this.loading.catch(() => undefined);
    if (this.disposed || generation !== this.lifecycleGeneration) return;
    await this.delegate?.stop();
  }

  async dispose(): Promise<void> {
    this.disposed = true;
    this.lifecycleGeneration += 1;
    if (this.loading) await this.loading.catch(() => undefined);
    await this.delegate?.dispose?.();
    this.listeners.clear();
    this.resultListeners.clear();
  }

  private load(): Promise<VisionRuntimeLike> {
    if (this.delegate) return Promise.resolve(this.delegate);
    if (!this.loading) {
      this.loading = this.loader().then(runtime => {
        this.delegate = runtime;
        runtime.subscribe(snapshot => {
          this.currentSnapshot = snapshot;
          this.listeners.forEach(listener => listener(snapshot));
        });
        runtime.onResult(result => this.resultListeners.forEach(listener => listener(result)));
        return runtime;
      });
    }
    return this.loading;
  }

  private static async loadDefault(): Promise<VisionRuntimeLike> {
    const [runtimeModule, workerModule] = await Promise.all([
      import('../shared/vision-runtime'),
      import('../workers/vision-worker/index?worker&classic'),
    ]);
    return new runtimeModule.VisionRuntime({}, { workerFactory: () => new workerModule.default() });
  }
}

export type ConsoleComposition = ConsolePorts & {
  deviceController: DeviceControlController;
  actionController: ActionController;
  graspController: GraspController;
  simulator: boolean;
  isPhysicalDevice: boolean;
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

export function createActionController(runtime: ConsolePorts, simulator: boolean, actionExtrasOverride?: typeof tauriRuntimeExtras.actions): ActionController {
  let state: ActionControllerState = { state: 'idle', progress: 0 };
  const listeners = stateListeners<ActionControllerState>();
  const set = (next: ActionControllerState) => { state = next; listeners.emit(state); };
  const extras = simulator ? undefined : actionExtrasOverride ?? tauriRuntimeExtras.actions;
  let simulatorTimer: number | undefined;
  let manualCommandSequence = 0;
  // 每个关键帧在设备上的停留时长：机械手需要足够时间完成关节弯曲到位，
  // 再切换到下一个姿态，避免动作序列播放过快导致姿态尚未到位就被打断。
  const FRAME_DURATION_MS = 1500;
  const validateFrames = async (id: string, poses: PosePreset[]): Promise<JointTargetCommand[]> => {
    const capabilities = await runtime.device.getCapabilities();
    const expected = capabilities.jointCount;
    if (poses.length === 0) throw new Error('动作至少需要一个姿态。');
    return poses.map((pose, index) => {
      if (!pose.positions || pose.positions.length !== expected || pose.positions.some(value => !Number.isFinite(value) || value < 0 || value > 1)) throw new Error(`姿态“${pose.name}”的关节向量必须包含 ${expected} 个 0..1 数值。`);
      return { schemaVersion: 1, commandId: `${id}:frame:${index}`, source: 'preset' as const, positions: [...pose.positions], durationMs: FRAME_DURATION_MS, finalCommand: index === poses.length - 1 };
    });
  };
  const validationFailure = async (message: string) => {
    set({ state: 'error', progress: 0, detail: message });
    await runtime.logs.record?.({ level: 'error', event: 'control.action.validation_failed', message, fields: { source: 'action-center' } });
    throw new Error(message);
  };
  const runFrames = async (id: string, name: string, poses: PosePreset[], options: PlaybackOptions) => {
    let frames: JointTargetCommand[];
    try { frames = await validateFrames(id, poses); } catch (error) { return validationFailure(error instanceof Error ? error.message : String(error)); }
    set({ state: 'playing', actionId: id, progress: 0, detail: name });
    try {
      if (extras) await extras.playFrames(id, name, frames, options);
      else {
        set({ state: 'playing', actionId: id, progress: 0, detail: simulator ? '浏览器模拟器执行中' : name });
        if (simulatorTimer !== undefined) window.clearTimeout(simulatorTimer);
        const repetitions = options.mode === 'loop' ? options.loopCount === null ? null : options.loopCount + 1 : 1;
        if (repetitions !== null) simulatorTimer = window.setTimeout(() => { simulatorTimer = undefined; set({ state: 'completed', actionId: id, progress: 1, detail: '动作执行完成' }); }, Math.max(20, Math.round(frames.length * FRAME_DURATION_MS * repetitions / Math.max(.25, options.speed))));
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set({ state: 'error', actionId: id, progress: 0, detail: message });
      throw error;
    }
  };
  /** 校验姿态向量并直接以 manual source 下发到设备（与首页关键目标控制面板一致）。 */
  const sendManualTarget = async (pose: PosePreset, finalCommand: boolean) => {
    const capabilities = await runtime.device.getCapabilities();
    const expected = capabilities.jointCount;
    if (!pose.positions || pose.positions.length !== expected || pose.positions.some(value => !Number.isFinite(value) || value < 0 || value > 1)) {
      const message = `姿态“${pose.name}”的关节向量必须包含 ${expected} 个 0..1 数值。`;
      set({ state: 'error', progress: 0, detail: message });
      throw new Error(message);
    }
    await runtime.device.setJointTarget({
      schemaVersion: 1,
      commandId: `${pose.id}:manual:${Date.now()}:${manualCommandSequence += 1}`,
      source: 'manual' as const,
      positions: [...pose.positions],
      durationMs: null,
      finalCommand,
    });
  };
  return {
    async startRecording(name) { if (extras) { await extras.startRecording(name); return; } set({ state: 'recording', progress: 0, detail: '浏览器模拟器录制中' }); },
    async pauseRecording() { if (extras) { await extras.pauseRecording(); return; } set({ ...state, state: 'recordingPaused' }); },
    async resumeRecording() { if (extras) { await extras.resumeRecording(); return; } set({ ...state, state: 'recording' }); },
    async finishRecording() { if (extras) { await extras.finishRecording(); return; } set({ state: 'idle', progress: 0 }); },
    async cancelRecording() { if (extras) { await extras.cancelRecording(); return; } set({ state: 'cancelled', progress: 0 }); },
    async play(actionId, options) { if (extras) { await extras.play(actionId, options); return; } set({ state: 'playing', actionId, progress: 0, detail: '浏览器模拟器执行中' }); },
    async previewPose(pose) {
      // 真机安全预览：直接下发一次完整的手动关节目标，让机械手先动到预览
      // 位置。finalCommand 为 true 会在发送后立即释放 motion 源，保证后续
      // “应用到设备”能以 manual 源重新占用而不被 SourceBusy 拒绝。
      await sendManualTarget(pose, true);
    },
    async applyPose(pose, _options) {
      // 复刻首页关键目标控制面板：单姿态直接以 manual source 下发，不走
      // action engine 的帧播放（时序播放会被 motion 源占用/锁定拒绝）。
      set({ state: 'playing', actionId: pose.id, progress: 0, detail: pose.name });
      try {
        await sendManualTarget(pose, true);
        set({ state: 'completed', actionId: pose.id, progress: 1, detail: '姿态已应用到设备' });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        set({ state: 'error', actionId: pose.id, progress: 0, detail: message });
        throw error;
      }
    },
    async streamPose(pose, finalCommand) {
      // 滑块实时下发：manual source 保持 motion 源占用（finalCommand=false），
      // 松手时 finalCommand=true 提交并释放，与首页关键目标控制面板行为一致。
      await sendManualTarget(pose, finalCommand);
    },
    async playPose(pose, options) { await runFrames(pose.id, pose.name, [pose], options); },
    async playProgrammedAction(action, options) { await runFrames(action.id, action.name, action.poses, options); },
    async pausePlayback() { if (extras) { await extras.pause(); return; } set({ ...state, state: 'paused' }); },
    async resumePlayback() { if (extras) { await extras.resume(); return; } set({ ...state, state: 'playing' }); },
    async stop() { if (extras) { await extras.stop(); return; } if (simulatorTimer !== undefined) { window.clearTimeout(simulatorTimer); simulatorTimer = undefined; } set({ state: 'cancelled', progress: 0, detail: '已取消' }); },
    async playLoop(loop, options) { if (extras) { await (extras as any).playLoop(loop, options); return; } set({ state: 'playing', actionId: loop.actionIds[0], progress: 0, detail: '浏览器模拟器循环执行中' }); },
    async stopLoop() { if (extras) { await (extras as any).stopLoop(); return; } if (simulatorTimer !== undefined) { window.clearTimeout(simulatorTimer); simulatorTimer = undefined; } set({ state: 'idle', progress: 0 }); },
    getState: async () => state,
    subscribe(listener) { const remove = listeners.add(listener); const remote = extras?.subscribe(listener); return () => { remove(); remote?.(); }; },
  };
}

function graspController(runtime: ConsolePorts, simulator: boolean): GraspController {
  const JOINT_NAMES = ['拇指弯曲', '拇指横摆', '食指弯曲', '中指弯曲', '无名指弯曲', '小指弯曲'];
  const jointName = (i: number) => JOINT_NAMES[i] ?? `J${i + 1}`;
  const makeJoints = (count: number) => Array.from({ length: count }, (_, i) => ({
    index: i,
    name: jointName(i),
    state: 'idle' as import('../features/smart-grasp').GraspJointState,
    contactScore: 0,
    load: 0,
    loadMax: 255,
  }));
  let state: GraspControllerState = {
    phase: 'idle',
    tactileAvailable: false,
    rawTouch: null,
    degraded: false,
    calibrated: false,
    joints: makeJoints(6),
    jointCount: 6,
  };
  const listeners = stateListeners<GraspControllerState>();
  const set = (next: Partial<GraspControllerState>) => { state = { ...state, ...next }; listeners.emit(state); };
  const extras = simulator ? undefined : tauriRuntimeExtras.grasp;
  /** Map the Tauri wire state into the feature-local state (phase + joints). */
  const mapRemote = (s: import('../shared/contracts/tauri-runtime').TauriGraspState): GraspControllerState => {
    const phaseMap: Record<string, GraspControllerState['phase']> = {
      idle: 'idle', calibrating: 'calibrating', ready: 'calibrated', approach: 'approaching',
      closingCoarse: 'closingCoarse', closingFine: 'closingFine', preloading: 'preloading',
      holding: 'holding', releasing: 'releasing', aborted: 'aborted', failed: 'failed',
    };
    const remoteJoints = s.joints ?? [];
    const joints = remoteJoints.length > 0
      ? remoteJoints.map(j => ({
          index: j.index,
          name: jointName(j.index),
          state: j.state as GraspControllerState['joints'][number]['state'],
          contactScore: j.contactScore,
          load: 0,
          loadMax: 255,
        }))
      : makeJoints(Math.max(remoteJoints.length, 6));
    return {
      phase: phaseMap[s.phase] ?? 'idle',
      failure: s.failure,
      tactileAvailable: s.tactileAvailable,
      rawTouch: s.rawTouch ?? null,
      degraded: s.degraded,
      calibrated: phaseMap[s.phase] === 'calibrated' || phaseMap[s.phase] === 'holding' || phaseMap[s.phase] === 'approaching' || phaseMap[s.phase] === 'closingCoarse' || phaseMap[s.phase] === 'closingFine' || phaseMap[s.phase] === 'preloading',
      joints,
      jointCount: joints.length,
    };
  };
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
    },
    async startGrasp(presetId, degraded) {
      if (extras) { await extras.startGrasp(presetId, degraded); return; }
      // 首次抓取强制要求先完成空载标定（标定结果仅会话内缓存）
      if (!state.calibrated) {
        set({ phase: 'failed', failure: { code: 'no_calibration', message: '未完成空载标定，请先执行标定后再开始抓取。' } });
        return;
      }
      // P0: preset-aware simulation — soft contacts easily, precision needs
      // strict scoring (mirrors the Rust GraspConfig preset parameters).
      const preset = presetId || 'cube';
      const contactRate = preset === 'soft' ? 0.85 : preset === 'precision' ? 0.45 : 0.7;
      const fineLoad = preset === 'soft' ? 40 : preset === 'precision' ? 70 : 55;
      // Simulate full grasp flow: coarse → fine → preload → holding → success
      set({ phase: 'closingCoarse', degraded });
      const coarseJoints = state.joints.map(j => ({ ...j, state: j.index === 1 ? 'frozen' as const : 'closingCoarse' as const, contactScore: 0, load: 15 + Math.floor(Math.random() * 12) }));
      set({ joints: coarseJoints });
      await new Promise(r => setTimeout(r, 800));

      set({ phase: 'closingFine' });
      const fineJoints = coarseJoints.map(j => ({ ...j, state: j.index === 1 ? 'frozen' as const : 'closingFine' as const, contactScore: 0.3 + Math.random() * 0.3, load: fineLoad + Math.floor(Math.random() * 18) }));
      set({ joints: fineJoints });
      await new Promise(r => setTimeout(r, 600));

      // Simulate contacts
      set({ phase: 'preloading' });
      const preloadJoints = fineJoints.map(j => {
        if (j.index === 1) return { ...j, state: 'frozen' as const };
        const contacted = Math.random() < contactRate;
        return {
          ...j,
          state: contacted ? 'contactConfirmed' as const : 'limitReached' as const,
          contactScore: contacted ? 0.85 + Math.random() * 0.15 : 0,
          load: contacted ? 70 + Math.floor(Math.random() * 35) : 25 + Math.floor(Math.random() * 10),
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
    subscribe(listener) {
      const remove = listeners.add(listener);
      const remote = extras?.subscribe((s: import('../shared/contracts/tauri-runtime').TauriGraspState) => listener(mapRemote(s)));
      return () => { remove(); remote?.(); };
    },
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
  const visionRuntime = new LazyVisionRuntime();
  const visionProposalController = createVisionProposalController(runtime, simulator);
  // In Tauri capabilities are loaded asynchronously by Shell. The app uses
  // O6 for the simulator and creates the RPS sink lazily with the authoritative
  // capability snapshot in Shell; this default sink remains disabled in a real
  // runtime until that snapshot is available.
  const createRps = (nextCapabilities: import('../shared/contracts').DeviceCapabilities) => createRpsActionController(runtime, nextCapabilities, simulator);
  const fallbackCapabilities = { schemaVersion: 1, deviceId: 'pending', model: 'O6' as const, hand: 'right' as const, transport: { type: 'can' as const, channel: 'pending' }, jointCount: 6, position: { length: 6, available: true, range: { min: 0, max: 255 } }, speed: { length: 6, available: true, range: { min: 0, max: 255 } }, current: { length: 6, available: true, range: { min: 0, max: 255 } }, torque: { length: 6, available: true, range: { min: 0, max: 255 } }, touch: { length: 0, available: false, range: { min: 0, max: 255 } }, speedCommandLength: 6, currentCommandLength: null, torqueCommandLength: 6, supportedOperations: ['setPosition' as const] };
  return { ...runtime, simulator, isPhysicalDevice: !simulator, visionRuntime, visionProposalController, rpsActionController: createRps(fallbackCapabilities), createRpsActionController: createRps, settingsController: createSettingsController(runtime, simulator), themePort: createThemePort(), deviceController: createDeviceController(runtime, simulator, simulator ? undefined : tauriRuntimeExtras.device), actionController: createActionController(runtime, simulator), graspController: graspController(runtime, simulator) };
}
