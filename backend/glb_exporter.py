"""Self-written glTF 2.0 binary (GLB) packer for the Clay Studio.

Writes a static mesh with morph targets and an optional morph
weights animation channel, in pure Python stdlib plus NumPy. No
external converter, no service, no signup: struct packing only,
following the Khronos glTF 2.0 container rules:

- 12-byte header (magic "glTF", version 2, total length), then a
  JSON chunk (type 0x4E4F534A, space padded to 4 bytes) and a BIN
  chunk (type 0x004E4942, zero padded to 4 bytes).
- Morph targets hold per-vertex displacements (deltas), never
  absolute positions: rendered = POSITION + sum_i w_i * target_i.
- Morph animation is a channel with target.path "weights" on the
  mesh node; the sampler input is time in seconds (SCALAR), the
  output is one weight per target per keyframe.

Morph deltas use SPARSE accessors, per RESEARCH.md section 7. A
dense float32 VEC3 delta costs 12 bytes per vertex: at the bust's
71,524 vertices that is about 0.86 MB per target, about 13 MB for
the 15 viseme targets. Mouth-region targets touch a small vertex
subset, so sparse storage (indices + values for nonzero rows only)
is the difference between a shippable file and a bloated one.

parse_glb / read_accessor below are the matching hand-rolled reader,
in the same style as bio-3d/stage7/recolor_v5.py, so tests can round
trip everything this module writes, including sparse expansion.
"""

import json
import struct

import numpy as np

GLB_MAGIC = b"glTF"
GLB_VERSION = 2
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

CT_UINT8 = 5121
CT_UINT16 = 5123
CT_UINT32 = 5125
CT_FLOAT = 5126

_COMP_SIZE = {CT_UINT8: 1, CT_UINT16: 2, CT_UINT32: 4, CT_FLOAT: 4}
_TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
               "MAT4": 16}
_NP_DTYPE = {CT_UINT8: np.uint8, CT_UINT16: "<u2", CT_UINT32: "<u4",
             CT_FLOAT: "<f4"}


def _pad4(n):
    return (4 - n % 4) % 4


class _BinBuilder:
    """Accumulates bufferViews and accessors over one BIN buffer."""

    def __init__(self):
        self.data = bytearray()
        self.buffer_views = []
        self.accessors = []

    def _add_view(self, raw, target=None):
        pad = _pad4(len(self.data))
        if pad:
            self.data.extend(b"\x00" * pad)
        offset = len(self.data)
        self.data.extend(raw)
        view = {"buffer": 0, "byteOffset": offset,
                "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        self.buffer_views.append(view)
        return len(self.buffer_views) - 1

    def add_accessor(self, array, comp_type, acc_type, target=None):
        """Dense accessor over a NumPy array shaped (count, ncomp)."""
        array = np.ascontiguousarray(array)
        view = self._add_view(array.tobytes(), target)
        acc = {"bufferView": view, "componentType": comp_type,
               "count": int(array.shape[0]), "type": acc_type,
               "min": array.min(axis=0).tolist(),
               "max": array.max(axis=0).tolist()}
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def add_sparse_accessor(self, dense, comp_type=CT_FLOAT,
                            acc_type="VEC3"):
        """Sparse accessor for a (count, ncomp) array.

        Stores only rows that are not exactly zero. An all-zero array
        stores a single zero row at index 0, which expands back to
        all zeros and keeps the accessor valid and tiny.
        """
        dense = np.ascontiguousarray(dense)
        count = int(dense.shape[0])
        nonzero = np.nonzero(np.any(dense != 0, axis=1))[0]
        if len(nonzero) == 0:
            nonzero = np.array([0], dtype=np.int64)
        values = dense[nonzero]
        if count <= 65535:
            idx = nonzero.astype("<u2")
            idx_ct = CT_UINT16
        else:
            idx = nonzero.astype("<u4")
            idx_ct = CT_UINT32
        idx_view = self._add_view(idx.tobytes())
        val_view = self._add_view(values.tobytes())
        # glTF 2.0 spec format: sparse.indices and sparse.values are
        # objects naming a bufferView directly (indices also carries
        # its componentType); they are not accessor indices. An
        # earlier build wrote accessor indices here, which standard
        # loaders (Three.js GLTFLoader) reject; the frontend build
        # caught it. The sparse accessor itself has no bufferView:
        # its base values are all zero.
        acc = {"componentType": comp_type, "count": count,
               "type": acc_type,
               "min": dense.min(axis=0).tolist(),
               "max": dense.max(axis=0).tolist(),
               "sparse": {
                   "count": int(len(nonzero)),
                   "indices": {"bufferView": idx_view,
                               "byteOffset": 0,
                               "componentType": idx_ct},
                   "values": {"bufferView": val_view,
                              "byteOffset": 0}}}
        self.accessors.append(acc)
        return len(self.accessors) - 1


def compute_smooth_normals(positions, indices):
    """Area-weighted vertex normals from triangle faces."""
    pos = np.asarray(positions, dtype=np.float64)
    idx = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    tris = pos[idx]
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals = np.zeros_like(pos)
    for corner in range(3):
        np.add.at(normals, idx[:, corner], cross)
    lens = np.linalg.norm(normals, axis=1)
    lens[lens == 0] = 1.0
    return (normals / lens[:, None]).astype(np.float32)


def build_glb(positions, indices, normals=None, morph_targets=None,
              weights_animation=None, mesh_name="clay-bust",
              base_color=(0.72, 0.70, 0.68, 1.0), roughness=0.9):
    """Pack a mesh (plus optional morphs and weights animation).

    positions: (N, 3) float. indices: (M, 3) int triangle indices.
    normals: (N, 3) float or None (computed smooth when None).
    morph_targets: list of dicts {"name": str,
        "position": (N, 3) delta array,
        "normal": optional (N, 3) delta array}.
    weights_animation: (times (K,) seconds, weights (K, T)) with T
        equal to len(morph_targets), or None.
    Returns the GLB file as bytes.
    """
    pos = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
    n = len(pos)
    idx = np.asarray(indices).reshape(-1, 3)
    idx_ct = CT_UINT16 if n <= 65535 else CT_UINT32
    idx_np = idx.reshape(-1).astype(
        "<u2" if idx_ct == CT_UINT16 else "<u4")
    if normals is None:
        normals = compute_smooth_normals(pos, idx)
    nrm = np.asarray(normals, dtype=np.float32).reshape(-1, 3)

    targets = morph_targets or []
    for t in targets:
        d = np.asarray(t["position"])
        if d.shape != (n, 3):
            raise ValueError(
                f"morph target {t.get('name')!r} position delta has "
                f"shape {d.shape}, expected {(n, 3)}")

    b = _BinBuilder()
    a_pos = b.add_accessor(pos, CT_FLOAT, "VEC3", target=34962)
    a_nrm = b.add_accessor(nrm, CT_FLOAT, "VEC3", target=34962)
    a_idx = b.add_accessor(idx_np, idx_ct, "SCALAR", target=34963)

    prim_targets = []
    for t in targets:
        entry = {"POSITION": b.add_sparse_accessor(
            np.asarray(t["position"], dtype=np.float32))}
        if t.get("normal") is not None:
            entry["NORMAL"] = b.add_sparse_accessor(
                np.asarray(t["normal"], dtype=np.float32))
        prim_targets.append(entry)

    gltf = {
        "asset": {"version": "2.0",
                  "generator": "clay-sculpt-studio glb_exporter"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": mesh_name}],
        "meshes": [{
            "name": mesh_name,
            "weights": [0.0] * len(targets),
            "primitives": [{
                "attributes": {"POSITION": a_pos, "NORMAL": a_nrm},
                "indices": a_idx,
                "material": 0,
                "targets": prim_targets,
            }],
            "extras": {"targetNames": [t["name"] for t in targets]},
        }],
        "materials": [{
            "name": "clay",
            "pbrMetallicRoughness": {
                "baseColorFactor": list(base_color),
                "metallicFactor": 0.0,
                "roughnessFactor": roughness,
            },
        }],
        "buffers": [{"byteLength": 0}],  # filled in below
    }

    if weights_animation is not None:
        times, weights = weights_animation
        times = np.asarray(times, dtype=np.float32).reshape(-1)
        weights = np.asarray(weights, dtype=np.float32)
        if weights.shape != (len(times), len(targets)):
            raise ValueError(
                f"weights animation shape {weights.shape} does not "
                f"match ({len(times)}, {len(targets)})")
        a_time = b.add_accessor(times.reshape(-1, 1), CT_FLOAT,
                                "SCALAR")
        a_w = b.add_accessor(weights.reshape(-1, 1), CT_FLOAT,
                             "SCALAR")
        gltf["animations"] = [{
            "name": "viseme-weights",
            "samplers": [{"input": a_time, "interpolation": "LINEAR",
                          "output": a_w}],
            "channels": [{"sampler": 0,
                          "target": {"node": 0, "path": "weights"}}],
        }]

    gltf["bufferViews"] = b.buffer_views
    gltf["accessors"] = b.accessors
    gltf["buffers"] = [{"byteLength": len(b.data)}]
    return pack_glb(gltf, bytes(b.data))


def pack_glb(gltf, bin_data):
    """Assemble the GLB container from a glTF dict and BIN bytes."""
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode()
    json_bytes += b" " * _pad4(len(json_bytes))
    bin_padded = bin_data + b"\x00" * _pad4(len(bin_data))
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_padded)
    out = bytearray()
    out += GLB_MAGIC
    out += struct.pack("<II", GLB_VERSION, total)
    out += struct.pack("<I", len(json_bytes)) + b"JSON"
    out += json_bytes
    out += struct.pack("<I", len(bin_padded)) + b"BIN\x00"
    out += bin_padded
    return bytes(out)


# ---- Reader (stage7 style, hand-rolled) ------------------------------

def parse_glb(data):
    """Return (gltf_dict, bin_bytes). Mirrors stage7 parse_glb."""
    if data[:4] != GLB_MAGIC:
        raise ValueError("not a GLB (bad magic)")
    version, total = struct.unpack("<II", data[4:12])
    if version != GLB_VERSION:
        raise ValueError(f"unsupported GLB version {version}")
    if total != len(data):
        raise ValueError("GLB length field does not match data")
    jlen, jtype = struct.unpack("<I4s", data[12:20])
    if jtype != b"JSON":
        raise ValueError("first chunk is not JSON")
    gltf = json.loads(data[20:20 + jlen])
    off = 20 + jlen
    blen, btype = struct.unpack("<I4s", data[off:off + 8])
    if btype != b"BIN\x00":
        raise ValueError("second chunk is not BIN")
    return gltf, data[off + 8:off + 8 + blen]


def _dense_bytes(gltf, bin_data, acc_idx):
    acc = gltf["accessors"][acc_idx]
    view = gltf["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    ncomp = _TYPE_COUNT[acc["type"]]
    size = _COMP_SIZE[acc["componentType"]]
    return bin_data[start:start + acc["count"] * ncomp * size], acc


def read_accessor(gltf, bin_data, acc_idx):
    """Read an accessor as a NumPy array, expanding sparse storage."""
    acc = gltf["accessors"][acc_idx]
    ncomp = _TYPE_COUNT[acc["type"]]
    dtype = _NP_DTYPE[acc["componentType"]]
    if "sparse" not in acc:
        raw, _ = _dense_bytes(gltf, bin_data, acc_idx)
        arr = np.frombuffer(raw, dtype=dtype)
        return arr.reshape(acc["count"], ncomp).copy()
    out = np.zeros((acc["count"], ncomp), dtype=dtype)
    sparse = acc["sparse"]
    n_sparse = sparse["count"]
    idx_def = sparse["indices"]
    idx_view = gltf["bufferViews"][idx_def["bufferView"]]
    idx_start = idx_view.get("byteOffset", 0) + \
        idx_def.get("byteOffset", 0)
    idx_dtype = _NP_DTYPE[idx_def["componentType"]]
    idx = np.frombuffer(
        bin_data[idx_start:idx_start + n_sparse *
                 _COMP_SIZE[idx_def["componentType"]]],
        dtype=idx_dtype).astype(np.int64)
    val_def = sparse["values"]
    val_view = gltf["bufferViews"][val_def["bufferView"]]
    val_start = val_view.get("byteOffset", 0) + \
        val_def.get("byteOffset", 0)
    vals = np.frombuffer(
        bin_data[val_start:val_start + n_sparse * ncomp *
                 _COMP_SIZE[acc["componentType"]]],
        dtype=dtype).reshape(n_sparse, ncomp)
    out[idx] = vals
    return out
