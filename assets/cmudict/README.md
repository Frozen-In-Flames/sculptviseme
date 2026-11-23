# CMUdict (vendored)

`cmudict.dict` is the CMU Pronouncing Dictionary, version 0.7b
(135,166 lines as vendored), fetched 2026-11-20 from the public
CMU Sphinx repository (github.com/cmusphinx/cmudict). No account or
signup was involved.

License: BSD 2-Clause. CMU states the dictionary may be used for
any research or commercial purpose without restriction.

It is the primary G2P source for backend/g2p.py. Stress digits in
its ARPAbet entries are stripped at load time, because the viseme
map keys on bare ARPAbet phonemes.
