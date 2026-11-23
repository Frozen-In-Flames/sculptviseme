"""Parity gate for the color grade.

Proves backend/grading_ref.py (NumPy) agrees within 1e-5 with an
independent scalar transliteration of the GLSL in
frontend/shaders/clay_grade.frag, written directly from the shader
text with the math module. Also covers the identity property (zero
ink, unit black plate returns the input unchanged) and the core
feature case: a neutral gray sculpt picks up ink tint because the
ink is added, not multiplied.

Run: python3 -m unittest tests.test_grading_parity -v
"""

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import grading_ref  # noqa: E402

TOL = 1e-5


# ---- Independent transliteration of clay_grade.frag -----------------
# Written from the GLSL source, scalar, one pixel at a time. It shares
# no code with grading_ref.py on purpose: agreement is the evidence.

def _ss(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def glsl_grade_cmyk(c, ink_shadow, ink_mid, ink_high, k_gain, k_gamma):
    r, g, b = c
    k = 1.0 - max(r, max(g, b))
    denom = max(1.0 - k, 1e-4)
    cmy = [(1.0 - r - k) / denom, (1.0 - g - k) / denom,
           (1.0 - b - k) / denom]
    lum = r * 0.2126 + g * 0.7152 + b * 0.0722
    ws = 1.0 - _ss(0.15, 0.5, lum)
    wh = _ss(0.5, 0.85, lum)
    wm = 1.0 - ws - wh
    cmy = [min(max(cmy[i] + ws * ink_shadow[i] + wm * ink_mid[i]
                   + wh * ink_high[i], 0.0), 1.0) for i in range(3)]
    k = min(max(k_gain * math.pow(k, k_gamma), 0.0), 1.0)
    return tuple((1.0 - cmy[i]) * (1.0 - k) for i in range(3))


def glsl_rgb_lgg(c, lift, gamma, gain):
    out = []
    for i in range(3):
        base = gain[i] * c[i] + lift[i] * (1.0 - c[i])
        out.append(min(max(math.pow(max(base, 0.0), 1.0 / gamma[i]),
                           0.0), 1.0))
    return tuple(out)


def glsl_grade(c, params):
    c1 = glsl_grade_cmyk(c, params["ink_shadow"], params["ink_mid"],
                         params["ink_high"], params["k_gain"],
                         params["k_gamma"])
    return glsl_rgb_lgg(c1, params["lift"], params["gamma"],
                        params["gain"])


PARAM_SETS = [
    # Studio default style: warm shadows, cool highlights, firm plate.
    dict(ink_shadow=(0.20, 0.05, 0.00), ink_mid=(0.00, 0.10, 0.05),
         ink_high=(0.00, 0.05, 0.20), k_gain=1.1, k_gamma=1.3,
         lift=(0.02, 0.01, 0.00), gamma=(1.05, 1.0, 0.95),
         gain=(1.02, 1.0, 0.98)),
    # Heavy ink everywhere, soft plate.
    dict(ink_shadow=(0.45, 0.30, 0.10), ink_mid=(0.30, 0.45, 0.20),
         ink_high=(0.10, 0.20, 0.45), k_gain=0.8, k_gamma=0.7,
         lift=(0.0, 0.0, 0.0), gamma=(1.0, 1.0, 1.0),
         gain=(1.0, 1.0, 1.0)),
    # Zero ink, non-identity RGB pass only.
    dict(ink_shadow=(0.0, 0.0, 0.0), ink_mid=(0.0, 0.0, 0.0),
         ink_high=(0.0, 0.0, 0.0), k_gain=1.0, k_gamma=1.0,
         lift=(0.05, 0.05, 0.05), gamma=(1.2, 1.1, 0.9),
         gain=(0.9, 1.0, 1.1)),
]


def color_grid():
    steps = [i / 10.0 for i in range(11)]
    pts = [(r, g, b) for r in steps for g in steps for b in steps]
    pts += [(0.5, 0.5, 0.5), (0.25, 0.25, 0.25), (0.75, 0.75, 0.75),
            (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.03, 0.97, 0.5)]
    return pts


class TestGradingParity(unittest.TestCase):

    def test_numpy_matches_glsl_transliteration(self):
        grid = np.array(color_grid(), dtype=np.float64)
        for params in PARAM_SETS:
            ref = grading_ref.grade(
                grid, params["ink_shadow"], params["ink_mid"],
                params["ink_high"], params["k_gain"], params["k_gamma"],
                params["lift"], params["gamma"], params["gain"])
            worst = 0.0
            for i, px in enumerate(color_grid()):
                got = glsl_grade(px, params)
                for ch in range(3):
                    worst = max(worst, abs(got[ch] - ref[i, ch]))
            self.assertLessEqual(
                worst, TOL,
                f"parity breach {worst:.3e} for params {params}")

    def test_zero_ink_unit_plate_is_identity(self):
        grid = np.array(color_grid(), dtype=np.float64)
        out = grading_ref.grade_cmyk(grid, (0, 0, 0), (0, 0, 0),
                                     (0, 0, 0), 1.0, 1.0)
        self.assertLessEqual(float(np.abs(out - grid).max()), TOL)

    def test_neutral_gray_picks_up_tint(self):
        # The core feature: additive ink tints a plain gray sculpt.
        # At luminance 0.5 the zone weights sit fully in the midtone
        # (ws = 1 - smoothstep(0.15, 0.5, 0.5) = 0), so the midtone
        # magenta ink is the one that lands: it cuts the green channel.
        gray = np.array([[0.5, 0.5, 0.5]])
        out = grading_ref.grade(
            gray, (0.25, 0.0, 0.0), (0.0, 0.18, 0.0), (0.0, 0.0, 0.22),
            1.0, 1.0, (0, 0, 0), (1, 1, 1), (1, 1, 1))[0]
        self.assertFalse(
            np.allclose(out[0], out[1]) and np.allclose(out[1], out[2]),
            f"gray stayed neutral under ink: {out}")
        self.assertLess(out[1], 0.5)   # magenta mid ink cuts green
        self.assertGreater(float(np.abs(out - 0.5).max()), 0.02)
        # A darker gray sits in the shadow zone: cyan ink cuts red.
        dark = grading_ref.grade(
            np.array([[0.25, 0.25, 0.25]]), (0.25, 0.0, 0.0),
            (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0, 1.0,
            (0, 0, 0), (1, 1, 1), (1, 1, 1))[0]
        self.assertLess(dark[0], 0.25)
        self.assertAlmostEqual(float(dark[1]), 0.25, places=6)

    def test_black_plate_darkens(self):
        c = np.array([[0.4, 0.4, 0.4]])
        plain = grading_ref.grade_cmyk(c, (0, 0, 0), (0, 0, 0),
                                       (0, 0, 0), 1.0, 1.0)
        plated = grading_ref.grade_cmyk(c, (0, 0, 0), (0, 0, 0),
                                        (0, 0, 0), 1.6, 1.0)
        self.assertTrue(np.all(plated < plain))

    def test_k_gamma_must_be_positive(self):
        with self.assertRaises(ValueError):
            grading_ref.grade_cmyk(np.zeros((1, 3)), (0, 0, 0),
                                   (0, 0, 0), (0, 0, 0), 1.0, 0.0)

    def test_output_stays_in_display_range(self):
        rng = np.random.default_rng(7)
        grid = rng.random((4096, 3))
        for params in PARAM_SETS:
            out = grading_ref.grade(
                grid, params["ink_shadow"], params["ink_mid"],
                params["ink_high"], params["k_gain"], params["k_gamma"],
                params["lift"], params["gamma"], params["gain"])
            self.assertGreaterEqual(float(out.min()), 0.0)
            self.assertLessEqual(float(out.max()), 1.0)


if __name__ == "__main__":
    unittest.main()
