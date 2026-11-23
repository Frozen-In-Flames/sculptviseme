# SculptViseme

A self-hosted studio that turns a captured person into a speaking
clay bust. The pipeline is: capture, reconstruct, sculpt, lip-sync,
grade, export. It runs with no accounts, no external APIs, and no
cloud dependency: the software is a local web frontend and a small
backend service, and the heavy stages run where the user chooses.

## What it does

1. **Capture.** A capture bundle (`.claybundle.zip`: an orbit video
   or a photo set, plus one WAV per spoken word) is validated
   against a written bundle specification before any work starts.
2. **Sculpt.** The subject is presented as a monochrome clay bust
   under matte lighting. Reconstruction from new captures
   (visual hull, COLMAP photo sets, and a non-rigid head fit) is
   specified in RESEARCH.md; those stage adapters are the next
   build step (see Status).
3. **Lip-sync.** Word clips are aligned word by word: local
   grapheme-to-phoneme conversion maps each word to phonemes,
   phonemes to the 15-viseme set, and clip energy (RMS) scales the
   keyframe curves. Playback drives the bust's viseme morph
   targets in sync with the audio.
4. **Grade.** A primary CMYK ink grade (ink added per tonal zone,
   so even neutral gray clay takes tint, with black-plate gain and
   gamma) followed by a secondary RGB lift/gamma/gain pass. The
   GLSL shader and the NumPy reference implementation are tested
   for parity to within 1e-5.
5. **Export.** GLB (model, morph targets, and the weights
   animation), STL (static geometry only, for fabrication), USDZ
   (one static neutral pose for AR preview), the keyframes JSON,
   and a graded lip-sync video recorded from the stage. Each
   format's limits are stated in the interface, not discovered
   after the fact: USDZ carries no morphs or animation, and where
   Pixar's USD library is not installed the USDZ endpoints answer
   501 with the reason rather than returning a fake package.

## Where the heavy stages run: the user's choice

Bundle validation, lip-sync alignment, and the USDZ build run on a
*runner*: the same backend service, deployed two ways.

- **Local (default).** The backend runs on the user's own machine
  and binds localhost. No setup, no token, nothing leaves the
  device.
- **Cloud (opt-in).** The same backend, packaged by the included
  Dockerfile for any container host, for users who want a remote
  GPU-class machine to do the work. A deployment sets an access
  token (`SV_API_TOKEN`) that the frontend sends with each job,
  and lists the web origins allowed to call it
  (`SV_CORS_ORIGINS`).

The frontend's Compute setting switches between the two and can
check which runner it is talking to. Capture, grading, playback,
and export stay on the device in both modes.

## Quick start (local)

```sh
pip install -r requirements.txt
cd backend
uvicorn app:app --host 127.0.0.1 --port 8077
```

Open http://127.0.0.1:8077/ and work through the five steps.

## Cloud runner

```sh
docker build -t sculptviseme .
docker run -p 8077:8077 \
  -e SV_API_TOKEN=<a-secret-you-choose> \
  -e SV_CORS_ORIGINS=https://your-frontend.example \
  -v sculptviseme-jobs:/app/var \
  sculptviseme
```

Then set the frontend's Compute setting to *Cloud runner* and
enter the runner's URL and token.

## Status

Implemented and covered by the test suite (100 tests):

- capture-bundle validation against the bundle specification
- word-by-word lip-sync alignment (grapheme-to-phoneme, viseme
  mapping, RMS-scaled curves), including a silence negative
  control: silence produces no motion
- CMYK + RGB grading with shader/reference parity at 1e-5
- GLB export with morph targets and weights animation; STL
  export; USDZ export where Pixar USD is installed
- the five-step frontend, fully self-contained (the three.js
  viewer library is vendored into this repository; the page makes
  zero external requests)
- dual runners: local mode, cloud mode with bearer-token gate and
  CORS, verified end to end through the real frontend
- visual-hull reconstruction (`backend/reconstruction.py`,
  `POST /api/mesh-reconstruct`): orbit silhouette masks carved
  into a voxel hull and surfaced with a naive surface net, plus
  empty-plate silhouette extraction. Verified against an
  analytic sphere oracle (volume within 3 percent at grid 48);
  the concavity limit is documented and asserted in tests
- the template fit engine (`backend/head_fit.py`): landmark
  initialized rigid alignment plus non-rigid ICP with trimmed
  matching and deformation-form Laplacian stiffness, verified
  against synthetic templates (identity fixed-point control
  included). The GNM Head template assets are not vendored yet,
  so the GNM gate reports unavailable and refuses; the COLMAP
  photo route (`backend/colmap_stage.py`) is likewise gated on
  COLMAP being installed on the host. Both gates are reported
  live in `GET /api/health`
- production viseme authoring (`backend/viseme_authoring.py`,
  `POST /api/mesh-author-visemes`): the 15 viseme morph targets
  are generated from a neutral bust as combinations of five
  articulation primitives (jaw, closure, rounding, spread, lower
  lip tuck) over smooth mouth-region fields, in units of the
  mouth width. Landmarks are an input; when absent they are
  estimated from the mesh's face band and reported. The
  verification fixture now exercises this same code path instead
  of its former hand-made scaffolding deltas

Designed and specified (RESEARCH.md), not yet built:

- vendoring the GNM Head template assets (pinned commit, hashes
  recorded at vendor time) so the fit engine runs on the real
  template, and a job-level pipeline that chains bundle, hull,
  fit, and authoring in one call. The fit is also what brings
  true lip topology to a bust: the clay relief the authoring is
  verified on has no sculpted lips, so its targets move the
  mouth region correctly without a lip line to articulate

## Tests

```sh
python -m unittest discover -s tests
```

Three USDZ tests skip where Pixar's `pxr` is not installed; the
exporter contract test still runs and asserts the labeled error.

## License

Apache License 2.0 (see LICENSE). The vendored three.js copy under
`frontend/vendor/` is MIT-licensed by its authors (see
`frontend/vendor/THREE-LICENSE.txt`); it is pinned at r164 and
included so the application has no runtime dependency on a CDN.

Developed by Aries Drake Hilton.
