"""Word-by-word lip-sync alignment for the Clay Sculpt Studio.

Pipeline per RESEARCH.md section 6. Each input clip is one known
word, so word boundaries are given and no forced aligner or speech
recognition is needed:

1. Load the WAV (stdlib wave), mix to mono, resample to 16 kHz.
2. Energy VAD trims leading and trailing silence.
3. G2P turns the word into ARPAbet (see g2p.py; the source of every
   pronunciation is recorded in the output).
4. ARPAbet maps to the 15 visemes through the Voice Asset Format map
   at assets/viseme/phonemes.json, a verbatim copy of
   voice-asset-format/examples/aries-hilton-reference/phonemes.json.
   This module never invents a second map.
5. Viseme weight curves: each phoneme gets a raised-cosine bump
   centered in its time segment (segments tile the trimmed clip),
   scaled by the short-time RMS envelope of the audio, following the
   section 6 formula w_k(t) = clamp(E_rms(t)^gamma * sum_p W(p,k) *
   Phi_cos(t), 0, 1). The envelope is normalized across the whole
   utterance, so a silent clip produces near-zero weights everywhere:
   silence means nothing, the same honesty rule as fif-ears.

Output: a keyframes JSON document (frames at a fixed fps, one weight
per viseme per frame) plus per-word timing, phonemes, visemes and
pronunciation source. glb_exporter.py can bake the same curves into
a GLB weights animation channel.

CLI:
    python3 lipsync_align.py words.json -o keyframes.json
where words.json is [{"text": "hello", "clip": "hello.wav"}, ...].
"""

import json
import math
import os
import wave

import numpy as np
from scipy.signal import resample_poly

import g2p

TARGET_SR = 16000
VISEMES = ["sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn",
           "RR", "aa", "E", "ih", "oh", "ou"]
_VISEME_INDEX = {v: i for i, v in enumerate(VISEMES)}

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_VISEME_MAP_PATH = os.path.join(_REPO, "assets", "viseme",
                                "phonemes.json")

_map_cache = None


def load_viseme_map(path=_VISEME_MAP_PATH):
    """The one phoneme to viseme map, loaded verbatim."""
    global _map_cache
    if _map_cache is None:
        with open(path, "r", encoding="utf-8") as fh:
            _map_cache = json.load(fh)["mapping"]
    return _map_cache


def phonemes_to_visemes(phonemes):
    mapping = load_viseme_map()
    return [mapping[p] for p in phonemes]


# ---- Audio -----------------------------------------------------------

def load_wav(path):
    """Return (mono float32 samples in -1..1, sample_rate)."""
    with wave.open(path, "rb") as wf:
        n_ch = wf.getnchannels()
        width = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
                - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {width} in {path}")
    if n_ch > 1:
        data = data.reshape(-1, n_ch).mean(axis=1)
    return data.astype(np.float32), sr


def resample_to_target(samples, sr, target_sr=TARGET_SR):
    if sr == target_sr:
        return samples
    g = math.gcd(sr, target_sr)
    return resample_poly(samples, target_sr // g, sr // g).astype(np.float32)


def frame_rms(samples, sr, frame_s=0.010, hop_s=0.005):
    """Short-time RMS. Returns (frame_center_times, rms_values)."""
    frame = max(1, int(sr * frame_s))
    hop = max(1, int(sr * hop_s))
    if len(samples) < frame:
        pad = frame - len(samples)
        samples = np.pad(samples, (0, pad))
    n_frames = 1 + (len(samples) - frame) // hop
    idx = np.arange(n_frames)[:, None] * hop + np.arange(frame)[None, :]
    frames = samples[idx]
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    times = (np.arange(n_frames) * hop + frame / 2.0) / sr
    return times, rms


def trim_silence(samples, sr, rel_thresh=0.02, floor=1e-4):
    """Energy VAD trim. Returns (trimmed, start_offset_seconds).

    A fully silent clip trims to an empty array; callers keep the
    original duration for timing and emit zero weights.
    """
    if len(samples) == 0:
        return samples, 0.0
    _, rms = frame_rms(samples, sr)
    peak = float(rms.max()) if len(rms) else 0.0
    if peak <= floor:
        return np.zeros(0, dtype=np.float32), 0.0
    active = rms > max(rel_thresh * peak, floor)
    if not active.any():
        return np.zeros(0, dtype=np.float32), 0.0
    hop = max(1, int(sr * 0.005))
    frame = max(1, int(sr * 0.010))
    first = int(np.argmax(active))
    last = len(active) - int(np.argmax(active[::-1]))
    start = first * hop
    end = min(len(samples), (last - 1) * hop + frame)
    return samples[start:end], start / sr


# ---- Curves ----------------------------------------------------------

def _raised_cosine(t, center, half_width):
    """Phi_cos: 1 at center, 0 at center +/- half_width, smooth."""
    d = np.abs(t - center) / half_width
    out = np.zeros_like(t)
    inside = d < 1.0
    out[inside] = 0.5 * (1.0 + np.cos(np.pi * d[inside]))
    return out


def word_curves(phonemes, duration, env_times, env_rms, gamma=1.0,
                fps=30, t_offset=0.0):
    """Viseme weight curves for one word.

    Returns (frame_times_local, weights) with weights of shape
    (n_frames, 15). Phonemes tile the word duration evenly; each
    phoneme's bump half width is 0.75 of its segment, so adjacent
    phonemes overlap by half a segment (coarticulation).
    """
    n_frames = max(1, int(round(duration * fps)))
    times = (np.arange(n_frames) + 0.5) / fps
    weights = np.zeros((n_frames, len(VISEMES)), dtype=np.float64)
    if not phonemes or duration <= 0:
        return times, weights
    visemes = phonemes_to_visemes(phonemes)
    seg = duration / len(phonemes)
    env_at = np.interp(times, env_times, env_rms,
                       left=0.0, right=0.0) if len(env_times) else \
        np.zeros(n_frames)
    scale = np.clip(env_at, 0.0, 1.0) ** gamma
    for p, vis in enumerate(visemes):
        center = (p + 0.5) * seg
        bump = _raised_cosine(times, center, 0.75 * seg)
        weights[:, _VISEME_INDEX[vis]] += bump * scale
    return times, np.clip(weights, 0.0, 1.0)


def align_words(clips, fps=30, gap_s=0.12, gamma=1.0):
    """Align a sequence of (word_text, wav_path) clips.

    Returns the keyframes document: per-word records plus dense
    frames across the whole utterance timeline.
    """
    prepared = []
    for text, path in clips:
        samples, sr = load_wav(path)
        samples = resample_to_target(samples, sr)
        duration_full = len(samples) / TARGET_SR
        trimmed, _ = trim_silence(samples, TARGET_SR)
        env_times, env_rms = frame_rms(
            trimmed if len(trimmed) else samples, TARGET_SR)
        prepared.append({
            "text": text, "path": path, "duration": duration_full,
            "trimmed": trimmed, "env_times": env_times,
            "env_rms": env_rms,
        })
    # Envelope normalization is utterance-wide: a quiet word stays
    # quiet relative to a loud one, and silence stays at zero.
    peak = max((float(p["env_rms"].max()) if len(p["env_rms"]) else 0.0)
               for p in prepared) if prepared else 0.0

    words_out = []
    all_times = []
    all_weights = []
    cursor = 0.0
    for p in prepared:
        phonemes, source = g2p.pronounce(p["text"])
        visemes = phonemes_to_visemes(phonemes)
        if peak > 0:
            env_norm = p["env_rms"] / peak
        else:
            env_norm = p["env_rms"]
        times, weights = word_curves(
            phonemes, p["duration"], p["env_times"], env_norm,
            gamma=gamma, fps=fps)
        if len(p["trimmed"]) == 0:
            weights[:] = 0.0  # silence: nothing, by construction
        words_out.append({
            "text": p["text"], "clip": os.path.basename(p["path"]),
            "start": round(cursor, 4),
            "end": round(cursor + p["duration"], 4),
            "phonemes": phonemes, "visemes": visemes,
            "pronunciation_source": source,
        })
        all_times.append(times + cursor)
        all_weights.append(weights)
        cursor += p["duration"] + gap_s

    total = cursor - gap_s if words_out else 0.0
    if all_times:
        times = np.concatenate(all_times)
        weights = np.vstack(all_weights)
        order = np.argsort(times)
        times, weights = times[order], weights[order]
    else:
        times = np.zeros(0)
        weights = np.zeros((0, len(VISEMES)))
    frames = [{
        "t": round(float(t), 4),
        "weights": [round(float(w), 5) for w in row],
    } for t, row in zip(times, weights)]
    return {
        "format": "clay-sculpt-studio/viseme-keyframes",
        "version": "0.1.0",
        "fps": fps,
        "sample_rate_hz": TARGET_SR,
        "visemes": VISEMES,
        "duration": round(total, 4),
        "envelope_gamma": gamma,
        "gap_s": gap_s,
        "words": words_out,
        "frames": frames,
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("words_json",
                    help='JSON list of {"text", "clip"} entries')
    ap.add_argument("-o", "--out", default="keyframes.json")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--gap", type=float, default=0.12)
    args = ap.parse_args(argv)
    with open(args.words_json, "r", encoding="utf-8") as fh:
        entries = json.load(fh)
    base = os.path.dirname(os.path.abspath(args.words_json))
    clips = []
    for e in entries:
        clip = e["clip"]
        if not os.path.isabs(clip):
            clip = os.path.join(base, clip)
        clips.append((e["text"], clip))
    doc = align_words(clips, fps=args.fps, gap_s=args.gap)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    print(f"wrote {args.out}: {len(doc['words'])} words, "
          f"{len(doc['frames'])} frames, {doc['duration']}s")


if __name__ == "__main__":
    main()
