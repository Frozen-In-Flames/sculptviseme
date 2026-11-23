"""Tests for the self-written GLB packer.

Covers the container (header, chunk types, 4-byte alignment), the
sparse morph accessor structure, a full round trip through the
hand-rolled reader, the weights animation channel, and the size
claim from RESEARCH.md section 7 at bust scale: sparse morph
storage must be a small fraction of the dense cost (about 0.86 MB
per target at 71,524 vertices).

Run: python3 -m unittest tests.test_glb_exporter -v
"""

import os
import struct
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import glb_exporter as gx  # noqa: E402


def grid_mesh(nx, ny):
    """A flat grid: nx * ny vertices, two triangles per cell."""
    xs, ys = np.meshgrid(np.linspace(0, 1, nx), np.linspace(0, 1, ny))
    pos = np.stack([xs.ravel(), ys.ravel(),
                    np.zeros(nx * ny)], axis=1).astype(np.float32)
    faces = []
    for r in range(ny - 1):
        for c in range(nx - 1):
            a = r * nx + c
            b = a + 1
            d = a + nx
            e = d + 1
            faces.append([a, d, b])
            faces.append([b, d, e])
    return pos, np.array(faces, dtype=np.int64)


def small_fixture():
    pos, faces = grid_mesh(12, 10)  # 120 verts
    rng = np.random.default_rng(3)
    mouth = np.zeros_like(pos)
    rows = np.arange(40, 52)  # a small mouth region
    mouth[rows] = rng.normal(0, 0.01, (len(rows), 3)).astype(np.float32)
    jaw = np.zeros_like(pos)
    jaw[rows] = np.array([0.0, -0.02, 0.0], dtype=np.float32)
    targets = [{"name": "aa", "position": mouth},
               {"name": "PP", "position": jaw}]
    times = np.array([0.0, 0.1, 0.2], dtype=np.float32)
    weights = np.array([[0.0, 0.0], [0.9, 0.1], [0.2, 0.8]],
                       dtype=np.float32)
    return pos, faces, targets, (times, weights), rows


class TestContainer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        pos, faces, targets, anim, _ = small_fixture()
        cls.data = gx.build_glb(pos, faces, morph_targets=targets,
                                weights_animation=anim)
        cls.gltf, cls.bin_data = gx.parse_glb(cls.data)

    def test_header(self):
        self.assertEqual(self.data[:4], b"glTF")
        version, total = struct.unpack("<II", self.data[4:12])
        self.assertEqual(version, 2)
        self.assertEqual(total, len(self.data))

    def test_chunk_types_and_buffer_length(self):
        jlen, jtype = struct.unpack("<I4s", self.data[12:20])
        self.assertEqual(jtype, b"JSON")
        off = 20 + jlen
        blen, btype = struct.unpack("<I4s", self.data[off:off + 8])
        self.assertEqual(btype, b"BIN\x00")
        self.assertEqual(self.gltf["buffers"][0]["byteLength"],
                         len(self.bin_data))
        self.assertLessEqual(off + 8 + blen, len(self.data))

    def test_all_buffer_views_aligned(self):
        for view in self.gltf["bufferViews"]:
            self.assertEqual(view["byteOffset"] % 4, 0,
                             f"unaligned bufferView {view}")


class TestRoundTrip(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.pos, cls.faces, cls.targets, cls.anim, cls.rows = \
            small_fixture()
        cls.data = gx.build_glb(cls.pos, cls.faces,
                                morph_targets=cls.targets,
                                weights_animation=cls.anim)
        cls.gltf, cls.bin_data = gx.parse_glb(cls.data)
        cls.prim = cls.gltf["meshes"][0]["primitives"][0]

    def test_positions_normals_indices(self):
        pos = gx.read_accessor(self.gltf, self.bin_data,
                               self.prim["attributes"]["POSITION"])
        self.assertTrue(np.array_equal(pos, self.pos))
        nrm = gx.read_accessor(self.gltf, self.bin_data,
                               self.prim["attributes"]["NORMAL"])
        self.assertEqual(nrm.shape, self.pos.shape)
        lens = np.linalg.norm(nrm.astype(np.float64), axis=1)
        self.assertTrue(np.allclose(lens, 1.0, atol=1e-5))
        idx = gx.read_accessor(self.gltf, self.bin_data,
                               self.prim["indices"])
        self.assertTrue(np.array_equal(
            idx.reshape(-1, 3).astype(np.int64), self.faces))

    def test_sparse_morph_structure_and_values(self):
        for t_i, target in enumerate(self.targets):
            acc_i = self.prim["targets"][t_i]["POSITION"]
            acc = self.gltf["accessors"][acc_i]
            self.assertIn("sparse", acc)
            self.assertEqual(acc["count"], len(self.pos))
            expected_nz = int(np.count_nonzero(
                np.any(target["position"] != 0, axis=1)))
            self.assertEqual(acc["sparse"]["count"], expected_nz)
            # glTF 2.0 spec shape: indices / values are objects
            # naming a bufferView, not accessor indices (Three.js
            # GLTFLoader rejects the accessor-index form).
            for part in ("indices", "values"):
                self.assertIsInstance(acc["sparse"][part], dict)
                self.assertIn("bufferView", acc["sparse"][part])
            self.assertIn("componentType", acc["sparse"]["indices"])
            self.assertNotIn("bufferView", acc)
            expanded = gx.read_accessor(self.gltf, self.bin_data, acc_i)
            self.assertTrue(np.array_equal(
                expanded, target["position"]))

    def test_target_names_and_default_weights(self):
        mesh = self.gltf["meshes"][0]
        self.assertEqual(mesh["extras"]["targetNames"], ["aa", "PP"])
        self.assertEqual(mesh["weights"], [0.0, 0.0])

    def test_weights_animation_channel(self):
        anim = self.gltf["animations"][0]
        channel = anim["channels"][0]
        self.assertEqual(channel["target"]["path"], "weights")
        self.assertEqual(channel["target"]["node"], 0)
        sampler = anim["samplers"][0]
        self.assertEqual(sampler["interpolation"], "LINEAR")
        times = gx.read_accessor(self.gltf, self.bin_data,
                                 sampler["input"]).reshape(-1)
        out = gx.read_accessor(self.gltf, self.bin_data,
                               sampler["output"]).reshape(-1)
        self.assertTrue(np.array_equal(times, self.anim[0]))
        self.assertEqual(len(out), len(self.anim[0]) * 2)
        self.assertTrue(np.array_equal(
            out.reshape(len(self.anim[0]), 2), self.anim[1]))

    def test_bad_morph_shape_raises(self):
        bad = [{"name": "x", "position": np.zeros((5, 3))}]
        with self.assertRaises(ValueError):
            gx.build_glb(self.pos, self.faces, morph_targets=bad)

    def test_bad_animation_shape_raises(self):
        with self.assertRaises(ValueError):
            gx.build_glb(self.pos, self.faces,
                         morph_targets=self.targets,
                         weights_animation=(np.zeros(3),
                                            np.zeros((3, 5))))


class TestSparseAtBustScale(unittest.TestCase):

    def test_sparse_beats_dense_at_71_5k_vertices(self):
        pos, faces = grid_mesh(268, 267)  # 71,556 vertices
        self.assertGreater(len(pos), 71000)
        delta = np.zeros_like(pos)
        mouth_rows = np.arange(30000, 30500)  # 500 touched vertices
        delta[mouth_rows, 1] = -0.02
        data = gx.build_glb(pos, faces, morph_targets=[
            {"name": "aa", "position": delta}])
        gltf, bin_data = gx.parse_glb(data)
        prim = gltf["meshes"][0]["primitives"][0]
        acc = gltf["accessors"][prim["targets"][0]["POSITION"]]
        self.assertEqual(acc["sparse"]["count"], 500)
        sparse = acc["sparse"]
        idx_view = gltf["bufferViews"][sparse["indices"]["bufferView"]]
        val_view = gltf["bufferViews"][sparse["values"]["bufferView"]]
        sparse_bytes = idx_view["byteLength"] + val_view["byteLength"]
        dense_bytes = len(pos) * 12  # float32 VEC3 per vertex
        self.assertLess(sparse_bytes, 0.05 * dense_bytes,
                        f"sparse {sparse_bytes} vs dense {dense_bytes}")
        expanded = gx.read_accessor(gltf, bin_data,
                                    prim["targets"][0]["POSITION"])
        self.assertTrue(np.array_equal(expanded, delta))


if __name__ == "__main__":
    unittest.main()
