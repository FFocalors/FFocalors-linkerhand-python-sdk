"""Pure Python binary STL loader.

This module provides utilities to parse binary STL files and convert them
into numpy arrays or ``pyqtgraph.opengl.MeshData`` objects suitable for
rendering with ``GLMeshItem``.  Only binary STL is supported; ASCII STL
is not needed for this project.
"""

from __future__ import annotations

import os
from typing import Tuple

import numpy as np


def load_stl(filepath: str) -> Tuple[np.ndarray, np.ndarray]:
    """Parse a binary STL file into deduplicated vertices and faces.

    Parameters
    ----------
    filepath:
        Absolute or relative path to the binary STL file.

    Returns
    -------
    vertexes:
        ``np.ndarray`` of shape ``(M, 3)`` containing the deduplicated
        3D vertex positions.  Vertices closer than ``1e-6`` in each
        coordinate are merged.
    faces:
        ``np.ndarray`` of shape ``(N, 3)`` containing integer indices
        into ``vertexes`` for each triangle.

    Raises
    ------
    FileNotFoundError
        If the STL file does not exist.
    ValueError
        If the file is too short to be a valid binary STL or the
        triangle count is inconsistent with the file size.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(
            f"STL file not found: {filepath}"
        )

    file_size = os.path.getsize(filepath)
    if file_size < 84:
        raise ValueError(
            f"File too short to be a binary STL ({file_size} bytes): {filepath}"
        )

    with open(filepath, "rb") as fh:
        _ = fh.read(80)
        # We do not validate the header text; some exporters leave it empty
        # or non-UTF-8, which is still a valid binary STL.
        raw_count = fh.read(4)
        triangle_count = int.from_bytes(raw_count, byteorder="little")

        expected_size = 84 + triangle_count * 50
        if expected_size != file_size:
            raise ValueError(
                f"File size ({file_size} bytes) does not match the STL header "
                f"triangle count ({triangle_count} triangles → {expected_size} bytes): {filepath}"
            )

        raw_triangles = fh.read(triangle_count * 50)

    # Each triangle: 12-byte normal + 9 * 4-byte vertices + 2-byte attribute
    # We only need the three vertex coordinates per triangle.
    dt = np.dtype([
        ("normal", "<f4", (3,)),
        ("v0", "<f4", (3,)),
        ("v1", "<f4", (3,)),
        ("v2", "<f4", (3,)),
        ("attr", "<u2"),
    ])

    triangles = np.frombuffer(raw_triangles, dtype=dt)
    raw_vertices = np.empty((triangle_count * 3, 3), dtype=np.float32)
    raw_vertices[0::3] = triangles["v0"]
    raw_vertices[1::3] = triangles["v1"]
    raw_vertices[2::3] = triangles["v2"]

    # Deduplicate vertices by rounding to 6 decimal places (1e-6 tolerance).
    rounded = np.round(raw_vertices.astype(np.float64), 6)
    vertexes, inverse = np.unique(rounded, axis=0, return_inverse=True)

    # Map each triangle's three raw vertices back to the deduplicated index.
    faces = inverse.reshape(-1, 3).astype(np.int32)

    return vertexes, faces


def load_stl_meshdata(filepath: str):
    """Load a binary STL file and return a ``MeshData`` object.

    Parameters
    ----------
    filepath:
        Absolute or relative path to the binary STL file.

    Returns
    -------
    pyqtgraph.opengl.MeshData
        A mesh data object ready for use with ``GLMeshItem``.

    Raises
    ------
    FileNotFoundError
        If the STL file does not exist.
    ValueError
        If the STL file is malformed.
    ImportError
        If ``pyqtgraph`` is not installed.
    """
    try:
        from pyqtgraph.opengl import MeshData
    except ImportError as exc:
        raise ImportError(
            "pyqtgraph is required for load_stl_meshdata(). "
            "Install it with: pip install pyqtgraph"
        ) from exc

    vertexes, faces = load_stl(filepath)
    return MeshData(vertexes=vertexes, faces=faces)
