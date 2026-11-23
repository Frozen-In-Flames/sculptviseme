// Clay Sculpt Studio grading shader.
//
// Grading stage for the clay material: gradeCMYK runs first (primary
// ink grade), RGB lift / gamma / gain runs second. gradeCMYK below is
// the function Aries supplied on 2026-11-19, carried verbatim.
// backend/grading_ref.py is its NumPy parity reference;
// tests/test_grading_parity.py holds the 1e-5 agreement gate.
//
// Integration: sample the clay base color (matte clay lighting result)
// into `base`, then call grade(base). Uniform contract: kGamma and
// rgbGamma stay above zero; the host UI enforces it.

precision highp float;

uniform vec3 inkShadow;   // CMY ink added in the shadow zone
uniform vec3 inkMid;      // CMY ink added in the midtone zone
uniform vec3 inkHigh;     // CMY ink added in the highlight zone
uniform float kGain;      // black plate gain
uniform float kGamma;     // black plate gamma, must stay above zero
uniform vec3 rgbLift;     // secondary RGB lift, per channel
uniform vec3 rgbGamma;    // secondary RGB gamma, per channel, above zero
uniform vec3 rgbGain;     // secondary RGB gain, per channel

// c: tone-mapped, display-referred RGB in 0..1
vec3 gradeCMYK(vec3 c, vec3 inkShadow, vec3 inkMid, vec3 inkHigh,
               float kGain, float kGamma) {
  float k = 1.0 - max(c.r, max(c.g, c.b));
  vec3 cmy = (1.0 - c - k) / max(1.0 - k, 1e-4);
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  float ws = 1.0 - smoothstep(0.15, 0.5, l);
  float wh = smoothstep(0.5, 0.85, l);
  float wm = 1.0 - ws - wh;
  cmy = clamp(cmy + ws * inkShadow + wm * inkMid + wh * inkHigh, 0.0, 1.0);
  k = clamp(kGain * pow(k, kGamma), 0.0, 1.0);
  return (1.0 - cmy) * (1.0 - k);
}

// Secondary RGB pass, ASC-CDL family form:
//   C2 = clamp( (gain * C1 + lift * (1 - C1)) ^ (1 / gamma) )
// The max() guard matches the NumPy reference: pow of a negative base
// is undefined in GLSL, so the base is clamped at zero first.
vec3 rgbLiftGammaGain(vec3 c, vec3 lift, vec3 gamma, vec3 gain) {
  vec3 base = gain * c + lift * (1.0 - c);
  return clamp(pow(max(base, vec3(0.0)), vec3(1.0) / gamma), 0.0, 1.0);
}

vec3 grade(vec3 base) {
  vec3 c = gradeCMYK(base, inkShadow, inkMid, inkHigh, kGain, kGamma);
  return rgbLiftGammaGain(c, rgbLift, rgbGamma, rgbGain);
}
