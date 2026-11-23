"""Production viseme authoring: real morph targets from a neutral bust.

Slice 2 of the SculptViseme plan (RESEARCH.md). Until now the only
viseme deltas in the project were the verification fixture's test
scaffolding (frontend/verify/make_fixture.py): a hardcoded mouth
center for one bust, an isotropic falloff clipped by a hard box, and
three crude rules. This module is the production replacement.

Method
------
A viseme target is a sum of articulation primitives, each a smooth
displacement field over the mouth region:

  jaw_open    the lower face drops (and slightly recedes) below the
              lip line, ramped smoothly with distance below the line
  lip_close   upper and lower lip vertices converge on the lip line
  lip_round   the corners draw inward and the lips push forward
  lip_spread  the corners draw outward and the lips thin to the line
  lip_tuck    the lower lip rises and recedes (the F/V articulation)

Each viseme in the aligner's 15-viseme set (lipsync_align.VISEMES)
is a documented combination of the five, with magnitudes in units
of the mouth width, so the same table authors any bust at any
scale. All fields use smooth (gaussian / smoothstep) falloffs:
there are no hard region boxes and no step weights, so no seam can
appear at a region boundary.

Landmarks
---------
The fields are placed by mouth landmarks: a center point and a
mouth width, in the bust's own coordinates, with the face assumed
upright and front-facing (+Y up, +Z forward, the convention of the
capture stage). Landmarks are an input: callers that know them
(a fitted template, a human placing two points) pass them in.
When they are absent, locate_mouth estimates them from the mesh:
the central column's front profile of a bust is a near-planar
face band between the forehead recession and the chin step, and
the mouth sits at a fixed proportion of that band. The estimate
is a starting point, reported with its measurements so a caller
can see and override it; it is not presented as a fit.

Everything here is deterministic NumPy: same mesh, same
landmarks, same deltas, byte for byte.
"""

import numpy as np

# The aligner's canonical order; targets are always emitted in it.
from lipsync_align import VISEMES

# Per-viseme articulation: (jaw, close, round, spread, tuck),
# each 0..1 (close may go negative to part the lips). The values
# encode the visible articulation of each viseme class:
#   PP  bilabial stop: full closure, a trace of jaw for the release
#   FF  labiodental: lower lip raised to the upper teeth (tuck)
#   TH  dental: lips parted, jaw slightly open (tongue not modeled)
#   DD  alveolar: small jaw opening, lips neutral
#   kk  velar: jaw mid-open, action is at the back of the mouth
#   CH  postalveolar: rounded lips, slight jaw
#   SS  sibilant: teeth near-closed, corners spread
#   nn  nasal: soft near-closure, small jaw
#   RR  rhotic: mid jaw, moderate rounding
#   aa  open vowel: full jaw, lips parted
#   E   mid vowel: mid jaw, spread corners
#   ih  near-close vowel: slight jaw, slight spread
#   oh  open rounded vowel: open jaw with rounding
#   ou  close rounded vowel: the tightest rounding, moderate jaw
ARTICULATION = {
    "sil": (0.00, 0.00, 0.00, 0.00, 0.00),
    "PP": (0.05, 1.00, 0.10, 0.00, 0.00),
    "FF": (0.08, 0.25, 0.00, 0.00, 1.00),
    "TH": (0.28, -0.25, 0.00, 0.00, 0.00),
    "DD": (0.22, 0.10, 0.00, 0.00, 0.00),
    "kk": (0.38, 0.00, 0.00, 0.00, 0.00),
    "CH": (0.25, 0.10, 0.75, 0.00, 0.00),
    "SS": (0.06, 0.55, 0.00, 0.55, 0.00),
    "nn": (0.14, 0.35, 0.00, 0.00, 0.00),
    "RR": (0.32, 0.00, 0.45, 0.00, 0.00),
    "aa": (1.00, -0.30, 0.00, 0.00, 0.00),
    "E": (0.45, 0.00, 0.00, 0.50, 0.00),
    "ih": (0.28, 0.10, 0.00, 0.35, 0.00),
    "oh": (0.62, 0.00, 0.70, 0.00, 0.00),
    "ou": (0.40, 0.00, 1.00, 0.00, 0.00),
}


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def locate_mouth(positions):
    """Estimate mouth landmarks from a front-facing bust mesh.

    Returns (landmarks, report): landmarks is a dict with
    "center" (3,) and "width" (float) in mesh units; report holds
    the measurements the estimate rests on (face band, profile
    peak), so a caller can judge and override it.

    The estimator reads the central column's front profile: the
    longest near-planar band of that profile is the face, the
    mouth sits 48% of the way up the band from its bottom (chin
    step) edge, set back from the profile plane by 9% of the band
    height, and the mouth width is 42% of the face's width at the
    mouth height. These proportions are the module's documented
    heuristic, regression-tested against the v3 clay bust whose
    hand-tuned fixture center they reproduce.
    """
    pos = np.asarray(positions, dtype=np.float64)
    x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
    span_x = float(x.max() - x.min())
    span_y = float(y.max() - y.min())
    # Central column around the most-forward vertex's x.
    x0 = float(x[np.argmax(z)])
    col = np.abs(x - x0) < 0.04 * span_x
    ys, zs = y[col], z[col]
    if len(ys) < 50:
        raise ValueError("locate_mouth: too few central-column vertices")
    bins = np.linspace(y.min(), y.max(), 161)
    prof = np.full(len(bins) - 1, np.nan)
    for i in range(len(bins) - 1):
        m = (ys >= bins[i]) & (ys < bins[i + 1])
        if m.any():
            prof[i] = zs[m].max()
    centers = 0.5 * (bins[:-1] + bins[1:])
    ok = ~np.isnan(prof)
    prof_f = np.interp(centers, centers[ok], prof[ok])
    prof_s = np.convolve(prof_f, np.ones(3) / 3.0, mode="same")
    z_peak = float(prof_s.max())
    # The face band: the longest contiguous run within 0.08 of the
    # profile peak (mesh units are ~head height 2.8 for the v3
    # bust; the tolerance scales with the span).
    tol = 0.03 * span_y
    in_band = prof_s >= z_peak - tol
    best, run, start = (0, 0), 0, 0
    for i, v in enumerate(in_band):
        if v:
            if run == 0:
                start = i
            run += 1
            if run > best[1]:
                best = (start, run)
        else:
            run = 0
    band_lo = float(centers[best[0]])
    band_hi = float(centers[best[0] + best[1] - 1])
    band_h = band_hi - band_lo
    if band_h <= 0:
        raise ValueError("locate_mouth: no face band found")
    mouth_y = band_lo + 0.48 * band_h
    z_plane = float(np.interp(mouth_y, centers, prof_s))
    center_z = z_plane - 0.09 * band_h
    # Center x: the mean of the near-front patch at the mouth
    # height (the single most-forward vertex can sit off-axis on
    # an asymmetric sculpt; the patch mean cannot drift as far).
    patch = (np.abs(y - mouth_y) < 0.02 * span_y) & (z > center_z - 0.03)
    if patch.sum() < 10:
        raise ValueError("locate_mouth: no face patch at mouth height")
    center_x = float(x[patch].mean())
    center = np.array([center_x, mouth_y, center_z])
    # Mouth width from the bust's full cross-section at the mouth
    # height (the head's silhouette width there): on a relief-style
    # bust the near-front patch alone is only the flat center of
    # the face and understates the anatomy by several times.
    section = np.abs(y - mouth_y) < 0.02 * span_y
    face_w = float(x[section].max() - x[section].min())
    width = 0.42 * face_w
    report = {
        "face_band": [band_lo, band_hi],
        "profile_peak_z": z_peak,
        "cross_section_width_at_mouth": face_w,
        "column_x": x0,
    }
    return {"center": center, "width": width}, report


def _fields(pos, center, width):
    """The shared spatial weights of the articulation primitives."""
    rel = pos - center
    # Anisotropic gaussian over the mouth region.
    sx, sy, sz = 0.62 * width, 0.42 * width, 0.62 * width
    d2 = (rel[:, 0] / sx) ** 2 + (rel[:, 1] / sy) ** 2 + (rel[:, 2] / sz) ** 2
    w = np.exp(-0.5 * d2)
    # Lip-line band: tight vertical window around the line.
    band = np.exp(-0.5 * (rel[:, 1] / (0.16 * width)) ** 2) * w
    # Jaw ramp: 0 at the line, 1 well below it, smooth between.
    ramp = _smoothstep((0.05 * width - rel[:, 1]) / (0.30 * width))
    # Corner weight: peaks at the mouth corners, zero at center.
    corner = _smoothstep((np.abs(rel[:, 0]) - 0.10 * width) / (0.40 * width)) * w
    return w, band, ramp, corner


def author_visemes(positions, landmarks=None):
    """Author the 15 viseme morph targets for a neutral bust.

    positions: (N, 3) vertex positions of the neutral mesh.
    landmarks: optional {"center": (3,), "width": float}; estimated
    from the mesh when absent.

    Returns (targets, info): targets is a list of {"name", "position"}
    dicts in lipsync_align.VISEMES order, each position an (N, 3)
    float64 delta array; info carries the landmarks used and the
    locate_mouth report when the landmarks were estimated.
    """
    pos = np.asarray(positions, dtype=np.float64)
    if pos.ndim != 2 or pos.shape[1] != 3:
        raise ValueError("author_visemes: positions must be (N, 3)")
    info = {}
    if landmarks is None:
        landmarks, report = locate_mouth(pos)
        info["estimated"] = report
    center = np.asarray(landmarks["center"], dtype=np.float64)
    width = float(landmarks["width"])
    if width <= 0:
        raise ValueError("author_visemes: landmark width must be positive")
    info["landmarks"] = {"center": center.tolist(), "width": width}

    w, band, ramp, corner = _fields(pos, center, width)
    rel_y = pos[:, 1] - center[1]
    rel_x = pos[:, 0] - center[0]

    targets = []
    for name in VISEMES:
        jaw, close, rnd, spread, tuck = ARTICULATION[name]
        d = np.zeros_like(pos)
        # jaw_open: lower face drops and slightly recedes.
        drop = jaw * 0.38 * width * w * ramp
        d[:, 1] -= drop
        d[:, 2] -= 0.22 * drop
        # lip_close: both lips converge on the line (negative parts).
        d[:, 1] += close * (-rel_y) * band
        # lip_round: corners inward, lips forward, slight pinch.
        d[:, 0] += rnd * (-rel_x) * 0.45 * w
        d[:, 2] += rnd * 0.20 * width * band
        d[:, 1] += rnd * (-rel_y) * 0.30 * band
        # lip_spread: corners outward, lips thin toward the line.
        d[:, 0] += spread * np.sign(rel_x) * 0.16 * width * corner
        d[:, 1] += spread * (-rel_y) * 0.20 * band
        # lip_tuck: lower lip rises to the teeth and recedes.
        lower_band = band * _smoothstep(-rel_y / (0.10 * width))
        d[:, 1] += tuck * 0.15 * width * lower_band
        d[:, 2] -= tuck * 0.07 * width * lower_band
        targets.append({"name": name, "position": d})
    return targets, info
