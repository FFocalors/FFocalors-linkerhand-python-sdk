import { describe, expect, it, vi } from 'vitest';
import type { VisionPoseProposal } from '../../shared/contracts';
import type { VisionLandmarkResult, VisionRuntimeSnapshot } from '../../shared/vision-runtime';
import { FIST_HAND_LANDMARK_FIXTURE, OPEN_HAND_LANDMARK_FIXTURE } from './model';
import { canSubmitProposal, LatestWinsProposalDispatcher, TRACKING_LOSS_GRACE_MS, VisionFeatureController, VISION_RUNTIME_STOP_TIMEOUT_MS, type VisionProposalController, type VisionRuntimeLike } from './controller';

const snapshot = (owner: VisionRuntimeSnapshot['owner'] = 'vision', state: VisionRuntimeSnapshot['state'] = 'running'): VisionRuntimeSnapshot => ({ state, owner, cameraDeviceId: 'camera', model: 'ready', frameSequence: 1, fps: 30, droppedFrames: 0, inflight: 0, lastError: null });
function fakeRuntime(initial = snapshot()): VisionRuntimeLike & { emit: (result: VisionLandmarkResult) => void; stop: ReturnType<typeof vi.fn> } {
  let current = initial;
  const runtimeListeners = new Set<(value: VisionRuntimeSnapshot) => void>();
  const resultListeners = new Set<(value: VisionLandmarkResult) => void>();
  const stop = vi.fn(async () => { current = snapshot(null, 'idle'); runtimeListeners.forEach(listener => listener(current)); });
  return { snapshot: () => current, subscribe: listener => { runtimeListeners.add(listener); listener(current); return () => runtimeListeners.delete(listener); }, onResult: listener => { resultListeners.add(listener); return () => resultListeners.delete(listener); }, start: vi.fn(async () => { current = snapshot(); runtimeListeners.forEach(listener => listener(current)); }), stop, emit: result => resultListeners.forEach(listener => listener(result)) };
}
const result = (frameSequence: number, landmarks = OPEN_HAND_LANDMARK_FIXTURE): VisionLandmarkResult => ({ source: 'vision', hands: [{ handedness: 'left', confidence: 0.95, landmarks }], monotonicTimeMs: frameSequence, frameSequence, fps: 30, droppedFrames: 0, inflight: 0 });
const HALF_HAND_LANDMARK_FIXTURE = OPEN_HAND_LANDMARK_FIXTURE.map((point, index) => ({ x: (point.x + FIST_HAND_LANDMARK_FIXTURE[index].x) / 2, y: (point.y + FIST_HAND_LANDMARK_FIXTURE[index].y) / 2, z: (point.z + FIST_HAND_LANDMARK_FIXTURE[index].z) / 2 }));
const proposal = (id: string): VisionPoseProposal => ({ schemaVersion: 1, id, label: id, confidence: 0.9, positions: [0, 0, 0, 0, 0, 0] });
const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0));

describe('vision proposal gates', () => {
  it.each([
    ['non-O6', { model: 'L7' as const, authorized: true, calibrated: true, confidence: 0.9, locked: false }],
    ['unauthorized', { model: 'O6' as const, authorized: false, calibrated: true, confidence: 0.9, locked: false }],
    ['low confidence', { model: 'O6' as const, authorized: true, calibrated: true, confidence: 0.69, locked: false }],
    ['locked', { model: 'O6' as const, authorized: true, calibrated: true, confidence: 0.9, locked: true }],
  ])('does not submit when %s', (_reason, input) => {
    expect(canSubmitProposal({ ...input, runtimeState: 'running', runtimeOwner: 'vision' })).toBe(false);
  });

  it('permits an authorized O6 continuous proposal without mandatory calibration', () => {
    expect(canSubmitProposal({ model: 'O6', authorized: true, calibrated: true, confidence: 0.9, locked: false, runtimeState: 'running', runtimeOwner: 'vision' })).toBe(true);
    expect(canSubmitProposal({ model: 'O6', authorized: true, calibrated: false, confidence: 0.9, locked: false, runtimeState: 'running', runtimeOwner: 'vision' })).toBe(true);
  });

  it('revokes on lock and stops a vision-owned shared runtime', async () => {
    const runtime = fakeRuntime();
    const sink: VisionProposalController = { submit: vi.fn(), revoke: vi.fn() };
    const controller = new VisionFeatureController(runtime, sink);
    controller.setModel('O6');
    controller.setLocked(true);
    await flush();
    expect(sink.revoke).toHaveBeenCalledWith('控制已锁定');
    expect(runtime.stop).toHaveBeenCalledTimes(1);
    await controller.dispose();
    expect(runtime.stop).toHaveBeenCalledTimes(1);
  });

  it('revokes visual authorization without stopping an RPS-owned runtime on lock or unmount', async () => {
    const runtime = fakeRuntime(snapshot('rps'));
    const revoke = vi.fn();
    const controller = new VisionFeatureController(runtime, { submit: vi.fn(), revoke });
    controller.setLocked(true);
    await flush();
    expect(runtime.stop).not.toHaveBeenCalled();
    expect(revoke).toHaveBeenCalled();
    await controller.dispose();
    expect(runtime.stop).not.toHaveBeenCalled();
  });

  it('does not leave an unbounded or unhandled runtime stop promise', async () => {
    vi.useFakeTimers();
    try {
      const runtime = fakeRuntime();
      runtime.stop.mockImplementation(() => new Promise<void>(() => undefined));
      const controller = new VisionFeatureController(runtime);
      controller.setLocked(true);
      await vi.advanceTimersByTimeAsync(VISION_RUNTIME_STOP_TIMEOUT_MS);
      expect(runtime.stop).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps transitional poses visible and submits them continuously after opt in', async () => {
    const runtime = fakeRuntime();
    const submit = vi.fn();
    const sink: VisionProposalController = { submit, revoke: vi.fn() };
    const controller = new VisionFeatureController(runtime, sink);
    controller.setModel('O6');
    controller.start(document.createElement('video'));
    controller.beginCalibration();
    for (let frame = 1; frame <= 5; frame += 1) runtime.emit(result(frame));
    for (let frame = 6; frame <= 10; frame += 1) runtime.emit(result(frame, FIST_HAND_LANDMARK_FIXTURE));
    controller.setAuthorized(true);
    runtime.emit(result(11, HALF_HAND_LANDMARK_FIXTURE));
    await flush();
    expect(submit).toHaveBeenCalled();
    expect(submit.mock.calls[0][0].positions).toHaveLength(6);
    expect(controller.snapshot().lastResult?.hands[0].landmarks).toEqual(HALF_HAND_LANDMARK_FIXTURE);
    runtime.emit(result(12, FIST_HAND_LANDMARK_FIXTURE));
    await flush();
    expect(submit.mock.calls.at(-1)?.[0].label).toBe('握拳');
    runtime.emit({ ...result(13), hands: [], monotonicTimeMs: 13 });
    await flush();
    expect(controller.snapshot().lastProposal).toBeNull();
    expect(controller.snapshot().lastResult).not.toBeNull();
    expect(sink.revoke).toHaveBeenCalledWith('未检测到手');
  });

  it('bridges a short detector miss for the overlay but clears it after the grace window', async () => {
    const runtime = fakeRuntime();
    const controller = new VisionFeatureController(runtime);
    await controller.start(document.createElement('video'));
    runtime.emit({ ...result(1), monotonicTimeMs: 1000 });
    runtime.emit({ ...result(2), monotonicTimeMs: 1000 + TRACKING_LOSS_GRACE_MS, hands: [] });
    expect(controller.snapshot().lastResult).not.toBeNull();
    runtime.emit({ ...result(3), monotonicTimeMs: 1001 + TRACKING_LOSS_GRACE_MS, hands: [] });
    expect(controller.snapshot().lastResult).toBeNull();
    await controller.dispose();
  });

  it.each(['resolve', 'reject'] as const)('pumps a new generation after the old in-flight submit %s and suppresses stale errors', async action => {
    let settleFirst: ((error?: Error) => void) | undefined;
    const submit = vi.fn((value: VisionPoseProposal) => new Promise<void>((resolve, reject) => {
      if (value.id === 'first') settleFirst = error => error ? reject(error) : resolve();
      else resolve();
    }));
    const revoke = vi.fn();
    const errors: Array<[unknown, string]> = [];
    const dispatcher = new LatestWinsProposalDispatcher({ submit, revoke }, (error, operation) => errors.push([error, operation]));
    dispatcher.submit(proposal('first'));
    await flush();
    dispatcher.submit(proposal('old-pending'));
    dispatcher.submit(proposal('newest-old-generation'));
    dispatcher.revoke('停止');
    dispatcher.submit(proposal('new-generation'));
    expect(submit).toHaveBeenCalledTimes(1);
    if (action === 'reject') settleFirst?.(new Error('stale submit boom'));
    else settleFirst?.();
    await flush();
    expect(submit.mock.calls.map(([value]) => value.id)).toEqual(['first', 'new-generation']);
    expect(errors).toEqual([]);
    expect(revoke).toHaveBeenCalledWith('停止');
  });

  it('captures rejected async submit and revoke operations', async () => {
    const errors: Array<[unknown, string]> = [];
    const dispatcher = new LatestWinsProposalDispatcher({ submit: () => Promise.reject(new Error('submit boom')), revoke: () => Promise.reject(new Error('revoke boom')) }, (error, operation) => errors.push([error, operation]));
    dispatcher.submit(proposal('reject'));
    await flush();
    dispatcher.revoke('错误');
    await flush();
    expect(errors.map(([, operation]) => operation)).toEqual(['submit', 'revoke']);
  });

  it('dispose wins a pending submit race', async () => {
    let resolveFirst: (() => void) | undefined;
    const submit = vi.fn(() => new Promise<void>(resolve => { resolveFirst = resolve; }));
    const dispatcher = new LatestWinsProposalDispatcher({ submit, revoke: vi.fn() }, vi.fn());
    dispatcher.submit(proposal('first'));
    await flush();
    dispatcher.submit(proposal('pending'));
    dispatcher.dispose('页面离开');
    resolveFirst?.();
    await flush();
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it('revokes immediately on low confidence or a missing hand and does not auto-restore after unlock', async () => {
    const runtime = fakeRuntime();
    const submit = vi.fn();
    const revoke = vi.fn();
    const controller = new VisionFeatureController(runtime, { submit, revoke });
    controller.setModel('O6');
    await controller.start(document.createElement('video'));
    controller.beginCalibration();
    for (let frame = 1; frame <= 5; frame += 1) runtime.emit(result(frame));
    for (let frame = 6; frame <= 10; frame += 1) runtime.emit(result(frame, FIST_HAND_LANDMARK_FIXTURE));
    controller.setAuthorized(true);
    for (let frame = 11; frame <= 13; frame += 1) runtime.emit(result(frame));
    await flush();
    expect(submit).toHaveBeenCalled();

    runtime.emit({ ...result(14), hands: [{ handedness: 'left', confidence: 0.1, landmarks: OPEN_HAND_LANDMARK_FIXTURE }] });
    expect(controller.snapshot().lastProposal).toBeNull();
    expect(controller.snapshot().lastResult).not.toBeNull();
    await flush();
    expect(revoke).toHaveBeenCalledWith('手势置信度不足');
    runtime.emit({ ...result(15), hands: [] });
    expect(controller.snapshot().lastProposal).toBeNull();
    await flush();
    expect(revoke).toHaveBeenCalledWith('未检测到手');

    controller.setLocked(true);
    await flush();
    controller.setLocked(false);
    expect(controller.snapshot().authorized).toBe(false);
    expect(controller.snapshot().proposalAllowed).toBe(false);
  });
});
