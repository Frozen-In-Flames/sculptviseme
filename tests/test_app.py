"""Smoke tests for backend/app.py using FastAPI's TestClient.

Skips cleanly when FastAPI is not installed in the running
interpreter (it is not a system package in this VM; the suite was
run in a venv with fastapi + httpx installed, see BUILD-LOG.md).
"""

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import wave
import zipfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "backend"))

try:
    import fastapi  # noqa: F401
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:
    HAVE_FASTAPI = False

_TMP = tempfile.mkdtemp()
os.environ["CSS_JOBS_DIR"] = os.path.join(_TMP, "jobs")


def _sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _wav_bytes(seconds=0.3, sr=16000):
    t = np.arange(int(seconds * sr)) / sr
    samples = (0.4 * np.sin(2 * np.pi * 220 * t) * 32767)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.astype("<i2").tobytes())
    return buf.getvalue()


def _bundle_zip():
    """A minimal valid Regime B bundle as zip bytes."""
    from PIL import Image
    files = {}
    for name in ("frame_front.jpg", "frame_left.jpg",
                 "frame_right.jpg"):
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (200, 180, 160)).save(buf, "JPEG")
        files[f"capture/{name}"] = buf.getvalue()
    wav = _wav_bytes()
    files["words/word_000_hello.wav"] = wav
    words = {"words": [{"index": 0, "text": "hello",
                        "clip": "word_000_hello.wav",
                        "sample_rate_hz": 16000, "channels": 1,
                        "sha256": _sha_bytes(wav)}]}
    files["words.json"] = json.dumps(words).encode()
    manifest = {"bundle_version": "0.1.0", "regime": "B",
                "subject": "smoke", "created_utc": "2026-11-20T00:00:00Z",
                "capture": {"device": "test",
                            "front_camera_mirrored": False},
                "words_file": "words.json",
                "provenance": {"source": "test", "consent": "test",
                               "tool": "test"},
                "hashes": {k: _sha_bytes(v) for k, v in files.items()}}
    files["manifest.json"] = json.dumps(manifest).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return out.getvalue()


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class TestApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as app_module
        cls.client = TestClient(app_module.app)

    def test_health_and_index(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("SculptViseme", r.text)

    def test_bundle_to_lipsync_to_glb(self):
        r = self.client.post(
            "/api/bundles",
            files={"bundle": ("b.claybundle.zip", _bundle_zip(),
                              "application/zip")})
        self.assertEqual(r.status_code, 200, r.text)
        job_id = r.json()["job_id"]

        r = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["regime"], "B")

        r = self.client.post(f"/api/jobs/{job_id}/lipsync")
        self.assertEqual(r.status_code, 200, r.text)
        doc = r.json()
        self.assertEqual(doc["format"],
                         "clay-sculpt-studio/viseme-keyframes")
        self.assertEqual(doc["words"][0]["text"], "hello")
        self.assertTrue(doc["frames"])

        # Pack a tiny mesh whose morph names match the keyframes
        # viseme order; the keyframes become the weights animation.
        import lipsync_align
        names = list(lipsync_align.VISEMES)
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                       dtype=np.float32)
        idx = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
        fields = {"positions": pos, "indices": idx,
                  "morph_names": np.array(names)}
        for i in range(len(names)):
            d = np.zeros_like(pos)
            d[3] = (0.0, 0.0, 0.05)
            fields[f"morph_{i}"] = d
        npz = io.BytesIO()
        np.savez(npz, **fields)
        r = self.client.post(
            "/api/mesh-glb",
            files={"mesh": ("mesh.npz", npz.getvalue()),
                   "keyframes": ("keyframes.json",
                                  json.dumps(doc).encode(),
                                  "application/json")})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.content[:4], b"glTF")

    def _tet_npz(self):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                       dtype=np.float32)
        idx = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
        buf = io.BytesIO()
        np.savez(buf, positions=pos, indices=idx)
        return buf.getvalue()

    def test_mesh_stl_and_glb_stl(self):
        import struct
        npz = self._tet_npz()
        r = self.client.post(
            "/api/mesh-stl",
            files={"mesh": ("mesh.npz", npz)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.content), 80 + 4 + 4 * 50)
        (count,) = struct.unpack_from("<I", r.content, 80)
        self.assertEqual(count, 4)
        self.assertEqual(r.headers["x-stl-triangles"], "4")
        self.assertEqual(r.headers["x-stl-degenerate-triangles"], "0")

        r = self.client.post(
            "/api/mesh-glb",
            files={"mesh": ("mesh.npz", npz)})
        self.assertEqual(r.status_code, 200, r.text)
        r2 = self.client.post(
            "/api/glb-stl",
            files={"mesh": ("mesh.glb", r.content,
                            "model/gltf-binary")})
        self.assertEqual(r2.status_code, 200, r2.text)
        (count2,) = struct.unpack_from("<I", r2.content, 80)
        self.assertEqual(count2, 4)
        self.assertEqual(len(r2.content), 80 + 4 + 4 * 50)

    def test_mesh_usdz_status_matches_pxr_availability(self):
        import usdz_exporter
        npz = self._tet_npz()
        r = self.client.post(
            "/api/mesh-usdz",
            files={"mesh": ("mesh.npz", npz)})
        if usdz_exporter.pxr_available():
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.content[:2], b"PK")
        else:
            # Honest 501 with the reason, never a fake package.
            self.assertEqual(r.status_code, 501, r.text)
            self.assertIn("pxr", r.json()["detail"])

    def test_invalid_bundle_422_with_report(self):
        r = self.client.post(
            "/api/bundles",
            files={"bundle": ("bad.zip", b"not a zip",
                              "application/zip")})
        self.assertEqual(r.status_code, 422)
        self.assertFalse(r.json()["ok"])
        self.assertIn("report", r.json())

    def test_unknown_job_404(self):
        r = self.client.get("/api/jobs/job-nope")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
