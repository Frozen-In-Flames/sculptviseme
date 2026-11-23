"""Tests for backend/bundle_loader.py (RESEARCH.md section 10).

Fixtures are built as real bundle directories with correct SHA-256
records, then mutated per test. Video fixtures use ffmpeg (present
in this VM); that test skips if ffmpeg is absent.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "backend"))
import bundle_loader  # noqa: E402


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _write_wav(path, seconds=0.3, sr=16000, freq=220.0):
    t = np.arange(int(seconds * sr)) / sr
    samples = (0.4 * np.sin(2 * np.pi * freq * t) * 32767)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.astype("<i2").tobytes())


def _write_image(path, size=(64, 48), left=(0, 0, 0),
                 right=(255, 255, 255)):
    im = Image.new("RGB", size)
    px = im.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = left if x < size[0] // 2 else right
    im.save(path)


def _finalize(root, manifest):
    """Compute the hashes record over every file and write manifest."""
    hashes = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if rel != "manifest.json":
                hashes[rel] = _sha(p)
    manifest["hashes"] = hashes
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump(manifest, f)
    return manifest


def _base_manifest(regime, **kw):
    m = {"bundle_version": "0.1.0", "regime": regime,
         "subject": "test subject",
         "created_utc": "2026-11-20T00:00:00Z",
         "capture": {"device": "test", "front_camera_mirrored": False},
         "provenance": {"source": "test", "consent": "test",
                        "tool": "test"}}
    m.update(kw)
    return m


def _add_words(root, words=(("hello", "word_000_hello.wav"),)):
    wdir = os.path.join(root, "words")
    os.makedirs(wdir, exist_ok=True)
    entries = []
    for i, (text, name) in enumerate(words):
        p = os.path.join(wdir, name)
        _write_wav(p)
        entries.append({"index": i, "text": text, "clip": name,
                        "sample_rate_hz": 16000, "channels": 1,
                        "sha256": _sha(p)})
    with open(os.path.join(root, "words.json"), "w") as f:
        json.dump({"words": entries}, f)
    return "words.json"


class BundleCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "bundle")
        self.jobs = os.path.join(self.tmp, "jobs")
        os.makedirs(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self):
        return bundle_loader.validate_and_load(self.root, self.jobs)


@unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg absent")
class TestRegimeA(BundleCase):
    def _build(self, mirrored=False, frames=30):
        cap = os.path.join(self.root, "capture")
        os.makedirs(cap)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             f"testsrc=size=64x64:rate=30:duration={frames / 30}",
             os.path.join(cap, "video.mp4")],
            check=True, capture_output=True)
        words_file = _add_words(self.root)
        m = _base_manifest("A", words_file=words_file)
        m["capture"]["front_camera_mirrored"] = mirrored
        _finalize(self.root, m)

    def test_valid_orbit_video(self):
        self._build()
        out = self.load()
        self.assertEqual(out["regime"], "A")
        self.assertTrue(out["job_id"].startswith("job-"))
        self.assertTrue(os.path.isfile(out["manifest_path"]))
        self.assertGreaterEqual(out["capture"]["probe"]["frames"], 24)
        self.assertEqual(len(out["words"]), 1)
        # No intrinsics supplied: estimated, and labeled as such.
        self.assertTrue(out["camera"]["estimated"])

    def test_short_video_rejected(self):
        self._build(frames=10)
        with self.assertRaises(bundle_loader.BundleError) as ctx:
            self.load()
        names = [c["name"] for c in ctx.exception.report["checks"]
                 if not c["ok"]]
        self.assertIn("orbit frame count", names)

    def test_mirrored_video_normalized(self):
        self._build(mirrored=True)
        out = self.load()
        rec = out["subject_frame"]["mirror_normalization"]
        self.assertTrue(rec["un_mirrored_on_ingest"])
        flipped = out["files"]["capture/video.mp4"]
        self.assertIn("normalized", flipped)
        self.assertTrue(os.path.isfile(flipped))


class TestRegimeB(BundleCase):
    def _build(self, mirrored=False, with_K=True, device="iphone"):
        cap = os.path.join(self.root, "capture")
        os.makedirs(cap)
        for name in ("frame_front.jpg", "frame_left.jpg",
                     "frame_right.jpg"):
            _write_image(os.path.join(cap, name))
        words_file = _add_words(self.root)
        m = _base_manifest("B", words_file=words_file)
        m["capture"]["device"] = device
        m["capture"]["front_camera_mirrored"] = mirrored
        if with_K:
            m["camera"] = {"intrinsics_K": [[55.0, 0, 32],
                                            [0, 55.0, 24],
                                            [0, 0, 1]]}
        _finalize(self.root, m)

    def test_valid_photo_set(self):
        self._build()
        out = self.load()
        self.assertEqual(out["regime"], "B")
        self.assertFalse(out["camera"]["estimated"])
        self.assertEqual(out["capture"]["coverage"]["missing"], [])

    def test_android_rgb_only_accepted(self):
        # Android bundles are RGB photos only: no depth, no poses.
        self._build(device="android")
        out = self.load()
        self.assertEqual(out["regime"], "B")
        self.assertEqual(out["capture"]["device"], "android")

    def test_missing_intrinsics_estimated(self):
        self._build(with_K=False)
        out = self.load()
        self.assertTrue(out["camera"]["estimated"])
        K = out["camera"]["intrinsics_K"]
        self.assertEqual(K[0][2], 32.0)  # principal point = center
        self.assertTrue(any("estimated" in w for w in
                            out["validation"]["warnings"]))

    def test_mirror_normalization_flips_pixels(self):
        self._build(mirrored=True)
        out = self.load()
        flipped = out["files"]["capture/frame_front.jpg"]
        self.assertIn("normalized", flipped)
        with Image.open(flipped) as im:
            px = im.load()
            # Source: left half black, right half white. After the
            # un-mirror flip, left is white and right is black.
            self.assertEqual(px[2, 24], (255, 255, 255))
            self.assertEqual(px[61, 24], (0, 0, 0))
        rec = out["subject_frame"]["mirror_normalization"]
        self.assertTrue(rec["un_mirrored_on_ingest"])

    def test_corrupt_hash_rejected(self):
        self._build()
        p = os.path.join(self.root, "capture", "frame_front.jpg")
        with open(p, "ab") as f:
            f.write(b"tamper")
        with self.assertRaises(bundle_loader.BundleError) as ctx:
            self.load()
        self.assertIn("hashes match",
                      [c["name"] for c in
                       ctx.exception.report["checks"] if not c["ok"]])

    def test_corrupt_image_rejected(self):
        cap = os.path.join(self.root, "capture")
        os.makedirs(cap)
        for name in ("frame_front.jpg", "frame_left.jpg",
                     "frame_right.jpg"):
            with open(os.path.join(cap, name), "wb") as f:
                f.write(b"this is not a jpeg at all")
        _finalize(self.root, _base_manifest("B"))
        with self.assertRaises(bundle_loader.BundleError):
            self.load()

    def test_two_word_clip_rejected(self):
        cap = os.path.join(self.root, "capture")
        os.makedirs(cap)
        for name in ("frame_front.jpg", "frame_left.jpg",
                     "frame_right.jpg"):
            _write_image(os.path.join(cap, name))
        words_file = _add_words(
            self.root, (("hello world", "word_000_hello_world.wav"),))
        _finalize(self.root, _base_manifest("B",
                                            words_file=words_file))
        with self.assertRaises(bundle_loader.BundleError):
            self.load()

    def test_mixed_regime_rejected(self):
        self._build()
        # Add a video file (Regime A material) and re-hash so the
        # hash checks pass; the regime check must still reject it.
        with open(os.path.join(self.root, "capture", "video.mp4"),
                  "wb") as f:
            f.write(b"fake")
        with open(os.path.join(self.root, "manifest.json")) as f:
            m = json.load(f)
        _finalize(self.root, m)
        with self.assertRaises(bundle_loader.BundleError) as ctx:
            self.load()
        self.assertIn("exactly one regime present",
                      [c["name"] for c in
                       ctx.exception.report["checks"] if not c["ok"]])


class TestRegimeC(BundleCase):
    def _build(self, with_pose_for_second=True, with_K=True):
        rgbd = os.path.join(self.root, "capture", "rgbd")
        os.makedirs(rgbd)
        frames = []
        for i in (1, 2):
            name = f"frame_{i:04d}.jpg"
            _write_image(os.path.join(rgbd, name), size=(32, 24))
            depth = np.arange(32 * 24, dtype=np.uint16).reshape(24, 32)
            # uint16 maps to mode I;16; naming the mode explicitly
            # is rejected by newer Pillow versions.
            Image.fromarray(depth).save(
                os.path.join(rgbd, f"frame_{i:04d}_depth.png"))
            if i == 1 or with_pose_for_second:
                frames.append({
                    "file": name,
                    "R": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    "t": [0.0, 0.0, 1.0], "confidence": 0.9})
        with open(os.path.join(rgbd, "poses.json"), "w") as f:
            json.dump({"frames": frames}, f)
        m = _base_manifest("C")
        if with_K:
            m["camera"] = {"intrinsics_K": [[28.0, 0, 16],
                                            [0, 28.0, 12],
                                            [0, 0, 1]]}
        _finalize(self.root, m)

    def test_valid_rgbd(self):
        self._build()
        out = self.load()
        self.assertEqual(out["regime"], "C")
        self.assertEqual(len(out["capture"]["kept_frames"]), 2)
        self.assertEqual(out["capture"]["dropped_frames"], [])

    def test_frame_without_pose_dropped(self):
        self._build(with_pose_for_second=False)
        out = self.load()
        self.assertEqual(len(out["capture"]["kept_frames"]), 1)
        dropped = out["capture"]["dropped_frames"]
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["file"], "frame_0002.jpg")

    def test_rgbd_requires_true_intrinsics(self):
        self._build(with_K=False)
        with self.assertRaises(bundle_loader.BundleError):
            self.load()


class TestZipSource(BundleCase):
    def test_zip_bundle_loads(self):
        cap = os.path.join(self.root, "capture")
        os.makedirs(cap)
        for name in ("frame_front.jpg", "frame_left.jpg",
                     "frame_right.jpg"):
            _write_image(os.path.join(cap, name))
        _finalize(self.root, _base_manifest("B"))
        zip_path = os.path.join(self.tmp, "bundle.claybundle.zip")
        shutil.make_archive(zip_path[:-4], "zip", self.root)
        out = bundle_loader.validate_and_load(zip_path, self.jobs)
        self.assertEqual(out["regime"], "B")


if __name__ == "__main__":
    unittest.main()
