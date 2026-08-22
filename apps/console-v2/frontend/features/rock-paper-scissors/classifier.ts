import type { HandLandmark, Landmark, VisionLandmarkResult } from '../../shared/vision-runtime';
import type { RpsInvalidReason, RpsMove } from './types';

export type RpsClassification = { move: RpsMove; confidence: number } | { move: null; reason: RpsInvalidReason; confidence: number };
export type RpsClassifierOptions = { minHandConfidence?: number; minGestureConfidence?: number; blurDepthRange?: number };

const FINGER_INDICES = [[8, 6, 5], [12, 10, 9], [16, 14, 13], [20, 18, 17]] as const;
const DEFAULTS = { minHandConfidence: .65, minGestureConfidence: .62, blurDepthRange: .015 };
const distance = (a: Landmark, b: Landmark) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);

function isExtended(landmarks: readonly Landmark[], tip: number, pip: number, mcp: number): boolean {
  const wrist = landmarks[0];
  // A finger is extended when its tip is farther from the wrist than the PIP
  // and its tip-to-MCP direction continues past the PIP. This works for both
  // mirrored camera previews and does not depend on handedness labels.
  return distance(landmarks[tip], wrist) > distance(landmarks[pip], wrist) * 1.12
    && distance(landmarks[tip], landmarks[mcp]) > distance(landmarks[pip], landmarks[mcp]) * .75;
}

function thumbExtended(landmarks: Landmark[]): boolean {
  return distance(landmarks[4], landmarks[0]) > distance(landmarks[3], landmarks[0]) * 1.08;
}

function gestureConfidence(hand: HandLandmark, extended: boolean[], move: RpsMove, blurDepthRange: number): number {
  const count = extended.filter(Boolean).length;
  const expected = move === 'rock' ? 0 : move === 'paper' ? 4 : 2;
  const countConfidence = Math.max(0, 1 - Math.abs(count - expected) / 4);
  const palmScale = Math.max(distance(hand.landmarks[0], hand.landmarks[9]), .001);
  const depthRange = Math.max(...hand.landmarks.map(point => point.z)) - Math.min(...hand.landmarks.map(point => point.z));
  const geometryConfidence = Math.min(1, palmScale * 8) * (depthRange < blurDepthRange ? .65 : 1);
  return Math.max(0, Math.min(1, hand.confidence * .55 + countConfidence * .3 + geometryConfidence * .15));
}

export function classifyHand(hand: HandLandmark, options: RpsClassifierOptions = {}): RpsClassification {
  const settings = { ...DEFAULTS, ...options };
  if (hand.landmarks.length !== 21) return { move: null, reason: 'blurred', confidence: 0 };
  if (hand.confidence < settings.minHandConfidence) return { move: null, reason: 'low-confidence', confidence: hand.confidence };
  const extended = FINGER_INDICES.map(([tip, pip, mcp]) => isExtended(hand.landmarks, tip, pip, mcp));
  const extendedCount = extended.filter(Boolean).length;
  const candidates: RpsMove[] = extendedCount === 0 ? ['rock'] : extended[0] && extended[1] && !extended[2] && !extended[3] ? ['scissors'] : extendedCount === 4 ? ['paper'] : [];
  if (candidates.length === 0) return { move: null, reason: 'unknown', confidence: .35 };
  const move = candidates[0];
  const confidence = gestureConfidence(hand, extended, move, settings.blurDepthRange);
  if (confidence < settings.minGestureConfidence) return { move: null, reason: 'blurred', confidence };
  return { move, confidence };
}

export function classifyResult(result: VisionLandmarkResult, options: RpsClassifierOptions = {}): RpsClassification {
  if (result.hands.length === 0) return { move: null, reason: 'no-hand', confidence: 0 };
  if (result.hands.length > 1) return { move: null, reason: 'multiple-hands', confidence: 0 };
  return classifyHand(result.hands[0], options);
}

/** Requires consecutive, high-confidence frames of the same move. */
export class StableMoveWindow {
  private readonly requiredFrames: number;
  private readonly minConfidence: number;
  private move: RpsMove | null = null;
  private count = 0;

  constructor(requiredFrames = 3, minConfidence = .7) {
    this.requiredFrames = Math.max(1, requiredFrames);
    this.minConfidence = minConfidence;
  }

  reset(): void { this.move = null; this.count = 0; }
  get frames(): number { return this.count; }
  push(classification: RpsClassification): { move: RpsMove; confidence: number } | null {
    if (classification.move === null || classification.confidence < this.minConfidence) { this.reset(); return null; }
    if (classification.move !== this.move) { this.move = classification.move; this.count = 1; }
    else this.count += 1;
    return this.count >= this.requiredFrames ? { move: classification.move, confidence: classification.confidence } : null;
  }
}
