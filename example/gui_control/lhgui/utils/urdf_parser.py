"""URDF parser for LinkerHand models.

This module parses URDF XML files describing the LinkerHand kinematic chain
and resolves the associated STL mesh paths.  It is designed to work with the
URDF files shipped under ``example/Linker_hand_Sapien/urdf/``.
"""

from __future__ import annotations

import os
import re
import glob
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------

def _preprocess_urdf_xml(text: str) -> str:
    """Clean known malformed tags in the shipped URDF files.

    Some exported URDFs contain stray characters after closing tags
    (e.g. ``</link>+`` or ``</link>21``).  This function strips any
    non-whitespace, non-``<`` junk that appears immediately after a
    closing XML tag so that the standard library parser can handle the
    document.
    """
    # Remove junk like </link>+  </link>21  etc.
    cleaned = re.sub(
        r"(</[a-zA-Z_][a-zA-Z0-9_]*>\s*)[^\s<]+",
        lambda m: m.group(1),
        text,
    )
    return cleaned


# ---------------------------------------------------------------------------
# Mesh path resolution
# ---------------------------------------------------------------------------

def _resolve_mesh_path(
    raw_path: str,
    urdf_dir: str,
) -> str:
    """Resolve a ``filename`` attribute from a URDF ``<mesh>`` element.

    Handles three cases:

    1. **Absolute paths** – returned unchanged.
    2. **``package://`` URIs** – the package prefix is stripped and the
       remaining path is resolved relative to the URDF directory, then
       relative to the URDF directory's parent, and finally by a
       basename search under the URDF directory's ``meshes/`` subtree.
    3. **Plain relative paths** – resolved against the URDF directory
       and, if that fails, by a basename search under ``meshes/``.

    Parameters
    ----------
    raw_path:
        The value of the ``filename`` attribute.
    urdf_dir:
        Directory that contains the URDF file.

    Returns
    -------
    str
        Resolved absolute path.  The function does *not* verify that the
        file exists; it only guarantees a deterministic path.
    """
    if not raw_path:
        return ""

    # Absolute paths (Windows drive letters or Unix leading slash)
    if os.path.isabs(raw_path):
        return raw_path

    # Strip package:// URI if present
    if raw_path.startswith("package://"):
        relative = raw_path[len("package://"):]
        # Remove the package name itself if the path starts with a segment
        # that looks like a ROS package name followed by a slash.
        parts = relative.split("/", 1)
        if len(parts) == 2 and "." not in parts[0] and parts[0]:
            relative = parts[1]

        candidates = [
            os.path.join(urdf_dir, relative),
            os.path.join(urdf_dir, "..", relative),
        ]
    else:
        candidates = [os.path.join(urdf_dir, raw_path)]

    # Direct candidates
    for candidate in candidates:
        normalized = os.path.normpath(candidate)
        if os.path.isfile(normalized):
            return normalized

    # Basename fallback: search under meshes/ for a file whose name matches
    # the tail of the raw path.  This handles the case where the URDF
    # references one directory name (e.g. linker_hand_l20_8_left) but the
    # actual mesh folder is named differently (e.g. l20_8_l), or where a
    # left-hand URDF reuses the right-hand mesh folder (l20_6_left -> l20_6_right).
    basename = os.path.basename(raw_path)
    search_roots = [
        os.path.join(urdf_dir, "meshes"),
        os.path.join(urdf_dir, "..", "meshes"),
    ]
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            if basename in filenames:
                return os.path.join(dirpath, basename)

    # Nothing found; return the first candidate as a best-effort path.
    return os.path.normpath(candidates[0])


# ---------------------------------------------------------------------------
# URDF element helpers
# ---------------------------------------------------------------------------

def _parse_xyz_rpy(element: ET.Element) -> Tuple[np.ndarray, np.ndarray]:
    """Extract ``xyz`` and ``rpy`` attributes from an ``<origin>`` element.

    Returns
    -------
    xyz:
        Length-3 array, defaults to ``[0, 0, 0]``.
    rpy:
        Length-3 array, defaults to ``[0, 0, 0]``.
    """
    xyz = np.array(
        [float(x) for x in element.get("xyz", "0 0 0").split()], dtype=np.float64
    )
    rpy = np.array(
        [float(x) for x in element.get("rpy", "0 0 0").split()], dtype=np.float64
    )
    return xyz, rpy


def _parse_limit(element: ET.Element) -> Optional[Dict[str, float]]:
    """Parse a ``<limit>`` element into a dict of floats."""
    if element is None:
        return None
    lower = element.get("lower")
    upper = element.get("upper")
    if lower is None or upper is None:
        return None
    return {
        "lower": float(lower),
        "upper": float(upper),
        "effort": float(element.get("effort", 0.0)),
        "velocity": float(element.get("velocity", 0.0)),
    }


def _parse_mimic(element: ET.Element) -> Optional[Dict[str, float]]:
    """Parse a ``<mimic>`` element if present."""
    if element is None:
        return None
    return {
        "joint": element.get("joint"),
        "multiplier": float(element.get("multiplier", 1.0)),
        "offset": float(element.get("offset", 0.0)),
    }


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def parse_urdf(urdf_path: str) -> Dict[str, Any]:
    """Parse a LinkerHand URDF file into a kinematic tree.

    Parameters
    ----------
    urdf_path:
        Path to the URDF XML file.

    Returns
    -------
    dict
        A dictionary with two keys:

        * ``links`` – ``{link_name: {"mesh_path": resolved_path | None}}``
        * ``joints`` – ``{joint_name: {parent_link, child_link, origin_xyz,
          origin_rpy, axis_xyz, limits, mesh_path, mimic}}``

        ``mesh_path`` in the joint dict refers to the *child link's* visual
        mesh, which is the geometry attached to that link.
    """
    if not os.path.isfile(urdf_path):
        raise FileNotFoundError(f"URDF file not found: {urdf_path}")

    with open(urdf_path, "r", encoding="utf-8") as fh:
        raw_text = fh.read()

    xml_text = _preprocess_urdf_xml(raw_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(
            f"Failed to parse URDF XML ({exc}): {urdf_path}"
        ) from exc

    urdf_dir = os.path.dirname(os.path.abspath(urdf_path))

    # ------------------------------------------------------------------
    # Collect links and their visual mesh paths
    # ------------------------------------------------------------------
    links: Dict[str, Dict[str, Any]] = {}
    for link_el in root.iter("link"):
        link_name = link_el.get("name")
        if not link_name:
            continue

        mesh_path: Optional[str] = None
        visual = link_el.find("visual")
        if visual is not None:
            geometry = visual.find("geometry")
            if geometry is not None:
                mesh_el = geometry.find("mesh")
                if mesh_el is not None:
                    raw_filename = mesh_el.get("filename", "")
                    if raw_filename:
                        mesh_path = _resolve_mesh_path(raw_filename, urdf_dir)

        links[link_name] = {"mesh_path": mesh_path}

    # ------------------------------------------------------------------
    # Collect joints
    # ------------------------------------------------------------------
    joints: Dict[str, Dict[str, Any]] = {}
    for joint_el in root.iter("joint"):
        joint_name = joint_el.get("name")
        if not joint_name:
            continue

        parent_el = joint_el.find("parent")
        child_el = joint_el.find("child")
        origin_el = joint_el.find("origin")
        axis_el = joint_el.find("axis")
        limit_el = joint_el.find("limit")
        mimic_el = joint_el.find("mimic")

        parent_link = parent_el.get("link") if parent_el is not None else None
        child_link = child_el.get("link") if child_el is not None else None

        origin_xyz = np.zeros(3, dtype=np.float64)
        origin_rpy = np.zeros(3, dtype=np.float64)
        if origin_el is not None:
            origin_xyz, origin_rpy = _parse_xyz_rpy(origin_el)

        axis_xyz = np.array(
            [float(x) for x in (axis_el.get("xyz", "0 0 0").split())],
            dtype=np.float64,
        ) if axis_el is not None else np.zeros(3, dtype=np.float64)

        limits = _parse_limit(limit_el)
        mimic = _parse_mimic(mimic_el)

        # Attach the child link's mesh to the joint so callers can easily
        # retrieve the visual geometry for each segment of the kinematic chain.
        child_mesh_path = links.get(child_link, {}).get("mesh_path")

        joints[joint_name] = {
            "joint_type": joint_el.get("type", "fixed"),
            "parent_link": parent_link,
            "child_link": child_link,
            "origin_xyz": origin_xyz,
            "origin_rpy": origin_rpy,
            "axis_xyz": axis_xyz,
            "limits": limits,
            "mimic": mimic,
            "mesh_path": child_mesh_path,
        }

    return {
        "links": links,
        "joints": joints,
    }


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def get_urdf_path(
    hand_type: str,
    hand_joint: str,
    urdf_dir: Optional[str] = None,
) -> str:
    """Return the URDF path for a given hand type and joint model.

    Parameters
    ----------
    hand_type:
        ``"left"`` or ``"right"``.
    hand_joint:
        Joint model string, e.g. ``"L20_8"`` or ``"L20_6"``.  The value
        is lower-cased and inserted into the standard filename pattern
        ``linker_hand_{hand_joint}_{hand_type}.urdf``.
    urdf_dir:
        Directory containing the URDF files.  Defaults to
        ``example/Linker_hand_Sapien/urdf/`` relative to the project
        root (i.e. four directories up from this file).

    Returns
    -------
    str
        Absolute path to the URDF file.

    Raises
    ------
    FileNotFoundError
        If no matching URDF file exists.
    """
    if urdf_dir is None:
        # __file__: .../example/gui_control/lhgui/utils/urdf_parser.py
        # Up 4 levels reaches the project root.
        urdf_dir = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..", "..", "..", "..",
                "example",
                "Linker_hand_Sapien",
                "urdf",
            )
        )

    candidate = os.path.join(urdf_dir, f"linker_hand_{hand_joint.lower()}_{hand_type}.urdf")
    if os.path.isfile(candidate):
        return candidate

    # Fallback: glob for any file that matches the partial model name.
    pattern = os.path.join(urdf_dir, f"linker_hand_{hand_joint.lower()}*{hand_type}.urdf")
    matches = glob.glob(pattern)
    if matches:
        return matches[0]

    available = "\n".join(
        sorted(os.listdir(urdf_dir))
    )
    raise FileNotFoundError(
        f"No URDF found for hand_type={hand_type!r}, hand_joint={hand_joint!r}.\n"
        f"Searched: {candidate}\n"
        f"Available URDFs in {urdf_dir}:\n{available}"
    )


def build_kinematic_tree(urdf_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build an ordered kinematic tree from ``parse_urdf`` output.

    The returned dictionary maps *joint name* to the same metadata dict
    produced by :func:`parse_urdf`, but the keys are ordered such that
    parents appear before children.  This makes it easy to traverse the
    chain in hierarchy order::

        tree = build_kinematic_tree(parse_urdf(path))
        for joint_name, info in tree.items():
            print(joint_name, info["parent_link"], "->", info["child_link"])

    Parameters
    ----------
    urdf_data:
        The dict returned by :func:`parse_urdf`.

    Returns
    -------
    dict
        Joints ordered from base to tip.
    """
    joints = urdf_data.get("joints", {})
    links = urdf_data.get("links", {})

    # Identify root links (those that are never a child)
    child_links = {j["child_link"] for j in joints.values() if j["child_link"]}
    root_links = [name for name in links if name not in child_links]

    # Build adjacency: parent_link -> [child_joint_names]
    children: Dict[str, List[str]] = {name: [] for name in links}
    for joint_name, info in joints.items():
        parent = info.get("parent_link")
        if parent is not None:
            children[parent].append(joint_name)

    ordered: Dict[str, Dict[str, Any]] = {}

    def _traverse(link_name: str) -> None:
        if link_name is None:
            return
        for joint_name in children.get(link_name, []):
            if joint_name in ordered:
                continue
            info = joints[joint_name]
            ordered[joint_name] = info
            child_link = info.get("child_link")
            if child_link:
                _traverse(child_link)

    for root in root_links:
        _traverse(root)

    # Include any joints that were not reached (e.g. disconnected sub-trees)
    for joint_name, info in joints.items():
        ordered.setdefault(joint_name, info)

    return ordered
