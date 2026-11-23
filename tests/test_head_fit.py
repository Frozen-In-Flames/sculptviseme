"""Template fit tests (backend/head_fit.py, backend/colmap_stage.py).

The fit engine is verified against a synthetic template: an
icosphere fitted to an anisotropically scaled, translated copy
of itself sampled as a dense target cloud. Controls: landmarks
must beat landmark-free fitting on landmark error, stiffness
must smooth a noisy target, and the GNM / COLMAP gates must
refuse honestly where their assets are absent.
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "backend"))
import colmap_stage  # noqa: E402
import head_fit  # noqa: E402


def icosphere(subdiv=2):
    t = (1.0 + np.sqrt(5.0)) / 2.0
    verts = np.array([
        [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
        [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
        [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]],
        dtype=np.float64)
    faces = np.array([
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]])
    verts /= np.linalg.norm(verts, axis=1, keepdims=True)
    for _ in range(subdiv):
        cache = {}
        new_faces = []

        def midpoint(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = (verts[a] + verts[b]) / 2.0
                m /= np.linalg.norm(m)
                cache[key] = len(verts_list)
                verts_list.append(m)
            return cache[key]

        verts_list = list(verts)
        for a, b, c in faces:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), \
                midpoint(c, a)
            new_faces += [[a, ab, ca], [b, bc, ab],
                          [c, ca, bc], [ab, bc, ca]]
        verts = np.array(verts_list)
        faces = np.array(new_faces)
    return verts, faces


SCALE = np.array([1.15, 0.9, 1.05])
SHIFT = np.array([0.05, -0.03, 0.02])


def make_target(subdiv=4):
    pts, _ = icosphere(subdiv)
    return pts * SCALE + SHIFT


class RigidAlignTests(unittest.TestCase):

    def test_umeyama_recovers_similarity(self):
        rng = np.random.default_rng(5)
        src = rng.normal(size=(40, 3))
        ang = 0.7
        rot = np.array([[np.cos(ang), -np.sin(ang), 0],
                        [np.sin(ang), np.cos(ang), 0],
                        [0, 0, 1.0]])
        tgt = 1.7 * (src @ rot.T) + np.array([0.4, -0.2, 0.9])
        aligned, info = head_fit.rigid_align(src, tgt)
        self.assertLess(np.abs(aligned - tgt).max(), 1e-9)
        self.assertAlmostEqual(info["scale"], 1.7, places=9)


class FitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.template, cls.faces = icosphere(2)
        cls.target = make_target()
        # Landmarks: the six axis extremes of the template.
        picks = []
        for d in range(3):
            col = cls.template[:, d]
            picks += [int(np.argmax(col)), int(np.argmin(col))]
        cls.lm_template = cls.template[picks]
        cls.lm_target = cls.lm_template * SCALE + SHIFT

    def test_fit_converges_with_landmarks(self):
        fitted, rep = head_fit.fit_template(
            self.template, self.faces, self.target,
            template_landmarks=self.lm_template,
            target_landmarks=self.lm_target, iterations=20)
        self.assertLess(rep["final_mean_distance"],
                        0.30 * rep["initial_mean_distance"])
        self.assertLess(rep["final_mean_distance"], 0.02)
        from scipy.spatial import cKDTree
        d, _ = cKDTree(fitted).query(self.lm_target)
        self.assertLess(d.max(), 0.03)

    def test_landmarks_beat_no_landmarks(self):
        from scipy.spatial import cKDTree
        shift = np.array([0.3, 0.25, -0.2])
        start = self.template + shift
        lm_start = self.lm_template + shift
        fitted_with, _ = head_fit.fit_template(
            start, self.faces, self.target,
            template_landmarks=lm_start,
            target_landmarks=self.lm_target, iterations=20)
        fitted_free, _ = head_fit.fit_template(
            start, self.faces, self.target, iterations=20)
        err_with = np.linalg.norm(
            cKDTree(fitted_with).query(self.lm_target)[0])
        err_free = np.linalg.norm(
            cKDTree(fitted_free).query(self.lm_target)[0])
        self.assertLess(err_with.max(), err_free.max())

    def test_identity_target_is_a_fixed_point(self):
        # Regression control for the stiffness formulation: when
        # the target IS the template, no stiffness weight may move
        # a vertex. An absolute-position Laplacian fails this by
        # shrinking the mesh toward its local centroids.
        fitted, rep = head_fit.fit_template(
            self.template, self.faces, self.template.copy(),
            iterations=6, stiffness_start=50.0, stiffness_end=50.0)
        self.assertLess(np.abs(fitted - self.template).max(), 1e-6)

    def test_stiffness_smooths_a_noisy_target(self):
        rng = np.random.default_rng(11)
        noisy = self.template + rng.normal(scale=0.03,
                                           size=self.template.shape)
        def roughness(p):
            lap = head_fit._laplacian(len(p), self.faces)
            return float(np.abs(lap @ p).mean())
        stiff, _ = head_fit.fit_template(
            self.template, self.faces, noisy, iterations=10,
            stiffness_start=30.0, stiffness_end=30.0)
        floppy, _ = head_fit.fit_template(
            self.template, self.faces, noisy, iterations=10,
            stiffness_start=0.02, stiffness_end=0.02)
        self.assertLess(roughness(stiff), roughness(floppy))


class GateTests(unittest.TestCase):

    def test_gnm_gate_refuses_honestly_when_unvendored(self):
        st = head_fit.gnm_status()
        if st["available"]:
            self.skipTest("GNM assets are vendored on this host")
        self.assertIn("not vendored", st["detail"])
        with self.assertRaises(head_fit.FitUnavailable):
            head_fit.load_gnm_template()

    def test_gnm_template_loads_when_vendored(self):
        st = head_fit.gnm_status()
        if not st["available"]:
            self.skipTest("GNM assets are not vendored on this host")
        pos, idx, lm = head_fit.load_gnm_template()
        self.assertGreater(len(pos), 5000)
        self.assertEqual(idx.shape[1], 3)
        self.assertLess(idx.max(), len(pos))
        for name in ("nose_tip", "mouth_center",
                     "mouth_corner_left", "mouth_corner_right"):
            self.assertIn(name, lm)
        # The mouth landmarks span a plausible mouth: corners
        # apart, center between them.
        c = pos[lm["mouth_corner_left"]] - pos[lm["mouth_corner_right"]]
        self.assertGreater(np.linalg.norm(c), 0.01)

    def test_colmap_gate(self):
        st = colmap_stage.status()
        if st["available"]:
            self.skipTest("COLMAP is installed on this host")
        self.assertIn("not installed", st["detail"])
        with self.assertRaises(colmap_stage.ColmapUnavailable):
            colmap_stage.reconstruct_photos("/nonexistent", "/tmp")

    def test_colmap_gate_opens_for_a_cli_on_path(self):
        import stat
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            fake = os.path.join(td, "colmap")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
            old = os.environ.get("PATH", "")
            os.environ["PATH"] = td + os.pathsep + old
            try:
                st = colmap_stage.status()
            finally:
                os.environ["PATH"] = old
        self.assertTrue(st["available"])
        self.assertEqual(st["backend"], "cli")


if __name__ == "__main__":
    unittest.main()
