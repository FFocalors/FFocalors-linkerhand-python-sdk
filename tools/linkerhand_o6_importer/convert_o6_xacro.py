#!/usr/bin/env python3
"""Convert o6.xacro to o6_left_runtime.json for LinkerHand O6 left hand."""
import json
import os
import sys
import xml.etree.ElementTree as ET

XACRO_PATH = sys.argv[1] if len(sys.argv) > 1 else "o6.xacro"
OUTPUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "o6_left_runtime.json"

# Parse xacro XML (it's not full xacro expansion, just extract the macro body)
tree = ET.parse(XACRO_PATH)
root = tree.getroot()

ns = {"xacro": "http://www.ros.org/wiki/xacro"}

# For direction=1 (left hand), evaluate expressions:
# ${direction == 1 and X or Y} -> X when direction=1
# ${direction*-0.010678} -> -0.010678 when direction=1
# ${direction*1} -> 1
# ${prefix} -> "" (name is empty)

direction = 1

def eval_dir(expr):
    """Evaluate xacro expression with direction=1, prefix=''."""
    expr = expr.strip()
    # ${direction == 1 and X or Y}
    if "direction == 1 and" in expr:
        parts = expr.replace("${", "").replace("}", "").split(" or ")
        true_val = parts[0].split("and")[1].strip()
        false_val = parts[1].strip() if len(parts) > 1 else "0"
        return float(true_val)
    # ${direction*X}
    if expr.startswith("${direction"):
        inner = expr.replace("${", "").replace("}", "")
        if "*" in inner:
            val = inner.split("*")[1].strip()
            return direction * float(val)
        return direction
    # ${direction*0.05236}
    if "direction*" in expr:
        inner = expr.replace("${", "").replace("}", "")
        val = inner.split("*")[1].strip()
        return direction * float(val)
    # Plain number
    return float(expr.replace("${", "").replace("}", ""))


def parse_xyz(s):
    """Parse 'x y z' string to [x, y, z]."""
    return [float(v) for v in s.strip().split()]


def parse_rpy(s):
    """Parse 'r p y' string to [r, p, y]."""
    return [float(v) for v in s.strip().split()]


# Build the runtime JSON
runtime = {
    "version": 1,
    "model": "O6",
    "handedness": "left",
    "direction": 1,
    "root_link": "hand_base",
    "links": {},
    "joints": {},
}

# Define links with their mesh info
# From the xacro, links that have visuals with meshes:
link_mesh_map = {
    "hand_base": {"mesh": "meshes/hand_base.glb", "scale": [1, -1, 1]},
    "thumb_metacarpals_base": {"mesh": "meshes/thumb_metacarpals_base.glb", "scale": [1, -1, 1]},
    "thumb_metacarpals": {"mesh": "meshes/thumb_metacarpals.glb", "scale": [1, -1, 1]},
    "thumb_distal": {"mesh": "meshes/thumb_distal.glb", "scale": [1, 1, 1]},
    "index_proximal": {"mesh": "meshes/index_proximal.glb", "scale": [1, 1, 1]},
    "index_distal": {"mesh": "meshes/index_distal.glb", "scale": [1, 1, 1]},
    "middle_proximal": {"mesh": "meshes/index_proximal.glb", "scale": [1, 1, 1]},
    "middle_distal": {"mesh": "meshes/index_distal.glb", "scale": [1, 1, 1]},
    "ring_proximal": {"mesh": "meshes/index_proximal.glb", "scale": [1, 1, 1]},
    "ring_distal": {"mesh": "meshes/index_distal.glb", "scale": [1, 1, 1]},
    "pinky_proximal": {"mesh": "meshes/index_proximal.glb", "scale": [1, 1, 1]},
    "pinky_distal": {"mesh": "meshes/index_distal.glb", "scale": [1, 1, 1]},
}

for link_name, info in link_mesh_map.items():
    runtime["links"][link_name] = {
        "mesh": info["mesh"],
        "visual_origin": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
        "scale": info["scale"],
    }

# Define joints from the xacro (direction=1, prefix="")
# For direction=1:
# - Y coordinates with direction* become negative
# - thumb_joint2 axis becomes [0, 0, 1] (direction*1 = 1)
# - ring_joint rpy becomes [-0.05236, 0, 0] (direction*-0.05236 = -0.05236)
# - pinky_joint rpy becomes [-0.087266, 0, 0] (direction*-0.087266 = -0.087266)

joints_def = {
    "thumb_joint2": {
        "type": "revolute",
        "parent": "hand_base",
        "child": "thumb_metacarpals_base",
        "origin_xyz": [0.011508, -0.022975, 0.032794],
        "origin_rpy": [0, 0, 0],
        "axis": [0, 0, 1],  # direction*1 = 1
        "limit": [0, 1.3],
    },
    "thumb_joint1": {
        "type": "revolute",
        "parent": "thumb_metacarpals_base",
        "child": "thumb_metacarpals",
        "origin_xyz": [0.0061649, -0.010678, -0.004891],
        "origin_rpy": [0, -1.1529, 2.0944],  # direction*2.0944 = 2.0944
        "axis": [0, 1, 0],
        "limit": [0, 0.58],
    },
    "thumb_dip": {
        "type": "revolute",
        "parent": "thumb_metacarpals",
        "child": "thumb_distal",
        "origin_xyz": [0.0037776, 0, 0.045368],
        "origin_rpy": [0, 0, 0],
        "axis": [0, 1, 0],
        "limit": [0, 1.08],
        "mimic": {"joint": "thumb_joint1", "multiplier": 1.86, "offset": 0},
    },
    "index_joint": {
        "type": "revolute",
        "parent": "hand_base",
        "child": "index_proximal",
        "origin_xyz": [0.0024758, -0.02419, 0.098779],
        "origin_rpy": [0.05236, 0, 0],  # direction*0.05236 = 0.05236
        "axis": [0, 1, 0],
        "limit": [0, 1.60],
    },
    "index_dip": {
        "type": "revolute",
        "parent": "index_proximal",
        "child": "index_distal",
        "origin_xyz": [-0.0052516, 0, 0.036625],
        "origin_rpy": [0, 0, 0],
        "axis": [0, 1, 0],
        "limit": [0, 1.43],
        "mimic": {"joint": "index_joint", "multiplier": 0.89, "offset": 0},
    },
    "middle_joint": {
        "type": "revolute",
        "parent": "hand_base",
        "child": "middle_proximal",
        "origin_xyz": [0.00052576, -0.00634, 0.1027],
        "origin_rpy": [0, 0, 0],
        "axis": [0, 1, 0],
        "limit": [0, 1.60],
    },
    "middle_dip": {
        "type": "revolute",
        "parent": "middle_proximal",
        "child": "middle_distal",
        "origin_xyz": [-0.0052516, 0, 0.036625],
        "origin_rpy": [0, 0, 0],
        "axis": [0, 1, 0],
        "limit": [0, 1.43],
        "mimic": {"joint": "middle_joint", "multiplier": 0.89, "offset": 0},
    },
    "ring_joint": {
        "type": "revolute",
        "parent": "hand_base",
        "child": "ring_proximal",
        "origin_xyz": [0.0010258, 0.011135, 0.098767],
        "origin_rpy": [-0.05236, 0, 0],  # direction*-0.05236 = -0.05236
        "axis": [0, 1, 0],
        "limit": [0, 1.60],
    },
    "ring_dip": {
        "type": "revolute",
        "parent": "ring_proximal",
        "child": "ring_distal",
        "origin_xyz": [-0.0052516, 0, 0.036625],
        "origin_rpy": [0, 0, 0],
        "axis": [0, 1, 0],
        "limit": [0, 1.43],
        "mimic": {"joint": "ring_joint", "multiplier": 0.89, "offset": 0},
    },
    "pinky_joint": {
        "type": "revolute",
        "parent": "hand_base",
        "child": "pinky_proximal",
        "origin_xyz": [0.0024758, 0.028372, 0.092741],
        "origin_rpy": [-0.087266, 0, 0],  # direction*-0.087266 = -0.087266
        "axis": [0, 1, 0],
        "limit": [0, 1.60],
    },
    "pinky_dip": {
        "type": "revolute",
        "parent": "pinky_proximal",
        "child": "pinky_distal",
        "origin_xyz": [-0.0052516, 0, 0.036625],
        "origin_rpy": [0, 0, 0],
        "axis": [0, 1, 0],
        "limit": [0, 1.43],
        "mimic": {"joint": "pinky_joint", "multiplier": 0.89, "offset": 0},
    },
}

runtime["joints"] = joints_def

# Write output
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(runtime, f, indent=2, ensure_ascii=False)

print(f"Written {OUTPUT_PATH}")
print(f"Links: {len(runtime['links'])}")
print(f"Joints: {len(runtime['joints'])}")

# Verify
for jname, jdef in joints_def.items():
    mimic = jdef.get("mimic", {})
    mimic_str = f" (mimic: {mimic['joint']}*{mimic['multiplier']})" if mimic else ""
    print(f"  {jname}: {jdef['parent']} -> {jdef['child']}, axis={jdef['axis']}, limit={jdef['limit']}{mimic_str}")
