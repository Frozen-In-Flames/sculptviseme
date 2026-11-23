"""Build the headless-verification fixture (NOT part of the app).

Reads the v3 clay bust from bio-3d, authors crude viseme morph
deltas on a mouth-region heuristic, generates two synthetic word
clips, runs the real aligner for keyframes, and packs everything
with the real exporter. The deltas are test scaffolding: per-vertex
viseme authoring on the real topology is Slice 2 work, and nothing
here is presented as it.

Output (default /tmp/css-fixture/): fixture.glb, keyframes.json,
hello.wav, world.wav
"""

import json
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, "..", "..", "backend")
sys.path.insert(0, BACKEND)

import glb_exporter  # noqa: E402
import lipsync_align  # noqa: E402

BUST = os.path.expanduser("~/workspace/bio-3d/aries-bust-clay-v3.glb")
MOUTH_CENTER = np.array([0.0, -0.35, 0.55])

# Crude per-viseme mouth behaviour for the fixture: jaw opening
# (lower verts move down), lip closure (verts pull toward the
# mouth line), rounding (verts pull inward in x, forward in z).
VISEME_BEHAVIOUR = {
    "sil": (0.0, 0.0, 0.0), "PP": (0.0, 0.7, 0.0),
    "FF": (0.05, 0.4, 0.0), "TH": (0.15, 0.2, 0.0),
    "DD": (0.1, 0.3, 0.0), "kk": (0.25, 0.1, 0.0),
    "CH": (0.2, 0.2, 0.4), "SS": (0.05, 0.35, 0.0),
    "nn": (0.08, 0.3, 0.0), "RR": (0.3, 0.15, 0.3),
    "aa": (0.55, 0.0, 0.0), "E": (0.3, 0.1, 0.0),
    "ih": (0.22, 0.15, 0.0), "oh": (0.42, 0.0, 0.5),
    "ou": (0.35, 0.0, 0.6),
}


def _wav(path, freq, seconds=0.35, sr=16000):
    t = np.arange(int(seconds * sr)) / sr
    samples = (0.5 * np.sin(2 * np.pi * freq * t) * 32767)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.astype("<i2").tobytes())


def main(out_dir="/tmp/css-fixture"):
    os.makedirs(out_dir, exist_ok=True)
    with open(BUST, "rb") as f:
        gltf, binb = glb_exporter.parse_glb(f.read())
    prim = gltf["meshes"][0]["primitives"][0]
    pos = glb_exporter.read_accessor(
        gltf, binb, prim["attributes"]["POSITION"]).astype(np.float64)
    nrm = glb_exporter.read_accessor(
        gltf, binb, prim["attributes"]["NORMAL"]).astype(np.float64)
    idx = glb_exporter.read_accessor(
        gltf, binb, prim["indices"]).reshape(-1, 3)

    rel = pos - MOUTH_CENTER
    dist2 = (rel ** 2).sum(axis=1)
    falloff = np.exp(-dist2 / (2 * 0.28 ** 2))
    in_region = (np.abs(pos[:, 0]) < 0.4) & (pos[:, 1] > -0.95) & \
        (pos[:, 1] < 0.1) & (pos[:, 2] > 0.15)
    w = falloff * in_region
    lower = (pos[:, 1] < MOUTH_CENTER[1]).astype(np.float64)

    targets = []
    for name in lipsync_align.VISEMES:
        jaw, close, rnd = VISEME_BEHAVIOUR[name]
        d = np.zeros_like(pos)
        d[:, 1] -= jaw * 0.22 * w * lower            # jaw drops
        d[:, 1] += close * (MOUTH_CENTER[1] - pos[:, 1]) * w * 0.6
        d[:, 0] -= rnd * pos[:, 0] * w * 0.5         # rounding
        d[:, 2] += rnd * 0.08 * w
        targets.append({"name": name, "position": d})

    hello = os.path.join(out_dir, "hello.wav")
    world = os.path.join(out_dir, "world.wav")
    _wav(hello, 180.0)
    _wav(world, 240.0)
    doc = lipsync_align.align_words([("hello", hello),
                                     ("world", world)])
    with open(os.path.join(out_dir, "keyframes.json"), "w") as f:
        json.dump(doc, f)

    times = np.array([fr["t"] for fr in doc["frames"]])
    weights = np.array([fr["weights"] for fr in doc["frames"]])
    glb = glb_exporter.build_glb(
        pos, idx, normals=nrm, morph_targets=targets,
        weights_animation=(times, weights),
        mesh_name="clay-bust-v3-fixture")
    out = os.path.join(out_dir, "fixture.glb")
    with open(out, "wb") as f:
        f.write(glb)
    print(f"fixture: {out} ({len(glb)} bytes), "
          f"{len(doc['frames'])} keyframes, "
          f"peak weight {weights.max():.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/css-fixture")
