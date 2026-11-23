"""SculptViseme backend (RESEARCH.md sections 2 and 3).

One FastAPI process, filesystem job directories, no database. It
runs in one of two modes, chosen by the user who deploys it:

  local (default)  binds localhost, no auth; the self-hosted
                   runner on the user's own machine.
  cloud            the same service packaged for a remote host
                   (see the Dockerfile). Set SV_API_TOKEN to
                   require a bearer token on the job and export
                   endpoints, and SV_CORS_ORIGINS so a frontend
                   served from another origin can call it.

The mode is configuration, not a different codebase: the pipeline
modules below are identical in both. It wires them together:

  POST /api/bundles            upload a .claybundle.zip, validate
                               it with bundle_loader, open a job
  GET  /api/jobs/{job_id}      the job's normalized bundle manifest
  POST /api/jobs/{job_id}/lipsync
                               run lipsync_align over the job's
                               word clips, store and return the
                               viseme keyframes document
  POST /api/mesh-glb           pack a mesh (NPZ upload: positions,
                               indices, optional morph deltas and
                               names, optional keyframes JSON) into
                               a GLB with glb_exporter
  POST /api/mesh-stl           the same NPZ mesh as binary STL
                               (static geometry only) with
                               stl_exporter
  POST /api/mesh-usdz          the same NPZ mesh as a static USDZ
                               (pxr route) with usdz_exporter;
                               501 when pxr is not installed here
  POST /api/glb-stl            a GLB upload re-exported as binary
                               STL from its first mesh primitive
  POST /api/glb-usdz           a GLB upload re-exported as a
                               static USDZ from its first mesh
                               primitive (morphs and animation do
                               not carry into USDZ; see the
                               usdz_exporter docstring)
  GET  /demo/clay-bust-v3.glb  the local demo fixture from bio-3d,
                               when present on this machine (local
                               development only, never packaged)
  GET  /                       the frontend (frontend/index.html)
  /static/...                  the frontend files

Jobs live under CSS_JOBS_DIR (default: ../var/jobs relative to this
repo). Heavy modules (lipsync_align, glb_exporter) are imported
lazily inside their endpoints so the shell itself needs only
FastAPI.

Run locally:  uvicorn app:app --host 127.0.0.1 --port 8077
Run as cloud: SV_MODE=cloud SV_API_TOKEN=<secret> \
              uvicorn app:app --host 0.0.0.0 --port 8077
(from the backend/ directory, or with PYTHONPATH=backend)
"""

import io
import json
import os

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FRONTEND = os.path.join(REPO, "frontend")
JOBS_DIR = os.environ.get(
    "CSS_JOBS_DIR", os.path.join(REPO, "var", "jobs"))
DEMO_BUST = os.environ.get(
    "CSS_DEMO_BUST",
    os.path.expanduser("~/workspace/bio-3d/aries-bust-clay-v3.glb"))

# Runner configuration. Local is the default and needs nothing;
# a cloud deployment sets SV_MODE=cloud and should set
# SV_API_TOKEN, because the service is then reachable by others.
MODE = os.environ.get("SV_MODE", "local").strip().lower()
API_TOKEN = os.environ.get("SV_API_TOKEN", "").strip()
CORS_ORIGINS = [o.strip() for o in
                os.environ.get("SV_CORS_ORIGINS", "").split(",")
                if o.strip()]

app = FastAPI(title=f"SculptViseme ({MODE})",
              docs_url=None, redoc_url=None, openapi_url=None)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def require_token_when_configured(request: Request, call_next):
    """Bearer-token gate for cloud deployments.

    Active only when SV_API_TOKEN is set; local mode without a
    token is untouched. /api/health stays open so a frontend can
    check where it is pointing before it has a token answer.
    """
    if API_TOKEN and request.url.path.startswith("/api/") \
            and request.url.path != "/api/health" \
            and request.method != "OPTIONS":
        if request.headers.get("authorization") != f"Bearer {API_TOKEN}":
            response = JSONResponse(status_code=401,
                                    content={"ok": False,
                                             "error": "unauthorized"})
            # This gate answers before the CORS middleware, so it
            # must carry the CORS header itself: without it a
            # browser reports a network failure instead of the
            # 401, and a wrong token looks like a dead runner.
            origin = request.headers.get("origin")
            if origin and origin in CORS_ORIGINS:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
            return response
    return await call_next(request)


def _job_manifest(job_id):
    path = os.path.join(JOBS_DIR, job_id, "bundle-manifest.json")
    if not os.path.isfile(path):
        raise HTTPException(404, f"no such job: {job_id}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f), path


@app.get("/api/health")
def health():
    return {"ok": True, "app": "SculptViseme", "mode": MODE,
            "auth_required": bool(API_TOKEN),
            "jobs_dir": JOBS_DIR,
            "demo_bust_available": os.path.isfile(DEMO_BUST)}


@app.post("/api/bundles")
async def create_bundle(bundle: UploadFile = File(...)):
    import bundle_loader
    os.makedirs(JOBS_DIR, exist_ok=True)
    upload_dir = os.path.join(JOBS_DIR, "_uploads")
    os.makedirs(upload_dir, exist_ok=True)
    dest = os.path.join(upload_dir, os.path.basename(bundle.filename
                                                     or "bundle.zip"))
    with open(dest, "wb") as f:
        while chunk := await bundle.read(1 << 20):
            f.write(chunk)
    try:
        manifest = bundle_loader.validate_and_load(dest, JOBS_DIR)
    except bundle_loader.BundleError as exc:
        return JSONResponse(status_code=422,
                            content={"ok": False,
                                     "report": exc.report})
    return {"ok": True, "job_id": manifest["job_id"],
            "regime": manifest["regime"], "manifest": manifest}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    manifest, _ = _job_manifest(job_id)
    return manifest


@app.post("/api/jobs/{job_id}/lipsync")
def job_lipsync(job_id: str, fps: int = 30):
    import lipsync_align
    manifest, _ = _job_manifest(job_id)
    clips = [(w["text"], w["path"]) for w in manifest.get("words", [])]
    if not clips:
        raise HTTPException(422, "job has no word clips")
    doc = lipsync_align.align_words(clips, fps=fps)
    out = os.path.join(JOBS_DIR, job_id, "keyframes.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    return doc


def _npz_data(raw):
    data = np.load(io.BytesIO(raw), allow_pickle=False)
    if "positions" not in data or "indices" not in data:
        raise HTTPException(422, "NPZ needs positions and indices")
    return data


def _glb_first_mesh(raw):
    """(positions, indices) of the first mesh primitive in a GLB.

    Uses the studio's own reader (glb_exporter.parse_glb and
    read_accessor, sparse aware). Morph targets and animation in
    the source GLB are not read: STL and USDZ exports are static.
    """
    import glb_exporter
    try:
        gltf, bin_data = glb_exporter.parse_glb(raw)
        prim = gltf["meshes"][0]["primitives"][0]
        positions = glb_exporter.read_accessor(
            gltf, bin_data, prim["attributes"]["POSITION"])
        indices = glb_exporter.read_accessor(
            gltf, bin_data, prim["indices"])
    except Exception as exc:
        raise HTTPException(422, f"GLB unreadable: {exc}")
    return (np.asarray(positions, dtype=np.float64),
            np.asarray(indices).reshape(-1, 3))


def _stl_response(positions, indices):
    import stl_exporter
    data, report = stl_exporter.build_stl_report(positions, indices)
    return Response(
        content=data, media_type="model/stl",
        headers={"Content-Disposition":
                 "attachment; filename=mesh.stl",
                 "X-STL-Triangles": str(report["triangles"]),
                 "X-STL-Degenerate-Triangles":
                     str(report["degenerate_triangles"])})


def _usdz_response(positions, indices):
    import usdz_exporter
    try:
        data = usdz_exporter.build_usdz(positions, indices)
    except usdz_exporter.UsdzUnavailable as exc:
        raise HTTPException(501, str(exc))
    return Response(
        content=data, media_type="application/octet-stream",
        headers={"Content-Disposition":
                 "attachment; filename=mesh.usdz"})


@app.post("/api/mesh-glb")
async def mesh_glb(mesh: UploadFile = File(...),
                   keyframes: UploadFile = File(None)):
    """Pack an NPZ mesh upload into a GLB.

    NPZ fields: positions (N,3), indices (M,3), optional
    morph_names (list of str) with morph_0, morph_1, ... (N,3)
    delta arrays. When a keyframes JSON (the lipsync_align output)
    is also uploaded and its viseme order matches morph_names, its
    frames become the weights animation channel.
    """
    import glb_exporter
    data = _npz_data(await mesh.read())
    targets = []
    names = []
    if "morph_names" in data:
        names = [str(n) for n in data["morph_names"].tolist()]
        for i, name in enumerate(names):
            key = f"morph_{i}"
            if key not in data:
                raise HTTPException(422, f"missing delta array {key}")
            targets.append({"name": name, "position": data[key]})
    weights_animation = None
    if keyframes is not None and targets:
        doc = json.loads((await keyframes.read()).decode("utf-8"))
        if doc.get("visemes") != names:
            raise HTTPException(
                422, "keyframes viseme order does not match "
                     "morph_names")
        times = np.array([fr["t"] for fr in doc["frames"]])
        weights = np.array([fr["weights"] for fr in doc["frames"]])
        weights_animation = (times, weights)
    glb = glb_exporter.build_glb(
        data["positions"], data["indices"], morph_targets=targets,
        weights_animation=weights_animation)
    return Response(content=glb, media_type="model/gltf-binary",
                    headers={"Content-Disposition":
                             "attachment; filename=mesh.glb"})


@app.post("/api/mesh-stl")
async def mesh_stl(mesh: UploadFile = File(...)):
    """The NPZ mesh as binary STL: static geometry only.

    No morph targets, no animation, no grade. The response headers
    carry the triangle count and the degenerate triangle count so
    a client can label the export honestly.
    """
    data = _npz_data(await mesh.read())
    return _stl_response(data["positions"], data["indices"])


@app.post("/api/mesh-usdz")
async def mesh_usdz(mesh: UploadFile = File(...)):
    """The NPZ mesh as a static USDZ (pxr route, neutral pose).

    Answers 501 with the reason when pxr is not installed in this
    backend environment; it never returns a fake package.
    """
    data = _npz_data(await mesh.read())
    return _usdz_response(data["positions"], data["indices"])


@app.post("/api/glb-stl")
async def glb_stl(mesh: UploadFile = File(...)):
    """A GLB upload re-exported as binary STL (first primitive)."""
    positions, indices = _glb_first_mesh(await mesh.read())
    return _stl_response(positions, indices)


@app.post("/api/glb-usdz")
async def glb_usdz(mesh: UploadFile = File(...)):
    """A GLB upload re-exported as a static USDZ (first primitive).

    Morph targets and animation in the source GLB do not carry:
    Quick Look drops them from USDZ (RESEARCH.md section 8), so
    this export is the neutral static pose and the UI says so.
    """
    positions, indices = _glb_first_mesh(await mesh.read())
    return _usdz_response(positions, indices)


@app.get("/demo/clay-bust-v3.glb")
def demo_bust():
    if not os.path.isfile(DEMO_BUST):
        raise HTTPException(404, "demo bust not present on this "
                                 "machine")
    return FileResponse(DEMO_BUST, media_type="model/gltf-binary")


# Frontend at the root, mounted last so the API and demo routes
# above take precedence. html=True serves index.html at /.
app.mount("/", StaticFiles(directory=FRONTEND, html=True),
          name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8077)
