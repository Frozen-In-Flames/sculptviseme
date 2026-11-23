"""COLMAP reconstruction stage (RESEARCH.md section 4b).

The unordered-photo route: COLMAP SfM plus dense reconstruction,
behind a detection gate. COLMAP is BSD 3-Clause and the CPU
headless build is the pinned route, but neither pycolmap nor the
colmap binary is installed on every host this app runs on, so
the stage reports its availability honestly and refuses with
the reason when absent (the same pattern as the USDZ stage).

The CLI pipeline below is implemented against the documented
COLMAP command interface; on a host without COLMAP it is
reachable only through the availability check, and the test
suite covers the gate and the refusal, not an execution this
host cannot perform.
"""

import os
import shutil
import subprocess


class ColmapUnavailable(Exception):
    """COLMAP is not installed on this host."""


def status():
    try:
        import pycolmap  # noqa: F401
        return {"available": True, "backend": "pycolmap"}
    except ImportError:
        pass
    binary = shutil.which("colmap")
    if binary:
        return {"available": True, "backend": "cli", "path": binary}
    return {"available": False, "backend": None,
            "detail": "COLMAP is not installed on this host "
                      "(no pycolmap module, no colmap binary on "
                      "PATH). Install the CPU build of COLMAP "
                      "4.x (BSD 3-Clause) or pycolmap to enable "
                      "the unordered-photo reconstruction route. "
                      "The orbit visual-hull route "
                      "(reconstruction.py) works without it."}


def reconstruct_photos(image_dir, work_dir):
    """Run the COLMAP pipeline over a directory of photos and
    return the path of the fused dense mesh (PLY)."""
    st = status()
    if not st["available"]:
        raise ColmapUnavailable(st["detail"])
    if st["backend"] != "cli":
        raise ColmapUnavailable(
            "pycolmap is present but the scripted pipeline in "
            "this stage drives the COLMAP CLI; install the CLI "
            "build to run it.")
    binary = st["path"]
    db = os.path.join(work_dir, "database.db")
    sparse = os.path.join(work_dir, "sparse")
    dense = os.path.join(work_dir, "dense")
    for d in (sparse, dense):
        os.makedirs(d, exist_ok=True)
    steps = [
        [binary, "feature_extractor", "--database_path", db,
         "--image_path", image_dir],
        [binary, "exhaustive_matcher", "--database_path", db],
        [binary, "mapper", "--database_path", db,
         "--image_path", image_dir, "--output_path", sparse],
        [binary, "image_undistorter", "--image_path", image_dir,
         "--input_path", os.path.join(sparse, "0"),
         "--output_path", dense, "--output_type", "COLMAP"],
        [binary, "patch_match_stereo", "--workspace_path", dense,
         "--workspace_format", "COLMAP"],
        [binary, "stereo_fusion", "--workspace_path", dense,
         "--workspace_format", "COLMAP", "--input_type",
         "geometric", "--output_path",
         os.path.join(dense, "fused.ply")],
    ]
    for cmd in steps:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"COLMAP step failed ({cmd[1]}): "
                f"{proc.stderr.strip()[:300]}")
    return os.path.join(dense, "fused.ply")
