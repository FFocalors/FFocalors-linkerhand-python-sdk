import { RpsGameController } from './controller';
import type { RpsActionController, RpsCapabilities, RpsScheduler, RpsState, RpsVisionRuntime } from './types';
import type { HandLandmark, Landmark, VisionLandmarkResult, VisionRuntimeSnapshot } from '../../shared/vision-runtime';

class FakeScheduler implements RpsScheduler {
  private id = 0;
  private tasks = new Map<number, { callback: () => void; delay: number }>();
  setTimeout(callback: () => void, delay: number): number { const id = ++this.id; this.tasks.set(id, { callback, delay }); return id; }
  clearTimeout(id: number): void { this.tasks.delete(id); }
  runNext(): number { const entry = this.tasks.entries().next().value as [number, { callback: () => void; delay: number }] | undefined; if (!entry) throw new Error('no scheduled task'); this.tasks.delete(entry[0]); entry[1].callback(); return entry[1].delay; }
  get pending(): number { return this.tasks.size; }
}

class FakeRuntime implements RpsVisionRuntime {
  snapshotValue: VisionRuntimeSnapshot = { state: 'idle', owner: null, cameraDeviceId: null, model: 'unloaded', frameSequence: 0, fps: null, droppedFrames: 0, inflight: 0, lastError: null };
  private runtimeListeners = new Set<(snapshot: VisionRuntimeSnapshot) => void>();
  private resultListeners = new Set<(result: VisionLandmarkResult) => void>();
  starts = 0; stops = 0; startError: Error | null = null; startGate: Promise<void> | null = null; resolveStart!: () => void;
  async start(_video: HTMLVideoElement, source: 'rps'): Promise<void> { this.starts += 1; if (this.startError) throw this.startError; if (this.startGate) await this.startGate; this.emitSnapshot({ state: 'running', owner: source, model: 'ready', lastError: null }); }
  async stop(): Promise<void> { this.stops += 1; this.emitSnapshot({ state: 'idle', owner: null, model: 'unloaded' }); }
  subscribe = (listener: (snapshot: VisionRuntimeSnapshot) => void): (() => void) => { this.runtimeListeners.add(listener); listener(this.snapshotValue); return () => this.runtimeListeners.delete(listener); };
  onResult = (listener: (result: VisionLandmarkResult) => void): (() => void) => { this.resultListeners.add(listener); return () => this.resultListeners.delete(listener); };
  snapshot = (): VisionRuntimeSnapshot => this.snapshotValue;
  emitSnapshot(changes: Partial<VisionRuntimeSnapshot>): void { this.snapshotValue = { ...this.snapshotValue, ...changes }; this.runtimeListeners.forEach(listener => listener(this.snapshotValue)); }
  emit(result: VisionLandmarkResult): void { this.resultListeners.forEach(listener => listener(result)); }
  get subscriberCount(): number { return this.runtimeListeners.size + this.resultListeners.size; }
}

const capabilities = (model: 'O6' | 'L7'): RpsCapabilities => ({ model, supportedOperations: model === 'O6' ? ['setPosition'] : [] } as RpsCapabilities);
const fakeVideo = {} as HTMLVideoElement;
const noHand = (): VisionLandmarkResult => ({ source: 'rps', hands: [], monotonicTimeMs: 1, frameSequence: 1, fps: 30, droppedFrames: 0, inflight: 0 });
function paperHand(): HandLandmark {
  const points: Landmark[] = Array.from({ length: 21 }, () => ({ x: 0, y: 0, z: .1 })); points[0] = { x: 0, y: .7, z: .1 };
  [[8, 6, 5], [12, 10, 9], [16, 14, 13], [20, 18, 17]].forEach(([tip, pip, mcp], index) => { points[mcp] = { x: index * .06 - .09, y: .5, z: .1 }; points[pip] = { x: index * .06 - .09, y: .25, z: .1 }; points[tip] = { x: index * .06 - .09, y: .05, z: .1 }; });
  points[1] = { x: -.15, y: .62, z: .1 }; points[3] = { x: -.24, y: .48, z: .1 }; points[4] = { x: -.3, y: .4, z: .1 };
  return { handedness: 'right', confidence: .98, landmarks: points };
}
const paperResult = (): VisionLandmarkResult => ({ ...noHand(), hands: [paperHand()] });
async function ready(controller: RpsGameController, runtime: FakeRuntime): Promise<void> { controller.attach(fakeVideo); await controller.startCamera(); expect(runtime.snapshot().state).toBe('running'); }

describe('RPS deterministic controller', () => {
  it('runs countdown, capture, invalid, reveal, score and ready with no score mutation', async () => {
    const runtime = new FakeRuntime(); const scheduler = new FakeScheduler(); const controller = new RpsGameController({ runtime, capabilities: capabilities('L7'), scheduler }); const phases: RpsState['phase'][] = []; controller.subscribe(state => phases.push(state.phase)); await ready(controller, runtime);
    expect(controller.beginRound()).toBe(true); expect(controller.snapshot().countdown).toBe(3); scheduler.runNext(); expect(controller.snapshot().countdown).toBe(2); scheduler.runNext(); expect(controller.snapshot().countdown).toBe(1); scheduler.runNext(); expect(controller.snapshot().phase).toBe('capture'); scheduler.runNext(); expect(controller.snapshot().phase).toBe('invalid'); scheduler.runNext(); expect(controller.snapshot().phase).toBe('reveal'); scheduler.runNext(); expect(controller.snapshot().phase).toBe('score'); scheduler.runNext(); expect(controller.snapshot().phase).toBe('ready'); expect(controller.snapshot().score).toEqual({ player: 0, machine: 0, draws: 0 }); expect(phases).toEqual(expect.arrayContaining(['countdown', 'capture', 'invalid', 'reveal', 'score', 'ready']));
  });

  it('recognizes a stable gesture and scores exactly once', async () => {
    const runtime = new FakeRuntime(); const scheduler = new FakeScheduler(); const controller = new RpsGameController({ runtime, capabilities: capabilities('L7'), scheduler, random: () => 0 }); await ready(controller, runtime); controller.beginRound(); scheduler.runNext(); scheduler.runNext(); scheduler.runNext(); runtime.emit(paperResult()); runtime.emit(paperResult()); expect(controller.snapshot().phase).toBe('capture'); runtime.emit(paperResult()); expect(controller.snapshot().phase).toBe('recognized'); scheduler.runNext(); expect(controller.snapshot().phase).toBe('reveal'); scheduler.runNext(); expect(controller.snapshot().phase).toBe('score'); const score = controller.snapshot().score; scheduler.runNext(); expect(controller.snapshot().phase).toBe('ready'); expect(controller.snapshot().score).toEqual(score); expect(score).toEqual({ player: 1, machine: 0, draws: 0 });
  });

  it('does not dispatch before explicit O6 authorization and supports action tests only after it', async () => {
    const runtime = new FakeRuntime(); const scheduler = new FakeScheduler(); const calls: string[] = []; const action: RpsActionController = { authorize: async () => { calls.push('authorize'); return true; }, dispatch: async request => { calls.push(`${request.reason}:${request.move}`); return { status: 'executed' }; }, cancel: async reason => { calls.push(`cancel:${reason}`); } }; const controller = new RpsGameController({ runtime, capabilities: capabilities('O6'), actionController: action, scheduler }); await ready(controller, runtime); expect(await controller.testAction('rock')).toBe(false); expect(controller.beginRound()).toBe(false); await controller.authorizeHardware(); await controller.testAction('rock'); expect(calls).toContain('rps-test:rock'); expect(controller.beginRound()).toBe(true); controller.lock(); expect(await controller.testAction('paper')).toBe(false); expect(calls).toContain('cancel:locked');
  });

  it('never exposes action dispatch for non-O6 even when a controller is present', async () => { const runtime = new FakeRuntime(); const action: RpsActionController = { authorize: async () => true, dispatch: vi.fn(async () => ({ status: 'executed' as const })), cancel: async () => undefined }; const controller = new RpsGameController({ runtime, capabilities: capabilities('L7'), actionController: action }); await ready(controller, runtime); expect(await controller.testAction('scissors')).toBe(false); expect(action.dispatch).not.toHaveBeenCalled(); });

  it('handles runtime error/device-lost as a session abort and clears timers and authorization', async () => {
    const runtime = new FakeRuntime(); const scheduler = new FakeScheduler(); const action: RpsActionController = { authorize: async () => true, dispatch: async () => ({ status: 'executed' }), cancel: vi.fn(async () => undefined) }; const controller = new RpsGameController({ runtime, capabilities: capabilities('O6'), actionController: action, scheduler }); await ready(controller, runtime); await controller.authorizeHardware(); controller.beginRound(); scheduler.runNext(); expect(scheduler.pending).toBe(1); runtime.emitSnapshot({ state: 'device-lost', owner: null, lastError: { code: 'CAMERA_DEVICE_LOST', message: 'lost' } }); expect(controller.snapshot().phase).toBe('idle'); expect(controller.snapshot().hardwareAuthorized).toBe(false); expect(scheduler.pending).toBe(0); expect(action.cancel).toHaveBeenCalled();
  });

  it('reports busy runtime as an idle RPS camera and does not stop a runtime owned by vision', async () => { const runtime = new FakeRuntime(); runtime.emitSnapshot({ state: 'running', owner: 'vision', model: 'ready' }); const controller = new RpsGameController({ runtime, capabilities: capabilities('L7') }); controller.attach(fakeVideo); expect(controller.snapshot().phase).toBe('idle'); expect(controller.snapshot().cameraState).toBe('idle'); expect(controller.snapshot().cameraError?.code).toBe('VISION_BUSY'); await controller.stop(); expect(runtime.stops).toBe(0); controller.lock(); await Promise.resolve(); expect(runtime.stops).toBe(0); });

  it('locks an RPS-owned runtime and stops it without affecting the vision owner', async () => { const runtime = new FakeRuntime(); runtime.emitSnapshot({ state: 'running', owner: 'rps', model: 'ready' }); const controller = new RpsGameController({ runtime, capabilities: capabilities('L7') }); controller.attach(fakeVideo); controller.lock(); await Promise.resolve(); await Promise.resolve(); expect(runtime.stops).toBe(1); expect(controller.snapshot().cameraState).toBe('idle'); });

  it('keeps late authorization and dispatch promises from reviving a cancelled session', async () => {
    const runtime = new FakeRuntime(); const scheduler = new FakeScheduler(); let resolveAuth!: (allowed: boolean) => void; let resolveDispatch!: (result: { status: 'executed' }) => void; const action: RpsActionController = { authorize: () => new Promise(resolve => { resolveAuth = resolve; }), dispatch: () => new Promise(resolve => { resolveDispatch = resolve; }), cancel: async () => undefined }; const controller = new RpsGameController({ runtime, capabilities: capabilities('O6'), actionController: action, scheduler }); await ready(controller, runtime);
    const firstAuth = controller.authorizeHardware(); controller.lock(); resolveAuth(true); await firstAuth; await Promise.resolve(); await Promise.resolve(); runtime.emitSnapshot({ state: 'running', owner: 'rps', model: 'ready' }); expect(controller.snapshot().hardwareAuthorized).toBe(false);
    const secondAuth = controller.authorizeHardware(); resolveAuth(true); await secondAuth; expect(controller.snapshot().hardwareAuthorized).toBe(true);
    const dispatch = controller.testAction('rock'); controller.lock(); resolveDispatch({ status: 'executed' }); await dispatch; expect(controller.snapshot().action.status).not.toBe('executed');
  });

  it('reset returns to cameraReady and clears score, while dispose stops, unsubscribes and cancels', async () => { const runtime = new FakeRuntime(); const scheduler = new FakeScheduler(); const action: RpsActionController = { authorize: async () => true, dispatch: async () => ({ status: 'executed' }), cancel: vi.fn(async () => undefined) }; const controller = new RpsGameController({ runtime, capabilities: capabilities('O6'), actionController: action, scheduler }); await ready(controller, runtime); await controller.authorizeHardware(); controller.reset(); expect(controller.snapshot().phase).toBe('cameraReady'); expect(controller.snapshot().score).toEqual({ player: 0, machine: 0, draws: 0 }); await controller.dispose(); expect(runtime.stops).toBe(1); expect(runtime.subscriberCount).toBe(0); expect(action.cancel).toHaveBeenCalledWith('unmounted'); });

  it('reports permission/busy start errors without opening a second session', async () => { const runtime = new FakeRuntime(); runtime.startError = Object.assign(new Error('busy'), { code: 'VISION_BUSY' }); const controller = new RpsGameController({ runtime, capabilities: capabilities('L7') }); controller.attach(fakeVideo); await controller.startCamera(); expect(controller.snapshot().cameraError?.code).toBe('VISION_BUSY'); expect(runtime.starts).toBe(1); });

  it('does not revive a start promise after stop', async () => { const runtime = new FakeRuntime(); runtime.startGate = new Promise(resolve => { runtime.resolveStart = resolve; }); const controller = new RpsGameController({ runtime, capabilities: capabilities('L7') }); controller.attach(fakeVideo); const start = controller.startCamera(); await Promise.resolve(); const stop = controller.stop(); runtime.resolveStart(); await start; await stop; expect(controller.snapshot().phase).toBe('idle'); expect(runtime.stops).toBe(1); });
});
