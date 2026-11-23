"""Visual-hull reconstruction (RESEARCH.md sections 4a and 10).

The primary reconstruction route: a turntable orbit of silhouette
masks carved into a voxel volume, then surfaced as a mesh. This
generalizes the studio's proven one-subject carve (the bio-3d
orbit pipeline, mean silhouette IoU 0.895 on its subject) into a
module any capture can use.

Camera model: orthographic turntable. The subject stands at the
origin, up is +Y, and view i sees it from azimuth[i] degrees
around Y. A silhouette pixel (row, col) of an H x W mask covers
u in [-1, 1] left to right and v in [1, -1] top to bottom, where
u = x cos(a) + z sin(a) and v = y, in a world scaled so the
subject spans [-extent, extent].

Known limits, stated plainly: a visual hull is the largest volume
consistent with the silhouettes, so concavities no silhouette can
see (the inside of a cup, the under-chin shadow region) come back
filled. More views tighten the hull; they never fix concavity.
That is what the fit stage is for.

Pure NumPy. No network, no external tools.
"""

import numpy as np


def silhouette_from_plate(frame, plate, threshold=24):
    """Boolean mask of a subject shot against an empty plate.

    frame and plate are same-shape uint8 images (H, W, 3) (or
    grayscale (H, W)); a pixel belongs to the subject when its
    absolute difference from the plate exceeds threshold on any
    channel. The standard orbit-capture matting step when the
    capture includes an empty background frame.
    """
    f = np.asarray(frame).astype(np.int16)
    p = np.asarray(plate).astype(np.int16)
    if f.shape != p.shape:
        raise ValueError(f"frame {f.shape} and plate {p.shape} differ")
    diff = np.abs(f - p)
    if diff.ndim == 3:
        diff = diff.max(axis=2)
    return diff > threshold


def _project_inside(pts, mask, azimuth_deg):
    """True where each point projects inside the silhouette."""
    a = np.deg2rad(azimuth_deg)
    u = pts[:, 0] * np.cos(a) + pts[:, 2] * np.sin(a)
    v = pts[:, 1]
    h, w = mask.shape
    col = ((u + 1.0) * 0.5 * (w - 1)).round().astype(np.int64)
    row = ((1.0 - v) * 0.5 * (h - 1)).round().astype(np.int64)
    ok = (col >= 0) & (col < w) & (row >= 0) & (row < h)
    inside = np.zeros(len(pts), dtype=bool)
    inside[ok] = mask[row[ok], col[ok]]
    return inside


def carve(masks, azimuths_deg, grid=72, extent=1.0):
    """Carve the visual hull. Returns (occupied, axis) where
    occupied is a (grid, grid, grid) boolean array indexed
    [iy, ix, iz] and axis is the voxel-center coordinate vector.

    A voxel survives when its center projects inside every
    silhouette. extent is the world half-size of the volume;
    silhouettes are assumed framed to it.
    """
    masks = [np.asarray(m, dtype=bool) for m in masks]
    azimuths = [float(a) for a in azimuths_deg]
    if len(masks) != len(azimuths) or not masks:
        raise ValueError("masks and azimuths must pair up, non-empty")
    axis = np.linspace(-extent, extent, grid)
    yy, xx, zz = np.meshgrid(axis, axis, axis, indexing="ij")
    pts = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], axis=1)
    keep = np.ones(len(pts), dtype=bool)
    for mask, az in zip(masks, azimuths):
        keep &= _project_inside(pts, mask, az)
    return keep.reshape(grid, grid, grid), axis


def surface_net(occupied, axis):
    """Naive surface net over a boolean volume -> (positions,
    indices). One vertex per sign-changing cell, placed at the
    mean of its edge crossings (midpoints on a binary field);
    one quad per sign-changing grid edge, oriented outward by
    construction (faces wind so their normal points from solid
    toward empty).
    """
    occ = np.asarray(occupied, dtype=bool)
    n = occ.shape[0]
    h = float(axis[1] - axis[0])
    origin = float(axis[0])
    # Pad so boundary cells can form faces.
    pad = np.zeros((n + 2, n + 2, n + 2), dtype=bool)
    pad[1:-1, 1:-1, 1:-1] = occ

    cell_id = -np.ones(pad.shape, dtype=np.int64)
    verts = []

    def coord(i, j, k):
        return np.array([origin + (i - 1) * h,
                         origin + (j - 1) * h,
                         origin + (k - 1) * h])

    # Cells are indexed by their low corner in padded space;
    # a cell is active when its 8 corners disagree.
    corners = np.stack([pad[:-1, :-1, :-1], pad[1:, :-1, :-1],
                        pad[:-1, 1:, :-1], pad[1:, 1:, :-1],
                        pad[:-1, :-1, 1:], pad[1:, :-1, 1:],
                        pad[:-1, 1:, 1:], pad[1:, 1:, 1:]])
    active = (corners.any(axis=0) & ~corners.all(axis=0))
    idx = np.argwhere(active)
    offsets = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0],
                        [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]])
    for j, i, k in idx:
        pts = []
        cell = [coord(i + di, j + dj, k + dk) for di, dj, dk in offsets]
        vals = [pad[j + dj, i + di, k + dk] for di, dj, dk in offsets]
        # Edge crossings: the 12 cell edges whose endpoints differ.
        edges = [(0, 1), (0, 2), (1, 3), (2, 3), (4, 5), (4, 6),
                 (5, 7), (6, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
        for a, b in edges:
            if vals[a] != vals[b]:
                pts.append((cell[a] + cell[b]) * 0.5)
        if pts:
            cell_id[j, i, k] = len(verts)
            verts.append(np.mean(pts, axis=0))
    positions = np.array(verts, dtype=np.float64).reshape(-1, 3)

    faces = []
    # For each interior grid edge along each axis whose endpoint
    # solids differ, join the 4 cells around the edge into a quad.
    # Padded coords: solid sample at (j, i, k) sits between cells
    # (j-1..j, i-1..i, k-1..k).
    def quad(cells, flip):
        ids = [cell_id[c] for c in cells]
        if min(ids) < 0:
            return
        a, b, c, d = ids
        if flip:
            faces.append([a, c, b])
            faces.append([b, c, d])
        else:
            faces.append([a, b, c])
            faces.append([b, d, c])

    m = pad.shape[0]
    for j in range(1, m - 1):
        for i in range(1, m - 1):
            for k in range(1, m - 1):
                s = pad[j, i, k]
                if i + 1 < m and pad[j, i + 1, k] != s:
                    quad([(j - 1, i, k - 1), (j, i, k - 1),
                          (j - 1, i, k), (j, i, k)], flip=not s)
                if j + 1 < m and pad[j + 1, i, k] != s:
                    quad([(j, i - 1, k - 1), (j, i, k - 1),
                          (j, i - 1, k), (j, i, k)], flip=s)
                if k + 1 < m and pad[j, i, k + 1] != s:
                    quad([(j - 1, i - 1, k), (j, i - 1, k),
                          (j - 1, i, k), (j, i, k)], flip=s)
    indices = np.array(faces, dtype=np.int64).reshape(-1, 3)
    return positions, indices


def mesh_volume(positions, indices):
    """Signed volume via the divergence theorem."""
    p = np.asarray(positions, dtype=np.float64)
    t = np.asarray(indices).reshape(-1, 3)
    a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def reconstruct(masks, azimuths_deg, grid=72, extent=1.0):
    """Full route: masks + azimuths -> (positions, indices, report)."""
    occupied, axis = carve(masks, azimuths_deg, grid=grid,
                           extent=extent)
    positions, indices = surface_net(occupied, axis)
    voxel = float(axis[1] - axis[0])
    report = {
        "views": len(masks),
        "grid": int(grid),
        "voxels_solid": int(occupied.sum()),
        "voxel_volume": float(occupied.sum() * voxel ** 3),
        "mesh_volume": mesh_volume(positions, indices),
        "vertices": int(len(positions)),
        "triangles": int(len(indices)),
    }
    return positions, indices, report
