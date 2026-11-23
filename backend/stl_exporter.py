"""Binary STL writer (RESEARCH.md sections 7 and 8, Step 18).

Self-written, pure stdlib plus NumPy. Input is the same mesh the
GLB path uses: positions (N, 3) and indices (M, 3), either as
arrays or as an NPZ byte payload with those two fields.

What STL carries, stated plainly: static surface geometry only.
An STL file has no morph targets, no animation, no vertex colors,
no material, and no color grade. The grade in this studio is a
shader pass and the lip-sync lives in morph targets; neither
survives into STL, and the export UI says so next to the button.
STL is the fabrication and CAD interchange copy: one triangle
soup, per-face normals, nothing else.

Format: 80-byte header (all zero here; a header starting with the
bytes "solid" would invite ASCII misdetection), a uint32 triangle
count, then 50 bytes per triangle: 12 float32 (the face normal,
then the three vertices) and a uint16 attribute byte count,
which is zero in every record this writer emits.

Degenerate triangles (repeated or collinear vertices, zero area)
are written like any other triangle, with a zero normal (0, 0, 0),
because STL carries no error channel and silently dropping faces
would misreport the mesh. They are never hidden: face_normals
returns the degenerate mask, build_stl_report counts them, and
callers can surface the count. Many slicers recompute normals and
will repair the shading on their side; the geometry record here
stays honest about what was in the source mesh.

Units are the input units (the studio mesh is in meters, as in
the GLB path). The scale argument exists for fabrication targets
that expect millimeters: pass scale=1000.0 and the vertices are
multiplied before normals are computed; the factor used is part
of the build report so an export can be audited after the fact.
"""

import io
import struct

import numpy as np

HEADER_BYTES = 80
RECORD_BYTES = 50


def _as_mesh(positions, indices):
    pos = np.asarray(positions, dtype=np.float64)
    idx = np.asarray(indices)
    if pos.ndim != 2 or pos.shape[1] != 3:
        raise ValueError(f"positions must be (N, 3), got {pos.shape}")
    if idx.ndim != 2 or idx.shape[1] != 3:
        raise ValueError(f"indices must be (M, 3), got {idx.shape}")
    if not np.issubdtype(idx.dtype, np.integer):
        if not np.all(np.equal(idx, np.floor(idx))):
            raise ValueError("indices must be integers")
    idx = idx.astype(np.int64)
    if idx.size and (idx.min() < 0 or idx.max() >= len(pos)):
        raise ValueError("indices out of range for positions")
    return pos, idx


def face_normals(positions, indices):
    """Per-face unit normals and the degenerate mask.

    Returns (normals (M, 3) float64, degenerate (M,) bool).
    Degenerate faces (zero area) get the zero normal and True in
    the mask; every other face gets the normalized cross product
    of its edges, following the index winding.
    """
    pos, idx = _as_mesh(positions, indices)
    tris = pos[idx]
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    area2 = np.linalg.norm(cross, axis=1)
    degenerate = area2 == 0.0
    normals = np.zeros_like(cross)
    ok = ~degenerate
    normals[ok] = cross[ok] / area2[ok, None]
    return normals, degenerate


def build_stl(positions, indices, scale=1.0):
    """Pack positions and indices into binary STL bytes."""
    data, _report = build_stl_report(positions, indices, scale=scale)
    return data


def build_stl_report(positions, indices, scale=1.0):
    """Binary STL bytes plus an honest report dict.

    The report records the triangle count, how many of those
    triangles are degenerate (zero area, written with a zero
    normal), and the scale factor applied to the vertices.
    """
    pos, idx = _as_mesh(positions, indices)
    if scale != 1.0:
        pos = pos * float(scale)
    normals, degenerate = face_normals(pos, idx)
    tris = pos[idx].astype("<f4")
    out = io.BytesIO()
    out.write(b"\x00" * HEADER_BYTES)
    out.write(struct.pack("<I", len(idx)))
    # One record per triangle: normal (3f), vertices (9f), attr (H).
    records = np.zeros((len(idx), 12), dtype="<f4")
    records[:, 0:3] = normals.astype("<f4")
    records[:, 3:12] = tris.reshape(len(idx), 9)
    body = records.tobytes()
    attrs = b"\x00\x00" * len(idx)
    # Interleave the 48-byte float block and the 2-byte attribute
    # count per record without a Python loop over triangles.
    merged = np.empty(len(idx) * RECORD_BYTES, dtype=np.uint8)
    src = np.frombuffer(body, dtype=np.uint8).reshape(len(idx), 48)
    dst = merged.reshape(len(idx), RECORD_BYTES)
    dst[:, :48] = src
    dst[:, 48:] = np.frombuffer(attrs, dtype=np.uint8).reshape(len(idx), 2)
    out.write(merged.tobytes())
    report = {
        "format": "stl-binary",
        "triangles": int(len(idx)),
        "degenerate_triangles": int(degenerate.sum()),
        "scale": float(scale),
        "carries": ["static geometry"],
        "does_not_carry": ["morph targets", "animation",
                           "vertex colors", "materials",
                           "color grade"],
    }
    return out.getvalue(), report


def arrays_from_npz(data):
    """(positions, indices) from NPZ bytes, the mesh-glb input."""
    with np.load(io.BytesIO(data), allow_pickle=False) as z:
        if "positions" not in z or "indices" not in z:
            raise ValueError("NPZ needs positions and indices")
        return z["positions"], z["indices"]


def build_stl_from_npz(data, scale=1.0):
    positions, indices = arrays_from_npz(data)
    return build_stl(positions, indices, scale=scale)


def parse_stl(data):
    """Read binary STL bytes back: header, count, records.

    Returns a dict with the raw header, the stored triangle
    count, a (M, 3) normals array, a (M, 3, 3) triangles array,
    and the attribute byte counts, so tests can round trip the
    writer field by field. Raises ValueError when the byte
    length disagrees with the stored count.
    """
    if len(data) < HEADER_BYTES + 4:
        raise ValueError("too short for binary STL")
    header = data[:HEADER_BYTES]
    (count,) = struct.unpack_from("<I", data, HEADER_BYTES)
    expected = HEADER_BYTES + 4 + count * RECORD_BYTES
    if len(data) != expected:
        raise ValueError(
            f"length {len(data)} disagrees with count {count} "
            f"(expected {expected})")
    raw = np.frombuffer(data, dtype=np.uint8,
                        offset=HEADER_BYTES + 4).reshape(count,
                                                          RECORD_BYTES)
    floats = np.ascontiguousarray(
        raw[:, :48]).view("<f4").reshape(count, 12)
    attrs = np.ascontiguousarray(raw[:, 48:]).view("<u2").reshape(count)
    return {
        "header": header,
        "count": count,
        "normals": floats[:, 0:3].astype(np.float64),
        "triangles": floats[:, 3:12].astype(np.float64).reshape(
            count, 3, 3),
        "attribute_byte_counts": attrs.astype(np.int64),
    }
