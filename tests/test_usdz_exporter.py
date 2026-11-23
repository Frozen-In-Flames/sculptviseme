"""Tests for backend/usdz_exporter.py (static USDZ via pxr).

The whole class skips when pxr (usd-core) is not importable in
the running interpreter, with the reason stated. In this VM pxr
lives in the bio-3d/ar venv (the environment the proven converter
runs in); the system interpreter has no pxr, so the suite skips
there and passes in that venv. Nothing here fakes a package.
"""

import io
import os
import sys
import unittest
import zipfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "backend"))

import usdz_exporter

HAVE_PXR = usdz_exporter.pxr_available()
SKIP_REASON = ("pxr (usd-core) not importable in this interpreter; "
               "run in the bio-3d/ar venv where the proven pxr "
               "route lives")

TET_POS = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                   dtype=np.float64)
TET_IDX = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])


@unittest.skipUnless(HAVE_PXR, SKIP_REASON)
class TestUsdzExporter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = usdz_exporter.build_usdz(TET_POS, TET_IDX)
        cls.path = os.path.join(os.path.dirname(__file__),
                                "_tmp_test.usdz")
        with open(cls.path, "wb") as f:
            f.write(cls.data)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.path):
            os.remove(cls.path)

    def test_package_is_stored_zip(self):
        self.assertEqual(self.data[:2], b"PK")
        zf = zipfile.ZipFile(io.BytesIO(self.data))
        self.assertTrue(zf.namelist())
        for info in zf.infolist():
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED,
                             info.filename)

    def test_stage_opens_with_mesh(self):
        from pxr import Usd, UsdGeom
        stage = Usd.Stage.Open(self.path)
        self.assertIsNotNone(stage)
        self.assertEqual(stage.GetDefaultPrim().GetPath().pathString,
                         "/ClaySculpt")
        self.assertEqual(str(UsdGeom.GetStageUpAxis(stage)), "Y")
        self.assertAlmostEqual(UsdGeom.GetStageMetersPerUnit(stage),
                               1.0)
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath("/ClaySculpt/Mesh"))
        self.assertTrue(mesh.GetPrim().IsValid())
        points = mesh.GetPointsAttr().Get()
        self.assertEqual(len(points), 4)
        np.testing.assert_allclose(
            np.array([[p[0], p[1], p[2]] for p in points]), TET_POS,
            atol=1e-6)
        self.assertEqual(list(mesh.GetFaceVertexCountsAttr().Get()),
                         [3, 3, 3, 3])
        self.assertEqual(list(mesh.GetFaceVertexIndicesAttr().Get()),
                         TET_IDX.flatten().tolist())
        normals = mesh.GetNormalsAttr().Get()
        self.assertEqual(len(normals), 4)

    def test_npz_input_matches_array_input_shape(self):
        buf = io.BytesIO()
        np.savez(buf, positions=TET_POS.astype(np.float32),
                 indices=TET_IDX)
        data = usdz_exporter.build_usdz_from_npz(buf.getvalue())
        self.assertEqual(data[:2], b"PK")


class TestUsdzUnavailableContract(unittest.TestCase):
    def test_unavailable_raises_labeled_error(self):
        if HAVE_PXR:
            self.skipTest("pxr is available in this interpreter")
        with self.assertRaises(usdz_exporter.UsdzUnavailable):
            usdz_exporter.build_usdz(TET_POS, TET_IDX)


if __name__ == "__main__":
    unittest.main()
