# Clay Sculpt & Lip-Sync Studio — Research Report (Priority 4)

Prepared: 2026-11-19 (America/Chicago)
Status: **Research only. Nothing built, published, or downloaded in this pass.**
Order: Aries, Nov 19 2026 — "Build that whole app! But first research more on how to do each part!"
Follow-up order Nov 19 23:53 UTC: complaints parked; labor first — GitHub audit, then this app.

## 0. Which blueprint governs

Two documents arrived together and contradict each other on hosting:

| Source | Hosting model | Verdict |
|---|---|---|
| PDF blueprint, 9 pp. (`~/workspace/user/files/4D_Clay_Sculpt___Lip-Sync_Studio_Technical_Blueprint.pdf`, created 2026-11-19 08:53 UTC) | Hybrid mobile-cloud: cloud GPU workers (A10G/L40S/A100), FLAME + N-ICP, WhisperX / Montreal Forced Aligner, React/TypeScript + Capacitor | **Superseded on hosting and on FLAME/WhisperX.** Its math (projection, bundle adjustment, TSDF, Taubin, N-ICP objective, viseme table, CMYK equations) is retained as reference. |
| Aries's pasted stack map + 20-step architecture, chat Nov 19 09:23–09:24 UTC, plus his `gradeCMYK` shader at 09:02 UTC | Self-hosted, zero external API, zero signup, no auth gates, no third-party API keys. Plain HTML5/ES6 + Three.js frontend, local FastAPI backend, COLMAP + Open3D, GNM Head (Apache 2.0), word-by-word G2P lip-sync, self-written GLB packer | **Governs.** Matches his standing terms: $0 budget, no cloud trial that enrolls his identity, no paywalled service on his account, standards-first / open-web build doctrine. |

Every choice below is checked against the governing version. Where the PDF names a gated or cloud component, the open local alternative is named in its place and the gated component is flagged, not silently dropped.

**Non-negotiable constraints carried into every part:**
- Self-hosted only; no external API calls at runtime, no signup, no auth gate, no API keys.
- FLAME pre-2023 weights must NOT be used or bundled (see §5).
- `gradeCMYK` is Aries's supplied code, carried forward verbatim; RGB lift/gamma/gain runs after it.
- Likeness claims equal measurements. His own bust measured 0.895 mean silhouette IoU — never "100%".

---

## 1. Inventory first — what already exists, per blueprint part

Checked 2026-11-19/20: `~/workspace/bio-3d/`, `~/workspace/voice-asset-format/`, `~/workspace/reactor/`, `~/workspace/theory-engine-studio/` (VariTheory), `~/workspace/collaborative-midi/`, `~/workspace/frozen-in-flames-kindling/`, `~/workspace/midi-vocal-trainer/`, `~/workspace/fif-ears/`, `~/workspace/bio-3d/bio-draft/twin.html`, and the goal briefs in `~/workspace/goals/4d-clay-sculpt-lip-sync-studio/briefs/`. Gaps are named only where no inventoried build implements the part.

| # | Blueprint part | Inventory match | State |
|---|---|---|---|
| 1 | Clay bust from own capture (reconstruction) | `bio-3d/stage5/` + `stage7/`: `orbit_carve.py`, `orbit_track4k.py`, `fine_carve.py`, `photometric.py`. Output of record: `bio-3d/aries-bust-clay-v3.glb` — 71,524 verts / 143,064 faces (v3 refined hull; stage-7 report), watertight, mean silhouette IoU **0.895**, worst view 0.835. STL/PLY/OBJ in `bio-3d/aries-bust-3d-files/` with `MANIFEST.md`. | **Proven, single-subject.** Visual-hull carve from a 4K orbit video (2160×3840, 60 fps, 30 views). Generalizing to arbitrary users is the gap, not the carve itself. |
| 2 | Clay material / monochrome look | Same carve pipeline; Aries's Nov 16 verdict: clay monochrome approved, color version rejected as the default face. Twin stage rig in `bio-draft/twin.html` (Three.js 0.164.1, calibrated lights, sRGB→linear COLOR_0 fix). | Proven pattern to copy. |
| 3 | Talking-bust / viseme ground truth | `bio-3d/google-avatar/clay-talking-bust.mp4` — 10 s talking clay bust (mouth, teeth, blinks, ±25° sway, front hemisphere only). | Reference footage only; no profile/back viseme data. |
| 4 | Phoneme → viseme map (15 visemes) | `voice-asset-format/examples/aries-hilton-reference/phonemes.json` — complete ARPAbet (39 phonemes + SIL) → 15-viseme map: `sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, ih, oh, ou`. Identical set to the Voice Asset Format SPEC §6.1. Plus `pronunciations.json` override table. | **Done.** Reuse verbatim; do not invent a second map. |
| 5 | Word-by-word voice data format | Voice Asset Format `.voicepack` (ZIP, mandatory provenance + SHA-256 per file, `tools/voicepack.py` 16/16 tests); Kindling V27 word calibration from Aries's own takes (`frozen-in-flames-kindling/`). | Format exists. Lip-sync consumes this convention. |
| 6 | RMS / audio analysis | `fif-ears` (deterministic audio analysis, v0.1.0); Kindling voice assets. | Adjacent plumbing exists; the per-clip RMS envelope scaler itself is new, small, pure NumPy. |
| 7 | GLB reading / writing / animation injection | `bio-3d/stage7/recolor_v4.py` / `recolor_v5.py` / `recolor_v5_1.py`: hand-rolled GLB parser (JSON chunk + accessor/bufferView byte access, geometry byte-identical proofs). `bio-3d/ar/build_avatar.py`: trimesh scene export to GLB + **pygltflib animation-channel injection** (breathing/sway samplers). | GLB *editing* and *animation injection* proven. A from-scratch packer that writes **morph targets** is the gap. |
| 8 | USDZ export | `bio-3d/ar/convert_usdz.py`: working Pixar `pxr` (Usd/UsdGeom/UsdShade) converter, GLB hierarchy → USD Xform prims, node animation as time samples, outputs `bio-3d/ar/avatar.usdz`. Plus `ar/usdz_src/avatar.usda`. | **Proven for node animation.** Morph-target USDZ is a different problem (see §8). |
| 9 | STL export | `aries-bust-3d-files/aries-bust-clay.stl` already exported from the bust. | Trivial; binary STL writer is ~30 lines. |
| 10 | Video export from browser canvas | `reactor/index.html` (live v1.1.0), lines 50 + 189: `canvas.captureStream(30)` + `MediaRecorder`, MIME fallback list `['video/mp4;codecs=avc1.42E01E,mp4a.40.2', 'video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm']`, 8 Mbps. | **Proven pattern — copy verbatim.** Do not design a new exporter first. |
| 11 | Three.js viewer discipline | Bio twin (`bio-draft/twin.html`), Polyglot Procedural Engine v3.3.0, VariTheory (single-file, zero network calls in operation). | Proven. |
| 12 | CMYK grade shader | Aries supplied `gradeCMYK()` GLSL in chat Nov 19 09:02 UTC: additive ink by tonal zone (`inkShadow/inkMid/inkHigh` as CMY vec3s), `k = 1 − max(R,G,B)`, `cmy = (1 − c − k)/max(1−k, 1e-4)`, zone weights from luminance (shadow `1−smoothstep(0.15,0.5,l)`, highlight `smoothstep(0.5,0.85,l)`), `k = clamp(kGain·pow(k,kGamma))`, return `(1−cmy)·(1−k)`. RGB lift/gamma/gain after. | **Code already written by Aries.** Remaining work is the NumPy parity reference + 1e-5 test. Note: this additive-ink formulation differs from the PDF's subtractive UCR/GCR equations (§7.1 of PDF) — Aries's version governs. |
| 13 | COLMAP / Open3D reconstruction | No code in workspace. VM check Nov 19–20: 4 CPUs, ~7.7 GB RAM, Python 3.12.3, numpy 1.26.4 + scipy 1.11.4 only; **no COLMAP, no Open3D, no PyTorch, no trimesh/pygltflib importable in the main env, no Blender, no GPU**; ffmpeg present at `/usr/bin/ffmpeg`. | **Gap — and a host gap.** Cannot be proven in this VM as-is. |
| 14 | GNM Head fit / non-rigid ICP | No code in workspace. Existing carve is a visual hull, not a template fit. | **Gap.** New module `head_fit.py`. |
| 15 | G2P (word → ARPAbet) | Only the 6-word `pronunciations.json` override table. No dictionary, no rule engine. | **Gap.** CMUdict route in §6. |
| 16 | Capture bundle handling | No bundle loader. Conventions exist to copy: `.voicepack` ZIP + manifest + hashes; bust MANIFEST camera record (K scale 340 px/unit at 720-wide masks, principal point cu 362.39, per-view cv, elev 10°, face +Z, unmirrored). | **Gap.** Spec drafted in §10 below. |

**Inventory conclusion:** roughly half the app already exists as proven code — carve, viseme map, word-clip format, GLB editing + animation injection, USDZ node-animation converter, video export, viewer, and the grade shader itself. The genuinely new engineering is: (a) generalized reconstruction (COLMAP path), (b) GNM fit + morph transfer, (c) G2P + RMS viseme curves, (d) morph-target GLB packing, (e) the bundle loader/validator, (f) the NumPy grade-parity reference.

---

## 2. Frontend & capture (Steps 1–3)

**Chosen method:** Plain HTML5 + ES6 JavaScript, Three.js via import map (pin `three@0.164.1`, the exact version the bio twin already ships), `<input type="file">` + `getUserMedia()` for capture, Web Audio API for word-clip recording. No framework, no build step, no analytics/auth SDK. Served as static files by the local FastAPI app or any static host.

| Component | License | Local route |
|---|---|---|
| Three.js 0.164.1 | MIT | CDN import map (as twin) or vendored copy for fully offline use — vendoring is preferred for the zero-external-API claim; the twin's CDN pattern is the fallback. |
| Browser APIs (`getUserMedia`, Web Audio, File) | W3C standards, no license | Native. Requires secure context (HTTPS or localhost). |

**Hard platform fact — LiDAR:** No browser API exposes iPhone LiDAR depth or ARKit poses. Safari on iPhone also has no WebXR `immersive-ar` for web pages (checked Nov 2026 sources). `getUserMedia` gives RGB only. Therefore:
- Regime C (RGB-D) bundles are **pre-captured** (native app / ARKit capture exported as a zip), never live in-browser LiDAR.
- The UI must not promise live depth capture in Safari.

**Untested:** capture flow on Aries's iPhone 15 Pro Max in Safari (resolution constraints are device-specific; iOS rejects arbitrary `getUserMedia` resolutions with `OverconstrainedError`).

## 3. Backend shell (Step 3)

**Chosen method:** FastAPI local job queue — one process, filesystem job directories, no database, no auth, binds localhost / tailnet only.

| Component | License | Notes |
|---|---|---|
| FastAPI | MIT | Verified via license listings Nov 2026. |
| Uvicorn / Starlette (FastAPI deps) | BSD-3-Clause | Standard. |
| NumPy / SciPy | BSD-3-Clause | Already in VM (1.26.4 / 1.11.4). |

**Untested:** nothing material; this is the lowest-risk part of the stack.

## 4. Reconstruction (Steps 4–6)

Three regimes, one router. This ordering matters: the proven path ships first.

### 4a. Orbit video → visual hull (v1 primary)
- **Method:** Aries's existing carve — silhouette masks per view → voxel carve → marching cubes → photometric displacement refinement (`stage5/`, `stage7/`). Pure NumPy/SciPy + PIL, all already in the VM.
- **License:** own code; NumPy/SciPy BSD.
- **Why primary:** it is the only reconstruction route with a measured result on his own capture (IoU 0.895). The capture UX guides the user into a turntable orbit, which is exactly the input this method needs.
- **Limits (state them in the UI):** silhouette-true; deep concavities (eye sockets, under-beard shadow) are bounded, not carved; requires ~360° coverage (his carve used 30 views).

### 4b. Unordered photo set → COLMAP + Open3D (v2 path, behind a flag)
| Component | License | Local route |
|---|---|---|
| COLMAP 4.2.1 (current, Oct 2026) / pycolmap | **BSD 3-Clause** (new BSD; changed from GPL in 3.5, 2018). Commercial use permitted. Caveat in `COPYING.txt`: building with certain dependencies (CUDA/Qt) can affect the combined license — use the CPU/headless build and record dependency licenses at pin time. | `pip install pycolmap` (wheels on PyPI; CUDA12 wheels separate as `pycolmap-cuda12`) or system COLMAP CLI. Since 3.10 pycolmap lives in the main COLMAP repo; 4.0 added GLOMAP global SfM. |
| Open3D | **MIT** (Intel ISL; not O3DE — a different project). Screened Poisson: `create_from_point_cloud_poisson`, plus TSDF volumetric integration, ICP (point-to-point / point-to-plane), ball-pivoting. | `pip install open3d` (or `open3d-cpu`). |

- **Method:** COLMAP SfM (feature extraction → matching → incremental/global mapper → bundle adjustment, Huber-robust per PDF Eq. 2.1) → MVS dense depth → depth back-projection (PDF Eq. 2.2) → TSDF fusion (Eq. 2.3) and/or Open3D Screened Poisson → watertight mesh → Taubin λ|μ smoothing (PDF Eq. 3.1, volume-preserving).
- **Untested / blocker:** neither library is installed in this VM; no GPU; 7.7 GB RAM caps dense MVS size. No reconstruction time may be claimed until one real orbit set is timed on the chosen host (see Decisions).

### 4c. Single photo → monocular depth fallback
| Component | License | Verdict |
|---|---|---|
| Depth Anything V2 — code | Apache 2.0 | OK. |
| Depth Anything V2 — **Small** weights | **Apache 2.0** | **Only size cleared for bundling.** ~95 MB safetensors. |
| Depth Anything V2 — Base / Large / Giant weights | **CC-BY-NC-4.0 (non-commercial)** | **FLAGGED — do not bundle.** Same trap class as FLAME: code license ≠ weights license. |
| PyTorch (runtime for the weights) | BSD-3-Clause | Not in VM; install is large (~2 GB+). Another reason this stays a fallback. |

- **Method:** Small weights only, cached locally after a one-time download Aries approves; relative (not metric) depth → back-project with estimated K → symmetry prior for the occluded side. Output must be labeled a fallback estimate, never measured geometry.
- **Alternative if Small's quality fails:** MiDaS small models are MIT-licensed (code and weights) — lower fidelity, cleaner license. Decide only after a side-by-side on his portrait.

## 5. Head fit — GNM Head, and the FLAME flag (Steps 7–9)

| Component | License | Verdict |
|---|---|---|
| **GNM Head** (`github.com/google/GNM`, verified live 2026-11-20: public, Apache-2.0, 1,646 stars, 178 commits, no releases/tags yet) | **Apache 2.0** — repo states "suitable for both non-commercial and commercial applications" | **Chosen.** Parametric head: identity + expression + pose, internal anatomy (eyeballs, teeth, tongue), backends NumPy / JAX / PyTorch / TensorFlow. Paper arXiv:2607.23687. NumPy backend matters: it can run in this VM without PyTorch. |
| FLAME 2017 / 2019 / 2020 / 2023 (standard) | Max Planck **non-commercial scientific research only**, single-user, non-transferable, **signup + license acceptance required to download** (verified at flame.is.tue.mpg.de/modellicense.html) | **FLAGGED — MUST NOT be used or bundled.** Every repo user would inherit the restriction. This confirms Aries's correction. |
| FLAME 2023 **Open** model only | CC-BY 4.0, commercial use allowed (same license page) | Legitimate fallback if GNM blocks. Still requires the license-page flow; keep as fallback, not default. |
| WhisperX diarization add-on (PDF stack) | pyannote models are gated on Hugging Face (token + terms acceptance) | **FLAGGED — not needed.** Word-by-word clips have known boundaries; no diarization, no token. Whisper itself is MIT but is also unnecessary in v1. |

**Method (`head_fit.py` + `morph_transfer.py`):**
1. Upright/yaw alignment of the reconstructed mesh (forward +Z, up +Y, unmirrored — the bust set's existing convention).
2. Non-rigid ICP against the GNM template: point-to-plane distance + landmark term + Laplacian stiffness (PDF Eq. 4.1), with **trimmed one-way matching** for partial overlap; eyes/teeth/tongue internals excluded from outer-surface fitting.
3. Static torso/bust mesh welded below the neck (GNM ships no torso — the weld from Step 8 of the architecture is still required).
4. Morph transfer: per-vertex position + normal deltas from the template's expression space onto the fitted topology, skipping internal structures.

**The one real catch — no ARKit blendshapes in GNM:** GNM's expression space is PCA directions + semantic categories, **not** the 52 named ARKit channels (`jawOpen`, `mouthPucker`, …) the PDF promises. Delivering "52 ARKit-compatible morph targets" is therefore a **retargeting job**: sample GNM expression directions and fit each ARKit-named target, or author the viseme targets directly on the fitted mesh. Gate: a test where each target moves only its own region (jaw opens without eyes closing, etc.). Do not claim ARKit compatibility until that test passes. For v1 lip-sync, only the targets the 15 visemes actually drive are required (see §6) — the full 52 is a stretch goal, not the v1 bar.

**Untested:** GNM weights total size and exact vendored file list (repo has no releases; assets live in-repo under `gnm/shape` and `assets/` — pin a commit hash, currently `dfd3e4b`, and record file hashes at vendor time). Fitting accuracy on a visual-hull mesh (as opposed to a scan) is unmeasured.

## 6. Word-by-word lip-sync (Steps 11–14)

**Chosen method — no forced aligner in v1.** Because each clip is one known word, boundaries are given. The pipeline is deterministic DSP + tables, pure Python/NumPy on the backend and mirrored in JS for playback:

1. Resample each clip to 16 kHz mono (ffmpeg, present in VM; or SciPy resample).
2. Silence-trim by energy VAD threshold.
3. **G2P:** word → ARPAbet.
4. ARPAbet → 15 visemes via the existing Voice Asset Format map (§1 #4).
5. **RMS scaling:** short-time RMS envelope E_rms(t) scales viseme weights, `w_k(t) = clamp(E_rms(t)^γ · Σ_p W(p,k) · Φ_cos((t − t_center,p)/τ), 0, 1)` (PDF Eq. 4.3), raised-cosine co-articulation overlap 35–50 ms between adjacent phonemes.
6. Secondary life layer: periodic blinks (every 3.5–5.5 s, 140 ms) + low-frequency head micro-nod. (Blink targets depend on the §5 retarget; sway can reuse the node-animation pattern from `ar/build_avatar.py`.)
7. Curves are baked into the GLB as a `weights` animation channel (§7) and also kept as JSON sidecar for the web player.

| Component | License | Local route |
|---|---|---|
| CMUdict 0.7b (134k+ entries, ARPAbet) | **BSD 2-Clause**; CMU states use for any research or commercial purpose is unrestricted | Vendor the dictionary text file (or a pruned subset) in-repo. Primary G2P source. |
| `g2p_en` (neural G2P for out-of-dictionary words) | Apache 2.0 (code + bundled license file observed) | Optional fallback for OOV words; heavier (NLTK + model). v1 alternative: a small rule-based fallback + the existing `pronunciations.json` override table, which is how proper nouns (Aries, Hilton) are already handled. Decide after measuring OOV rate on a real word list. |
| Montreal Forced Aligner 3.x | MIT (code; Kaldi is Apache 2.0) — **but** install is conda-only with Kaldi/Pynini/OpenFst native deps | **Deferred to v2**, only if full-sentence audio is ever supported. Not needed for word clips; do not pay its install cost in v1. Its LICENSE file was not read in-repo in this pass — read it before any future bundling. |
| ffmpeg | LGPL-2.1+ (GPL if built with GPL components — use a stock LGPL build and invoke as a subprocess, do not link) | Already in VM. Used for resample/trim and optional server-side video render. |

**Test gate (sensory, per Aries's standing rule):** one known sentence assembled from his own word clips, played on the bust, judged by eye/ear on his iPhone. A timing table alone does not pass.

## 7. GLB export — morph targets + animation (Step 17)

**Chosen method:** self-written pure-Python GLB 2.0 packer (`struct.pack`, no dependency), extending the proven hand-rolled GLB code in `stage7/recolor_*.py`. Validate output with the Khronos glTF Validator (Apache 2.0) in tests.

**Spec facts the packer must honor (Khronos glTF 2.0, verified Nov 2026):**
- GLB container: 12-byte header (`glTF` magic, version 2, total length), JSON chunk (type `0x4E4F534A`, space-padded to 4 bytes), BIN chunk (type `0x004E4942`, zero-padded to 4 bytes). All bufferViews/accessors 4-byte aligned.
- Morph targets live on `mesh.primitives[].targets[]`: each target is a dict of attribute accessors holding **displacements (deltas), not absolute positions** — `rendered = POSITION + Σ weights[i] · targets[i].POSITION` (same for NORMAL/TANGENT deltas). Target count must match across all primitives of a mesh; `mesh.weights[]` holds the default weights.
- Animation of morphs is a channel with `target.path = "weights"` on the mesh's node; sampler input = time (seconds, SCALAR float), output = one weight per target per keyframe (SCALAR floats, count = keyframes × targets). Interpolation LINEAR is sufficient for baked viseme curves.
- **File-size math:** dense targets cost `verts × 12 bytes` each (POSITION delta). At 71,524 verts: ~0.86 MB per target uncompressed — 15 viseme targets ≈ 13 MB, 52 targets ≈ 45 MB. **Use sparse accessors** (accessor `sparse.indices` + `sparse.values`, storing only non-zero deltas): mouth-region targets touch a small vertex subset, so sparse encoding is the difference between a shippable file and a bloated one. Sparse support in Three.js GLTFLoader is standard. This is a required design point, not an optimization.
- COLOR_0 in Aries's existing files is sRGB-authored; any packer that writes colors must keep that convention and the twin's sRGB→linear-on-load note, or renders wash out (documented in the bust MANIFEST).
- pygltflib (MIT) + trimesh (MIT) are the proven fallback if the hand packer stalls — both already used in `bio-3d/ar/`; neither is installed in the main VM env today (import check failed Nov 20), so pinning/installing them is a Slice-0 task if the fallback is chosen. The self-written packer remains the primary per Aries's architecture ("self-written packers").

**STL (Step 18):** binary little-endian (80-byte header, uint32 count, 50 bytes/triangle), static watertight mesh, millimetre scale factor recorded at export. No color, no animation — label it as such in the UI.

## 8. USDZ export (Step 18)

| Route | License | Verdict |
|---|---|---|
| Pixar OpenUSD `usd-core` (`pxr`) — author UsdGeom mesh + UsdPreviewSurface, zip stored (no compression) as `.usdz` | Apache 2.0 (OpenUSD modified Apache) | **Chosen for v1 static USDZ.** Aries already has a working pxr converter (`bio-3d/ar/convert_usdz.py`) proving the route locally, including time-sampled node animation. |
| Google `usd_from_gltf` | Apache 2.0, C++ build against USD; README self-describes as "not an officially supported Google product" | Not needed given the pxr route. Its README is, however, the authority for the limit below. |

**Hard limit, verified from the `usd_from_gltf` README:** AR Quick Look does **not** support morph targets or vertex animation, and the converter cannot emulate them. Vertex colors are also unsupported in Quick Look.
- **v1 USDZ = static pose** (one frozen viseme/neutral pose, clay material via UsdPreviewSurface, metersPerUnit = 1, Y-up, 64-byte-aligned entries in a stored ZIP).
- **Animated USDZ** would need UsdSkel blendshape authoring via pxr directly — a separate research spike, and Quick Look playback of it is **unproven**. Do not promise it.
- Validation is sensory: open the file in Quick Look on Aries's iPhone. Unzipping it or parsing the USDA is not validation.

## 9. Grading (Steps 15–16) + video export (Step 19)

### Grade
- **GLSL:** Aries's `gradeCMYK` verbatim (see §1 #12), in `frontend/shaders/clay_grade.frag`, followed by RGB lift/gamma/gain: `C2 = clamp((gain·C1 + lift·(1−C1))^(1/gamma))`-family ASC-CDL form. Uniforms: `inkShadow/inkMid/inkHigh` (vec3 CMY each), `kGain`, `kGamma` (enforce > 0), RGB lift/gamma/gain (vec3 each). Runs as a Three.js `ShaderMaterial` / onBeforeCompile injection over the clay PBR base (Oren-Nayar diffuse + GGX spec, ρ_clay ≈ 0.48–0.56, α_r ≈ 0.55–0.68 per PDF §5.3 — reference values, tune by eye on his bust).
- **Do NOT copy the PDF's §7.2 tail blindly:** it applies ACES Filmic and then an extra `^(1/2.2)`; ACES output is already display-referred, so the double conversion is an approximation, not a standard. If ACES is offered at all, it is a tested visible option, off by default.
- **Parity gate:** NumPy reference (`backend/grading_ref.py`) implementing the identical math; test asserts GLSL-vs-NumPy agreement within **1e-5** on a fixed color grid including neutral grays (the additive-ink property — a plain gray sculpt must pick up tint — is an explicit test case).

### Video
- **Primary:** Reactor's pattern verbatim — `canvas.captureStream(30)` + `MediaRecorder` with the MIME fallback list (§1 #10), muxing the sequenced word audio via Web Audio `MediaStreamDestination`. Target 1080×1920.
- **iOS Safari constraints (checked Nov 2026):** MediaRecorder exists on iOS Safari 14.5+; through 18.3 it records **MP4/H.264+AAC only**; Safari 18.4+ adds WebM recording (VP8/VP9 + Opus) and HEVC. The Reactor list's first entry (MP4 avc1+mp4a) is therefore the one that will actually hit on his iPhone — good. `getUserMedia` needs HTTPS/localhost + a user gesture. Frame rate: `captureStream(30)` requests 30 fps; **do not claim 60 fps** — the PDF's 1080×1920@60 target is unverified on device.
- **WebCodecs:** Safari 16.4–18.7 exposes video-only WebCodecs (no AudioEncoder); full support lands in Safari 26. It also needs an external muxer (mp4-muxer, MIT). **Verdict: fallback research only, not the v1 path.**
- **Server-side alternative:** local ffmpeg render of frames + word audio (LGPL build, subprocess) — deterministic, no browser codec roulette; offer as the "export via backend" option. Untested for render time.

## 10. Capture bundle spec (draft — settles the open offer from chat Nov 19 09:02 UTC)

One ZIP, one manifest, three regimes. Follows the Voice Asset Format's provenance rule: a package without a complete hash record is not valid.

```text
capture.claybundle.zip
├── manifest.json
├── capture/
│   ├── video.mp4                 # Regime A only
│   ├── frame_0001.jpg …          # Regime B only
│   └── rgbd/                     # Regime C only
│       ├── frame_0001.jpg
│       ├── frame_0001_depth.png  # 16-bit PNG
│       └── poses.json
├── words/
│   ├── word_001_hello.wav …
└── words.json
```

**Regimes (exactly one per bundle; mixed bundles are rejected):**
- **A — Orbit video (default):** one continuous 360° turntable video. Proven: his bust used 2160×3840 @ 60 fps, 30 views, IoU 0.895. Validator minimum: ≥24 usable frames spanning 360°.
- **B — Photo set:** unordered photos; validator reports missing coverage (front / left profile / right profile minimum) instead of failing on count alone. COLMAP path.
- **C — RGB-D bundle (pre-captured only):** per-frame RGB + 16-bit depth PNG + pose (R, t) + depth confidence. Safari cannot capture this live (§2); frames without a pose are dropped by the validator with indices listed.

**manifest.json (required fields):** `bundle_version` (`0.1.0`), `regime`, `subject`, `created_utc`, `capture` (device, source file, width/height/fps, `front_camera_mirrored` bool), `camera.intrinsics_K` (3×3; when unknown, loader estimates from frame size and records `estimated: true` — quality is then unmeasured, not assumed), `subject_frame` (forward +Z, up +Y, mirrored flag — front-camera captures are un-mirrored on ingest and the manifest records that it happened; a forgotten mirror flag is a likeness error, not a cosmetic one), `words_file`, `provenance` (source, consent, tool), `hashes` (SHA-256 for **every** file in the bundle).

**words.json:** ordered word list; each entry `{index, text, clip, sample_rate_hz, channels, sha256}`. Clips are WAV, resampled to 16 kHz mono on ingest. One word per clip — a two-word clip is a validation error, because the whole v1 lip-sync design rests on known word boundaries. Re-recording a word replaces one clip; indices never shift. Pronunciation overrides come from the `.voicepack`-style `pronunciations.json` convention.

**Validator (`bundle_loader.py`, pure Python + stdlib + NumPy, no GPU, no network):** ZIP opens → manifest parses → exactly one regime's files present → all hashes match → regime checks (A: video decodes via ffmpeg, fps/frames within tolerance; B: coverage report; C: pose + depth + confidence + true K for every kept frame) → words checks (every word has a decodable clip, indices contiguous from 0, per-word duration sanity flagged not auto-split) → JSON report naming the failing file/index per check. A failed bundle never reaches the reconstruction queue.

## 11. Per-part summary table

| Part (steps) | Chosen method | License | Local route | Still untested |
|---|---|---|---|---|
| Frontend + capture (1–3) | Plain ES6 + Three.js 0.164.1, file input / getUserMedia / Web Audio | Three.js MIT | Static page served by local FastAPI | iPhone Safari capture resolutions |
| Backend shell (3) | FastAPI job dirs | MIT / BSD | localhost only, no auth | — |
| Recon v1 (4–6) | Orbit visual hull + photometric refinement (existing stage5/7 code) | Own code, BSD libs | This VM, CPU | Generalization beyond his capture |
| Recon v2 (4–6) | COLMAP SfM/MVS → Open3D TSDF / Screened Poisson → Taubin | COLMAP BSD-3; Open3D MIT | pip wheels, CPU build | Install + timing on chosen host; RAM ceiling |
| Single-photo fallback (4) | Depth Anything V2 **Small only** + symmetry prior | Code Apache 2.0; Small weights Apache 2.0; **Base/Large/Giant CC-BY-NC — excluded** | Cached weights, PyTorch | Quality vs MiDaS (MIT) alternative |
| Head fit (7–9) | GNM Head non-rigid ICP (trimmed, Laplacian stiffness) + bust weld + morph transfer | **GNM Apache 2.0**; FLAME pre-2023 non-commercial — **excluded**; FLAME 2023 Open CC-BY = fallback only | NumPy backend, in-repo assets pinned by commit | Weights size/file list; fit quality on hull meshes; ARKit retarget |
| Lip-sync (11–14) | Word clips → CMUdict G2P → existing 15-viseme map → RMS-scaled raised-cosine curves | CMUdict BSD-2; g2p_en Apache 2.0 (optional) | Pure NumPy; ffmpeg subprocess | Sensory pass on his phone with his clips |
| Grade (15–16) | Aries's `gradeCMYK` GLSL verbatim → RGB LGG; NumPy parity ref | Own code | Phone GPU shader | Parity test at 1e-5; ACES variant by eye only |
| GLB export (17) | Self-written packer, **sparse morph accessors**, weights animation channel | Own code; Khronos validator Apache 2.0 for tests | Pure Python stdlib | Morph packer itself; sparse round-trip in Three.js |
| STL export (18) | Binary STL writer, mm scale | Own code | Pure Python | — |
| USDZ export (18) | Pixar `usd-core` authoring, stored ZIP | OpenUSD Apache 2.0 | Local pxr (proven in `bio-3d/ar/`) | **Static only in v1**; animated UsdSkel spike unproven; Quick Look check on his iPhone |
| Video export (19) | Reactor MediaRecorder pattern; ffmpeg backend alternative | Own code; ffmpeg LGPL (subprocess) | Browser canvas + Web Audio | Actual fps/file on iPhone 15 Pro Max; no 60 fps claim |
| Downloads (20) | Direct local downloads, no links/accounts | — | Browser download | — |

## 12. Build order (dependency order — each slice shippable and testable alone)

1. **Slice 0 — Repo + bundle spec + validator.** New repo (name and publish word are Aries's — nothing public without his explicit word, per the Nov 17 repair rule). Spec = §10. Validator is pure Python, testable today in this VM. Also pin/vendor decisions recorded here: Three.js copy, CMUdict file, GNM commit hash.
2. **Slice 1 — Viewer + grade + export from the existing bust.** Fixture: `aries-bust-clay-v3.glb`. Three.js viewer (twin pattern), `gradeCMYK` + RGB grade with the 1e-5 parity gate, GLB/STL download (existing files re-served), Reactor-pattern video capture. First thing Aries can open on his phone and judge. Needs no GPU, no COLMAP, no GNM.
3. **Slice 2 — Word-by-word lip-sync on that bust.** G2P (CMUdict + overrides) → viseme map (existing) → RMS curves → morph targets authored on the v3 topology for the viseme subset + sparse GLB packer (§7) → in-viewer playback with sequenced audio. Gate: sensory check with his own word clips.
4. **Slice 3 — Generalized reconstruction.** Package the orbit-hull carve so any user's orbit video produces a bust (not only his pre-tracked capture); bundle loader wired to the queue. COLMAP/Open3D path behind a flag for Regime B, once a host decision lands.
5. **Slice 4 — GNM Head fit.** Identity fit + bust weld + morph transfer for arbitrary reconstructions; viseme/ARKit retarget with the region-isolation test as its gate. This is what turns a carve into a rigged head for any subject.
6. **Slice 5 — USDZ.** Static-pose USDZ via pxr, Quick-Look-verified on his iPhone. Animated UsdSkel only after a spike proves playback.

## 13. Open risks

1. **Compute host (biggest).** This VM (4 CPU / 7.7 GB / no GPU / no COLMAP, Open3D, PyTorch, or trimesh in env) proves Slices 0–2 and the orbit-hull path only. COLMAP dense MVS, Depth Anything, and GNM-with-JAX/PyTorch backends need a host decision: install CPU builds here and accept slow runs ($0), or wait for the AWS Free Plan host (signup paused at the password step, Aries enters it himself; no card entry). No timing claims until measured.
2. **GNM is young.** Repo created Mar 2026, zero releases/tags; pinning a raw commit is the only reproducibility route. Weights size unverified (not downloaded in this pass).
3. **ARKit-52 expectation.** Neither GNM nor the viseme pipeline natively yields 52 ARKit targets; the retarget (§5) is real work with its own failure mode (cross-region leakage). v1 scopes to the viseme subset.
4. **Weights-license trap class.** Depth Anything V2 Base/Large/Giant (CC-BY-NC) and FLAME pre-2023 (non-commercial) are the same failure shape: permissive code, restricted weights. Any future model swap must check the weights license separately, in the weights' own LICENSE/model card, before vendoring.
5. **USDZ animation.** Expected to fail in Quick Look; v1 promises static only.
6. **Video on iOS.** MediaRecorder MP4 path is sound, but resolution/fps on his exact device is unmeasured; WebCodecs is not a v1 dependency.
7. **Single-photo regime.** Relative depth + symmetry prior produces a plausible bust, not a measured one; UI must label it as a fallback estimate.
8. **MFA license file** was not read in-repo this pass (deferred component; read before any v2 bundling).

## 14. Decisions still Aries's

1. Repo name, new Frozen-In-Flames repo vs. existing repo, and the **publish word** before anything goes public.
2. Compute host for heavy stages (CPU-install here vs. AWS Free Plan host vs. another host he names).
3. Whether Slice 1 may use `aries-bust-clay-v3.glb` as its fixture, and whether that fixture may appear in a public demo (local testing ≠ public use).
4. Approval of the §10 capture bundle spec as the Slice 0 artifact.

## Sources

- Governing architecture + shader: Aries's chat messages Nov 19 2026, 09:02 / 09:23 / 09:24 / 09:26 UTC; PDF blueprint `~/workspace/user/files/4D_Clay_Sculpt___Lip-Sync_Studio_Technical_Blueprint.pdf` (9 pp.).
- Prior goal briefs (consistent with this report; this report is the consolidated copy at the task-specified path): `~/workspace/goals/4d-clay-sculpt-lip-sync-studio/briefs/` (Research, Capture Bundle Spec, Slice 1, all 2026-11-19).
- Inventory: `~/workspace/bio-3d/` (stage5/stage7 code, `aries-bust-3d-files/MANIFEST.md`, `ar/build_avatar.py`, `ar/convert_usdz.py`, `bio-draft/twin.html`), `~/workspace/voice-asset-format/` (SPEC.md, `examples/aries-hilton-reference/phonemes.json`), `~/workspace/reactor/index.html` lines 50/189.
- GNM: github.com/google/GNM read live 2026-11-20 (Apache-2.0, commit dfd3e4b); arXiv:2607.23687.
- FLAME licenses: flame.is.tue.mpg.de/modellicense.html (pre-2023 + FLAME 2023 standard = non-commercial, signup-gated; FLAME 2023 Open = CC-BY).
- COLMAP: colmap.github.io + COPYING.txt (BSD 3-Clause; 4.2.1 current; pycolmap on PyPI).
- Open3D: open3d.org / PyPI (MIT; Screened Poisson + TSDF + ICP).
- Depth Anything V2: code Apache 2.0; Small weights Apache 2.0; Base/Large/Giant weights CC-BY-NC-4.0 (license roundups checked Nov 2026).
- CMUdict: speech.cs.cmu.edu/cgi-bin/cmudict (0.7b, BSD 2-Clause, 134k entries); g2p_en Apache 2.0.
- glTF morph targets: Khronos glTF Tutorials #18 + spec (targets = deltas, weights channel, sparse accessors).
- USDZ: google/usd_from_gltf README (Quick Look unsupported: vertex colors, morph targets, vertex animation); Pixar OpenUSD (Apache 2.0).
- Browser limits: MediaRecorder/WebCodecs support matrices checked Nov 2026 (iOS Safari MP4-only recording through 18.3, WebM from 18.4; WebCodecs video-only on Safari 16.4–18.7, full in Safari 26; no WebXR AR / no LiDAR API in Safari).
- VM check 2026-11-19/20: 4 CPU, 7.7 GB RAM, Python 3.12.3, numpy/scipy only, ffmpeg present, no COLMAP/Open3D/PyTorch/Blender/GPU.
