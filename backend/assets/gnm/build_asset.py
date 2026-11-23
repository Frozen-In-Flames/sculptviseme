"""Build the vendored GNM template asset (mean_shape.npz).

Reads the official GNM head model file (gnm_head.npz, google/
gnm-v3 on Hugging Face, Apache 2.0) and the sparse-68 landmark
definitions shipped in the GNM repository (commit dfd3e4b), and
extracts what the fit stage needs: the skin component's template
vertices and triangles, the 68 landmarks (as the template vertex
of maximum barycentric weight), and the upper/lower lip vertex
sets. The full parametric model (identity and expression bases)
is NOT vendored: the fit stage needs the template, not the
generator, and the smaller asset keeps the repository lean.

Usage: python build_asset.py <gnm_head.npz> <head_sparse_68.txt>
Hashes of inputs and output are printed for VENDOR.md.
"""

import hashlib
import sys

import numpy as np

# iBUG 68-point naming, by index range.
def landmark_name(i):
    if i <= 16:
        return f"jaw_{i}"
    if i <= 21:
        return f"brow_right_{i - 17}"
    if i <= 26:
        return f"brow_left_{i - 22}"
    if i <= 30:
        return f"nose_bridge_{i - 27}" if i < 30 else "nose_tip"
    if i <= 35:
        return f"nostril_{i - 31}"
    if i <= 41:
        return f"eye_right_{i - 36}"
    if i <= 47:
        return f"eye_left_{i - 42}"
    if i == 48:
        return "mouth_corner_left"
    if i == 54:
        return "mouth_corner_right"
    if i <= 59:
        return f"lip_upper_{i - 49}"
    if i == 62:
        return "mouth_center"
    if i <= 67:
        return f"lip_lower_{i - 60}"
    return f"landmark_{i}"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    src_path, lm_path = sys.argv[1], sys.argv[2]
    d = np.load(src_path)
    pos = np.asarray(d["template_vertex_positions"], dtype=np.float64)
    tris = np.asarray(d["triangles"], dtype=np.int64)
    groups = {str(n): np.asarray(d["vertex_groups"][i])
              for i, n in enumerate(d["vertex_group_names"])}
    skin_mask = groups["skin"] > 0.5
    keep = np.where(skin_mask)[0]
    remap = -np.ones(len(pos), dtype=np.int64)
    remap[keep] = np.arange(len(keep))
    skin_tris = tris[skin_mask[tris].all(axis=1)]
    skin_tris = remap[skin_tris]
    skin_pos = pos[keep]

    lm_idx, lm_names = [], []
    with open(lm_path) as f:
        rows = [ln.split() for ln in f if ln.strip()]
    assert len(rows) == 68, f"expected 68 landmarks, got {len(rows)}"
    for i, row in enumerate(rows):
        idx = [int(row[j]) for j in (0, 2, 4)]
        wts = [float(row[j]) for j in (1, 3, 5)]
        best = idx[int(np.argmax(wts))]
        assert skin_mask[best], f"landmark {i} not on skin"
        lm_idx.append(int(remap[best]))
        lm_names.append(landmark_name(i))

    def group_indices(name):
        m = (groups[name] > 0.5) & skin_mask
        return remap[np.where(m)[0]].astype(np.int64)

    out = "mean_shape.npz"
    np.savez(
        out,
        positions=skin_pos.astype(np.float32),
        indices=skin_tris.astype(np.int32),
        landmark_names=np.array(lm_names),
        landmark_indices=np.array(lm_idx, dtype=np.int64),
        upper_lip_indices=group_indices("upper_lip"),
        lower_lip_indices=group_indices("lower_lip"))
    print(f"skin vertices {len(skin_pos)} of {len(pos)}, "
          f"triangles {len(skin_tris)} of {len(tris)}")
    print(f"src sha256  {sha256(src_path)}")
    print(f"lm sha256   {sha256(lm_path)}")
    print(f"out sha256  {sha256(out)}")


if __name__ == "__main__":
    main()
