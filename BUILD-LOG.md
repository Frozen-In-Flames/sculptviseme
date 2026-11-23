# Clay Sculpt and Lip-Sync Studio: Build Log

Local build only. Nothing in this directory has been published, no
repository has been created, and nothing has been pushed anywhere.
Build order follows RESEARCH.md section 12; this pass covers the
slices this VM can prove (NumPy / SciPy / ffmpeg, no GPU).

Date: 2026-11-20 (America/Chicago)

## Built in this pass

### Slice: grading reference and shader (RESEARCH section 9)

- `backend/grading_ref.py`: NumPy reference of the grade. The
  primary pass is Aries's gradeCMYK exactly as supplied (additive
  ink by tonal zone through luminance weights, kGain / kGamma black
  plate, (1 - cmy) * (1 - k) inversion). The secondary pass is RGB
  lift / gamma / gain in the ASC-CDL family form, run after
  gradeCMYK as specified.
- `frontend/shaders/clay_grade.frag`: the GLSL grading stage with
  gradeCMYK carried verbatim, plus the matching RGB pass and the
  uniform contract (kGamma and rgbGamma stay above zero).
- `tests/test_grading_parity.py`: 6 tests. The NumPy reference is
  checked against an independent scalar transliteration of the GLSL
  (written from the shader text with the math module, sharing no
  code) over a 1,337-point color grid and three parameter sets:
  worst difference within the 1e-5 gate. Includes the identity
  property (zero ink and a unit black plate return the input), the
  black plate darkening check, the kGamma guard, output range, and
  the core feature case: neutral gray picks up tint, because the
  ink is added rather than multiplied. One test expectation was
  corrected during the build: at luminance exactly 0.5 the zone
  weights sit fully in the midtone, so midtone ink is what lands
  there; shadow ink is asserted on a darker gray instead. The math
  under test is Aries's and was not changed.

### Slice: word-by-word lip-sync (RESEARCH section 6)

- `backend/g2p.py`: word to ARPAbet with three labeled sources,
  tried in order: the Voice Asset Format override table, then
  CMUdict 0.7b (vendored at `assets/cmudict/cmudict.dict`, BSD
  2-Clause, fetched from the public CMU Sphinx repository with no
  signup), then a small deterministic grapheme rule fallback that
  is labeled "rules" everywhere its output travels.
- `backend/lipsync_align.py`: WAV in (stdlib wave, mono mixdown),
  resample to 16 kHz mono (SciPy resample_poly), energy VAD trim,
  G2P, phoneme to viseme through the existing Voice Asset Format
  map (vendored verbatim at `assets/viseme/phonemes.json`, SHA-256
  verified against the original by test), RMS envelope scaling
  with raised-cosine coarticulation bumps per the section 6
  formula, envelope normalized across the whole utterance. Output
  is a viseme keyframes JSON (30 fps default, per-word phonemes,
  visemes, timing, and pronunciation source). CLI included.
- `tests/test_lipsync_align.py`: 12 tests with synthetic WAV
  fixtures (tones as voiced clips, including a 22050 Hz resample
  case and a stereo case). Negative control: a silent clip
  produces peak viseme weight under 1e-3 while loud clips in the
  same utterance move normally. A quiet word stays quiet relative
  to a loud one. The vendored viseme map is asserted byte-identical
  to the Voice Asset Format original on every run.

### Slice: GLB exporter with sparse morph targets (RESEARCH section 7)

- `backend/glb_exporter.py`: self-written GLB 2.0 packer in pure
  stdlib plus NumPy. Static mesh (positions, smooth normals
  computed when not supplied, indices), morph targets written as
  SPARSE accessors (only nonzero delta rows are stored), default
  weights, target names in mesh extras, a clay PBR material, and a
  weights animation channel writer (LINEAR, time in seconds, one
  weight per target per keyframe). Includes the matching
  hand-rolled reader (parse_glb / read_accessor with sparse
  expansion) in the style of bio-3d/stage7.
- `tests/test_glb_exporter.py`: 10 tests. Header (magic, version,
  length), chunk types, buffer length agreement, 4-byte alignment
  of every bufferView, full round trip of positions / normals /
  indices, sparse structure (accessor carries sparse storage whose
  count equals the nonzero row count) and sparse value round trip,
  target names and default weights, the weights animation channel
  round trip, and shape error cases. At bust scale (a 71,556
  vertex grid, a 500-vertex mouth delta), sparse storage for one
  target measures under 5 percent of the dense cost of 12 bytes
  per vertex (about 0.86 MB per target at 71,524 vertices), and
  the expanded sparse data round trips exactly. One bug was found
  and fixed by these tests: the index accessor initially counted
  faces instead of indices because the index array was not
  flattened before packing.
- Integration smoke (run once, recorded here): lip-sync keyframes
  for "hello" (9 frames by 15 visemes) were baked through the
  exporter into a GLB with 15 viseme morph targets; the weights
  animation read back exactly equal to the aligner output.

## Test totals

- tests/test_grading_parity.py: 6 tests, all passing.
- tests/test_lipsync_align.py: 12 tests, all passing.
- tests/test_glb_exporter.py: 10 tests, all passing.
- Total: 28 tests, all passing.
  Run with: python3 -m unittest discover -s tests

## What remains, with blockers named

- Capture bundle loader and validator (RESEARCH section 10,
  Slice 0 remainder): BUILT in the second pass, below.
- Frontend viewer (Slice 1 remainder): BUILT in the second pass,
  below (viewer, grade controls, video export, GLB download;
  STL download still open). Sensory verification needs Aries's
  iPhone; the VM cannot judge it.
- Morph targets authored on the real bust topology (Slice 2
  remainder): the aligner produces the curves and the exporter
  packs them, but per-vertex viseme deltas on the 71,524 vertex
  clay bust (mouth region definition on that topology) are not
  authored yet.
- Generalized reconstruction (Slice 3): the orbit visual hull
  exists as proven single-subject code in bio-3d/stage5 and
  stage7 and has not been packaged into this repo yet. The
  COLMAP plus Open3D path is blocked on a host decision: neither
  library is installed in this VM, there is no GPU, and RAM is
  about 7.7 GB. No reconstruction timing may be claimed until
  measured on the chosen host.
- GNM Head fit and morph transfer (Slice 4): blocked on vendoring
  the GNM assets (pin commit dfd3e4b, record file hashes) and on
  the ARKit retarget question documented in RESEARCH section 5.
  FLAME pre-2023 weights remain excluded (non-commercial, signup
  gated); Depth Anything V2 Base / Large / Giant weights remain
  excluded (CC-BY-NC); only the Small weights are cleared.
- USDZ (Slice 5): static pose only, via the proven pxr route in
  bio-3d/ar. Animated USDZ is unproven in Quick Look and is not
  promised.
- Decisions that stay Aries's (RESEARCH section 14): the repo
  name and the publish word before anything goes public, the
  compute host for heavy stages, and approval of the capture
  bundle spec.

## Second pass (2026-11-20): bundle loader, backend, frontend

### Slice 0 remainder: capture bundle loader (RESEARCH section 10)

- `backend/bundle_loader.py`: validates and loads a bundle from a
  directory or a .claybundle.zip. Exactly one regime per bundle
  (A orbit video, B photo set, C pre-captured RGB-D); mixed
  bundles are rejected. SHA-256 record must cover every file
  except manifest.json itself (a manifest cannot carry its own
  hash; the spec text is read that way and the loader docstring
  says so). Regime A probes the video with ffprobe (frame count
  against the 24 frame minimum; the 360 degree span is recorded
  as not measurable by the validator). Regime B decodes every
  photo and reports coverage from filename hints, labeled in the
  output as a hint report, not a vision measurement. Regime C
  requires a pose and a 16-bit depth PNG per frame and a true
  intrinsics_K; frames without a pose are dropped with indices
  listed, per spec. Intrinsics are validated when present and
  estimated from frame size when absent (regimes A and B only),
  always recorded with estimated: true and a warning that quality
  is unmeasured. Front-camera mirror normalization happens on
  ingest: images flipped with Pillow, video hflipped through
  ffmpeg, Regime C poses conjugated by the mirror matrix, and
  the normalized manifest records that it happened. Words are
  checked for contiguous indices, single-word text (a two-word
  clip is a validation error), matching hashes, and decodable
  WAV; long clips are flagged, never auto-split. Output is a
  normalized bundle-manifest.json in a new job directory with a
  local job ID.
- `tests/test_bundle_loader.py`: 15 tests, all passing. Valid
  bundles of each regime, zip source, short video rejection,
  corrupt hash rejection, corrupt image rejection, two-word clip
  rejection, mixed regime rejection, missing intrinsics
  estimation, mirror flip pixel correctness, mirrored video
  normalization, pose-less RGB-D frame drop, Regime C true
  intrinsics requirement, and an Android RGB-only photo bundle
  accepted.

### Backend shell (RESEARCH section 3)

- `backend/app.py`: FastAPI, one process, filesystem job
  directories, no auth, localhost only. Endpoints: POST
  /api/bundles (validate and open a job; invalid bundles return
  422 with the full loader report), GET /api/jobs/{id}, POST
  /api/jobs/{id}/lipsync (runs lipsync_align over the job word
  clips and stores keyframes.json), POST /api/mesh-glb (packs an
  NPZ mesh upload, optional morph deltas, optional keyframes
  JSON as the weights animation, through glb_exporter), GET
  /demo/clay-bust-v3.glb (streams the bio-3d fixture on this
  machine only; it is not part of any package), and the frontend
  mounted at the root.
- `tests/test_app.py`: 4 TestClient smoke tests (health and
  index, bundle to lipsync to GLB round trip, invalid bundle
  422 with report, unknown job 404). FastAPI is not a system
  package in this VM (PEP 668), so the tests skip under the
  system interpreter and were run green in a venv with fastapi,
  httpx, and python-multipart installed from PyPI.

### Slice 1: frontend (RESEARCH sections 2 and 9)

- `frontend/index.html`: mobile-first single page, steps Upload,
  Sculpt, Lip-Sync, Grade, Export. Three.js pinned at 0.164.1 by
  import map, the twin's exact version.
- `frontend/viewer.js`: Three.js stage, clay lighting rig, and
  the grade injected into the clay MeshStandardMaterial after
  the colorspace fragment, so grade() from
  shaders/clay_grade.frag (fetched and applied verbatim, one
  source of truth with the parity test) receives
  display-referred color. Morph targets surface through
  GLTFLoader; weights apply by viseme name.
- `frontend/app.js`: bundle upload to the backend, GLB file and
  demo fixture loading, the word-clip sequencer (Web Audio
  decode, keyframes by file or from the backend aligner, morph
  playback on the audio clock with a silent-clock fallback, word
  highlighting), all grade sliders (CMY per zone, K gain, K
  gamma with the above-zero floor, RGB lift / gamma / gain),
  GLB and keyframes downloads, and video export using Reactor's
  captureStream(30) plus MediaRecorder pattern with its MIME
  fallback list verbatim (MP4 first, the entry iOS Safari
  records).
- Headless verification (frontend/verify/verify_frontend.cjs,
  the twin's pattern: local server, three.js CDN intercepted
  from byte-identical local copies, puppeteer): the fixture GLB
  built by frontend/verify/make_fixture.py from the real v3
  clay bust (235,600 vertices, 15 viseme targets with crude
  mouth-region deltas, labeled test scaffolding) loads with all
  15 morph targets; driving the real grade sliders changed the
  rendered pixel mean by (9.00, 5.86, 5.48) in RGB and the
  graded screenshot shows the cyan ink tint on the clay; the
  sequencer animated morph influences to a 0.887 peak on the
  test keyframes and returned them to exactly zero at the end;
  zero page errors, zero console errors, zero bad responses.
  Results in frontend/verify/verify-results.json, screenshots
  studio-before-grade.png and studio-after-grade.png beside it.
  The iPhone sensory check remains Aries's gate; nothing here
  claims it.

### Bug found by this pass in the first-pass exporter

- Three.js GLTFLoader rejected the exporter's sparse morph
  accessors: the first pass wrote sparse.indices and
  sparse.values as accessor indices, a private convention its
  own reader shared, so its tests passed while no standard
  loader could read the files. The glTF 2.0 spec format names a
  bufferView object in each. glb_exporter.py now writes the
  spec format, read_accessor reads the spec format, and the
  exporter tests assert the spec shape (indices and values are
  bufferView objects, the sparse accessor carries no bufferView
  of its own). All 10 exporter tests pass on the corrected
  format, and the fixture above is the proof at bust scale: a
  standard loader opens it.

### Test totals after the second pass

- tests/test_grading_parity.py: 6 passing.
- tests/test_lipsync_align.py: 12 passing.
- tests/test_glb_exporter.py: 10 passing (format corrected, see
  above).
- tests/test_bundle_loader.py: 15 passing.
- tests/test_app.py: 4 passing in the FastAPI venv, skipped
  under the system interpreter (FastAPI not installed there).
- Total: 47 tests. System interpreter: 47 run, OK, 4 skipped.
  Venv interpreter: 47 run, all OK.
  Run with: python3 -m unittest discover -s tests
- Frontend headless verification: exit 0, all checks above.

### What remains after the second pass

- STL download in the frontend export step (binary STL writer
  is still Slice 5 scope in the research order): BUILT in the
  third pass, below, together with static USDZ.
- Morph targets authored on the real bust topology (Slice 2
  remainder, unchanged): the fixture deltas are scaffolding.
- Generalized reconstruction (Slice 3) and the COLMAP plus
  Open3D path: blocked on the compute host decision, as before.
- GNM Head fit and morph transfer (Slice 4): blocked on
  vendoring the GNM assets and the ARKit retarget question.
- USDZ (Slice 5): static pose only via the proven pxr route;
  animated USDZ is unproven in Quick Look and is not promised.
- Decisions that stay Aries's: repo name and publish word,
  compute host, capture bundle spec approval, and the iPhone
  sensory pass on this frontend.

## Third pass (2026-11-20): export completion, STL and USDZ

### Slice 5: binary STL (RESEARCH sections 7 and 8, Step 18)

- `backend/stl_exporter.py`: self-written binary STL writer,
  pure stdlib plus NumPy, from the same positions and indices
  the GLB path uses (arrays or NPZ bytes). 80-byte zero header,
  uint32 triangle count, 50-byte records with per-face normals
  computed from the geometry and the attribute byte count zero
  in every record. A matching parse_stl reader round trips the
  writer field by field. Degenerate (zero area) triangles are
  written, never dropped, with a zero normal; face_normals
  returns the degenerate mask and build_stl_report counts them,
  so the handling is labeled in data, not silent. A scale
  argument (default 1.0, the input units) exists for fabrication
  targets expecting millimeters and is recorded in the report.
  The module docstring states what STL does not carry: morph
  targets, animation, vertex colors, materials, and the grade.
- `tests/test_stl_exporter.py`: 9 tests, all passing. Header and
  count fields, attribute byte counts zero, exact tetrahedron
  normals, the tilted plane (z = x) normal (-1, 0, 1) / sqrt(2),
  vertex round trip, the degenerate case (counted in the
  report, zero normal in the file, face still present), scale
  applied to vertices and not normals, NPZ input identical to
  array input, and shape error cases.

### Slice 5: static USDZ (RESEARCH section 8, Step 18)

- `backend/usdz_exporter.py`: the proven pxr route from
  bio-3d/ar/convert_usdz.py, adapted to the studio mesh input.
  One /ClaySculpt default prim (Y-up, metersPerUnit 1), one
  Mesh with smooth normals (the GLB writer's helper), a clay
  UsdPreviewSurface (neutral 180 gray, roughness 0.95), and
  UsdUtils.CreateNewUsdzPackage for the stored ZIP. Static
  neutral pose only: the docstring states that Quick Look drops
  morph targets and vertex animation from USDZ, so animated
  USDZ is not promised anywhere in this studio. pxr is imported
  lazily; where it is missing, build_usdz raises the labeled
  UsdzUnavailable and the backend answers 501 with the reason.
- `tests/test_usdz_exporter.py`: 4 tests. Under the system
  interpreter (no pxr) the three package tests skip with the
  reason stated, and the unavailable-contract test passes. In
  the bio-3d/ar venv, where pxr lives, the three package tests
  pass for real: the package is a stored ZIP, the stage opens
  with the default prim, up axis, meters per unit, the exact
  points, face counts, and indices of the tetrahedron fixture,
  and NPZ input works. The contract test skips there (pxr is
  available). No pass is claimed for an environment that did
  not run the code.

### Wiring: backend endpoints and the frontend Export step

- `backend/app.py`: POST /api/mesh-stl and /api/mesh-usdz take
  the same NPZ upload as /api/mesh-glb; POST /api/glb-stl and
  /api/glb-usdz take a GLB upload and export its first mesh
  primitive through the studio's own GLB reader. The STL
  response headers carry the triangle and degenerate counts.
  The USDZ endpoints answer 501 with the pxr reason when pxr is
  absent, never a fake package. tests/test_app.py grows to 6
  tests: mesh-stl and glb-stl byte checks, and a USDZ status
  test that asserts 200 with a PK package when pxr is available
  in the server environment and the honest 501 when it is not
  (the FastAPI venv run exercised the 501 path; the 200 path is
  covered at module level in the pxr venv, as recorded above).
- `frontend/index.html`: the Export step gains a Download STL
  and a Download USDZ button beside GLB, keyframes, and video,
  with copy stating exactly what each format carries and does
  not carry (STL static geometry only; USDZ one static neutral
  pose, no morphs or animation, no grade).
- `frontend/app.js`: the STL button builds the binary STL in
  the page from the stage geometry (neutral pose, world
  transforms applied), mirroring the backend writer's format.
  The USDZ button posts the loaded GLB to /api/glb-usdz and
  surfaces the backend's reason verbatim when it cannot build
  one, including when the page is not served through the
  backend.
- Headless verification (verify_frontend.cjs, extended): the
  fixture and the local three.js CDN copies had to be rebuilt
  first (both lived in /tmp and were gone; make_fixture.py
  regenerated the fixture, the CDN files were re-fetched from
  jsDelivr at the pinned 0.164.1). Two harness findings. First,
  the morph peak is now recorded in the page by wrapping
  applyWeights: external polling at 100 ms intervals read 0.000
  on two consecutive runs because the 0.82 second playback
  finished between evaluate round trips under SwiftShader,
  while an in-page probe showed the sequencer applying a 0.978
  peak over 30 steps; the harness now measures what the
  sequencer applied (0.958 this run) and still asserts the
  influences end at exactly zero. The app code was not changed
  for this; the defect was in the measurement. Second, the new
  export checks: both buttons render enabled after the model
  loads, and a real click on the STL button downloaded
  fixture.stl, 23,568,284 bytes and 471,364 triangles, with the
  count field at byte 80 exactly consistent with the byte
  length. Grade pixel delta reproduced the second pass numbers
  exactly (9.00, 5.86, 5.48). Zero page errors, zero console
  errors, zero bad responses; exit 0. Results in
  frontend/verify/verify-results.json.

### Test totals after the third pass

- tests/test_grading_parity.py: 6 passing.
- tests/test_lipsync_align.py: 12 passing.
- tests/test_glb_exporter.py: 10 passing.
- tests/test_bundle_loader.py: 15 passing.
- tests/test_app.py: 6 passing in the FastAPI venv, skipped
  under the system interpreter.
- tests/test_stl_exporter.py: 9 passing.
- tests/test_usdz_exporter.py: 4 tests; 1 passing and 3 skipped
  (pxr absent) under the system interpreter, 3 passing and 1
  skipped in the bio-3d/ar pxr venv.
- Total: 62 tests. System interpreter: 62 run, OK, 9 skipped.
  FastAPI venv: 62 run, OK, 3 skipped (the pxr package tests).
  Run with: python3 -m unittest discover -s tests
- Frontend headless verification: exit 0, all checks above,
  including the STL download header validation.

### What remains after the third pass

- Morph targets authored on the real bust topology (Slice 2
  remainder, unchanged): the fixture deltas are scaffolding.
- Generalized reconstruction (Slice 3) and the COLMAP plus
  Open3D path: blocked on the compute host decision, as before.
- GNM Head fit and morph transfer (Slice 4): blocked on
  vendoring the GNM assets and the ARKit retarget question.
- USDZ on the iPhone: the package structure is verified here;
  Quick Look playback of the static USDZ is Aries's sensory
  gate, as is the frontend as a whole. Animated USDZ remains
  unproven and unpromised.
- Decisions that stay Aries's: repo name and publish word,
  compute host, capture bundle spec approval, and the iPhone
  sensory pass.

## Owner decision: dual compute backends, user preference (Nov 23, 2026)

Aries reviewed an external pipeline diagram that placed Reconstruct,
Clay sculpt, and Rig/lip-sync "in the cloud (GPU)" and directed: the
heavy stages can be set up to run in BOTH places, as a user
preference. Recorded as the compute-host decision for this app:

- The three heavy stages (Reconstruct, Clay sculpt, Rig and
  lip-sync) sit behind one job interface with two runners: Local
  (self-hosted backend, the existing FastAPI service) and Cloud GPU
  (an opt-in remote runner).
- Local is the default. Cloud is the user's choice, never a
  requirement; the zero-external-API, no-account path stays whole
  for users who never enable it.
- Capture, Color grade, and Export are on-device in both modes and
  do not change.
- This resolves the "compute host" owner call: it is no longer a
  single host decision. Still Aries's alone: repo name and publish
  word, capture bundle spec approval, the iPhone sensory pass, and
  the word to build the cloud runner itself.

## Name decided: SculptViseme (Nov 23, 2026)

Aries asked for a name that matches what the app technically does
and chose SculptViseme: the sculpt (capture, reconstruction, and
non-rigid fit into a clay bust) plus the viseme (the unit the
lip-sync engine maps speech to). Clearance run the same day, at
the standard used for VariTheory:

- GitHub: Frozen-In-Flames/sculptviseme and sculpt-viseme both
  free; zero repositories and zero code mentions of the name
  anywhere on GitHub.
- Web: no product, app, or software named SculptViseme; nearest
  neighbors are distinct names in distinct lanes (ViSculpt, an
  arXiv mesh-editing research system; VisemeMaker, a VRChat
  viseme tool; FaceSculpt AI, a face-tracking app).
- Trademark: no mark named SculptViseme surfaced in
  trademark-targeted search.
- Domain: sculptviseme.com unregistered (Verisign RDAP 404).

The repo-name gate is answered. Creating or publishing the repo
still waits on Aries's publish word.

## Named SculptViseme; dual runners built; published (Nov 23, 2026)

Aries chose the name SculptViseme (sculpt + viseme; clearance
recorded above). On his go-ahead, the dual-runner build and the
publish both landed the same night:

- Backend: one codebase, two modes. SV_MODE=cloud with
  SV_API_TOKEN (bearer gate on job/export endpoints, health open)
  and SV_CORS_ORIGINS. Local stays the default: localhost, no
  token. Health reports app, mode, and auth_required.
- Frontend: a Compute setting (This device / Cloud runner, URL +
  token, localStorage) routes all job calls; a Check button reads
  the runner's health and reports its mode. All three API call
  sites and the USDZ export go through the one helper.
- Deployment: requirements.txt + Dockerfile (python:3.12-slim,
  SV_MODE=cloud, jobs on a volume).
- three.js vendored (r164, MIT license file included): the
  frontend previously imported three from the jsDelivr CDN, which
  contradicts the zero-external-dependency design and made the
  page dead wherever the CDN is unreachable. The importmap now
  points at frontend/vendor/; the page makes zero external
  requests.
- Defect found by live verification and fixed: the token gate
  answers before the CORS middleware, so its 401 carried no
  Access-Control-Allow-Origin header and a browser reported a
  wrong token as a network failure. The 401 now echoes the
  configured origin; a regression test holds it.
- Verification: suite at 71 tests, all passing (3 pxr skips as
  before). Live two-server run through the real frontend: local
  health check, cloud health check, a bundle job opened and
  lip-sync executed on the cloud runner cross-origin with the
  token, a wrong token answered "Bundle rejected: 401", no page
  errors; the vendored viewer loaded the real v3 bust
  (235,600 vertices).
- Published: github.com/Frozen-In-Flames/sculptviseme (public,
  Apache-2.0). No GitHub Pages demo: the application is a
  self-hosted tool whose steps need its backend; the README
  quickstart is the entry point. The Hugging Face mirror follows
  the standing batch cadence (~March 2027).

## Slice 2: production viseme authoring (Nov 23, 2026)

- backend/viseme_authoring.py: the 15 viseme targets are sums of
  five articulation primitives (jaw_open, lip_close, lip_round,
  lip_spread, lip_tuck) over smooth anisotropic fields in units
  of mouth width; the per-viseme combination table is documented
  per articulation. No hard boxes, no step weights (the fixture
  scaffolding had both).
- Landmarks are an input with an estimator: locate_mouth reads
  the central column's front profile, takes the longest
  near-planar band as the face (the v3 bust's face is a relief:
  profile z 0.63-0.67 flat from y -0.96 to +0.33, so profile-peak
  methods have nothing to find), places the mouth 48% up the
  band, set back 9% of band height, width 42% of the bust's
  cross-section at mouth height. Estimate on the v3 bust:
  center (0.036, -0.295, 0.552), width 0.405, against the
  hand-tuned fixture center (0, -0.35, 0.55). Regression-tested.
  Two estimator defects were caught by measurement and fixed
  before shipping: naive nose/chin proportions (the bust runs
  well below the chin) and width from the near-front patch
  (0.226, several times too small on a relief).
- POST /api/mesh-author-visemes: NPZ in, authored NPZ out
  (morph_names + morph_i), landmarks echoed in a response
  header; the output feeds /api/mesh-glb unchanged (tested).
- 12 new tests (83 total, 3 pxr skips as before): articulation
  direction (PP gap closes >2x, aa opens >1.5x, ou corners in
  + lips forward, FF lower lip up and in), smoothness, bounded
  support, landmark-shift negative control, determinism, GLB
  round-trip, estimator regression, endpoint round-trip + 422.
- The verification fixture now authors through the production
  module (estimated landmarks); frontend verification re-run
  green: 15 targets load, sequencer peak influence 0.902 and
  zero at the end, STL export 471,364 triangles, no errors.
- Sensory pass (screenshots, sil vs aa at full influence): the
  lower face drops and elongates smoothly, no tearing; sil is
  untouched. Honest limit, now stated in the README: the clay
  relief has no sculpted lip topology, so targets move the
  mouth region correctly without a lip line to articulate; the
  GNM fit stage is what brings lip topology.

## Slice 3: reconstruction + fit stages (Nov 23, 2026)

- backend/reconstruction.py: generalized visual hull. Orbit
  silhouette masks (orthographic turntable model, documented)
  carved into voxels, naive surface net to a mesh, plus
  silhouette_from_plate (empty-plate differencing) for capture
  matting. POST /api/mesh-reconstruct serves it statelessly.
  Oracle: analytic sphere silhouettes -> volume within 3% at
  grid 48, centroid exact; controls assert the hull contains
  the shape, 4 views loosen it >10% vs 24, azimuth labels
  rotated 90 degrees measurably misplace an off-center sphere,
  and a bored cylinder comes back filled (the documented
  concavity limit).
- backend/head_fit.py: the fit engine. Umeyama landmark init +
  non-rigid ICP, trimmed one-way matching, Laplacian stiffness
  decaying 8 -> 0.35. One real defect was caught by the
  convergence test and root-caused with an identity probe: the
  first implementation put the Laplacian on absolute positions,
  which shrinks the mesh toward local centroids (one step moved
  mean error 0.065 -> 0.588). The shipped form acts on the
  deformation (Amberg et al.), making the identity target an
  exact fixed point at any stiffness; that probe is now a
  regression test.
- backend/colmap_stage.py: the COLMAP photo route behind a
  detection gate (pycolmap or CLI), honest refusal when absent,
  CLI pipeline implemented against the documented interface.
- GNM assets NOT vendored: the clone of google/GNM was stopped
  after the environment's execution-risk check flagged the
  third-party content; no GNM code or assets were read, run, or
  copied. head_fit.gnm_status() reports unavailable with the
  pinned commit (dfd3e4b) and load_gnm_template() refuses.
  Vendoring is a separate step taken with the owner.
- GET /api/health now reports both stage gates live.
- 17 new tests (100 total, 3 pxr skips as before).

## Slice 3b: GNM vendored, first real fit (Nov 23, 2026)

- Owner approved the vendoring explicitly after the
  execution-risk flag was explained. Source: google/GNM at
  dfd3e4b (the RESEARCH pin); the model data does not live in
  the repo, it is one npz served from the project's Hugging
  Face repo (google/gnm-v3, v3_0/gnm_head.npz, 53 MB,
  sha256 61d78bbf...). Extracted with build_asset.py: skin
  component only (12,466 of 17,821 verts; 24,820 tris), the 68
  sparse landmarks (max-barycentric-weight vertex, all on
  skin), upper/lower lip vertex sets. Asset is 457 KB;
  provenance + hashes in backend/assets/gnm/VENDOR.md.
- First real fit: GNM template -> v3 clay bust face region
  (39,721 target points), 5 landmarks (chin, nose tip, mouth
  center + corners; bust side estimated), 30 iterations, 10 s.
  Mean surface distance 0.534 -> 0.0274 bust units; max 0.745
  (back of head/neck, where the relief target has no surface).
  Fitted mouth from inherited landmarks: center
  (0.041, -0.299, 0.664), width 0.405, against the bust's
  measured (0.036, -0.295), 0.405. Note: locate_mouth's
  estimator misreads the fitted full head (it was built for
  relief busts); on fitted meshes the inherited landmarks are
  the correct source, and were used.
- Visemes authored on the fitted mesh from its landmarks and
  exported as a GLB with all 15 morph targets (2.8 MB).
  Sensory screenshots (sil vs aa): the fitted head has a real
  lip line with an opening the relief never had, and aa drops
  the jaw and opens the mouth. Honest limits: the relief's
  striations transfer into the fit, the surface is lumpy, and
  the lip corners tear slightly at full influence. A working
  chain, not a likeness. Refinement path is in the README.
- 101 tests (new: vendored template load + landmark sanity;
  the refusal test now skips, as designed, where vendored).
