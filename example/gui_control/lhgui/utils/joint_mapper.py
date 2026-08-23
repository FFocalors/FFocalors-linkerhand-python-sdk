"""Joint mapping module for multi-model LinkerHand support.

Translates SDK joint indices (0-255 range values) to URDF joint names and
computes rotation angles using the limits parsed from the URDF.

Typical usage::

    from lhgui.utils.urdf_parser import parse_urdf
    from lhgui.utils.joint_mapper import sdk_range_to_urdf_angles, get_urdf_model_for_hand

    urdf_data = parse_urdf(get_urdf_path(...))
    angles = sdk_range_to_urdf_angles(sdk_values, "L20", urdf_data["joints"])
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Joint mapping tables
# ---------------------------------------------------------------------------

#: Maps each hand model to a list of SDK-to-URDF joint configurations.
#:
#: Each entry describes one SDK joint index and which URDF joint(s) it
#: controls.  ``urdf_joints`` may be empty for reserved / unmapped indices.
#:
#: ``is_bend`` follows the SDK convention:
#: - **bend**: value 255 = fully open, value 0 = fully bent.
#: - **swing / spread**: value 0 = closed, value 255 = open.
JOINT_MAPPING: Dict[str, List[Dict[str, Any]]] = {
    # -----------------------------------------------------------------------
    # L6 / O6: 6-DOF models mapped to L20_6 URDF joints
    # -----------------------------------------------------------------------
    "L6": [
        {
            "sdk_index": 0,
            "sdk_name": "拇指弯曲",
            "urdf_joints": ["thumb_joint0", "thumb_joint2", "thumb_joint3"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 1,
            "sdk_name": "拇指横摆",
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 2,
            "sdk_name": "食指弯曲",
            "urdf_joints": ["index_joint1", "index_joint2", "index_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 3,
            "sdk_name": "中指弯曲",
            "urdf_joints": ["middle_joint1", "middle_joint2", "middle_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 4,
            "sdk_name": "无名指弯曲",
            "urdf_joints": ["ring_joint1", "ring_joint2", "ring_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 5,
            "sdk_name": "小指弯曲",
            "urdf_joints": ["little_joint1", "little_joint2", "little_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
    ],
    "O6": [
        {
            "sdk_index": 0,
            "sdk_name": "大拇指弯曲",
            "urdf_joints": ["thumb_joint0", "thumb_joint2", "thumb_joint3"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 1,
            "sdk_name": "大拇指横摆",
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 2,
            "sdk_name": "食指弯曲",
            "urdf_joints": ["index_joint1", "index_joint2", "index_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 3,
            "sdk_name": "中指弯曲",
            "urdf_joints": ["middle_joint1", "middle_joint2", "middle_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 4,
            "sdk_name": "无名指弯曲",
            "urdf_joints": ["ring_joint1", "ring_joint2", "ring_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 5,
            "sdk_name": "小拇指弯曲",
            "urdf_joints": ["little_joint1", "little_joint2", "little_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
    ],
    # -----------------------------------------------------------------------
    # L7: 7-DOF model mapped to L20_8 URDF joints
    # -----------------------------------------------------------------------
    "L7": [
        {
            "sdk_index": 0,
            "sdk_name": "大拇指弯曲",
            "urdf_joints": ["thumb_joint0", "thumb_joint2", "thumb_joint3"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 1,
            "sdk_name": "大拇指横摆",
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 2,
            "sdk_name": "食指弯曲",
            "urdf_joints": ["index_joint1", "index_joint2", "index_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 3,
            "sdk_name": "中指弯曲",
            "urdf_joints": ["middle_joint1", "middle_joint2", "middle_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 4,
            "sdk_name": "无名指弯曲",
            "urdf_joints": ["ring_joint1", "ring_joint2", "ring_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 5,
            "sdk_name": "小拇指弯曲",
            "urdf_joints": ["little_joint1", "little_joint2", "little_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 6,
            "sdk_name": "拇指旋转",
            "urdf_joints": ["thumb_joint4"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
    ],
    # -----------------------------------------------------------------------
    # L10: 10-DOF model mapped to L20_8 URDF joints
    # -----------------------------------------------------------------------
    "L10": [
        {
            "sdk_index": 0,
            "sdk_name": "拇指根部",
            "urdf_joints": ["thumb_joint0", "thumb_joint2", "thumb_joint3"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 1,
            "sdk_name": "拇指侧摆",
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 2,
            "sdk_name": "食指根部",
            "urdf_joints": ["index_joint1", "index_joint2", "index_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 3,
            "sdk_name": "中指根部",
            "urdf_joints": ["middle_joint1", "middle_joint2", "middle_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 4,
            "sdk_name": "无名指根部",
            "urdf_joints": ["ring_joint1", "ring_joint2", "ring_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 5,
            "sdk_name": "小指根部",
            "urdf_joints": ["little_joint1", "little_joint2", "little_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 6,
            "sdk_name": "食指侧摆",
            "urdf_joints": ["index_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 7,
            "sdk_name": "无名指侧摆",
            "urdf_joints": ["ring_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 8,
            "sdk_name": "小指侧摆",
            "urdf_joints": ["little_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 9,
            "sdk_name": "拇指旋转",
            "urdf_joints": ["thumb_joint4"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
    ],
    # -----------------------------------------------------------------------
    # L20: 20-DOF model mapped to L20_8 URDF joints
    # -----------------------------------------------------------------------
    "L20": [
        {
            "sdk_index": 0,
            "sdk_name": "拇指根部",
            "urdf_joints": ["thumb_joint0", "thumb_joint2", "thumb_joint3"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 1,
            "sdk_name": "食指根部",
            "urdf_joints": ["index_joint1", "index_joint2", "index_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 2,
            "sdk_name": "中指根部",
            "urdf_joints": ["middle_joint1", "middle_joint2", "middle_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 3,
            "sdk_name": "无名指根部",
            "urdf_joints": ["ring_joint1", "ring_joint2", "ring_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 4,
            "sdk_name": "小指根部",
            "urdf_joints": ["little_joint1", "little_joint2", "little_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 5,
            "sdk_name": "拇指侧摆",
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 6,
            "sdk_name": "食指侧摆",
            "urdf_joints": ["index_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 7,
            "sdk_name": "中指侧摆",
            "urdf_joints": ["middle_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 8,
            "sdk_name": "无名指侧摆",
            "urdf_joints": ["ring_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 9,
            "sdk_name": "小指侧摆",
            "urdf_joints": ["little_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 10,
            "sdk_name": "拇指横摆",
            # In the L20_8 URDF thumb_joint1 is the only thumb roll / yaw DOF.
            # Both side-swing (index 5) and CMC yaw (index 10) share this joint
            # because the exported URDF collapses the thumb base to a single
            # revolute axis.
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 11,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 12,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 13,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 14,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 15,
            "sdk_name": "拇指尖部",
            "urdf_joints": ["thumb_joint4"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 16,
            "sdk_name": "食指末端",
            "urdf_joints": ["index_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 17,
            "sdk_name": "中指末端",
            "urdf_joints": ["middle_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 18,
            "sdk_name": "无名指末端",
            "urdf_joints": ["ring_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 19,
            "sdk_name": "小指末端",
            "urdf_joints": ["little_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
    ],
    # -----------------------------------------------------------------------
    # L21: 25-DOF model mapped to L20_8 URDF joints
    # -----------------------------------------------------------------------
    "L21": [
        {
            "sdk_index": 0,
            "sdk_name": "大拇指根部",
            "urdf_joints": ["thumb_joint0", "thumb_joint2", "thumb_joint3"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 1,
            "sdk_name": "食指根部",
            "urdf_joints": ["index_joint1", "index_joint2", "index_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 2,
            "sdk_name": "中指根部",
            "urdf_joints": ["middle_joint1", "middle_joint2", "middle_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 3,
            "sdk_name": "无名指根部",
            "urdf_joints": ["ring_joint1", "ring_joint2", "ring_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 4,
            "sdk_name": "小拇指根部",
            "urdf_joints": ["little_joint1", "little_joint2", "little_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 5,
            "sdk_name": "大拇指侧摆",
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 6,
            "sdk_name": "食指侧摆",
            "urdf_joints": ["index_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 7,
            "sdk_name": "中指侧摆",
            "urdf_joints": ["middle_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 8,
            "sdk_name": "无名指侧摆",
            "urdf_joints": ["ring_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 9,
            "sdk_name": "小指侧摆",
            "urdf_joints": ["little_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 10,
            "sdk_name": "大拇指横滚",
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 11,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 12,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 13,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 14,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 15,
            "sdk_name": "大拇指中部",
            "urdf_joints": ["thumb_joint4"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 16,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 17,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 18,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 19,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 20,
            "sdk_name": "大拇指指尖",
            "urdf_joints": ["thumb_joint4"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 21,
            "sdk_name": "食指指尖",
            "urdf_joints": ["index_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 22,
            "sdk_name": "中指指尖",
            "urdf_joints": ["middle_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 23,
            "sdk_name": "无名指指尖",
            "urdf_joints": ["ring_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 24,
            "sdk_name": "小拇指指尖",
            "urdf_joints": ["little_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
    ],
    # -----------------------------------------------------------------------
    # L25: 25-DOF model mapped to L20_8 URDF joints
    # -----------------------------------------------------------------------
    "L25": [
        {
            "sdk_index": 0,
            "sdk_name": "大拇指根部",
            "urdf_joints": ["thumb_joint0", "thumb_joint2", "thumb_joint3"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 1,
            "sdk_name": "食指根部",
            "urdf_joints": ["index_joint1", "index_joint2", "index_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 2,
            "sdk_name": "中指根部",
            "urdf_joints": ["middle_joint1", "middle_joint2", "middle_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 3,
            "sdk_name": "无名指根部",
            "urdf_joints": ["ring_joint1", "ring_joint2", "ring_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 4,
            "sdk_name": "小拇指根部",
            "urdf_joints": ["little_joint1", "little_joint2", "little_joint3"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 5,
            "sdk_name": "大拇指侧摆",
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 6,
            "sdk_name": "食指侧摆",
            "urdf_joints": ["index_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 7,
            "sdk_name": "中指侧摆",
            "urdf_joints": ["middle_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 8,
            "sdk_name": "无名指侧摆",
            "urdf_joints": ["ring_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 9,
            "sdk_name": "小指侧摆",
            "urdf_joints": ["little_joint0"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 10,
            "sdk_name": "大拇指横滚",
            "urdf_joints": ["thumb_joint1"],
            "urdf_axis": "z",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 11,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 12,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 13,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 14,
            "sdk_name": "预留",
            "urdf_joints": [],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": False,
        },
        {
            "sdk_index": 15,
            "sdk_name": "大拇指中部",
            "urdf_joints": ["thumb_joint4"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 16,
            "sdk_name": "食指中部",
            "urdf_joints": [],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 17,
            "sdk_name": "中指中部",
            "urdf_joints": [],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 18,
            "sdk_name": "无名指中部",
            "urdf_joints": [],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 19,
            "sdk_name": "小拇指中部",
            "urdf_joints": [],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 20,
            "sdk_name": "大拇指指尖",
            "urdf_joints": ["thumb_joint4"],
            "urdf_axis": "x",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 21,
            "sdk_name": "食指指尖",
            "urdf_joints": ["index_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 22,
            "sdk_name": "中指指尖",
            "urdf_joints": ["middle_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 23,
            "sdk_name": "无名指指尖",
            "urdf_joints": ["ring_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
        {
            "sdk_index": 24,
            "sdk_name": "小拇指指尖",
            "urdf_joints": ["little_joint4"],
            "urdf_axis": "y",
            "scale_factor": 1.0,
            "is_bend": True,
        },
    ],
}

# ---------------------------------------------------------------------------
# Model aliases
# ---------------------------------------------------------------------------

#: Some models share an identical mechanical layout with a canonical model.
_MODEL_ALIASES: Dict[str, str] = {
    "G20": "L20",
}

for _alias, _target in _MODEL_ALIASES.items():
    JOINT_MAPPING[_alias] = [dict(_entry) for _entry in JOINT_MAPPING[_target]]

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_urdf_model_for_hand(hand_joint: str) -> str:
    """Get the URDF model name for a given hand model.

    Args:
        hand_joint: Hand model name (e.g. ``"L6"``, ``"L20"``).

    Returns:
        The URDF model stem used to locate the URDF file:
        - ``"L20_6"`` for L6 and O6.
        - ``"L20_8"`` for all other supported models.
    """
    if hand_joint in ("L6", "O6"):
        return "L20_6"
    return "L20_8"


def get_axis_rotation(axis_str: str) -> Tuple[float, float, float]:
    """Convert axis string to rotation vector for ``QMatrix4x4.rotate()``.

    Args:
        axis_str: One of ``"x"``, ``"y"``, or ``"z"`` (case-insensitive).

    Returns:
        A 3-tuple representing the unit axis vector.

    Raises:
        ValueError: If ``axis_str`` is not one of the supported axes.
    """
    axis = axis_str.strip().lower()
    if axis == "x":
        return (1.0, 0.0, 0.0)
    if axis == "y":
        return (0.0, 1.0, 0.0)
    if axis == "z":
        return (0.0, 0.0, 1.0)
    raise ValueError(f"Unsupported axis string {axis_str!r}. Expected 'x', 'y', or 'z'.")


def sdk_range_to_urdf_angles(
    sdk_values: List[float],
    hand_joint: str,
    urdf_joints: Dict[str, Any],
) -> Dict[str, float]:
    """Convert SDK range values (0-255) to URDF joint rotation angles (radians).

    The conversion uses the URDF joint limits parsed from the URDF file, so
    it works correctly for both positive-limit (L20_8) and negative-limit
    (L20_6) models without hardcoding any angle bounds.

    Args:
        sdk_values: List of joint values in the 0-255 range.  The list index
            corresponds to the SDK joint index defined in ``JOINT_MAPPING``.
        hand_joint: Hand model name (e.g. ``"L6"``, ``"L20"``).
        urdf_joints: The ``joints`` dict returned by
            :func:`lhgui.utils.urdf_parser.parse_urdf`.

    Returns:
        Dict mapping URDF joint name -> rotation angle in radians.
        Joints that are fixed or have no limits are silently skipped.
    """
    mapping = JOINT_MAPPING.get(hand_joint)
    if mapping is None:
        logger.warning(
            "Hand model %r not found in JOINT_MAPPING; returning empty dict.",
            hand_joint,
        )
        return {}

    if not sdk_values:
        return {}

    result: Dict[str, float] = {}

    for entry in mapping:
        idx = entry["sdk_index"]
        if idx >= len(sdk_values):
            # Defensive: caller provided a shorter list than expected.
            continue

        value = float(sdk_values[idx])
        # Clamp raw SDK value to the expected 0-255 range.
        value = max(0.0, min(255.0, value))

        scale = float(entry.get("scale_factor", 1.0))

        for joint_name in entry["urdf_joints"]:
            joint_info = urdf_joints.get(joint_name)
            if joint_info is None:
                # Joint name not present in this URDF variant; skip silently.
                continue

            if joint_info.get("joint_type") == "fixed":
                continue

            limits = joint_info.get("limits")
            if limits is None:
                continue

            lower = limits["lower"]
            upper = limits["upper"]

            if entry["is_bend"]:
                # Bend joints: value 255 = fully open, value 0 = fully bent.
                # The "open" rest position is the limit closer to zero; the
                # "bent" extreme is the one farther from zero.  This handles
                # both L20_8 (0 .. 1.57) and L20_6 (-1.57 .. 0) correctly.
                if abs(lower) < abs(upper):
                    open_angle = lower
                    bent_angle = upper
                else:
                    open_angle = upper
                    bent_angle = lower
                angle = open_angle + ((255.0 - value) / 255.0) * (bent_angle - open_angle)
            else:
                # Swing / spread joints: value 0 = closed, value 255 = open.
                angle = lower + (value / 255.0) * (upper - lower)

            angle *= scale
            # Clamp to the URDF joint limits.
            angle = float(np.clip(angle, lower, upper))
            result[joint_name] = angle

    return result
