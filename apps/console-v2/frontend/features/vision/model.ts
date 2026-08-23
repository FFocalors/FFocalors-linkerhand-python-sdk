import type { Landmark, HandLandmark } from '../../shared/vision-runtime';

export type Gesture = 'open' | 'fist' | 'unknown';
export type CalibrationPhase = 'idle' | 'open' | 'fist' | 'complete';
export type MapperSettings = { deadZone: number; emaAlpha: number; maxDeltaPerFrame: number };
export type CalibrationSnapshot = { phase: CalibrationPhase; openSamples: number; fistSamples: number; complete: boolean; openReference: number[] | null; fistReference: number[] | null; openPose: number[] | null; fistPose: number[] | null };

export const DEFAULT_MAPPER_SETTINGS: MapperSettings = { deadZone: 0.02, emaAlpha: 0.35, maxDeltaPerFrame: 0.12 };
export const MIN_STABLE_GESTURE_CONFIDENCE = 0.5;

const clamp01 = (value: number): number => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));

function dist3(a: Landmark, b: Landmark): number {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

function angleAt(a: Landmark, b: Landmark, c: Landmark): number {
  const ba = { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z };
  const bc = { x: c.x - b.x, y: c.y - b.y, z: c.z - b.z };
  const dot = ba.x * bc.x + ba.y * bc.y + ba.z * bc.z;
  const normBA = Math.hypot(ba.x, ba.y, ba.z);
  const normBC = Math.hypot(bc.x, bc.y, bc.z);
  if (normBA < 1e-8 || normBC < 1e-8) return Math.PI;
  return Math.acos(Math.max(-1, Math.min(1, dot / (normBA * normBC))));
}

function jointBend(straight: number, bent: number, angle: number): number {
  return clamp01((straight - angle) / (straight - bent));
}

function mean(values: Landmark[]): Landmark {
  const n = values.length;
  return {
    x: values.reduce((s, v) => s + v.x, 0) / n,
    y: values.reduce((s, v) => s + v.y, 0) / n,
    z: values.reduce((s, v) => s + v.z, 0) / n,
  };
}

function fingerCurl(
  wrist: Landmark,
  mcp: Landmark,
  pip: Landmark,
  dip: Landmark,
  tip: Landmark,
  palmCenter: Landmark,
): number {
  const a1 = angleAt(wrist, mcp, pip);
  const a2 = angleAt(mcp, pip, dip);
  const a3 = angleAt(pip, dip, tip);
  const proximal = 0.45 * jointBend(2.65, 1.05, a1) + 0.55 * jointBend(2.85, 1.0, a2);
  const distal = 0.55 * jointBend(2.85, 1.0, a2) + 0.45 * jointBend(2.85, 1.0, a3);
  const tipDist = dist3(tip, palmCenter);
  const mcpDist = dist3(mcp, palmCenter);
  const chainLen = dist3(mcp, pip) + dist3(pip, dip) + dist3(dip, tip);
  const tipAux = chainLen > 1e-6 ? 1 - clamp01((tipDist - mcpDist) / (chainLen * 0.75)) : 0;
  return clamp01(0.45 * proximal + 0.35 * distal + 0.2 * tipAux);
}

function thumbFeatures(
  wrist: Landmark,
  cmc: Landmark,
  mcp: Landmark,
  ip: Landmark,
  tip: Landmark,
  palmCenter: Landmark,
  palmScale: number,
): { bend: number; swing: number } {
  const angleBend = clamp01(
    0.55 * jointBend(2.55, 1.05, angleAt(cmc, mcp, ip)) +
    0.45 * jointBend(2.85, 1.0, angleAt(mcp, ip, tip)),
  );

  const tipPalmDist = dist3(tip, palmCenter) / palmScale;
  const palmAux = clamp01((1.15 - tipPalmDist) / (1.15 - 0.35));
  const tipBaseDist = Math.min(
    dist3(tip, mcp),
    dist3(tip, { x: (palmCenter.x + wrist.x) / 2, y: (palmCenter.y + wrist.y) / 2, z: (palmCenter.z + wrist.z) / 2 }),
  ) / palmScale;
  const baseAux = clamp01((1.05 - tipBaseDist) / (1.05 - 0.30));

  const chainLen = dist3(cmc, mcp) + dist3(mcp, ip) + dist3(ip, tip);
  const tipDist = dist3(tip, palmCenter);
  const mcpDist = dist3(mcp, palmCenter);
  const tipAux = chainLen > 1e-6 ? 1 - clamp01((tipDist - mcpDist) / (chainLen * 0.75)) : 0;
  const opposition = Math.max(tipAux, palmAux, baseAux);

  const bendLinear = clamp01(0.5 * angleBend + 0.34 * opposition + 0.16 * Math.max(angleBend, opposition));
  const bend = clamp01(Math.pow(bendLinear, 0.62));

  const swingRaw = dist3(tip, { x: palmCenter.x, y: palmCenter.y, z: palmCenter.z }) / palmScale;
  const swing = clamp01((swingRaw - 0.25) / 0.85);

  return { bend, swing };
}

export function extractContinuousPose(landmarks: Landmark[]): number[] | null {
  if (landmarks.length !== 21) return null;

  const wrist = landmarks[0];
  const palmCenter = mean([wrist, landmarks[5], landmarks[9], landmarks[13], landmarks[17]]);
  const palmScale = Math.max(dist3(landmarks[5], landmarks[17]), dist3(wrist, landmarks[9]), 1e-6);

  const index = fingerCurl(wrist, landmarks[5], landmarks[6], landmarks[7], landmarks[8], palmCenter);
  const middle = fingerCurl(wrist, landmarks[9], landmarks[10], landmarks[11], landmarks[12], palmCenter);
  const ring = fingerCurl(wrist, landmarks[13], landmarks[14], landmarks[15], landmarks[16], palmCenter);
  const little = fingerCurl(wrist, landmarks[17], landmarks[18], landmarks[19], landmarks[20], palmCenter);

  const thumb = thumbFeatures(wrist, landmarks[1], landmarks[2], landmarks[3], landmarks[4], palmCenter, palmScale);

  return [
    clamp01(1 - thumb.bend),
    clamp01(thumb.swing),
    clamp01(1 - index),
    clamp01(1 - middle),
    clamp01(1 - ring),
    clamp01(1 - little),
  ];
}

export function landmarkFeatures(landmarks: Landmark[]): number[] {
  if (landmarks.length !== 21) return [0, 0, 0, 0, 0, 0];
  const raw = extractContinuousPose(landmarks);
  return raw ?? [0, 0, 0, 0, 0, 0];
}

export function classifyGesture(hand: HandLandmark): { gesture: Gesture; confidence: number; openness: number } {
  const features = landmarkFeatures(hand.landmarks);
  const openness = features.slice(2).reduce((sum, value) => sum + value, 0) / 4;
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
    if (gesture === 'unknown' || confidence < MIN_STABLE_GESTURE_CONFIDENCE) {
      this.reset();
      return { gesture: 'unknown', confidence: 0 };
    }
    if (gesture === this.candidate) this.count += 1;
    else { this.candidate = gesture; this.count = 1; this.stable = 'unknown'; this.stableConfidence = 0; }
    if (this.count >= frames) { this.stable = gesture; this.stableConfidence = confidence; }
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
  private lastAcceptTime = 0;
  private readonly minSampleIntervalMs = 500;

  constructor(requiredSamples = 3) { this.requiredSamples = Math.max(1, requiredSamples); }
  begin(): void { this.phase = 'open'; this.open = []; this.fist = []; this.openReference = null; this.fistReference = null; this.lastAcceptTime = 0; }
  accept(landmarks: Landmark[]): void {
    if (this.phase !== 'open' && this.phase !== 'fist') return;
    const now = performance.now();
    if (now - this.lastAcceptTime < this.minSampleIntervalMs) return;
    this.lastAcceptTime = now;
    const features = landmarkFeatures(landmarks);
    // features 已按 O6 语义：curl 相关维度 0=弯曲, 1=伸直；因此 openness 高=伸直, 低=弯曲
    const openness = features.slice(2).reduce((sum, value) => sum + value, 0) / 4;
    if (this.phase === 'open' && openness >= 0.55) {
      this.open.push(features);
      if (this.open.length >= this.requiredSamples) { this.openReference = average(this.open); this.phase = 'fist'; }
    } else if (this.phase === 'fist' && openness <= 0.45) {
      this.fist.push(features);
      if (this.fist.length >= this.requiredSamples) { this.fistReference = average(this.fist); this.phase = 'complete'; }
    }
  }
  snapshot(): CalibrationSnapshot {
    const openPose = this.openReference ? this.openReference.map(v => clamp01(v)) : null;
    const fistPose = this.fistReference ? this.fistReference.map(v => clamp01(v)) : null;
    return {
      phase: this.phase,
      openSamples: this.open.length,
      fistSamples: this.fist.length,
      complete: this.phase === 'complete',
      openReference: this.openReference ? [...this.openReference] : null,
      fistReference: this.fistReference ? [...this.fistReference] : null,
      openPose,
      fistPose,
    };
  }
}

function average(samples: number[][]): number[] { return samples[0].map((_, index) => samples.reduce((sum, sample) => sum + sample[index], 0) / samples.length); }

export function mapLandmarksToO6(landmarks: Landmark[], calibration?: CalibrationSnapshot): number[] {
  const raw = extractContinuousPose(landmarks);
  if (!raw) return [0, 0, 0, 0, 0, 0];
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
