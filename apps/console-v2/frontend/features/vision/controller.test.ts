import { describe, expect, it, vi } from 'vitest';
import type { VisionLandmarkResult, VisionRuntimeSnapshot } from '../../shared/vision-runtime';
import { FIST_HAND_LANDMARK_FIXTURE, OPEN_HAND_LANDMARK_FIXTURE } from './model';
import { canSubmitProposal, VisionFeatureController, type VisionProposalController, type VisionRuntimeLike } from './controller';

const snapshot = (owner: VisionRuntimeSnapshot['owner'] = 'vision', state: VisionRuntimeSnapshot['state'] = 'running'): VisionRuntimeSnapshot => ({ state, owner, cameraDeviceId: 'camera', model: 'ready', frameSequence: 1, fps: 30, droppedFrames: 0, inflight: 0, lastError: null });
function fakeRuntime(initial = snapshot()): VisionRuntimeLike & { emit: (result: VisionLandmarkResult) => void; stop: ReturnType<typeof vi.fn> } {
  let current = initial;
  const runtimeListeners = new Set<(value: VisionRuntimeSnapshot) => void>();
  const resultListeners = new Set<(value: VisionLandmarkResult) => void>();
  const stop = vi.fn(async () => { current = snapshot(null, 'idle'); runtimeListeners.forEach(listener => listener(current)); });
  return { snapshot: () => current, subscribe: listener => { runtimeListeners.add(listener); listener(current); return () => runtimeListeners.delete(listener); }, onResult: listener => { resultListeners.add(listener); return () => resultListeners.delete(listener); }, start: vi.fn(async () => { current = snapshot(); runtimeListeners.forEach(listener => listener(current)); }), stop, emit: result => resultListeners.forEach(listener => listener(result)) };
}
const result = (frameSequence: number, landmarks = OPEN_HAND_LANDMARK_FIXTURE): VisionLandmarkResult => ({ source: 'vision', hands: [{ handedness: 'left', confidence: 0.95, landmarks }], monotonicTimeMs: frameSequence, frameSequence, fps: 30, droppedFrames: 0, inflight: 0 });

describe('vision proposal gates', () => {
  it.each([
    ['non-O6', { model: 'L7' as const, authorized: true, calibrated: true, confidence: 0.9, locked: false }],
    ['unauthorized', { model: 'O6' as const, authorized: false, calibrated: true, confidence: 0.9, locked: false }],
    ['uncalibrated', { model: 'O6' as const, authorized: true, calibrated: false, confidence: 0.9, locked: false }],
    ['low confidence', { model: 'O6' as const, authorized: true, calibrated: true, confidence: 0.69, locked: false }],
    ['locked', { model: 'O6' as const, authorized: true, calibrated: true, confidence: 0.9, locked: true }],
  ])('does not submit when %s', (_reason, input) => {
    expect(canSubmitProposal({ ...input, runtimeState: 'running', runtimeOwner: 'vision' })).toBe(false);
  });

  it('permits only an authorized calibrated O6 complete-vector proposal', () => {
    expect(canSubmitProposal({ model: 'O6', authorized: true, calibrated: true, confidence: 0.9, locked: false, runtimeState: 'running', runtimeOwner: 'vision' })).toBe(true);
  });

  it('revokes on lock and stops the shared runtime on dispose', async () => {
    const runtime = fakeRuntime();
    const sink: VisionProposalController = { submit: vi.fn(), revoke: vi.fn() };
    const controller = new VisionFeatureController(runtime, sink);
    controller.setModel('O6');
    controller.setLocked(true);
    expect(sink.revoke).toHaveBeenCalledWith('控制已锁定');
    await controller.dispose();
    expect(runtime.stop).toHaveBeenCalledTimes(1);
  });

  it('does not stop an RPS-owned runtime during unmount', async () => {
    const runtime = fakeRuntime(snapshot('rps'));
    const controller = new VisionFeatureController(runtime);
    await controller.dispose();
    expect(runtime.stop).not.toHaveBeenCalled();
  });

  it('submits only after three stable frames for each calibration pose', () => {
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
    for (let frame = 11; frame <= 13; frame += 1) runtime.emit(result(frame, FIST_HAND_LANDMARK_FIXTURE));
    expect(submit).toHaveBeenCalled();
    expect(submit.mock.calls[0][0].positions).toHaveLength(6);
  });
});
