"""Tests for backend/viseme_authoring.py (production viseme authoring).

The claims graded here:
  - targets come out in the aligner's viseme order, sil is exactly
    zero, and every other viseme actually moves vertices;
  - the articulation is directional, not decorative: PP closes the
    lip gap, aa opens it, ou draws the corners in and pushes the
    lips forward, FF raises the lower lip;
  - the fields are smooth (no step seams) and bounded (a vertex
    far from the mouth does not move);
  - the fields follow the landmarks: shifting the landmark center
    shifts the displacement (negative control against a hardcoded
    mouth position, which is what the old fixture scaffolding had);
  - the mouth estimator reproduces the v3 clay bust's hand-tuned
    fixture center (regression, run only where the local fixture
    bust exists);
  - authored targets round-trip through the real GLB exporter and
    through the /api/mesh-author-visemes endpoint, landing in the
    NPZ shape /api/mesh-glb consumes.
"""

import io
import json
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import viseme_authoring  # noqa: E402
import lipsync_align  # noqa: E402

WIDTH = 0.6
CENTER = np.array([0.0, 0.0, 0.0])
LM = {"center": CENTER, "width": WIDTH}


def _grid():
    """A flat face card: 41x41 grid, spacing 0.05, z = 0."""
    ax = np.linspace(-1.0, 1.0, 41)
    xx, yy = np.meshgrid(ax, ax)
    pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)], axis=1)
    idx = []
    n = 41
    for r in range(n - 1):
        for c in range(n - 1):
            a, b, d = r * n + c, r * n + c + 1, (r + 1) * n + c
            idx.append([a, d, b])
            idx.append([b, d, d + 1])
    return pos, np.array(idx)


def _at(pos, x, y):
    """Index of the grid vertex nearest (x, y)."""
    d = (pos[:, 0] - x) ** 2 + (pos[:, 1] - y) ** 2
    return int(np.argmin(d))


def _by_name(targets):
    return {t["name"]: t["position"] for t in targets}


class FieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pos, cls.idx = _grid()
        cls.targets, cls.info = viseme_authoring.author_visemes(
            cls.pos, landmarks=LM)
        cls.t = _by_name(cls.targets)
        cls.upper = _at(cls.pos, 0.0, 0.05)
        cls.lower = _at(cls.pos, 0.0, -0.05)
        cls.corner_l = _at(cls.pos, -0.3, 0.0)
        cls.corner_r = _at(cls.pos, 0.3, 0.0)
        cls.center_lip = _at(cls.pos, 0.0, 0.0)

    def _gap(self, delta):
        up = self.pos[self.upper] + delta[self.upper]
        lo = self.pos[self.lower] + delta[self.lower]
        return float(up[1] - lo[1])

    def test_order_and_silence(self):
        self.assertEqual([t["name"] for t in self.targets],
                         list(lipsync_align.VISEMES))
        self.assertTrue(np.all(self.t["sil"] == 0.0))
        for name, d in self.t.items():
            if name != "sil":
                self.assertGreater(np.abs(d).max(), 0.0, name)

    def test_pp_closes_and_aa_opens(self):
        neutral = self._gap(self.t["sil"])
        self.assertAlmostEqual(neutral, 0.10, places=6)
        self.assertLess(self._gap(self.t["PP"]), 0.5 * neutral)
        self.assertGreater(self._gap(self.t["aa"]), 1.5 * neutral)

    def test_ou_rounds(self):
        d = self.t["ou"]
        cl = self.pos[self.corner_l] + d[self.corner_l]
        cr = self.pos[self.corner_r] + d[self.corner_r]
        self.assertLess(float(cr[0] - cl[0]), 0.85 * 0.6)
        lip = self.pos[self.center_lip] + d[self.center_lip]
        self.assertGreater(float(lip[2]), 0.05)

    def test_ff_tucks_lower_lip_up_and_in(self):
        d = self.t["FF"]
        lo = self.pos[self.lower] + d[self.lower]
        self.assertGreater(float(lo[1]), self.pos[self.lower][1])
        self.assertLess(float(lo[2]), self.pos[self.lower][2])

    def test_support_is_bounded(self):
        far = _at(self.pos, 0.0, 1.0)  # top edge, >3 widths away in y falloff terms
        for name, d in self.t.items():
            self.assertLess(np.abs(d[far]).max(), 1e-3, name)

    def test_fields_are_smooth(self):
        pos, _ = self.pos, self.idx
        n = 41
        d = self.t["aa"]
        maxd = np.abs(d).max()
        worst = 0.0
        for r in range(n):
            for c in range(n - 1):
                a, b = r * n + c, r * n + c + 1
                worst = max(worst, np.abs(d[a] - d[b]).max())
        self.assertLess(worst, 0.35 * maxd)

    def test_landmarks_move_the_field(self):
        shifted = {"center": np.array([0.0, 0.3, 0.0]), "width": WIDTH}
        t2, _ = viseme_authoring.author_visemes(self.pos, landmarks=shifted)
        d2 = _by_name(t2)["aa"]
        mag = np.abs(self.t["aa"]).max(axis=1)
        mag2 = np.abs(d2).max(axis=1)
        c1 = float((self.pos[:, 1] * mag).sum() / mag.sum())
        c2 = float((self.pos[:, 1] * mag2).sum() / mag2.sum())
        self.assertAlmostEqual(c2 - c1, 0.3, delta=0.06)

    def test_deterministic(self):
        again, _ = viseme_authoring.author_visemes(self.pos, landmarks=LM)
        for a, b in zip(self.targets, again):
            self.assertTrue(np.array_equal(a["position"], b["position"]))

    def test_glb_round_trip(self):
        import glb_exporter
        glb = glb_exporter.build_glb(
            self.pos, self.idx, morph_targets=self.targets)
        gltf, binb = glb_exporter.parse_glb(glb)
        prim = gltf["meshes"][0]["primitives"][0]
        self.assertEqual(len(prim["targets"]), 15)
        back = glb_exporter.read_accessor(
            gltf, binb, prim["targets"][10]["POSITION"])  # aa
        np.testing.assert_allclose(
            back, self.t["aa"].astype(np.float32), atol=1e-6)


class EstimatorTests(unittest.TestCase):
    BUST = os.path.expanduser("~/workspace/bio-3d/aries-bust-clay-v3.glb")

    @unittest.skipUnless(os.path.isfile(BUST), "local demo bust not present")
    def test_estimator_finds_the_fixture_mouth(self):
        import glb_exporter
        with open(self.BUST, "rb") as f:
            gltf, binb = glb_exporter.parse_glb(f.read())
        prim = gltf["meshes"][0]["primitives"][0]
        pos = glb_exporter.read_accessor(
            gltf, binb, prim["attributes"]["POSITION"]).astype(np.float64)
        lm, report = viseme_authoring.locate_mouth(pos)
        # The hand-tuned fixture center (frontend/verify) is
        # (0, -0.35, 0.55); the estimate must land on the mouth.
        self.assertLessEqual(abs(lm["center"][0]), 0.08)
        self.assertLessEqual(abs(lm["center"][1] + 0.35), 0.10)
        self.assertLessEqual(abs(lm["center"][2] - 0.55), 0.05)
        self.assertTrue(0.3 <= lm["width"] <= 0.55)
        self.assertIn("face_band", report)


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import app as app_module
        cls.client = TestClient(app_module.app)
        cls.pos, cls.idx = _grid()

    def _npz(self):
        buf = io.BytesIO()
        np.savez(buf, positions=self.pos.astype(np.float32),
                 indices=self.idx)
        return buf.getvalue()

    def test_author_endpoint_round_trip(self):
        r = self.client.post(
            "/api/mesh-author-visemes",
            files={"mesh": ("m.npz", self._npz())},
            data={"landmarks": json.dumps(
                {"center": [0.0, 0.0, 0.0], "width": WIDTH})})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(json.loads(r.headers["X-SculptViseme-Landmarks"]),
                         {"center": [0.0, 0.0, 0.0], "width": WIDTH})
        out = np.load(io.BytesIO(r.content))
        self.assertEqual([str(n) for n in out["morph_names"].tolist()],
                         list(lipsync_align.VISEMES))
        self.assertTrue(np.all(out["morph_0"] == 0))  # sil
        self.assertGreater(np.abs(out["morph_10"]).max(), 0.0)  # aa
        # The authored NPZ feeds /api/mesh-glb unchanged.
        r2 = self.client.post(
            "/api/mesh-glb",
            files={"mesh": ("m.npz", r.content)})
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.content[:4], b"glTF")

    def test_bad_landmarks_rejected(self):
        r = self.client.post(
            "/api/mesh-author-visemes",
            files={"mesh": ("m.npz", self._npz())},
            data={"landmarks": "{\"center\": [0, 0]}"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
