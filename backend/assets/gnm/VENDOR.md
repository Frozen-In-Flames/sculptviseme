# Vendored asset: GNM Head template (mean shape)

`mean_shape.npz` holds the skin component of the GNM Head
template: 12,466 vertices, 24,820 triangles, the 68 sparse
landmarks, and the upper/lower lip vertex sets. It is the
template the fit stage (backend/head_fit.py) deforms onto a
reconstructed bust. The full parametric model (identity and
expression bases, eyes, teeth, tongue) is not vendored; the fit
needs the template only.

## Source

- Model: GNM Head, Google LLC, Apache License 2.0.
- Code and landmark definitions: https://github.com/google/GNM
  at commit dfd3e4b ("Avoid Keras predict overhead and batch
  random GNM semantic sampling"), the pin recorded in
  RESEARCH.md.
- Model data file: `gnm_head.npz` from the project's official
  Hugging Face repository, google/gnm-v3, path
  `v3_0/gnm_head.npz` (the same file the project's own OSS data
  loader downloads).
- Landmark definitions: `gnm/shape/data/landmarks/
  head_sparse_68.txt` in the repository above (barycentric
  triples over template vertices; the vendored landmark index
  is the vertex of maximum weight).

## Hashes (SHA-256)

- gnm_head.npz (source, not vendored):
  61d78bbfb4ad8e0b38495804a4caef3214d3df00f8c3f68761e63b41ce3747eb
- head_sparse_68.txt (source, not vendored):
  d8b6066a87ca37c48bcf4d0834542db841709b65cb983e873fa1e441a22219d0
- mean_shape.npz (this asset):
  ebfcabbff01dac9716e1eba5c1bc854c79cd65958e03afffbebf65dbfa3cdb86

## Rebuild

`build_asset.py` in this directory regenerates the asset from
the two source files and prints their hashes. Extracted
2026-11-23 with the project owner's approval.
