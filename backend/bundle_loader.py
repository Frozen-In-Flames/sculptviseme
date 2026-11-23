"""Capture bundle ingestion and validation (RESEARCH.md section 10).

One bundle, one manifest, three regimes:

  A - orbit video:   capture/video.mp4
  B - photo set:     capture/frame_XXXX.jpg ...
  C - RGB-D:         capture/rgbd/frame_XXXX.jpg plus a 16-bit
                     frame_XXXX_depth.png and poses.json per frame

Exactly one regime per bundle; mixed bundles are rejected. Every
file in the bundle must be listed in manifest["hashes"] with a
matching SHA-256 (the Voice Asset Format provenance rule: a package
without a complete hash record is not valid). The one exception is
manifest.json itself, which cannot carry its own hash.

The loader:
  - validates file integrity (hashes, decodability) and camera
    intrinsics where present (estimated from frame size when
    unknown, and recorded as estimated, never assumed),
  - normalizes front-camera mirror transforms on ingest (images
    flipped, video hflipped through ffmpeg, Regime C poses
    conjugated by the mirror), and records that it happened,
  - assigns a local job ID and writes a normalized bundle manifest
    JSON into the job directory.

Pure Python plus stdlib, NumPy, and Pillow. ffmpeg / ffprobe are
used as subprocesses for Regime A video checks when present. No
network, no external APIs, no auth.
"""

import hashlib
import json
import math
import os
import shutil
import subprocess
import uuid
import wave
from datetime import datetime, timezone

import numpy as np
from PIL import Image

BUNDLE_VERSION = "0.1.0"
MIN_ORBIT_FRAMES = 24
MAX_WORD_SANITY_S = 5.0
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
_MIRROR = np.diag([-1.0, 1.0, 1.0])


class BundleError(Exception):
    """Raised when a bundle fails validation; carries the report."""

    def __init__(self, report):
        self.report = report
        first = report["errors"][0] if report["errors"] else "invalid"
        super().__init__(f"bundle rejected: {first}")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check(report, name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok),
                             "detail": detail})
    if not ok:
        report["errors"].append(f"{name}: {detail}" if detail else name)
    return ok


def _warn(report, name, detail):
    report["warnings"].append(f"{name}: {detail}")


def _extract_source(source, work_dir):
    """Return the bundle root directory for a zip or a directory."""
    if os.path.isdir(source):
        return source
    if os.path.isfile(source) and source.lower().endswith(".zip"):
        import zipfile
        dest = os.path.join(work_dir, "bundle")
        with zipfile.ZipFile(source) as zf:
            for name in zf.namelist():
                if name.startswith("/") or ".." in name.split("/"):
                    raise ValueError(f"unsafe path in zip: {name}")
            zf.extractall(dest)
        return dest
    raise ValueError(f"source is neither a bundle directory nor a "
                     f".zip file: {source}")


def _ffprobe(path):
    """Return ffprobe JSON for a media file, or None if unavailable."""
    if shutil.which("ffprobe") is None:
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, timeout=60)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout.decode())
    except Exception:
        return None


def _estimate_intrinsics(width, height):
    """Pinhole estimate from frame size at a nominal 60 degree
    horizontal field of view. Recorded as estimated, never measured."""
    fx = width / (2.0 * math.tan(math.radians(30.0)))
    return [[fx, 0.0, width / 2.0],
            [0.0, fx, height / 2.0],
            [0.0, 0.0, 1.0]]


def _validate_intrinsics(raw):
    """Return (K, error_detail). K is a 3x3 list of floats."""
    try:
        K = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError):
        return None, "camera.intrinsics_K is not numeric"
    if K.shape != (3, 3):
        return None, f"camera.intrinsics_K has shape {K.shape}, " \
                     f"expected (3, 3)"
    if not np.all(np.isfinite(K)):
        return None, "camera.intrinsics_K contains non-finite values"
    if K[0, 0] <= 0 or K[1, 1] <= 0:
        return None, "camera.intrinsics_K focal lengths must be " \
                     "positive"
    if abs(K[2, 2] - 1.0) > 1e-6 or abs(K[2, 0]) > 1e-9 or \
            abs(K[2, 1]) > 1e-9:
        return None, "camera.intrinsics_K bottom row must be [0, 0, 1]"
    return K.tolist(), ""


def _image_size(path):
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        return im.size  # (width, height)


def _flip_image(src, dst):
    with Image.open(src) as im:
        im.transpose(Image.FLIP_LEFT_RIGHT).save(dst)


def _flip_video(src, dst):
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to un-mirror video")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", "hflip",
         "-c:a", "copy", dst], check=True, capture_output=True,
        timeout=600)


def _mirror_pose(R, t):
    """Conjugate a camera pose by the x-mirror: R' = M R M, t' = M t."""
    R = np.asarray(R, dtype=np.float64)
    t = np.asarray(t, dtype=np.float64)
    return (_MIRROR @ R @ _MIRROR).tolist(), (_MIRROR @ t).tolist()


def validate_and_load(source, jobs_root):
    """Validate a bundle and load it as a local job.

    source: path to a bundle directory or a .claybundle.zip file.
    jobs_root: directory under which the job directory is created.

    Returns the normalized bundle manifest (dict). Raises
    BundleError (carrying the full report) on any hard failure;
    a failed bundle never produces a job.
    """
    job_id = "job-" + uuid.uuid4().hex[:12]
    os.makedirs(jobs_root, exist_ok=True)
    job_dir = os.path.join(jobs_root, job_id)
    os.makedirs(job_dir)
    report = {"job_id": job_id, "ok": False, "checks": [],
              "errors": [], "warnings": [], "dropped_frames": []}
    try:
        root = _extract_source(source, job_dir)
        return _load(root, job_dir, job_id, report)
    except BundleError:
        raise
    except Exception as exc:  # unreadable zip, missing manifest, ...
        _check(report, "bundle readable", False, str(exc))
        raise BundleError(report)


def _load(root, job_dir, job_id, report):
    manifest_path = os.path.join(root, "manifest.json")
    if not os.path.isfile(manifest_path):
        _check(report, "manifest present", False,
               "manifest.json not found at bundle root")
        raise BundleError(report)
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    _check(report, "bundle_version",
           manifest.get("bundle_version") == BUNDLE_VERSION,
           f"expected {BUNDLE_VERSION}, got "
           f"{manifest.get('bundle_version')!r}")
    regime = manifest.get("regime")
    _check(report, "regime named", regime in ("A", "B", "C"),
           f"regime must be A, B, or C, got {regime!r}")
    if report["errors"]:
        raise BundleError(report)

    # ---- integrity: every file hashed, every hash matching -------
    hashes = manifest.get("hashes")
    if not isinstance(hashes, dict) or not hashes:
        _check(report, "hashes complete", False,
               "manifest.hashes is missing or empty")
        raise BundleError(report)
    on_disk = set()
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            rel = rel.replace(os.sep, "/")
            if rel != "manifest.json":
                on_disk.add(rel)
    listed = set(hashes.keys())
    _check(report, "hashes cover every file",
           listed == on_disk,
           "unlisted: %s; listed but absent: %s" % (
               sorted(on_disk - listed), sorted(listed - on_disk))
           if listed != on_disk else "")
    bad = [rel for rel in sorted(listed & on_disk)
           if _sha256_file(os.path.join(root, rel)) != hashes[rel]]
    _check(report, "hashes match", not bad,
           f"SHA-256 mismatch: {bad}" if bad else "")
    if report["errors"]:
        raise BundleError(report)

    capture = manifest.get("capture") or {}
    mirrored = bool(capture.get("front_camera_mirrored", False))
    norm_dir = os.path.join(job_dir, "normalized")
    normalized_files = {}  # bundle rel path -> usable local path

    def usable(rel):
        return normalized_files.get(rel, os.path.join(root, rel))

    # ---- regime file inventory: exactly one regime present -------
    cap_dir = os.path.join(root, "capture")
    video_rel = "capture/video.mp4"
    photo_rels = []
    rgbd_dir = os.path.join(cap_dir, "rgbd")
    rgbd_rgb, rgbd_depth = [], []
    if os.path.isdir(cap_dir):
        for name in sorted(os.listdir(cap_dir)):
            if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                photo_rels.append(f"capture/{name}")
    if os.path.isdir(rgbd_dir):
        for name in sorted(os.listdir(rgbd_dir)):
            low = name.lower()
            if low.endswith("_depth.png"):
                rgbd_depth.append(f"capture/rgbd/{name}")
            elif os.path.splitext(low)[1] in IMAGE_EXTS:
                rgbd_rgb.append(f"capture/rgbd/{name}")
    present = {"A": os.path.isfile(os.path.join(root, video_rel)),
               "B": bool(photo_rels),
               "C": bool(rgbd_rgb or rgbd_depth)}
    found = [r for r, p in present.items() if p]
    _check(report, "exactly one regime present", found == [regime],
           f"manifest declares {regime} but files present for "
           f"{found or 'none'}")
    if report["errors"]:
        raise BundleError(report)

    frame_size = None  # (width, height) of the primary capture

    # ---- Regime A: orbit video ------------------------------------
    if regime == "A":
        video_path = os.path.join(root, video_rel)
        probe = _ffprobe(video_path)
        if probe is None:
            _check(report, "video decodes", False,
                   "ffprobe could not read capture/video.mp4 (or "
                   "ffprobe is not installed)")
            raise BundleError(report)
        vstream = next((s for s in probe.get("streams", [])
                        if s.get("codec_type") == "video"), None)
        if vstream is None:
            _check(report, "video stream present", False,
                   "no video stream in capture/video.mp4")
            raise BundleError(report)
        num, _, den = (vstream.get("avg_frame_rate") or "0/1").partition("/")
        fps = float(num) / float(den) if float(den or 0) else 0.0
        duration = float(probe.get("format", {}).get("duration", 0.0))
        n_frames = int(vstream.get("nb_frames") or
                       round(fps * duration))
        _check(report, "orbit frame count", n_frames >= MIN_ORBIT_FRAMES,
               f"{n_frames} frames, minimum is {MIN_ORBIT_FRAMES}")
        frame_size = (int(vstream["width"]), int(vstream["height"]))
        report["capture_probe"] = {
            "fps": fps, "duration_s": duration, "frames": n_frames,
            "width": frame_size[0], "height": frame_size[1],
            "span_note": "frame count checked; 360 degree span is "
                         "not measurable by the validator"}
        if mirrored:
            dst = os.path.join(norm_dir, "video.mp4")
            os.makedirs(norm_dir, exist_ok=True)
            try:
                _flip_video(video_path, dst)
                normalized_files[video_rel] = dst
            except Exception as exc:
                _check(report, "mirror normalization", False, str(exc))
                raise BundleError(report)

    # ---- Regime B: photo set --------------------------------------
    if regime == "B":
        for rel in photo_rels:
            try:
                size = _image_size(os.path.join(root, rel))
                if frame_size is None:
                    frame_size = size
            except Exception as exc:
                _check(report, f"photo decodes {rel}", False, str(exc))
        _check(report, "photo count", len(photo_rels) >= 3,
               f"{len(photo_rels)} photos, minimum is 3")
        # Coverage in v1 is read from filename hints (front / left /
        # right / back tokens). It is a report, not a vision result.
        hints = {"front": False, "left": False, "right": False,
                 "back": False}
        for rel in photo_rels:
            name = os.path.basename(rel).lower()
            for token in hints:
                if token in name:
                    hints[token] = True
        missing = [t for t in ("front", "left", "right")
                   if not hints[t]]
        report["coverage"] = {
            "basis": "filename hints (v1; not a vision measurement)",
            "found": [t for t, v in hints.items() if v],
            "missing": missing}
        if missing:
            _warn(report, "coverage",
                  f"no photo filename hints at: {missing}")
        if mirrored:
            os.makedirs(norm_dir, exist_ok=True)
            for rel in photo_rels:
                dst = os.path.join(norm_dir, os.path.basename(rel))
                _flip_image(os.path.join(root, rel), dst)
                normalized_files[rel] = dst

    # ---- Regime C: pre-captured RGB-D ------------------------------
    poses = {}
    if regime == "C":
        poses_rel = "capture/rgbd/poses.json"
        poses_path = os.path.join(root, poses_rel)
        if not os.path.isfile(poses_path):
            _check(report, "poses present", False,
                   "capture/rgbd/poses.json is missing")
            raise BundleError(report)
        with open(poses_path, "r", encoding="utf-8") as f:
            poses_doc = json.load(f)
        for entry in poses_doc.get("frames", []):
            poses[entry["file"]] = entry
        depth_set = set(rgbd_depth)
        kept = []
        for rel in rgbd_rgb:
            base = os.path.basename(rel)
            depth_rel = f"capture/rgbd/{base.rsplit('.', 1)[0]}" \
                        f"_depth.png"
            entry = poses.get(base)
            if entry is None:
                report["dropped_frames"].append(
                    {"file": base, "reason": "no pose"})
                continue
            if depth_rel not in depth_set:
                _check(report, f"depth present {base}", False,
                       f"missing {depth_rel}")
                continue
            try:
                with Image.open(os.path.join(root, depth_rel)) as im:
                    is16 = im.mode in ("I;16", "I") or \
                        (im.format == "PNG" and
                         im.info.get("bitdepth") == 16)
                _check(report, f"depth is 16-bit {base}", is16,
                       "depth PNG is not 16-bit")
                size = _image_size(os.path.join(root, rel))
                if frame_size is None:
                    frame_size = size
            except Exception as exc:
                _check(report, f"rgbd frame decodes {base}", False,
                       str(exc))
                continue
            if "confidence" not in entry:
                _warn(report, "depth confidence",
                      f"{base} pose entry carries no confidence")
            kept.append(rel)
        _check(report, "rgbd kept frames", len(kept) >= 1,
               f"{len(kept)} frames kept, "
               f"{len(report['dropped_frames'])} dropped")
        report["kept_frames"] = kept
        if mirrored:
            os.makedirs(norm_dir, exist_ok=True)
            for rel in kept:
                dst = os.path.join(norm_dir, os.path.basename(rel))
                _flip_image(os.path.join(root, rel), dst)
                normalized_files[rel] = dst
                base = os.path.basename(rel)
                depth_rel = f"capture/rgbd/" \
                            f"{base.rsplit('.', 1)[0]}_depth.png"
                ddst = os.path.join(
                    norm_dir, os.path.basename(depth_rel))
                _flip_image(os.path.join(root, depth_rel), ddst)
                normalized_files[depth_rel] = ddst
                R, t = _mirror_pose(poses[base]["R"], poses[base]["t"])
                poses[base] = {**poses[base], "R": R, "t": t}

    if report["errors"]:
        raise BundleError(report)

    # ---- camera intrinsics -----------------------------------------
    camera = manifest.get("camera") or {}
    raw_K = camera.get("intrinsics_K")
    K, estimated = None, False
    if raw_K is not None:
        K, err = _validate_intrinsics(raw_K)
        _check(report, "intrinsics valid", K is not None, err)
        if K is None:
            raise BundleError(report)
    else:
        if regime == "C":
            _check(report, "intrinsics present (Regime C)", False,
                   "Regime C requires a true intrinsics_K for every "
                   "kept frame; estimation is not accepted")
            raise BundleError(report)
        if frame_size is None:
            _check(report, "intrinsics estimable", False,
                   "no intrinsics_K and no readable frame size")
            raise BundleError(report)
        K = _estimate_intrinsics(*frame_size)
        estimated = True
        _warn(report, "intrinsics",
              "intrinsics_K estimated from frame size; reconstruction "
              "quality is unmeasured, not assumed")

    # ---- words ------------------------------------------------------
    words_rel = manifest.get("words_file", "words.json")
    words_path = os.path.join(root, words_rel)
    words_out = []
    if os.path.isfile(words_path):
        with open(words_path, "r", encoding="utf-8") as f:
            words_doc = json.load(f)
        entries = words_doc.get("words", [])
        indices = [e.get("index") for e in entries]
        _check(report, "word indices contiguous",
               indices == list(range(len(entries))),
               f"indices are {indices}")
        for entry in entries:
            text = (entry.get("text") or "").strip()
            _check(report, f"word {entry.get('index')} single word",
                   bool(text) and len(text.split()) == 1,
                   f"text is {entry.get('text')!r}; a two-word clip "
                   f"is a validation error")
            clip_rel = f"words/{entry.get('clip')}"
            clip_path = os.path.join(root, clip_rel)
            if not os.path.isfile(clip_path):
                _check(report, f"word clip present {clip_rel}", False,
                       "file missing")
                continue
            if entry.get("sha256") and \
                    _sha256_file(clip_path) != entry["sha256"]:
                _check(report, f"word clip hash {clip_rel}", False,
                       "SHA-256 does not match words.json")
                continue
            try:
                with wave.open(clip_path, "rb") as wf:
                    sr = wf.getframerate()
                    dur = wf.getnframes() / float(sr)
            except Exception as exc:
                _check(report, f"word clip decodes {clip_rel}", False,
                       str(exc))
                continue
            if dur > MAX_WORD_SANITY_S:
                _warn(report, "word duration",
                      f"{clip_rel} runs {dur:.2f}s; flagged, not "
                      f"auto-split")
            words_out.append({
                "index": entry["index"], "text": text,
                "clip": clip_rel, "path": usable(clip_rel),
                "sample_rate_hz": sr, "duration_s": round(dur, 4)})
    elif manifest.get("words_file"):
        _check(report, "words file present", False,
               f"{words_rel} named in manifest but missing")
    if report["errors"]:
        raise BundleError(report)

    # ---- normalized manifest ---------------------------------------
    mirror_record = {
        "front_camera_mirrored": mirrored,
        "un_mirrored_on_ingest": mirrored,
        "method": ("image flip / video hflip / pose conjugation"
                   if mirrored else "none needed"),
    }
    normalized = {
        "format": "clay-sculpt-studio/bundle-manifest",
        "version": BUNDLE_VERSION,
        "job_id": job_id,
        "job_dir": job_dir,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "regime": regime,
        "subject": manifest.get("subject"),
        "source": {"root": root, "manifest": manifest_path},
        "capture": {
            **capture,
            "frame_size": list(frame_size) if frame_size else None,
            "probe": report.get("capture_probe"),
            "coverage": report.get("coverage"),
            "kept_frames": report.get("kept_frames"),
            "dropped_frames": report["dropped_frames"],
        },
        "camera": {"intrinsics_K": K, "estimated": estimated},
        "subject_frame": {
            **(manifest.get("subject_frame") or {}),
            "forward": "+Z", "up": "+Y",
            "mirror_normalization": mirror_record,
        },
        "files": {rel: usable(rel) for rel in sorted(on_disk)},
        "words": words_out,
        "provenance": manifest.get("provenance"),
        "validation": {"ok": True, "checks": report["checks"],
                       "warnings": report["warnings"]},
    }
    out_path = os.path.join(job_dir, "bundle-manifest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2)
    normalized["manifest_path"] = out_path
    report["ok"] = True
    normalized["validation"]["warnings"] = report["warnings"]
    return normalized
