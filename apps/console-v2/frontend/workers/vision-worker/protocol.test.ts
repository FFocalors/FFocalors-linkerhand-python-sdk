import { describe, expect, it } from 'vitest';
import type { VisionLandmarkResult, VisionWorkerRequest, VisionWorkerResponse } from '../../shared/vision-runtime';

describe('vision worker protocol fixture', () => {
  it('keeps a frame request and result JSON shape stable', () => {
    const request: VisionWorkerRequest = { type: 'init', requestId: 'fixture-init', modelAssetUrl: '/vision/hand_landmarker.task', wasmRootUrl: '/vision/wasm/', numHands: 2, minHandDetectionConfidence: .5, minHandPresenceConfidence: .5, minTrackingConfidence: .5 };
    const result: VisionLandmarkResult = { source: 'vision', frameSequence: 7, monotonicTimeMs: 1234, fps: 15, droppedFrames: 2, inflight: 1, hands: [{ handedness: 'left', confidence: .9, landmarks: Array.from({ length: 21 }, (_, index) => ({ x: index / 21, y: index / 21, z: 0 })) }] };
    const response: VisionWorkerResponse = { type: 'result', requestId: 'fixture-frame', result };
    expect(request.type).toBe('init');
    expect(response.result.hands[0].landmarks).toHaveLength(21);
    expect(response.result.inflight).toBe(1);
    expect(JSON.parse(JSON.stringify(response))).toMatchObject({ type: 'result', result: { frameSequence: 7, droppedFrames: 2 } });
  });
});
