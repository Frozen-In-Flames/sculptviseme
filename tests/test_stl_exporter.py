"""Tests for backend/stl_exporter.py (binary STL writer).

Fixtures are small meshes whose face normals are known exactly:
a tetrahedron and a tilted plane (the plane z = x, whose unit
normal is (-1, 0, 1) / sqrt(2) for the winding used here).
"""

import io
import os
import struct
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "backend"))

import stl_exporter

# Tetrahedron, same winding as the app smoke tests.
TET_POS = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                   dtype=np.float64)
TET_IDX = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])


class TestStlExporter(unittest.TestCase):
    def test_header_and_count_fields(self):
        data = stl_exporter.build_stl(TET_POS, TET_IDX)
        self.assertEqual(len(data), 80 + 4 + 4 * 50)
        self.assertEqual(data[:80], b"\x00" * 80)
        (count,) = struct.unpack_from("<I", data, 80)
        self.assertEqual(count, 4)

    def test_attribute_byte_counts_are_zero(self):
        parsed = stl_exporter.parse_stl(
            stl_exporter.build_stl(TET_POS, TET_IDX))
        self.assertTrue(np.all(parsed["attribute_byte_counts"] == 0))

    def test_tetrahedron_normals_exact(self):
        parsed = stl_exporter.parse_stl(
            stl_exporter.build_stl(TET_POS, TET_IDX))
        # Face [0, 2, 1]: (0,1,0) x (1,0,0) normalized is (0,0,-1).
        np.testing.assert_allclose(parsed["normals"][0], [0, 0, -1],
                                   atol=1e-6)
        # Face [0, 1, 3]: (1,0,0) x (0,0,1) normalized is (0,-1,0).
        np.testing.assert_allclose(parsed["normals"][1], [0, -1, 0],
                                   atol=1e-6)
        # Every normal is a unit vector on this mesh.
        lens = np.linalg.norm(parsed["normals"], axis=1)
        np.testing.assert_allclose(lens, np.ones(4), atol=1e-6)

    def test_tilted_plane_normal(self):
        # Quad in the plane z = x, split along the 0-2 diagonal.
        pos = np.array([[0, 0, 0], [1, 0, 1], [1, 1, 1], [0, 1, 0]],
                       dtype=np.float64)
        idx = np.array([[0, 1, 2], [0, 2, 3]])
        parsed = stl_exporter.parse_stl(stl_exporter.build_stl(pos, idx))
        expected = np.array([-1.0, 0.0, 1.0]) / np.sqrt(2.0)
        np.testing.assert_allclose(parsed["normals"],
                                   [expected, expected], atol=1e-6)

    def test_round_trip_vertices(self):
        data = stl_exporter.build_stl(TET_POS, TET_IDX)
        parsed = stl_exporter.parse_stl(data)
        self.assertEqual(parsed["count"], 4)
        np.testing.assert_allclose(parsed["triangles"],
                                   TET_POS[TET_IDX], atol=1e-7)

    def test_degenerate_triangles_labeled_not_dropped(self):
        # One collinear (zero area) triangle appended to the tet.
        pos = np.vstack([TET_POS, [[2, 0, 0], [3, 0, 0]]])
        idx = np.vstack([TET_IDX, [[1, 4, 5]]])
        data, report = stl_exporter.build_stl_report(pos, idx)
        self.assertEqual(report["triangles"], 5)
        self.assertEqual(report["degenerate_triangles"], 1)
        parsed = stl_exporter.parse_stl(data)
        self.assertEqual(parsed["count"], 5)
        np.testing.assert_allclose(parsed["normals"][4], [0, 0, 0],
                                   atol=1e-7)
        _n, mask = stl_exporter.face_normals(pos, idx)
        self.assertEqual(mask.tolist(), [False] * 4 + [True])

    def test_scale_applies_to_vertices_not_normals(self):
        data, report = stl_exporter.build_stl_report(
            TET_POS, TET_IDX, scale=1000.0)
        self.assertEqual(report["scale"], 1000.0)
        parsed = stl_exporter.parse_stl(data)
        np.testing.assert_allclose(parsed["triangles"],
                                   TET_POS[TET_IDX] * 1000.0,
                                   atol=1e-3)
        np.testing.assert_allclose(parsed["normals"][0], [0, 0, -1],
                                   atol=1e-6)

    def test_npz_input_matches_array_input(self):
        buf = io.BytesIO()
        np.savez(buf, positions=TET_POS.astype(np.float32),
                 indices=TET_IDX)
        self.assertEqual(stl_exporter.build_stl_from_npz(buf.getvalue()),
                         stl_exporter.build_stl(TET_POS, TET_IDX))

    def test_shape_errors_raise(self):
        with self.assertRaises(ValueError):
            stl_exporter.build_stl(np.zeros((4, 2)), TET_IDX)
        with self.assertRaises(ValueError):
            stl_exporter.build_stl(TET_POS, np.array([[0, 1, 9]]))
        with self.assertRaises(ValueError):
            stl_exporter.parse_stl(b"\x00" * 100)


if __name__ == "__main__":
    unittest.main()
