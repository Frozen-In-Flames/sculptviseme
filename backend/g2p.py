"""Grapheme to phoneme for the word-by-word lip-sync pipeline.

Three sources, tried in order, and the source is always reported so
no caller ever mistakes a guess for a dictionary entry:

1. "override": the Voice Asset Format pronunciations table (proper
   nouns and house words: aries, hilton, frozen, flames, voicepack).
2. "cmudict": the CMU Pronouncing Dictionary 0.7b, vendored at
   assets/cmudict/cmudict.dict (BSD 2-Clause; CMU states use for any
   research or commercial purpose is unrestricted). Stress digits are
   stripped, because the viseme map keys on bare ARPAbet.
3. "rules": a small deterministic grapheme rule fallback for out of
   dictionary words. It is a fallback, labeled as such everywhere its
   output travels. It never claims dictionary accuracy.

No network, no signup, no external service at runtime.
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_CMUDICT_PATH = os.path.join(_REPO, "assets", "cmudict", "cmudict.dict")
_OVERRIDES_PATH = os.path.join(_REPO, "assets", "viseme",
                               "pronunciations.json")

_ARPABET = {
    "AA", "AE", "AH", "AO", "AW", "AY", "B", "CH", "D", "DH", "EH",
    "ER", "EY", "F", "G", "HH", "IH", "IY", "JH", "K", "L", "M", "N",
    "NG", "OW", "OY", "P", "R", "S", "SH", "T", "TH", "UH", "UW",
    "V", "W", "Y", "Z", "ZH",
}

_dict_cache = None
_override_cache = None


def _strip_stress(phoneme):
    return re.sub(r"[0-9]+$", "", phoneme)


def load_overrides(path=_OVERRIDES_PATH):
    global _override_cache
    if _override_cache is None:
        import json
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        _override_cache = {k.lower(): list(v) for k, v in raw.items()}
    return _override_cache


def load_cmudict(path=_CMUDICT_PATH):
    """Parse the vendored CMUdict into {word: [phonemes]}.

    Alternate pronunciations (WORD(2) etc.) are skipped; the base
    entry wins. Comment lines start with ';'.
    """
    global _dict_cache
    if _dict_cache is not None:
        return _dict_cache
    table = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line or line.startswith(";"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            word = parts[0].lower()
            if "(" in word:  # alternate pronunciation entry
                continue
            phonemes = [_strip_stress(p) for p in parts[1:]]
            if all(p in _ARPABET for p in phonemes):
                table.setdefault(word, phonemes)
    _dict_cache = table
    return table


# ---- Rule fallback ---------------------------------------------------
# Ordered grapheme rules. Deliberately small and readable; this is a
# labeled fallback for out of dictionary words, not a second engine.

_DIGRAPHS = [
    ("PH", ["F"]), ("CH", ["CH"]), ("SH", ["SH"]), ("TH", ["TH"]),
    ("WH", ["W"]), ("CK", ["K"]), ("NG", ["NG"]), ("QU", ["K", "W"]),
    ("GH", []), ("KN", ["N"]), ("WR", ["R"]), ("MB", []),
]
_VOWEL_TEAMS = [
    ("EE", ["IY"]), ("EA", ["IY"]), ("OO", ["UW"]), ("OU", ["AW"]),
    ("OW", ["AW"]), ("AI", ["AY"]), ("AY", ["AY"]), ("OI", ["OY"]),
    ("OY", ["OY"]), ("AU", ["AO"]), ("AW", ["AO"]), ("OA", ["OW"]),
    ("IE", ["IY"]), ("EI", ["EY"]), ("EY", ["EY"]),
]
_SINGLE = {
    "A": ["AE"], "E": ["EH"], "I": ["IH"], "O": ["AA"], "U": ["AH"],
    "B": ["B"], "C": ["K"], "D": ["D"], "F": ["F"], "G": ["G"],
    "H": ["HH"], "J": ["JH"], "K": ["K"], "L": ["L"], "M": ["M"],
    "N": ["N"], "P": ["P"], "R": ["R"], "S": ["S"], "T": ["T"],
    "V": ["V"], "W": ["W"], "X": ["K", "S"], "Z": ["Z"],
}


def pronounce_rules(word):
    """Deterministic grapheme rules. Returns a list of ARPAbet codes."""
    w = word.upper()
    out = []
    i = 0
    while i < len(w):
        ch = w[i]
        if not ch.isalpha():
            i += 1
            continue
        matched = False
        for pat, ph in _DIGRAPHS + _VOWEL_TEAMS:
            if w.startswith(pat, i):
                # Soft C / G handling comes first for CE, CI, GE, GI.
                out.extend(ph)
                i += len(pat)
                matched = True
                break
        if matched:
            continue
        if ch == "C" and i + 1 < len(w) and w[i + 1] in "EIY":
            out.append("S")
            i += 1
            continue
        if ch == "G" and i + 1 < len(w) and w[i + 1] in "EIY":
            out.append("JH")
            i += 1
            continue
        if ch == "Y":
            out.append("IY" if i == len(w) - 1 or i > 1 else "Y")
            i += 1
            continue
        if ch == "E" and i == len(w) - 1 and out:
            i += 1  # silent final E
            continue
        ph = _SINGLE.get(ch)
        if ph:
            out.extend(ph)
        i += 1
    return out if out else ["AH"]


def pronounce(word):
    """Return (phonemes, source) for one word.

    source is one of "override", "cmudict", "rules".
    """
    w = word.strip().lower()
    overrides = load_overrides()
    if w in overrides:
        return list(overrides[w]), "override"
    table = load_cmudict()
    if w in table:
        return list(table[w]), "cmudict"
    return pronounce_rules(w), "rules"
