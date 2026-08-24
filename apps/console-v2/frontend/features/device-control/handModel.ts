/**
 * Typed kinematic model for the LinkerHand L20_8_left URDF.
 *
 * Mirrors the URDF joints/links and exposes O6 drive rules plus
 * SDK-normalized (0..1) -> URDF angle conversion helpers.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HandJointDef {
  name: string; // URDF joint name, e.g. "thumb_joint0"
  type: 'revolute' | 'fixed';
  parent: string; // parent link name
  child: string; // child link name
  mesh: string; // mesh URL path, e.g. "/assets/hand/thumb_link0.STL"
  origin: [number, number, number]; // xyz in meters
  rpy: [number, number, number]; // roll-pitch-yaw in radians
  axis: [number, number, number]; // rotation axis
  limits?: { lower: number; upper: number }; // radians, only for revolute
}

export interface HandModel {
  name: string; // "L20_8_left"
  baseLink: string; // "base_link"
  joints: HandJointDef[]; // ALL joints (parents before children)
  links: Record<string, string>; // link name -> mesh URL
}

export interface DriveRule {
  sdkIndex: number; // 0..5 (O6)
  name: string; // e.g. "拇指弯曲"
  urdfJoints: string[]; // e.g. ["thumb_joint0", "thumb_joint2", "thumb_joint3"]
  axis: 'x' | 'y' | 'z'; // primary rotation axis
  kind: 'bend' | 'spread'; // bend: 1=open(limit near 0) 0=bent(limit far) ; spread: linear
}

// ---------------------------------------------------------------------------
// Joint definitions extracted from linker_hand_l20_8_left.urdf
// ---------------------------------------------------------------------------

const JOINTS: HandJointDef[] = [
  // ---- Thumb chain ----
  {
    name: 'thumb_joint0',
    type: 'revolute',
    parent: 'base_link',
    child: 'thumb_link0',
    mesh: '/assets/hand/thumb_link0.STL',
    origin: [-0.0025188, -0.0050821, 0.052292],
    rpy: [0, 0, 0],
    axis: [1, 0, 0],
    limits: { lower: -1.57, upper: 0 },
  },
  {
    name: 'thumb_joint1',
    type: 'revolute',
    parent: 'thumb_link0',
    child: 'thumb_link1',
    mesh: '/assets/hand/thumb_link1.STL',
    origin: [0.024508, -0.00083332, -0.00845],
    rpy: [0, 0, 0],
    axis: [0, 0, 1],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'thumb_joint2',
    type: 'revolute',
    parent: 'thumb_link1',
    child: 'thumb_link2',
    mesh: '/assets/hand/thumb_link2.STL',
    origin: [0.010985, -0.030795, 0.012414],
    rpy: [0, 0, 0],
    axis: [1, 0, 0],
    limits: { lower: -1, upper: 0 },
  },
  {
    name: 'thumb_joint3',
    type: 'revolute',
    parent: 'thumb_link2',
    child: 'thumb_link3',
    mesh: '/assets/hand/thumb_link3.STL',
    origin: [-0.0010999, -0.044701, 0.034112],
    rpy: [0, 0, 0],
    axis: [1, 0, 0],
    limits: { lower: -1.57, upper: 0 },
  },
  {
    name: 'thumb_joint4',
    type: 'revolute',
    parent: 'thumb_link3',
    child: 'thumb_link4',
    mesh: '/assets/hand/thumb_link4.STL',
    origin: [-0.01277, -0.030981, 0.015322],
    rpy: [0, 0, 0],
    axis: [1, 0, 0],
    limits: { lower: -1.57, upper: 0 },
  },
  {
    name: 'thumb_joint5',
    type: 'fixed',
    parent: 'thumb_link4',
    child: 'thumb_link5',
    mesh: '/assets/hand/thumb_link5.STL',
    origin: [0.0040254, -0.030887, 0.0073227],
    rpy: [0, 0, 0],
    axis: [0, 0, 0],
  },

  // ---- Index finger chain ----
  {
    name: 'index_joint0',
    type: 'revolute',
    parent: 'base_link',
    child: 'index_link0',
    mesh: '/assets/hand/index_link0.STL',
    origin: [-0.025865, -0.026698, 0.15421],
    rpy: [0, 0, 0],
    axis: [1, 0, 0],
    limits: { lower: -0.26, upper: 0.26 },
  },
  {
    name: 'index_joint1',
    type: 'revolute',
    parent: 'index_link0',
    child: 'index_link1',
    mesh: '/assets/hand/index_link1.STL',
    origin: [0.011115, -0.0047959, 0],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'index_joint2',
    type: 'revolute',
    parent: 'index_link1',
    child: 'index_link2',
    mesh: '/assets/hand/index_link2.STL',
    origin: [-0.0034454, 0.0010465, 0.044883],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'index_joint3',
    type: 'revolute',
    parent: 'index_link2',
    child: 'index_link3',
    mesh: '/assets/hand/index_link3.STL',
    origin: [0.0084126, -0.0012, 0.03069],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'index_joint4',
    type: 'fixed',
    parent: 'index_link3',
    child: 'index_link4',
    mesh: '/assets/hand/index_link4.STL',
    origin: [-0.013709, 0.0063957, 0.024981],
    rpy: [0, 0, 0],
    axis: [0, 0, 0],
  },

  // ---- Middle finger chain ----
  {
    name: 'middle_joint0',
    type: 'revolute',
    parent: 'base_link',
    child: 'middle_link0',
    mesh: '/assets/hand/middle_link0.STL',
    origin: [-0.030599, -0.0050984, 0.1587],
    rpy: [0, 0, 0],
    axis: [1, 0, 0],
    limits: { lower: -0.26, upper: 0.26 },
  },
  {
    name: 'middle_joint1',
    type: 'revolute',
    parent: 'middle_link0',
    child: 'middle_link1',
    mesh: '/assets/hand/middle_link1.STL',
    origin: [0.011115, -0.0047959, 0],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'middle_joint2',
    type: 'revolute',
    parent: 'middle_link1',
    child: 'middle_link2',
    mesh: '/assets/hand/middle_link2.STL',
    origin: [-0.0034454, 0.0010465, 0.044883],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'middle_joint3',
    type: 'revolute',
    parent: 'middle_link2',
    child: 'middle_link3',
    mesh: '/assets/hand/middle_link3.STL',
    origin: [0.0084126, -0.0012, 0.03069],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'middle_joint4',
    type: 'fixed',
    parent: 'middle_link3',
    child: 'middle_link4',
    mesh: '/assets/hand/middle_link4.STL',
    origin: [-0.013709, 0.0063957, 0.024981],
    rpy: [0, 0, 0],
    axis: [0, 0, 0],
  },

  // ---- Ring finger chain ----
  {
    name: 'ring_joint0',
    type: 'revolute',
    parent: 'base_link',
    child: 'ring_link0',
    mesh: '/assets/hand/ring_link0.STL',
    origin: [-0.028294, 0.016502, 0.15421],
    rpy: [0, 0, 0],
    axis: [1, 0, 0],
    limits: { lower: -0.26, upper: 0.26 },
  },
  {
    name: 'ring_joint1',
    type: 'revolute',
    parent: 'ring_link0',
    child: 'ring_link1',
    mesh: '/assets/hand/ring_link1.STL',
    origin: [0.011115, -0.0047959, 0],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'ring_joint2',
    type: 'revolute',
    parent: 'ring_link1',
    child: 'ring_link2',
    mesh: '/assets/hand/ring_link2.STL',
    origin: [-0.0034454, 0.0010465, 0.044883],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'ring_joint3',
    type: 'revolute',
    parent: 'ring_link2',
    child: 'ring_link3',
    mesh: '/assets/hand/ring_link3.STL',
    origin: [0.0084126, -0.0012, 0.03069],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'ring_joint4',
    type: 'fixed',
    parent: 'ring_link3',
    child: 'ring_link4',
    mesh: '/assets/hand/ring_link4.STL',
    origin: [-0.013709, 0.0063957, 0.024981],
    rpy: [0, 0, 0],
    axis: [0, 0, 0],
  },

  // ---- Little finger chain ----
  {
    name: 'little_joint0',
    type: 'revolute',
    parent: 'base_link',
    child: 'little_link0',
    mesh: '/assets/hand/little_link0.STL',
    origin: [-0.02467, 0.038102, 0.14521],
    rpy: [0, 0, 0],
    axis: [1, 0, 0],
    limits: { lower: -0.26, upper: 0.26 },
  },
  {
    name: 'little_joint1',
    type: 'revolute',
    parent: 'little_link0',
    child: 'little_link1',
    mesh: '/assets/hand/little_link1.STL',
    origin: [0.011115, -0.0047959, 0],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'little_joint2',
    type: 'revolute',
    parent: 'little_link1',
    child: 'little_link2',
    mesh: '/assets/hand/little_link2.STL',
    origin: [-0.0034454, 0.0010465, 0.044883],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'little_joint3',
    type: 'revolute',
    parent: 'little_link2',
    child: 'little_link3',
    mesh: '/assets/hand/little_link3.STL',
    origin: [0.0084126, -0.0012, 0.03069],
    rpy: [0, 0, 0],
    axis: [0, 1, 0],
    limits: { lower: 0, upper: 1.57 },
  },
  {
    name: 'little_joint4',
    type: 'fixed',
    parent: 'little_link3',
    child: 'little_link4',
    mesh: '/assets/hand/little_link4.STL',
    origin: [-0.013709, 0.0063957, 0.024981],
    rpy: [0, 0, 0],
    axis: [0, 0, 0],
  },
];

// ---------------------------------------------------------------------------
// Hand model
// ---------------------------------------------------------------------------

export const HAND_MODEL: HandModel = {
  name: 'L20_8_left',
  baseLink: 'base_link',
  joints: JOINTS,
  links: {
    base_link: '/assets/hand/base_link.STL',
    thumb_link0: '/assets/hand/thumb_link0.STL',
    thumb_link1: '/assets/hand/thumb_link1.STL',
    thumb_link2: '/assets/hand/thumb_link2.STL',
    thumb_link3: '/assets/hand/thumb_link3.STL',
    thumb_link4: '/assets/hand/thumb_link4.STL',
    thumb_link5: '/assets/hand/thumb_link5.STL',
    index_link0: '/assets/hand/index_link0.STL',
    index_link1: '/assets/hand/index_link1.STL',
    index_link2: '/assets/hand/index_link2.STL',
    index_link3: '/assets/hand/index_link3.STL',
    index_link4: '/assets/hand/index_link4.STL',
    middle_link0: '/assets/hand/middle_link0.STL',
    middle_link1: '/assets/hand/middle_link1.STL',
    middle_link2: '/assets/hand/middle_link2.STL',
    middle_link3: '/assets/hand/middle_link3.STL',
    middle_link4: '/assets/hand/middle_link4.STL',
    ring_link0: '/assets/hand/ring_link0.STL',
    ring_link1: '/assets/hand/ring_link1.STL',
    ring_link2: '/assets/hand/ring_link2.STL',
    ring_link3: '/assets/hand/ring_link3.STL',
    ring_link4: '/assets/hand/ring_link4.STL',
    little_link0: '/assets/hand/little_link0.STL',
    little_link1: '/assets/hand/little_link1.STL',
    little_link2: '/assets/hand/little_link2.STL',
    little_link3: '/assets/hand/little_link3.STL',
    little_link4: '/assets/hand/little_link4.STL',
  },
};

// ---------------------------------------------------------------------------
// O6 drive rules
// ---------------------------------------------------------------------------

/**
 * Maps each O6 SDK joint index to one or more URDF joints.
 *
 * Mirrors `example/gui_control/lhgui/utils/joint_mapper.py`
 * `JOINT_MAPPING["O6"]`, expressed in the web-friendly types used by the
 * device-control page.
 */
export const O6_DRIVE_RULES: DriveRule[] = [
  {
    sdkIndex: 0,
    name: '拇指弯曲',
    urdfJoints: ['thumb_joint0', 'thumb_joint2', 'thumb_joint3'],
    axis: 'x',
    kind: 'bend',
  },
  {
    sdkIndex: 1,
    name: '拇指横摆',
    urdfJoints: ['thumb_joint1'],
    axis: 'z',
    kind: 'spread',
  },
  {
    sdkIndex: 2,
    name: '食指弯曲',
    urdfJoints: ['index_joint1', 'index_joint2', 'index_joint3'],
    axis: 'y',
    kind: 'bend',
  },
  {
    sdkIndex: 3,
    name: '中指弯曲',
    urdfJoints: ['middle_joint1', 'middle_joint2', 'middle_joint3'],
    axis: 'y',
    kind: 'bend',
  },
  {
    sdkIndex: 4,
    name: '无名指弯曲',
    urdfJoints: ['ring_joint1', 'ring_joint2', 'ring_joint3'],
    axis: 'y',
    kind: 'bend',
  },
  {
    sdkIndex: 5,
    name: '小指弯曲',
    urdfJoints: ['little_joint1', 'little_joint2', 'little_joint3'],
    axis: 'y',
    kind: 'bend',
  },
];

// ---------------------------------------------------------------------------
// Angle conversion helpers
// ---------------------------------------------------------------------------

/**
 * Convert normalized O6 SDK values (0..1) to URDF joint angles (radians).
 *
 * - **bend** kind: 1 = fully open, 0 = fully bent.
 *   The URDF "open" rest is the limit closer to zero; the "bent" extreme is
 *   the one farther from zero.  This matches both positive-limit joints
 *   (L20_8: 0 .. 1.57) and negative-limit joints (L20_6: -1.57 .. 0).
 * - **spread** kind: 0 -> lower, 1 -> upper.
 *
 * Fixed joints and joints without limits are silently skipped.
 */
export function sdkNormalizedToJointAngles(
  values: number[],
  driveRules: DriveRule[],
  model: HandModel,
): Record<string, number> {
  const result: Record<string, number> = {};

  for (const rule of driveRules) {
    const raw = values[rule.sdkIndex];
    if (raw === undefined) continue;

    // Clamp normalized value to [0, 1].
    const value = Math.max(0, Math.min(1, raw));

    for (const jointName of rule.urdfJoints) {
      const joint = model.joints.find((j) => j.name === jointName);
      if (!joint || joint.type === 'fixed' || !joint.limits) {
        continue;
      }

      const { lower, upper } = joint.limits;
      let angle: number;

      if (rule.kind === 'bend') {
        // Bend joints: value 1 = fully open, value 0 = fully bent.
        // "open" is the limit closer to zero; "bent" is the one farther away.
        const absLower = Math.abs(lower);
        const absUpper = Math.abs(upper);
        const openAngle = absLower < absUpper ? lower : upper;
        const bentAngle = absLower < absUpper ? upper : lower;

        angle = openAngle + (1 - value) * (bentAngle - openAngle);
      } else {
        // Spread joints: linear mapping from lower to upper.
        angle = lower + value * (upper - lower);
      }

      // Clamp to URDF joint limits.
      angle = Math.max(lower, Math.min(upper, angle));

      result[jointName] = angle;
    }
  }

  return result;
}
