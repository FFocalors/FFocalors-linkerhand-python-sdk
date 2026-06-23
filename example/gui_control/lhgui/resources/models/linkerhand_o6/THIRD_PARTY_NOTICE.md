# Third-Party Notice

## LinkerHand O6 3D Model Assets

This project includes 3D model assets for the LinkerHand O6 robotic hand.

- **Source Repository**: [fiveages-sim/robot-descriptions-common](https://github.com/fiveages-sim/robot-descriptions-common)
- **Resource Directory**: `dexhands/linkerhand_description/meshes/o6/`
- **Model Used**: LinkerHand O6 (left hand, direction=1)
- **License**: Apache License 2.0
- **Copyright**: Zhenbiao@FiveAges

### Files Included

- `meshes/hand_base.glb` - Hand base palm mesh
- `meshes/index_proximal.glb` - Index finger proximal segment (also used for middle/ring/pinky)
- `meshes/index_distal.glb` - Index finger distal segment (also used for middle/ring/pinky)
- `meshes/thumb_metacarpals_base.glb` - Thumb metacarpals base
- `meshes/thumb_metacarpals.glb` - Thumb metacarpals segment
- `meshes/thumb_distal.glb` - Thumb distal segment
- `meshes/flange.glb` - Flange attachment
- `source/o6.xacro` - Original URDF/Xacro kinematic definition

### Usage

These assets are used in the `lhgui` console application to display a real-time 3D visualization of the LinkerHand O6 hand, driven by joint state data from the hardware API.

### Disclaimer

These model assets are NOT original works of this project. They are sourced from the open-source repository listed above. All credit for the 3D models and kinematic definitions belongs to the original authors at FiveAges.
