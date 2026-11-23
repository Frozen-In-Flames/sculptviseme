"""Tests for the word-by-word lip-sync aligner.

Fixtures are synthetic WAVs written with the stdlib wave module:
tones stand in for voiced word clips. The negative control is a
silent clip: silence must produce near-zero viseme weights, the
same honesty rule fif-ears runs under.

Run: python3 -m unittest tests.test_lipsync_align -v
"""

import json
import os
import sys
import tempfile
import unittest
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import g2p  # noqa: E402
import lipsync_align as la  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")
ORIG_MAP = os.path.expanduser(
    "~/workspace/voice-asset-format/examples/"
    "aries-hilton-reference/phonemes.json")


def write_wav(path, samples, sr, channels=1):
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    if channels == 2:
        pcm = np.repeat(pcm[:, None], 2, axis=1).reshape(-1)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def tone(sr, seconds, freq=220.0, amp=0.8):
    t = np.arange(int(sr * seconds)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class TestVisemeMap(unittest.TestCase):

    def test_vendored_map_is_verbatim(self):
        if not os.path.exists(ORIG_MAP):
            self.skipTest("original viseme map not present")
        with open(ORIG_MAP, "rb") as fh:
            orig = fh.read()
        vendored = os.path.join(REPO, "assets", "viseme",
                                "phonemes.json")
        with open(vendored, "rb") as fh:
            self.assertEqual(orig, fh.read())

    def test_map_covers_arpabet_plus_sil(self):
        mapping = la.load_viseme_map()
        self.assertEqual(len(mapping), 40)  # 39 ARPAbet + SIL
        self.assertEqual(set(mapping.values()), set(la.VISEMES))
        self.assertEqual(mapping["SIL"], "sil")


class TestG2P(unittest.TestCase):

    def test_cmudict_word(self):
        phonemes, source = g2p.pronounce("hello")
        self.assertEqual(source, "cmudict")
        self.assertEqual(phonemes, ["HH", "AH", "L", "OW"])

    def test_override_word(self):
        phonemes, source = g2p.pronounce("Aries")
        self.assertEqual(source, "override")
        self.assertEqual(phonemes, ["EH", "R", "IY", "Z"])

    def test_rules_fallback_is_labeled_and_valid(self):
        phonemes, source = g2p.pronounce("zxqwv")
        self.assertEqual(source, "rules")
        self.assertTrue(phonemes)
        self.assertTrue(all(p in g2p._ARPABET for p in phonemes))

    def test_every_dictionary_output_maps_to_visemes(self):
        for word in ["the", "clay", "sculpt", "frozen", "banana",
                     "rhythm", "export"]:
            phonemes, _ = g2p.pronounce(word)
            visemes = la.phonemes_to_visemes(phonemes)
            self.assertEqual(len(visemes), len(phonemes))
            self.assertTrue(all(v in la.VISEMES for v in visemes))


class TestAlign(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="lipsync-test-")
        cls.hello = os.path.join(cls.dir, "hello.wav")
        write_wav(cls.hello, tone(22050, 0.30), 22050)  # resample case
        cls.world = os.path.join(cls.dir, "world.wav")
        write_wav(cls.world, tone(16000, 0.30, amp=0.9), 16000)
        cls.quiet = os.path.join(cls.dir, "quiet.wav")
        write_wav(cls.quiet, tone(16000, 0.30, amp=0.05), 16000)
        cls.silence = os.path.join(cls.dir, "silence.wav")
        write_wav(cls.silence, np.zeros(8000, dtype=np.float32), 16000)
        cls.stereo = os.path.join(cls.dir, "aries.wav")
        write_wav(cls.stereo, tone(16000, 0.25), 16000, channels=2)

    def frames_in(self, doc, word):
        rec = next(w for w in doc["words"] if w["text"] == word)
        return [f for f in doc["frames"]
                if rec["start"] <= f["t"] < rec["end"]]

    def test_word_records_and_timeline(self):
        doc = la.align_words([("hello", self.hello),
                              ("world", self.world)], gap_s=0.1)
        self.assertEqual([w["text"] for w in doc["words"]],
                         ["hello", "world"])
        hello, world = doc["words"]
        self.assertEqual(hello["phonemes"], ["HH", "AH", "L", "OW"])
        self.assertEqual(hello["visemes"], ["kk", "aa", "nn", "oh"])
        self.assertEqual(hello["pronunciation_source"], "cmudict")
        self.assertAlmostEqual(hello["end"] - hello["start"], 0.30,
                               delta=0.02)  # 22050 Hz resampled, kept
        self.assertAlmostEqual(world["start"], 0.40, delta=0.02)
        self.assertAlmostEqual(doc["duration"], 0.70, delta=0.03)
        self.assertTrue(doc["frames"])

    def test_loud_word_moves_visemes(self):
        doc = la.align_words([("world", self.world)])
        frames = self.frames_in(doc, "world")
        self.assertTrue(frames)
        peak = max(max(f["weights"]) for f in frames)
        self.assertGreater(peak, 0.5)
        for f in frames:
            self.assertTrue(all(0.0 <= w <= 1.0 for w in f["weights"]))

    def test_silence_negative_control(self):
        doc = la.align_words([("world", self.world),
                              ("pause", self.silence),
                              ("world", self.world)], gap_s=0.05)
        frames = self.frames_in(doc, "pause")
        self.assertTrue(frames)
        peak = max(max(f["weights"]) for f in frames)
        self.assertLess(peak, 1e-3,
                        f"silence produced viseme weight {peak}")

    def test_quiet_word_stays_quiet_relative_to_loud(self):
        doc = la.align_words([("world", self.world),
                              ("world", self.quiet)], gap_s=0.05)
        loud = self.frames_in(doc, "world")
        recs = [w for w in doc["words"] if w["text"] == "world"]
        quiet_frames = [f for f in doc["frames"]
                        if recs[1]["start"] <= f["t"] < recs[1]["end"]]
        loud_peak = max(max(f["weights"]) for f in loud)
        quiet_peak = max(max(f["weights"]) for f in quiet_frames)
        self.assertLess(quiet_peak, 0.35 * loud_peak)

    def test_stereo_clip_and_override_word(self):
        doc = la.align_words([("aries", self.stereo)])
        rec = doc["words"][0]
        self.assertEqual(rec["pronunciation_source"], "override")
        self.assertEqual(rec["visemes"], ["E", "RR", "ih", "SS"])
        self.assertTrue(self.frames_in(doc, "aries"))

    def test_json_round_trip(self):
        doc = la.align_words([("hello", self.hello)])
        text = json.dumps(doc)
        back = json.loads(text)
        self.assertEqual(back["visemes"], la.VISEMES)
        self.assertEqual(len(back["frames"]), len(doc["frames"]))


if __name__ == "__main__":
    unittest.main()
