import { classifyHand, classifyResult, StableMoveWindow } from './classifier';
import type { HandLandmark, Landmark, VisionLandmarkResult } from '../../shared/vision-runtime';

function fixture(extended: readonly number[]): HandLandmark {
  const points: Landmark[] = Array.from({ length: 21 }, () => ({ x: 0, y: 0, z: .1 }));
  points[0] = { x: 0, y: .7, z: .1 };
  const fingers: Array<[number, number, number]> = [[8, 6, 5], [12, 10, 9], [16, 14, 13], [20, 18, 17]];
  fingers.forEach(([tip, pip, mcp], index) => { points[mcp] = { x: index * .06 - .09, y: .5, z: .1 }; points[pip] = { x: index * .06 - .09, y: extended.includes(index) ? .25 : .48, z: .1 }; points[tip] = { x: index * .06 - .09, y: extended.includes(index) ? .05 : .46, z: .1 }; });
  points[1] = { x: -.15, y: .62, z: .1 }; points[3] = { x: -.24, y: .48, z: .1 }; points[4] = { x: -.3, y: .4, z: .1 };
  return { handedness: 'right', confidence: .98, landmarks: points };
}
const result = (hands: HandLandmark[]): VisionLandmarkResult => ({ source: 'rps', hands, monotonicTimeMs: 1, frameSequence: 1, fps: 30, droppedFrames: 0, inflight: 0 });

describe('RPS landmark classifier', () => {
  it.each([[[], 'rock'], [[0, 1, 2, 3], 'paper'], [[0, 1], 'scissors']] as const)('recognizes %s', (extended, expected) => { expect(classifyHand(fixture(extended))).toMatchObject({ move: expected }); });
  it('reports no hand and multiple hands without inventing a move', () => { const hand = fixture([]); expect(classifyResult(result([]))).toMatchObject({ move: null, reason: 'no-hand' }); expect(classifyResult(result([hand, hand]))).toMatchObject({ move: null, reason: 'multiple-hands' }); });
  it('rejects low confidence and requires a stable window', () => { const hand = fixture([]); expect(classifyHand({ ...hand, confidence: .2 })).toMatchObject({ move: null, reason: 'low-confidence' }); const window = new StableMoveWindow(3, .7); const sample = { move: 'rock' as const, confidence: .9 }; expect(window.push(sample)).toBeNull(); expect(window.push(sample)).toBeNull(); expect(window.push(sample)).toMatchObject({ move: 'rock' }); expect(window.frames).toBe(3); expect(window.push({ move: 'paper', confidence: .9 })).toBeNull(); });
});
