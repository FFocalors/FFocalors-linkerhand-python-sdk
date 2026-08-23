import { classifyResult } from './classifier';
import { chooseMachineGesture, createInitialState, outcomeFor, scoreFor, updatePlayerProfile } from './game';
import type { RpsActionController, RpsCapabilities, RpsInvalidReason, RpsMove, RpsOutcome, RpsRoundMode, RpsScheduler, RpsState, RpsStrategy, RpsVisionRuntime } from './types';
import type { VisionLandmarkResult, VisionRuntimeSnapshot } from '../../shared/vision-runtime';

const realScheduler: RpsScheduler = { setTimeout: (callback, delay) => window.setTimeout(callback, delay), clearTimeout: handle => window.clearTimeout(handle) };
const defaultRandom = () => Math.random();
const ACTIVE_PHASES = new Set<RpsState['phase']>(['countdown', 'capture', 'recognized', 'invalid', 'reveal', 'score', 'matchOver']);

export type RpsControllerOptions = { runtime: RpsVisionRuntime; capabilities: RpsCapabilities; actionController?: RpsActionController; scheduler?: RpsScheduler; random?: () => number; roundMode?: RpsRoundMode; autoAdvanceMs?: number; countdownMs?: number; captureMs?: number; revealMs?: number; scoreMs?: number };
export type RpsControllerListener = (state: RpsState) => void;

export class RpsGameController {
  private readonly runtime: RpsVisionRuntime;
  private readonly capabilities: RpsCapabilities;
  private readonly actionController?: RpsActionController;
  private readonly scheduler: RpsScheduler;
  private readonly random: () => number;
  private readonly countdownMs: number;
  private readonly captureMs: number;
  private readonly revealMs: number;
  private readonly scoreMs: number;
  private readonly autoAdvanceMs: number;
  private state: RpsState = createInitialState();
  private readonly listeners = new Set<RpsControllerListener>();
  private readonly timers = new Set<number>();
  private unsubscribeRuntime: (() => void) | null = null;
  private unsubscribeResults: (() => void) | null = null;
  private video: HTMLVideoElement | null = null;
  private disposed = false;
  private generation = 0;
  private startGeneration: number | null = null;
  private dispatchInFlight = false;
  private lastInvalidReason: RpsInvalidReason | null = null;

  constructor(options: RpsControllerOptions) {
    this.runtime = options.runtime; this.capabilities = options.capabilities; this.actionController = options.actionController;
    this.scheduler = options.scheduler ?? realScheduler; this.random = options.random ?? defaultRandom;
    this.countdownMs = options.countdownMs ?? 1000; this.captureMs = options.captureMs ?? 700; this.revealMs = options.revealMs ?? 280; this.scoreMs = options.scoreMs ?? 420; this.autoAdvanceMs = options.autoAdvanceMs ?? 3000;
    const hardware = this.hardwareAvailable() ? 'idle' : 'disabled';
    this.state = { ...this.state, action: { status: hardware, detail: hardware === 'disabled' ? '仅 O6 且接入动作控制器时可控制机械手' : null }, roundMode: options.roundMode ?? 'unlimited' };
  }

  subscribe(listener: RpsControllerListener): () => void { this.listeners.add(listener); listener(this.state); return () => this.listeners.delete(listener); }
  snapshot(): RpsState { return this.state; }

  attach(video: HTMLVideoElement): void {
    this.unsubscribeRuntime?.(); this.unsubscribeResults?.(); this.video = video;
    this.unsubscribeRuntime = this.runtime.subscribe(snapshot => this.onRuntime(snapshot));
    this.unsubscribeResults = this.runtime.onResult(result => this.onResult(result));
  }

  async startCamera(): Promise<void> {
    if (this.disposed || !this.video) return;
    const token = this.generation;
    this.startGeneration = token;
    try { await this.runtime.start(this.video, 'rps'); }
    catch (error) { if (this.isCurrent(token)) this.emit({ cameraError: error as RpsState['cameraError'] }); }
    finally {
      if (this.startGeneration === token) {
        if (!this.isCurrent(token) && this.runtime.snapshot().owner === 'rps') await this.runtime.stop();
        this.startGeneration = null;
      }
    }
  }

  async authorizeHardware(): Promise<boolean> {
    if (!this.hardwareAvailable() || !this.actionController || this.state.hardwareAuthorized || this.disposed || this.state.cameraState !== 'running') return false;
    const token = this.generation;
    this.emit({ action: { status: 'authorizing', detail: '正在等待本局机械手授权…' } });
    try {
      const allowed = await this.actionController.authorize();
      if (!this.isCurrent(token)) return false;
      if (!allowed) { this.emit({ action: { status: 'idle', detail: '本局未授权，机械手不会动作' } }); return false; }
      this.emit({ hardwareAuthorized: true, action: { status: 'authorized', detail: '本局已授权，揭晓后将请求机械手动作' } }); return true;
    } catch (error) { if (this.isCurrent(token)) this.emit({ action: { status: 'error', detail: error instanceof Error ? error.message : '授权失败' } }); return false; }
  }

  setStrategy(strategy: RpsStrategy): void {
    this.emit({ strategy });
  }

  setRoundMode(roundMode: RpsRoundMode): void {
    if (this.disposed || this.state.roundMode === roundMode) return;
    const matchWinner = this.matchCompleteFor(roundMode) ? this.state.score.player > this.state.score.machine ? 'player' : 'machine' : null;
    this.emit({ roundMode, matchWinner });
  }

  resetProfile(): void {
    this.emit({ profile: createInitialState().profile, chain: null });
  }

  beginRound(): boolean {
    if (this.disposed || (this.state.phase !== 'cameraReady' && this.state.phase !== 'ready')) return false;
    if (this.matchComplete()) { this.emit({ phase: 'matchOver', matchWinner: this.state.score.player > this.state.score.machine ? 'player' : 'machine', countdown: null, machineMove: null, playerMove: null, outcome: null }); return false; }
    this.generation += 1; this.clearTimers(); this.lastInvalidReason = null;
    const nextRound = this.state.round + 1;
    const { machineGesture, chain } = chooseMachineGesture(this.state.profile, this.state.strategy, this.random);
    this.emit({ phase: 'countdown', countdown: 3, playerMove: null, machineMove: machineGesture, outcome: null, invalidReason: null, round: nextRound, stableFrames: 0, chain });
    this.schedule(() => this.countdownTick(3), this.countdownMs); return true;
  }

  /** 停止当前对局（保留比分），回到可重新开始的状态；取消任何进行中的机械手动作。 */
  stopRound(): void {
    const active = ['countdown', 'capture', 'recognized', 'invalid', 'reveal', 'score', 'ready', 'matchOver'] as const;
    if (this.disposed || !active.includes(this.state.phase as typeof active[number])) return;
    this.generation += 1; this.clearTimers();
    const token = this.generation; void this.cancelAction('stopped', token).catch(() => undefined);
    this.emit({ phase: this.state.cameraState === 'running' ? 'cameraReady' : 'idle', countdown: null, playerMove: null, machineMove: null, outcome: null, invalidReason: null, matchWinner: null });
  }

  retry(): void {
    if (this.state.phase !== 'invalid' && this.state.phase !== 'ready') return;
    this.generation += 1; this.clearTimers();
    const token = this.generation; void this.cancelAction('reset', token, false).catch(() => undefined);
    this.emit({ phase: this.state.cameraState === 'running' ? 'cameraReady' : 'idle', countdown: null, playerMove: null, machineMove: null, outcome: null, invalidReason: null, hardwareAuthorized: false, action: this.hardwareAvailable() ? { status: 'idle', detail: null } : this.state.action });
  }

  reset(): void {
    this.generation += 1; this.clearTimers();
    const token = this.generation; void this.cancelAction('reset', token, false).catch(() => undefined);
    const cameraState = this.state.cameraState;
    const action = this.hardwareAvailable() ? { status: 'idle' as const, detail: null } : this.state.action;
    this.emit({ ...createInitialState(), cameraState, phase: cameraState === 'running' ? 'cameraReady' : 'idle', action, roundMode: this.state.roundMode });
  }

  lock(): void {
    this.generation += 1; this.clearTimers();
    const token = this.generation; const ownedByRps = this.runtime.snapshot().owner === 'rps';
    this.emit({ hardwareAuthorized: false, phase: ownedByRps ? 'idle' : this.state.cameraState === 'running' ? 'cameraReady' : 'idle', cameraState: ownedByRps ? 'stopping' : this.state.cameraState, countdown: null, playerMove: null, machineMove: null, outcome: null });
    void this.cancelAction('locked', token).then(async () => { if (ownedByRps && this.runtime.snapshot().owner === 'rps') await this.runtime.stop(); }).catch(() => undefined);
  }

  async stop(reason: 'stopped' | 'unmounted' = 'stopped'): Promise<void> {
    this.generation += 1; this.clearTimers();
    const token = this.generation; const ownedByRps = this.runtime.snapshot().owner === 'rps';
    this.emit({ phase: 'idle', countdown: null, cameraState: 'idle', hardwareAuthorized: false, playerMove: null, machineMove: null, outcome: null });
    await this.cancelAction(reason, token);
    if (ownedByRps && this.runtime.snapshot().owner === 'rps') await this.runtime.stop();
  }

  async testAction(move: RpsMove): Promise<boolean> {
    if (!this.hardwareAvailable() || !this.state.hardwareAuthorized || this.state.cameraState !== 'running' || (this.state.phase !== 'cameraReady' && this.state.phase !== 'ready')) return false;
    const result = await this.dispatch(move, 'rps-test');
    return result?.status === 'executed';
  }

  async revokeHardware(): Promise<void> {
    if (!this.actionController || this.disposed) return;
    const token = this.generation;
    this.emit({ hardwareAuthorized: false });
    await this.cancelAction('stopped', token);
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    this.unsubscribeRuntime?.(); this.unsubscribeResults?.(); this.unsubscribeRuntime = null; this.unsubscribeResults = null; this.disposed = true;
    await this.stop('unmounted'); this.listeners.clear();
  }

  private hardwareAvailable(): boolean { return this.capabilities.model === 'O6' && this.capabilities.supportedOperations.includes('setPosition') && Boolean(this.actionController); }
  private isCurrent(token: number): boolean { return !this.disposed && token === this.generation; }
  private schedule(callback: () => void, delay: number): void { const handle = this.scheduler.setTimeout(() => { this.timers.delete(handle); callback(); }, delay); this.timers.add(handle); }
  private clearTimers(): void { this.timers.forEach(handle => this.scheduler.clearTimeout(handle)); this.timers.clear(); }
  private countdownTick(current: 3 | 2 | 1): void { if (this.state.phase !== 'countdown') return; if (current > 1) { const next = (current - 1) as 1 | 2; this.emit({ countdown: next }); this.schedule(() => this.countdownTick(next), this.countdownMs); return; } this.emit({ phase: 'capture', countdown: null }); this.schedule(() => this.finishInvalid('no-hand'), this.captureMs); }

  private onRuntime(snapshot: VisionRuntimeSnapshot): void {
    if (this.disposed) return;
    if (snapshot.state === 'running' && snapshot.owner === 'rps' && this.startGeneration !== null && this.startGeneration !== this.generation) { void this.runtime.stop().catch(() => undefined); return; }
    if (snapshot.state === 'running' && snapshot.owner !== 'rps') {
      const wasActive = this.state.cameraState === 'running' || ACTIVE_PHASES.has(this.state.phase) || this.state.hardwareAuthorized;
      if (wasActive) { this.generation += 1; this.clearTimers(); const token = this.generation; this.emit({ cameraState: 'idle', phase: 'idle', cameraError: { code: 'VISION_BUSY', message: `视觉输入当前由 ${snapshot.owner ?? '其他功能'} 占用` }, countdown: null, hardwareAuthorized: false, playerMove: null, machineMove: null, outcome: null, stableFrames: 0 }); void this.cancelAction('stopped', token).catch(() => undefined); }
      else this.emit({ cameraState: 'idle', phase: 'idle', cameraError: { code: 'VISION_BUSY', message: `视觉输入当前由 ${snapshot.owner ?? '其他功能'} 占用` } });
      return;
    }
    const leavingRunning = snapshot.state !== 'running' && (this.state.cameraState === 'running' || ACTIVE_PHASES.has(this.state.phase) || this.state.hardwareAuthorized);
    const cameraError = snapshot.lastError ? { code: snapshot.lastError.code, message: snapshot.lastError.message } : null;
    if (leavingRunning) {
      this.generation += 1; this.clearTimers();
      const token = this.generation;
      this.emit({ phase: 'idle', countdown: null, cameraState: snapshot.state, cameraError, playerMove: null, machineMove: null, outcome: null, hardwareAuthorized: false, stableFrames: 0 });
      void this.cancelAction('stopped', token).catch(() => undefined);
      return;
    }
    const phase = snapshot.state === 'running' && this.state.phase === 'idle' ? 'cameraReady' : this.state.phase;
    this.emit({ cameraState: snapshot.state, cameraError, phase });
  }

  private onResult(result: VisionLandmarkResult): void {
    this.emit({ lastHand: result.hands[0] ?? null });
    if (this.state.phase !== 'capture') return;
    // 系统出拳瞬间：capture 第一帧有效识别即锁定，避免用户看到机器手势后临时变招
    const classification = classifyResult(result);
    if (classification.move === null) { this.lastInvalidReason = classification.reason; return; }
    this.clearTimers();
    this.emit({ phase: 'recognized', playerMove: classification.move, invalidReason: null, stableFrames: 1 });
    this.schedule(() => this.reveal(), this.revealMs);
  }

  private finishInvalid(reason: RpsInvalidReason): void { if (this.state.phase !== 'capture') return; this.emit({ phase: 'invalid', invalidReason: this.lastInvalidReason ?? reason, stableFrames: 0 }); this.schedule(() => this.reveal(), this.revealMs); }
  private reveal(): void {
    if (this.state.phase !== 'recognized' && this.state.phase !== 'invalid') return;
    const player = this.state.playerMove;
    const machine = this.state.machineMove;
    let outcome: RpsOutcome = null;
    let judgeResult: string = 'invalid';
    if (player && machine) {
      if (player === machine) {
        outcome = 'draw';
        judgeResult = 'draw';
      } else if (
        (player === 'rock' && machine === 'scissors') ||
        (player === 'scissors' && machine === 'paper') ||
        (player === 'paper' && machine === 'rock')
      ) {
        outcome = 'win';
        judgeResult = 'human';
      } else {
        outcome = 'lose';
        judgeResult = 'machine';
      }
    }
    const nextScore = outcome ? scoreFor(this.state.score, outcome) : this.state.score;
    this.emit({ phase: 'reveal', outcome });
    if (machine && outcome && this.hardwareAvailable() && this.state.hardwareAuthorized) void this.dispatch(machine, 'rps-reveal').catch(() => undefined);
    this.schedule(() => this.emit({ phase: 'score', score: nextScore }), this.revealMs);
    this.schedule(() => this.finishRound(player, machine, judgeResult), this.revealMs + this.scoreMs);
  }

  private async finishRound(player: RpsMove | null, machine: RpsMove | null, judgeResult: string): Promise<void> {
    if (this.state.phase !== 'score') return;
    const human = player ?? this.state.playerMove;
    const machineGesture = machine ?? this.state.machineMove ?? 'rock';
    const updatedProfile = human ? updatePlayerProfile(this.state.profile, human, machineGesture, judgeResult, this.state.chain) : this.state.profile;
    this.generation += 1; const token = this.generation;
    const wasDispatching = this.state.action.status === 'dispatching';
    if (this.matchCompleteFor(this.state.roundMode)) {
      this.emit({ phase: 'matchOver', countdown: null, hardwareAuthorized: false, profile: updatedProfile, chain: null, matchWinner: this.state.score.player > this.state.score.machine ? 'player' : 'machine' });
    } else {
      this.emit({ phase: 'ready', countdown: null, hardwareAuthorized: false, profile: updatedProfile, chain: null, matchWinner: null });
      this.schedule(() => { if (this.state.phase === 'ready') this.beginRound(); }, this.autoAdvanceMs);
    }
    await this.cancelAction('stopped', token, wasDispatching);
  }

  private matchCompleteFor(mode: RpsRoundMode): boolean {
    if (mode === 'unlimited') return false;
    const target = mode === 'best_of_3' ? 2 : 3;
    return this.state.score.player >= target || this.state.score.machine >= target;
  }
  private matchComplete(): boolean { return this.matchCompleteFor(this.state.roundMode); }

  private async dispatch(move: RpsMove, reason: 'rps-reveal' | 'rps-test'): Promise<{ status: 'executed' | 'cancelled' | 'error'; message?: string } | null> {
    if (!this.actionController || this.dispatchInFlight) return null;
    this.dispatchInFlight = true; const token = this.generation;
    if (this.isCurrent(token)) this.emit({ action: { status: 'dispatching', detail: '已向动作控制器请求机械手动作…' } });
    try {
      const result = await this.actionController.dispatch({ move, round: this.state.round, reason });
      if (this.isCurrent(token)) this.emit({ action: { status: result.status, detail: result.message ?? null } });
      return this.isCurrent(token) ? result : null;
    } catch (error) {
      if (this.isCurrent(token)) this.emit({ action: { status: 'error', detail: error instanceof Error ? error.message : '动作请求失败' } });
      return null;
    } finally { this.dispatchInFlight = false; }
  }

  private async cancelAction(reason: 'locked' | 'stopped' | 'unmounted' | 'reset', token: number, updateStatus = true): Promise<void> {
    if (!this.actionController) return;
    try { await this.actionController.cancel(reason); }
    finally { if (this.isCurrent(token) && updateStatus && this.state.action.status !== 'disabled') this.emit({ action: { status: 'cancelled', detail: '动作已撤销' }, hardwareAuthorized: false }); }
  }

  private emit(changes: Partial<RpsState> = {}): void { this.state = { ...this.state, ...changes }; this.listeners.forEach(listener => listener(this.state)); }
}
