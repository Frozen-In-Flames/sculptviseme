"""NumPy reference implementation of the Clay Sculpt Studio color grade.

Primary pass: gradeCMYK, the GLSL function Aries supplied in chat on
2026-11-19, transliterated line for line. Ink is added (not multiplied)
into the CMY channels, weighted by tonal zone through luminance, so a
neutral gray sculpt picks up tint. The black plate is shaped by kGain
and kGamma (kGamma must stay above zero). The result inverts back to
RGB as (1 - cmy) * (1 - k).

Secondary pass: RGB lift / gamma / gain in the ASC-CDL family form
named in RESEARCH.md section 9:

    C2 = clamp( (gain * C1 + lift * (1 - C1)) ^ (1 / gamma) )

applied per channel. It runs after gradeCMYK, per Aries's spec.

This module is the parity reference for frontend/shaders/clay_grade.frag.
tests/test_grading_parity.py proves the two agree within 1e-5.

All functions accept arrays of shape (..., 3) with values in 0..1 and
return float64 arrays of the same shape. No network, no files, no GPU.
"""

import numpy as np

_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


def _smoothstep(edge0, edge1, x):
    """GLSL smoothstep: clamped cubic Hermite between the edges."""
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def grade_cmyk(c, ink_shadow, ink_mid, ink_high, k_gain, k_gamma):
    """Aries's gradeCMYK, exact transliteration of the GLSL.

    c: (..., 3) display-referred RGB in 0..1.
    ink_shadow / ink_mid / ink_high: (3,) CMY ink added in each zone.
    k_gain, k_gamma: black plate controls; k_gamma must be > 0.
    """
    if k_gamma <= 0:
        raise ValueError("k_gamma must be above zero")
    c = np.asarray(c, dtype=np.float64)
    ink_shadow = np.asarray(ink_shadow, dtype=np.float64)
    ink_mid = np.asarray(ink_mid, dtype=np.float64)
    ink_high = np.asarray(ink_high, dtype=np.float64)

    k = 1.0 - c.max(axis=-1, keepdims=True)
    cmy = (1.0 - c - k) / np.maximum(1.0 - k, 1e-4)
    lum = (c * _LUMA).sum(axis=-1, keepdims=True)
    ws = 1.0 - _smoothstep(0.15, 0.5, lum)
    wh = _smoothstep(0.5, 0.85, lum)
    wm = 1.0 - ws - wh
    cmy = np.clip(cmy + ws * ink_shadow + wm * ink_mid + wh * ink_high,
                  0.0, 1.0)
    k = np.clip(k_gain * np.power(k, k_gamma), 0.0, 1.0)
    return (1.0 - cmy) * (1.0 - k)


def rgb_lift_gamma_gain(c, lift, gamma, gain):
    """Secondary RGB pass. lift / gamma / gain are per-channel (3,).

    The base is clamped at zero before the power, matching the guard
    written into the GLSL (pow of a negative base is undefined in GLSL).
    """
    gamma = np.asarray(gamma, dtype=np.float64)
    if np.any(gamma <= 0):
        raise ValueError("gamma must be above zero on every channel")
    c = np.asarray(c, dtype=np.float64)
    lift = np.asarray(lift, dtype=np.float64)
    gain = np.asarray(gain, dtype=np.float64)
    base = gain * c + lift * (1.0 - c)
    out = np.power(np.maximum(base, 0.0), 1.0 / gamma)
    return np.clip(out, 0.0, 1.0)


def grade(c, ink_shadow, ink_mid, ink_high, k_gain, k_gamma,
          lift, gamma, gain):
    """Full grade: gradeCMYK first, RGB lift/gamma/gain second."""
    cmyk_out = grade_cmyk(c, ink_shadow, ink_mid, ink_high,
                          k_gain, k_gamma)
    return rgb_lift_gamma_gain(cmyk_out, lift, gamma, gain)
