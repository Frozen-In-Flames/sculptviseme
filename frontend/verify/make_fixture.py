"""Build the headless-verification fixture (NOT part of the app).

Reads the v3 clay bust from bio-3d, authors its viseme morph
deltas with the production author (backend/viseme_authoring.py,
landmarks estimated from the mesh), generates two synthetic word
clips, runs the real aligner for keyframes, and packs everything
with the real exporter. Since Slice 2 landed, the fixture
exercises the same authoring code the app serves; it is a
verification harness, not a second implementation.

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
import viseme_authoring  # noqa: E402

BUST = os.path.expanduser("~/workspace/bio-3d/aries-bust-clay-v3.glb")


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

    targets, info = viseme_authoring.author_visemes(pos)
    lm = info["landmarks"]
    print(f"authored landmarks: center "
          f"{[round(v, 3) for v in lm['center']]}, "
          f"width {lm['width']:.3f} (estimated)")

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
