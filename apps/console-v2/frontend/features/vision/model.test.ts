import { describe, expect, it, vi } from 'vitest';
import { classifyGesture, FIST_HAND_LANDMARK_FIXTURE, GestureStabilizer, mapLandmarksToO6, OPEN_HAND_LANDMARK_FIXTURE, PoseMapper, SessionCalibration } from './model';

const hand = (landmarks: typeof OPEN_HAND_LANDMARK_FIXTURE, confidence = 0.95) => ({ handedness: 'left' as const, confidence, landmarks });

describe('vision gesture model', () => {
  it('recognises the fixed 21-landmark open and fist fixtures', () => {
    expect(OPEN_HAND_LANDMARK_FIXTURE).toHaveLength(21);
    expect(FIST_HAND_LANDMARK_FIXTURE).toHaveLength(21);
    expect(classifyGesture(hand(OPEN_HAND_LANDMARK_FIXTURE)).gesture).toBe('open');
    expect(classifyGesture(hand(FIST_HAND_LANDMARK_FIXTURE)).gesture).toBe('fist');
  });

  it('requires stable repeated frames before changing gesture', () => {
    const stabilizer = new GestureStabilizer();
    expect(stabilizer.update('open', 0.9).gesture).toBe('unknown');
    expect(stabilizer.update('open', 0.9).gesture).toBe('unknown');
    expect(stabilizer.update('open', 0.9).gesture).toBe('open');
  });

  it('completes session calibration from open then fist samples', () => {
    const calibration = new SessionCalibration(2);
    calibration.begin();
    let now = 0;
    const spy = vi.spyOn(performance, 'now').mockImplementation(() => now);
    calibration.accept(OPEN_HAND_LANDMARK_FIXTURE);
    now += 600;
    calibration.accept(OPEN_HAND_LANDMARK_FIXTURE);
    expect(calibration.snapshot().phase).toBe('fist');
    calibration.accept(FIST_HAND_LANDMARK_FIXTURE);
    now += 600;
    calibration.accept(FIST_HAND_LANDMARK_FIXTURE);
    expect(calibration.snapshot().complete).toBe(true);
    expect(mapLandmarksToO6(OPEN_HAND_LANDMARK_FIXTURE, calibration.snapshot())).toHaveLength(6);
    spy.mockRestore();
  });

  it('keeps mapped vectors normalized and rate limited', () => {
    const mapper = new PoseMapper({ deadZone: 0, emaAlpha: 1, maxDeltaPerFrame: 0.05 });
    const first = mapper.map(FIST_HAND_LANDMARK_FIXTURE);
    const second = mapper.map(OPEN_HAND_LANDMARK_FIXTURE);
    expect(first).toHaveLength(6);
    expect(second.every(value => value >= 0 && value <= 1)).toBe(true);
    expect(second.every((value, index) => Math.abs(value - first[index]) <= 0.050001)).toBe(true);
  });
});
