"""Template head fit: non-rigid ICP (RESEARCH.md section 5).

Fits a template head mesh to a reconstructed target mesh so the
result carries the template's topology (including its lip line)
in the target's shape. The recipe, implemented here from the
architecture: landmark-initialized rigid alignment (Umeyama,
with scale), then iterative non-rigid ICP with point-to-point
correspondences, trimmed one-way matching for partial overlap,
and a Laplacian stiffness term whose weight decays across
iterations (stiff first, flexible last).

The GNM Head model (google/GNM, Apache 2.0) is the intended
template source. Its assets are NOT vendored in this repository:
the fit engine is template-agnostic and is verified against
synthetic templates, and the GNM gate below reports availability
honestly and refuses when the assets are absent. Vendoring is
pinned to GNM commit dfd3e4b per RESEARCH.md and is a deliberate,
separate step (asset hashes recorded at vendor time).

Pure NumPy + SciPy. No network.
"""

import os

import numpy as np

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "gnm")
GNM_PIN = "dfd3e4b"
GNM_MEAN_FILE = "mean_shape.npz"


class FitUnavailable(Exception):
    """The requested template assets are not installed."""


def gnm_status():
    path = os.path.join(ASSET_DIR, GNM_MEAN_FILE)
    if os.path.isfile(path):
        return {"available": True, "path": path, "pin": GNM_PIN}
    return {"available": False, "pin": GNM_PIN,
            "detail": "GNM Head assets are not vendored in this "
                      "installation (expected at backend/assets/"
                      "gnm/mean_shape.npz, pinned to google/GNM "
                      f"commit {GNM_PIN}, Apache 2.0). The fit "
                      "engine itself is installed and verified "
                      "against synthetic templates; only the GNM "
                      "template data is missing."}


def load_gnm_template():
    """(positions, indices, landmarks) of the vendored GNM mean
    shape; landmarks maps name -> vertex index."""
    status = gnm_status()
    if not status["available"]:
        raise FitUnavailable(status["detail"])
    data = np.load(status["path"], allow_pickle=False)
    landmarks = {}
    if "landmark_names" in data and "landmark_indices" in data:
        for name, idx in zip(data["landmark_names"],
                             data["landmark_indices"]):
            landmarks[str(name)] = int(idx)
    return (np.asarray(data["positions"], dtype=np.float64),
            np.asarray(data["indices"]).reshape(-1, 3), landmarks)


def rigid_align(source, target):
    """Umeyama similarity transform (scale, rotation, translation)
    mapping source points onto target points (paired rows).
    Returns (aligned_source, {"scale", "rotation", "translation"}).
    """
    src = np.asarray(source, dtype=np.float64)
    tgt = np.asarray(target, dtype=np.float64)
    if src.shape != tgt.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError("paired (N, 3) point sets required")
    cs, ct = src.mean(axis=0), tgt.mean(axis=0)
    xs, xt = src - cs, tgt - ct
    cov = xs.T @ xt / len(src)
    u, d, vt = np.linalg.svd(cov)
    rot = vt.T @ u.T
    if np.linalg.det(rot) < 0:
        vt[-1] *= -1
        rot = vt.T @ u.T
    var = (xs ** 2).sum() / len(src)
    scale = float(d.sum() / var) if var > 0 else 1.0
    aligned = scale * (src @ rot.T) + (ct - scale * (cs @ rot.T))
    return aligned, {"scale": scale, "rotation": rot,
                     "translation": ct - scale * (cs @ rot.T)}


def _laplacian(n, indices):
    import scipy.sparse as sp
    rows, cols = [], []
    for a, b, c in np.asarray(indices).reshape(-1, 3):
        for u, v in ((a, b), (b, c), (c, a)):
            rows += [u, v]
            cols += [v, u]
    data = np.ones(len(rows))
    adj = sp.coo_matrix((data, (rows, cols)), shape=(n, n))
    adj = (adj > 0).astype(np.float64)
    deg = np.asarray(adj.sum(axis=1)).ravel()
    return sp.diags(deg) - adj


def fit_template(template_pos, template_idx, target_pos,
                 template_landmarks=None, target_landmarks=None,
                 iterations=24, stiffness_start=8.0,
                 stiffness_end=0.35, trim_percentile=90.0,
                 landmark_weight=25.0):
    """Non-rigid ICP fit. Landmarks, when given, are paired
    (K, 3) arrays: template_landmarks[k] is the template vertex
    position's counterpart target_landmarks[k] in the target.

    Returns (fitted_positions, report).
    """
    from scipy.spatial import cKDTree
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl

    pos = np.array(template_pos, dtype=np.float64)
    target = np.asarray(target_pos, dtype=np.float64)
    n = len(pos)
    lap = _laplacian(n, template_idx)

    anchors = None
    if template_landmarks is not None and target_landmarks is not None:
        tl = np.asarray(template_landmarks, dtype=np.float64)
        tg = np.asarray(target_landmarks, dtype=np.float64)
        # Landmark rows are positions on the template surface;
        # anchor the nearest template vertex to each.
        tree0 = cKDTree(pos)
        _, anchor_idx = tree0.query(tl)
        # Apply the landmark similarity to the whole template.
        _, info = rigid_align(tl, tg)
        pos = info["scale"] * (pos @ info["rotation"].T) \
            + info["translation"]
        anchors = (np.asarray(anchor_idx), tg)

    tree = cKDTree(target)
    dist0, _ = tree.query(pos)
    report = {"initial_mean_distance": float(dist0.mean()),
              "iterations": int(iterations)}
    stiffness = np.geomspace(stiffness_start, stiffness_end,
                             max(iterations, 1))
    for it in range(iterations):
        dist, nn = tree.query(pos)
        thresh = np.percentile(dist, trim_percentile)
        w = (dist <= thresh).astype(np.float64)
        corr = target[nn]
        if anchors is not None:
            aidx, atgt = anchors
            w[aidx] = landmark_weight
            corr[aidx] = atgt
        wmat = sp.diags(w)
        lam = float(stiffness[it])
        lhs = wmat + lam * lap
        # Stiffness acts on the deformation, not the absolute
        # positions (Amberg et al.): the Laplacian term anchors
        # edge vectors to the previous iteration's, so a step
        # whose correspondences equal the current positions is
        # exactly the identity at any stiffness. An absolute
        # Laplacian instead shrinks the mesh toward its local
        # centroids and the fit explodes before it can converge.
        rhs = wmat @ corr + lam * (lap @ pos)
        solved = np.column_stack(
            [spl.spsolve(lhs.tocsc(), rhs[:, d]) for d in range(3)])
        if np.isnan(solved).any():
            raise RuntimeError("fit diverged (NaN in solve)")
        pos = solved
    dist1, _ = tree.query(pos)
    report["final_mean_distance"] = float(dist1.mean())
    report["final_max_distance"] = float(dist1.max())
    return pos, report
