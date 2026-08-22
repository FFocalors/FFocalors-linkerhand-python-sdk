import type { Landmark, HandLandmark } from '../../shared/vision-runtime';

export type Gesture = 'open' | 'fist' | 'unknown';
export type CalibrationPhase = 'idle' | 'open' | 'fist' | 'complete';
export type MapperSettings = { deadZone: number; emaAlpha: number; maxDeltaPerFrame: number };
export type CalibrationSnapshot = { phase: CalibrationPhase; openSamples: number; fistSamples: number; complete: boolean; openReference: number[] | null; fistReference: number[] | null };

export const DEFAULT_MAPPER_SETTINGS: MapperSettings = { deadZone: 0.025, emaAlpha: 0.35, maxDeltaPerFrame: 0.12 };
const FINGER_GROUPS = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16], [17, 18, 19, 20]] as const;
const clamp01 = (value: number): number => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
const distance = (a: Landmark, b: Landmark): number => Math.hypot(a.x - b.x, a.y - b.y, (a.z - b.z) * 0.25);

function fingerScore(landmarks: Landmark[], group: readonly number[]): number {
  const wrist = landmarks[0];
  const pip = landmarks[group[1]];
  const tip = landmarks[group[3]];
  if (!wrist || !pip || !tip) return 0;
  const extension = distance(tip, wrist) - distance(pip, wrist);
  return clamp01((extension + 0.035) / 0.19);
}

export function landmarkFeatures(landmarks: Landmark[]): number[] {
  if (landmarks.length !== 21) return [0, 0, 0, 0, 0, 0];
  const fingers = FINGER_GROUPS.map(group => fingerScore(landmarks, group));
  return [...fingers, fingers.reduce((sum, value) => sum + value, 0) / fingers.length];
}

export function classifyGesture(hand: HandLandmark): { gesture: Gesture; confidence: number; openness: number } {
  const features = landmarkFeatures(hand.landmarks);
  const openness = features.slice(0, 5).reduce((sum, value) => sum + value, 0) / 5;
  const margin = Math.abs(openness - 0.5) * 2;
  const confidence = clamp01(hand.confidence * (0.55 + margin * 0.45));
  if (openness >= 0.65) return { gesture: 'open', confidence, openness };
  if (openness <= 0.35) return { gesture: 'fist', confidence, openness };
  return { gesture: 'unknown', confidence: confidence * 0.5, openness };
}

export class GestureStabilizer {
  private candidate: Gesture = 'unknown';
  private count = 0;
  private stable: Gesture = 'unknown';
  private stableConfidence = 0;

  update(gesture: Gesture, confidence: number, frames = 3): { gesture: Gesture; confidence: number } {
    if (gesture === this.candidate) this.count += 1;
    else { this.candidate = gesture; this.count = 1; }
    if (this.count >= frames) {
      this.stable = gesture;
      this.stableConfidence = confidence;
    }
    return { gesture: this.stable, confidence: this.stableConfidence };
  }

  reset(): void { this.candidate = 'unknown'; this.count = 0; this.stable = 'unknown'; this.stableConfidence = 0; }
}

export class SessionCalibration {
  private phase: CalibrationPhase = 'idle';
  private open: number[][] = [];
  private fist: number[][] = [];
  private openReference: number[] | null = null;
  private fistReference: number[] | null = null;
  private readonly requiredSamples: number;

  constructor(requiredSamples = 3) { this.requiredSamples = Math.max(1, requiredSamples); }
  begin(): void { this.phase = 'open'; this.open = []; this.fist = []; this.openReference = null; this.fistReference = null; }
  accept(gesture: Gesture, landmarks: Landmark[]): void {
    if (this.phase !== 'open' && this.phase !== 'fist') return;
    if (gesture !== this.phase) return;
    const sample = landmarkFeatures(landmarks);
    if (this.phase === 'open') {
      this.open.push(sample);
      if (this.open.length >= this.requiredSamples) { this.openReference = average(this.open); this.phase = 'fist'; }
    } else {
      this.fist.push(sample);
      if (this.fist.length >= this.requiredSamples) { this.fistReference = average(this.fist); this.phase = 'complete'; }
    }
  }
  snapshot(): CalibrationSnapshot { return { phase: this.phase, openSamples: this.open.length, fistSamples: this.fist.length, complete: this.phase === 'complete', openReference: this.openReference ? [...this.openReference] : null, fistReference: this.fistReference ? [...this.fistReference] : null }; }
}

function average(samples: number[][]): number[] { return samples[0].map((_, index) => samples.reduce((sum, sample) => sum + sample[index], 0) / samples.length); }

export function mapLandmarksToO6(landmarks: Landmark[], calibration?: CalibrationSnapshot): number[] {
  const raw = landmarkFeatures(landmarks);
  if (!calibration?.complete || !calibration.openReference || !calibration.fistReference) return raw.map(clamp01);
  return raw.map((value, index) => {
    const low = calibration.fistReference![index];
    const high = calibration.openReference![index];
    return clamp01(Math.abs(high - low) < 0.02 ? value : (value - low) / (high - low));
  });
}

export class PoseMapper {
  private options: MapperSettings;
  private previous: number[] | null = null;
  constructor(settings: Partial<MapperSettings> = {}) { this.options = { ...DEFAULT_MAPPER_SETTINGS, ...settings }; }
  settings(): MapperSettings { return { ...this.options }; }
  setSettings(settings: Partial<MapperSettings>): void { this.options = { ...this.options, ...settings, deadZone: clamp01(settings.deadZone ?? this.options.deadZone), emaAlpha: clamp01(settings.emaAlpha ?? this.options.emaAlpha), maxDeltaPerFrame: clamp01(settings.maxDeltaPerFrame ?? this.options.maxDeltaPerFrame) }; }
  reset(): void { this.previous = null; }
  map(landmarks: Landmark[], calibration?: CalibrationSnapshot): number[] {
    const target = mapLandmarksToO6(landmarks, calibration);
    if (!this.previous) { this.previous = target; return [...target]; }
    const next = target.map((value, index) => {
      const old = this.previous![index];
      const smoothed = old + (value - old) * this.options.emaAlpha;
      const dead = Math.abs(smoothed - old) <= this.options.deadZone ? old : smoothed;
      return Math.max(0, Math.min(1, old + Math.max(-this.options.maxDeltaPerFrame, Math.min(this.options.maxDeltaPerFrame, dead - old))));
    });
    this.previous = next;
    return [...next];
  }
}

function makeLandmarks(points: Array<[number, number, number]>): Landmark[] { return points.map(([x, y, z]) => ({ x, y, z })); }

export const OPEN_HAND_LANDMARK_FIXTURE: Landmark[] = makeLandmarks([
  [0.50, 0.82, 0], [0.39, 0.69, 0], [0.30, 0.59, 0], [0.23, 0.48, 0], [0.15, 0.34, 0],
  [0.43, 0.62, 0], [0.41, 0.48, 0], [0.40, 0.35, 0], [0.39, 0.20, 0],
  [0.50, 0.60, 0], [0.50, 0.45, 0], [0.50, 0.30, 0], [0.50, 0.14, 0],
  [0.57, 0.62, 0], [0.59, 0.48, 0], [0.60, 0.35, 0], [0.61, 0.20, 0],
  [0.64, 0.66, 0], [0.68, 0.54, 0], [0.70, 0.43, 0], [0.72, 0.31, 0],
]);

export const FIST_HAND_LANDMARK_FIXTURE: Landmark[] = makeLandmarks([
  [0.50, 0.82, 0], [0.43, 0.73, 0], [0.42, 0.69, 0], [0.43, 0.66, 0], [0.45, 0.62, 0],
  [0.43, 0.65, 0], [0.45, 0.68, 0], [0.47, 0.70, 0], [0.48, 0.72, 0],
  [0.50, 0.64, 0], [0.51, 0.68, 0], [0.52, 0.70, 0], [0.53, 0.72, 0],
  [0.57, 0.65, 0], [0.58, 0.68, 0], [0.59, 0.70, 0], [0.60, 0.72, 0],
  [0.63, 0.68, 0], [0.65, 0.70, 0], [0.66, 0.72, 0], [0.67, 0.74, 0],
]);
export const OPEN_HAND_FIXTURE = OPEN_HAND_LANDMARK_FIXTURE;
export const FIST_HAND_FIXTURE = FIST_HAND_LANDMARK_FIXTURE;
