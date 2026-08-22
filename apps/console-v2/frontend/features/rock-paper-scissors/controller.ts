import { classifyResult, StableMoveWindow } from './classifier';
import { createInitialState, machineMove, outcomeFor, scoreFor } from './game';
import type { RpsActionController, RpsCapabilities, RpsInvalidReason, RpsMove, RpsScheduler, RpsState, RpsVisionRuntime } from './types';
import type { VisionLandmarkResult, VisionRuntimeSnapshot } from '../../shared/vision-runtime';

const realScheduler: RpsScheduler = { setTimeout: (callback, delay) => window.setTimeout(callback, delay), clearTimeout: handle => window.clearTimeout(handle) };
const defaultRandom = () => Math.random();
const ACTIVE_PHASES = new Set<RpsState['phase']>(['countdown', 'capture', 'recognized', 'invalid', 'reveal', 'score']);

export type RpsControllerOptions = { runtime: RpsVisionRuntime; capabilities: RpsCapabilities; actionController?: RpsActionController; scheduler?: RpsScheduler; random?: () => number; countdownMs?: number; captureMs?: number; revealMs?: number; scoreMs?: number };
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
  private readonly stable = new StableMoveWindow();
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
    this.countdownMs = options.countdownMs ?? 1000; this.captureMs = options.captureMs ?? 1400; this.revealMs = options.revealMs ?? 280; this.scoreMs = options.scoreMs ?? 420;
    const hardware = this.hardwareAvailable() ? 'idle' : 'disabled';
    this.state = { ...this.state, action: { status: hardware, detail: hardware === 'disabled' ? '仅 O6 且接入动作控制器时可控制机械手' : null } };
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

  beginRound(): boolean {
    if (this.disposed || (this.state.phase !== 'cameraReady' && this.state.phase !== 'ready')) return false;
    if (this.hardwareAvailable() && !this.state.hardwareAuthorized) return false;
    this.generation += 1; this.clearTimers(); this.stable.reset(); this.lastInvalidReason = null;
    this.emit({ phase: 'countdown', countdown: 3, playerMove: null, machineMove: null, outcome: null, invalidReason: null, round: this.state.round + 1, stableFrames: 0 });
    this.schedule(() => this.countdownTick(3), this.countdownMs); return true;
  }

  retry(): void {
    if (this.state.phase !== 'invalid' && this.state.phase !== 'ready') return;
    this.generation += 1; this.clearTimers(); this.stable.reset();
    const token = this.generation; void this.cancelAction('reset', token, false);
    this.emit({ phase: this.state.cameraState === 'running' ? 'cameraReady' : 'idle', countdown: null, playerMove: null, machineMove: null, outcome: null, invalidReason: null, hardwareAuthorized: false, action: this.hardwareAvailable() ? { status: 'idle', detail: null } : this.state.action });
  }

  reset(): void {
    this.generation += 1; this.clearTimers(); this.stable.reset();
    const token = this.generation; void this.cancelAction('reset', token, false);
    const cameraState = this.state.cameraState;
    const action = this.hardwareAvailable() ? { status: 'idle' as const, detail: null } : this.state.action;
    this.emit({ ...createInitialState(), cameraState, phase: cameraState === 'running' ? 'cameraReady' : 'idle', action });
  }

  lock(): void {
    this.generation += 1; this.clearTimers(); this.stable.reset();
    const token = this.generation; const ownedByRps = this.runtime.snapshot().owner === 'rps';
    this.emit({ hardwareAuthorized: false, phase: ownedByRps ? 'idle' : this.state.cameraState === 'running' ? 'cameraReady' : 'idle', cameraState: ownedByRps ? 'stopping' : this.state.cameraState, countdown: null, playerMove: null, machineMove: null, outcome: null });
    void this.cancelAction('locked', token).then(async () => { if (ownedByRps && this.runtime.snapshot().owner === 'rps') await this.runtime.stop(); });
  }

  async stop(reason: 'stopped' | 'unmounted' = 'stopped'): Promise<void> {
    this.generation += 1; this.clearTimers(); this.stable.reset();
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
    if (snapshot.state === 'running' && snapshot.owner === 'rps' && this.startGeneration !== null && this.startGeneration !== this.generation) { void this.runtime.stop(); return; }
    if (snapshot.state === 'running' && snapshot.owner !== 'rps') {
      const wasActive = this.state.cameraState === 'running' || ACTIVE_PHASES.has(this.state.phase) || this.state.hardwareAuthorized;
      if (wasActive) { this.generation += 1; this.clearTimers(); this.stable.reset(); const token = this.generation; this.emit({ cameraState: 'idle', phase: 'idle', cameraError: { code: 'VISION_BUSY', message: `视觉输入当前由 ${snapshot.owner ?? '其他功能'} 占用` }, countdown: null, hardwareAuthorized: false, playerMove: null, machineMove: null, outcome: null, stableFrames: 0 }); void this.cancelAction('stopped', token); }
      else this.emit({ cameraState: 'idle', phase: 'idle', cameraError: { code: 'VISION_BUSY', message: `视觉输入当前由 ${snapshot.owner ?? '其他功能'} 占用` } });
      return;
    }
    const leavingRunning = snapshot.state !== 'running' && (this.state.cameraState === 'running' || ACTIVE_PHASES.has(this.state.phase) || this.state.hardwareAuthorized);
    const cameraError = snapshot.lastError ? { code: snapshot.lastError.code, message: snapshot.lastError.message } : null;
    if (leavingRunning) {
      this.generation += 1; this.clearTimers(); this.stable.reset();
      const token = this.generation;
      this.emit({ phase: 'idle', countdown: null, cameraState: snapshot.state, cameraError, playerMove: null, machineMove: null, outcome: null, hardwareAuthorized: false, stableFrames: 0 });
      void this.cancelAction('stopped', token);
      return;
    }
    const phase = snapshot.state === 'running' && this.state.phase === 'idle' ? 'cameraReady' : this.state.phase;
    this.emit({ cameraState: snapshot.state, cameraError, phase });
  }

  private onResult(result: VisionLandmarkResult): void {
    if (this.state.phase !== 'capture') return;
    const classification = classifyResult(result);
    if (classification.move === null) this.lastInvalidReason = classification.reason;
    const stable = this.stable.push(classification); this.emit({ stableFrames: this.stable.frames });
    if (stable) { this.clearTimers(); this.emit({ phase: 'recognized', playerMove: stable.move, invalidReason: null }); this.schedule(() => this.reveal(), this.revealMs); }
  }

  private finishInvalid(reason: RpsInvalidReason): void { if (this.state.phase !== 'capture') return; this.stable.reset(); this.emit({ phase: 'invalid', invalidReason: this.lastInvalidReason ?? reason, stableFrames: 0 }); this.schedule(() => this.reveal(), this.revealMs); }
  private reveal(): void {
    if (this.state.phase !== 'recognized' && this.state.phase !== 'invalid') return;
    const player = this.state.playerMove; const machine = player ? machineMove(this.random) : null; const outcome = player && machine ? outcomeFor(player, machine) : null; const nextScore = outcome ? scoreFor(this.state.score, outcome) : this.state.score;
    this.emit({ phase: 'reveal', machineMove: machine, outcome });
    if (machine && outcome && this.hardwareAvailable() && this.state.hardwareAuthorized) void this.dispatch(machine, 'rps-reveal');
    this.schedule(() => this.emit({ phase: 'score', score: nextScore }), this.revealMs);
    this.schedule(() => this.finishRound(), this.revealMs + this.scoreMs);
  }

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

  private async finishRound(): Promise<void> {
    if (this.state.phase !== 'score') return;
    this.generation += 1; const token = this.generation;
    this.emit({ phase: 'ready', countdown: null, hardwareAuthorized: false });
    await this.cancelAction('stopped', token, this.state.action.status === 'dispatching');
  }

  private async cancelAction(reason: 'locked' | 'stopped' | 'unmounted' | 'reset', token: number, updateStatus = true): Promise<void> {
    if (!this.actionController) return;
    try { await this.actionController.cancel(reason); }
    finally { if (this.isCurrent(token) && updateStatus && this.state.action.status !== 'disabled') this.emit({ action: { status: 'cancelled', detail: '动作已撤销' }, hardwareAuthorized: false }); }
  }

  private emit(changes: Partial<RpsState> = {}): void { this.state = { ...this.state, ...changes }; this.listeners.forEach(listener => listener(this.state)); }
}
