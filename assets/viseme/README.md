# Viseme assets (verbatim copies, single source of truth)

`phonemes.json` and `pronunciations.json` in this directory are
byte-identical copies of the files in
`voice-asset-format/examples/aries-hilton-reference/`, verified by
SHA-256 at vendor time (2026-11-20) and re-verified by
tests/test_lipsync_align.py on every run:

- phonemes.json: 32d00120a78452b602f43aefb90c560dec9da4a0fbe7cad0e10a8d09fb2d2d61
- pronunciations.json: 879d116a8878e804e65b286fc356e351ae174ae06d93fa62b3b9a29ca28fab23

The phoneme map (39 ARPAbet phonemes plus SIL, mapped to the 15
visemes of the Voice Asset Format spec) is reused verbatim. This
project does not invent a second map. If the Voice Asset Format
original changes, re-copy it here and update these hashes.
