"""Static USDZ writer (RESEARCH.md section 8, Step 18).

The route is the proven one from bio-3d/ar/convert_usdz.py: author
a USD stage with Pixar's pxr (Usd, UsdGeom, UsdShade), one mesh
prim with a clay UsdPreviewSurface material, then package it with
UsdUtils.CreateNewUsdzPackage, which writes the stored (stored,
not deflated) ZIP a USDZ must be. This module adapts that route to
this studio's mesh input: the same positions (N, 3) and indices
(M, 3) arrays the GLB path uses, or an NPZ byte payload with those
two fields.

What USDZ carries here, stated plainly: one static pose, the
neutral mesh, with a matte clay material. It does not carry morph
targets, lip-sync animation, or the color grade. That is a format
limit, not a shortcut: the research (section 8) found that Quick
Look drops morph targets and vertex animation from USDZ files, so
an animated USDZ would look correct in a validator and wrong on
the phone. Animated USDZ is not promised anywhere in this studio.
GLB is the animated format; USDZ is the static AR preview copy.

pxr (the usd-core wheel) is imported lazily. Where it is not
installed, build_usdz raises UsdzUnavailable and the backend
answers 501 with that reason; the test suite skips with the same
reason. Nothing in this module fakes a package.
"""

import io
import os
import tempfile

import numpy as np

CLAY_COLOR = (180 / 255.0, 180 / 255.0, 180 / 255.0)
CLAY_ROUGHNESS = 0.95


class UsdzUnavailable(RuntimeError):
    """Raised when the pxr (usd-core) package is not importable."""


def _import_pxr():
    try:
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils
    except ImportError as exc:
        raise UsdzUnavailable(
            "pxr (usd-core) is not installed in this environment: "
            f"{exc}") from exc
    return Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils


def pxr_available():
    try:
        _import_pxr()
        return True
    except UsdzUnavailable:
        return False


def _as_mesh(positions, indices):
    pos = np.asarray(positions, dtype=np.float64)
    idx = np.asarray(indices)
    if pos.ndim != 2 or pos.shape[1] != 3:
        raise ValueError(f"positions must be (N, 3), got {pos.shape}")
    if idx.ndim != 2 or idx.shape[1] != 3:
        raise ValueError(f"indices must be (M, 3), got {idx.shape}")
    idx = idx.astype(np.int64)
    if idx.size and (idx.min() < 0 or idx.max() >= len(pos)):
        raise ValueError("indices out of range for positions")
    return pos, idx


def build_usdz(positions, indices, normals=None):
    """Pack a static mesh into USDZ bytes via the pxr route.

    Y-up, metersPerUnit 1, default prim /ClaySculpt with one Mesh
    child, vertex normals (computed smooth when not supplied, the
    same helper the GLB writer uses), subdivision scheme none,
    and a clay UsdPreviewSurface bound to the mesh.
    """
    Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils = _import_pxr()
    import glb_exporter
    pos, idx = _as_mesh(positions, indices)
    if normals is None:
        normals = glb_exporter.compute_smooth_normals(pos, idx)
    normals = np.asarray(normals, dtype=np.float64)

    with tempfile.TemporaryDirectory(prefix="css-usdz-") as tmp:
        usda = os.path.join(tmp, "mesh.usda")
        out = os.path.join(tmp, "mesh.usdz")
        stage = Usd.Stage.CreateNew(usda)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)

        root = UsdGeom.Xform.Define(stage, "/ClaySculpt")
        stage.SetDefaultPrim(root.GetPrim())

        mat = UsdShade.Material.Define(stage, "/ClaySculpt/Clay")
        surf = UsdShade.Shader.Define(stage, "/ClaySculpt/Clay/Surface")
        surf.CreateIdAttr("UsdPreviewSurface")
        surf.CreateInput("diffuseColor",
                         Sdf.ValueTypeNames.Color3f).Set(
                             Gf.Vec3f(*CLAY_COLOR))
        surf.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(
            CLAY_ROUGHNESS)
        surf.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        mat.CreateSurfaceOutput().ConnectToSource(
            surf.CreateOutput("surface", Sdf.ValueTypeNames.Token))

        mesh = UsdGeom.Mesh.Define(stage, "/ClaySculpt/Mesh")
        mesh.CreatePointsAttr([Gf.Vec3f(*[float(c) for c in v])
                               for v in pos])
        mesh.CreateFaceVertexCountsAttr([3] * len(idx))
        mesh.CreateFaceVertexIndicesAttr(idx.flatten().tolist())
        mesh.CreateNormalsAttr([Gf.Vec3f(*[float(c) for c in n])
                                for n in normals])
        mesh.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
        mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        mesh.CreateDoubleSidedAttr(False)
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)

        stage.GetRootLayer().Save()
        ok = UsdUtils.CreateNewUsdzPackage(usda, out)
        if not ok or not os.path.isfile(out):
            raise RuntimeError("UsdUtils.CreateNewUsdzPackage failed")
        with open(out, "rb") as f:
            return f.read()


def arrays_from_npz(data):
    """(positions, indices) from NPZ bytes, the mesh-glb input."""
    with np.load(io.BytesIO(data), allow_pickle=False) as z:
        if "positions" not in z or "indices" not in z:
            raise ValueError("NPZ needs positions and indices")
        return z["positions"], z["indices"]


def build_usdz_from_npz(data):
    positions, indices = arrays_from_npz(data)
    return build_usdz(positions, indices)
