import { describe, expect, it } from 'vitest';
import { HAND_MODEL, O6_DRIVE_RULES, sdkNormalizedToJointAngles } from './handModel';

// thumb_joint0 URDF range: lower = -1.57 (bent), upper = 0 (open).
function thumbBendFraction(angle: number): number {
  const joint = HAND_MODEL.joints.find((j) => j.name === 'thumb_joint0')!;
  const { lower, upper } = joint.limits!;
  // 0 = fully open, 1 = fully bent (fraction of the bend range).
  return (upper - angle) / (upper - lower);
}

describe('O6 thumb bend digital-twin mapping', () => {
  it('maps the physical thumb bend 0-100 to the model 70-100 band', () => {
    const open = sdkNormalizedToJointAngles([1, 0.5, 0.5, 0.5, 0.5, 0.5], O6_DRIVE_RULES, HAND_MODEL);
    const bent = sdkNormalizedToJointAngles([0, 0.5, 0.5, 0.5, 0.5, 0.5], O6_DRIVE_RULES, HAND_MODEL);
    // physical fully open (1) -> model sits at 70% of the bend range
    expect(thumbBendFraction(open['thumb_joint0'])).toBeCloseTo(0.7, 1);
    // physical fully bent (0) -> model at the bent URDF limit (100%)
    expect(thumbBendFraction(bent['thumb_joint0'])).toBeCloseTo(1.0, 1);
  });

  it('keeps the full-range bend mapping for the fingers', () => {
    const open = sdkNormalizedToJointAngles([0.5, 0.5, 1, 0.5, 0.5, 0.5], O6_DRIVE_RULES, HAND_MODEL);
    const bent = sdkNormalizedToJointAngles([0.5, 0.5, 0, 0.5, 0.5, 0.5], O6_DRIVE_RULES, HAND_MODEL);
    const joint = HAND_MODEL.joints.find((j) => j.name === 'index_joint1')!;
    const { lower, upper } = joint.limits!;
    // fingers without a bendScale keep the full URDF range
    expect(open['index_joint1']).toBeCloseTo(lower, 1);
    expect(bent['index_joint1']).toBeCloseTo(upper, 1);
  });
});
