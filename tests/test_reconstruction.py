"""Visual-hull reconstruction tests (backend/reconstruction.py).

The oracle is analytic: a sphere's silhouette under the
documented orthographic turntable model is a disk, rasterized
here directly from the equation, an independent path from the
carve code. Controls: fewer views must loosen the hull, a
concavity must come back filled (the method's documented
limit), and mislabeled azimuths must hurt.
"""

import io
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "backend"))
import reconstruction  # noqa: E402


def disk_masks(radius=0.55, views=24, size=96, center=(0.0, 0.0)):
    v = 1.0 - np.arange(size) * (2.0 / (size - 1))
    u = -1.0 + np.arange(size) * (2.0 / (size - 1))
    UU, VV = np.meshgrid(u, v)
    disk = ((UU - center[0]) ** 2 + (VV - center[1]) ** 2
            <= radius ** 2)
    return ([disk.copy() for _ in range(views)],
            [i * 360.0 / views for i in range(views)])


class HullOracleTests(unittest.TestCase):

    def test_sphere_volume_and_centroid(self):
        masks, az = disk_masks()
        pos, idx, rep = reconstruction.reconstruct(masks, az,
                                                   grid=48)
        true_vol = 4.0 / 3.0 * np.pi * 0.55 ** 3
        self.assertGreater(rep["mesh_volume"], 0.0)
        self.assertLess(abs(rep["mesh_volume"] - true_vol)
                        / true_vol, 0.12)
        self.assertLess(np.abs(pos.mean(axis=0)).max(), 0.05)

    def test_hull_contains_the_shape(self):
        masks, az = disk_masks()
        occ, axis = reconstruction.carve(masks, az, grid=32)
        yy, xx, zz = np.meshgrid(axis, axis, axis, indexing="ij")
        inner = (xx ** 2 + yy ** 2 + zz ** 2) <= (0.55 - 0.08) ** 2
        self.assertTrue(occ[inner].all())

    def test_fewer_views_loosen_the_hull(self):
        m24, a24 = disk_masks(views=24)
        m4, a4 = disk_masks(views=4)
        _, _, r24 = reconstruction.reconstruct(m24, a24, grid=40)
        _, _, r4 = reconstruction.reconstruct(m4, a4, grid=40)
        self.assertGreater(r4["voxel_volume"],
                           r24["voxel_volume"] * 1.10)

    def test_off_center_sphere_and_azimuth_control(self):
        # A sphere centered at x=+0.3: silhouettes shift with the
        # azimuth; carving with the true azimuths finds it, and
        # carving with azimuths rotated 90 degrees must do worse.
        size = 96
        views = 24
        masks, az = [], []
        for i in range(views):
            a = np.deg2rad(i * 360.0 / views)
            cu = 0.3 * np.cos(a)
            m, _ = disk_masks(views=1, size=size, center=(cu, 0.0))
            masks.append(m[0])
            az.append(i * 360.0 / views)
        occ, axis = reconstruction.carve(masks, az, grid=40)
        yy, xx, zz = np.meshgrid(axis, axis, axis, indexing="ij")
        cx = float((xx * occ).sum() / occ.sum())
        self.assertLess(abs(cx - 0.3), 0.07)
        occ_bad, _ = reconstruction.carve(
            masks, [(a + 90.0) % 360.0 for a in az], grid=40)
        cx_bad = float((xx * occ_bad).sum() / occ_bad.sum())
        self.assertGreater(abs(cx_bad - 0.3), abs(cx - 0.3) + 0.10)

    def test_concavity_comes_back_filled(self):
        # A vertical cylinder (r 0.5, height 1.2) with a vertical
        # bore (r 0.25) through it: no turntable silhouette can
        # see the bore, so every mask is the same rectangle and
        # the hull must come back solid, its volume well above
        # the true bored volume. The documented limit, asserted.
        size = 96
        v = 1.0 - np.arange(size) * (2.0 / (size - 1))
        u = -1.0 + np.arange(size) * (2.0 / (size - 1))
        UU, VV = np.meshgrid(u, v)
        rect = (np.abs(UU) <= 0.5) & (np.abs(VV) <= 0.6)
        masks = [rect.copy() for _ in range(24)]
        az = [i * 15.0 for i in range(24)]
        _, _, rep = reconstruction.reconstruct(masks, az, grid=48)
        true_vol = np.pi * (0.5 ** 2 - 0.25 ** 2) * 1.2
        self.assertGreater(rep["voxel_volume"], true_vol * 1.15)


class PlateTests(unittest.TestCase):

    def test_plate_difference_recovers_mask(self):
        rng = np.random.default_rng(3)
        plate = np.full((40, 50, 3), 120, dtype=np.uint8)
        frame = plate.copy()
        frame[10:25, 15:35] = 30
        mask = reconstruction.silhouette_from_plate(frame, plate)
        want = np.zeros((40, 50), dtype=bool)
        want[10:25, 15:35] = True
        self.assertTrue((mask == want).all())
        noisy = (plate.astype(int)
                 + rng.integers(-8, 9, plate.shape)).astype(np.uint8)
        self.assertFalse(reconstruction.silhouette_from_plate(
            noisy, plate).any())

    def test_shape_mismatch_raises(self):
        with self.assertRaises(ValueError):
            reconstruction.silhouette_from_plate(
                np.zeros((4, 4, 3), np.uint8),
                np.zeros((5, 4, 3), np.uint8))


class EndpointTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import app
        cls.client = TestClient(app.app)

    def test_reconstruct_endpoint_round_trip(self):
        masks, az = disk_masks(views=8, size=48)
        buf = io.BytesIO()
        np.savez(buf, masks=np.array(masks, dtype=np.uint8),
                 azimuths_deg=np.array(az))
        resp = self.client.post(
            "/api/mesh-reconstruct",
            files={"masks_npz": ("masks.npz", buf.getvalue())},
            data={"grid": "32"})
        self.assertEqual(resp.status_code, 200, resp.text[:200])
        self.assertIn("views", resp.headers[
            "X-SculptViseme-Reconstruct"])
        out = np.load(io.BytesIO(resp.content))
        self.assertGreater(len(out["positions"]), 100)
        self.assertEqual(out["indices"].shape[1], 3)

    def test_reconstruct_endpoint_rejects_bad_npz(self):
        buf = io.BytesIO()
        np.savez(buf, masks=np.zeros((3, 8, 8), np.uint8))
        resp = self.client.post(
            "/api/mesh-reconstruct",
            files={"masks_npz": ("bad.npz", buf.getvalue())})
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
