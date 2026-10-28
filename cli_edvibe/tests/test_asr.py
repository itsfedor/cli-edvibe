"""Offline unit tests: core.asr (normalize + transcribe file plumbing)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli_edvibe.core import asr  # noqa: E402

RAW = {
    "metadata": {"duration": 9.35, "model_info": {"name": "nova-3"}},
    "results": {
        "channels": [{"alternatives": [{
            "transcript": "I usually, um, wake up early. Я обычно встаю рано.",
            "words": [
                {"punctuated_word": "I", "start": 0.1, "end": 0.3,
                 "confidence": 0.99, "language": "en", "speaker": 0},
                {"punctuated_word": "usually,", "start": 0.3, "end": 0.7,
                 "confidence": 0.95, "language": "en", "speaker": 0},
                {"word": "um", "punctuated_word": "um", "start": 0.8, "end": 1.0,
                 "confidence": 0.88, "language": "en", "speaker": 0, "filler": True},
                {"punctuated_word": "wake", "start": 1.1, "end": 1.4,
                 "confidence": 0.97, "language": "en"},
                {"punctuated_word": "up", "start": 1.4, "end": 1.6,
                 "confidence": 0.4, "language": "en"},
                {"punctuated_word": "early.", "start": 1.6, "end": 2.0,
                 "confidence": 0.99, "language": "en"},
                {"punctuated_word": "Я", "start": 2.9, "end": 3.1,
                 "confidence": 0.93, "language": "ru"},
                {"punctuated_word": "обычно", "start": 3.1, "end": 3.6,
                 "confidence": 0.9, "language": "ru"},
                {"punctuated_word": "встаю", "start": 3.6, "end": 4.0,
                 "confidence": 0.9, "language": "ru"},
                {"punctuated_word": "рано.", "start": 4.0, "end": 4.4,
                 "confidence": 0.9, "language": "ru"},
            ],
        }], "detected_language": "en"}],
        "utterances": [
            {"start": 0.0, "end": 2.0, "transcript": "I usually, um, wake up early."},
            {"start": 2.9, "end": 4.4, "transcript": "Я обычно встаю рано."},
        ],
    },
}


def test_normalize_stats():
    r = asr.normalize(RAW, "x.mp3", "nova-3", "multi")
    s = r["stats"]
    assert s["words_total"] == 10
    assert s["fillers"] == {"um": 1}
    assert r["words"][1]["word"] == "usually"      # punctuation stripped
    assert r["words"][5]["word"] == "early"
    # one pause: 2.0 -> 2.9 (0.9 s); the 0.3->0.8 gap is 0.5 s (< 0.6)
    assert len(s["pauses"]) == 1
    assert s["pauses"][0] == {"start": 2.0, "end": 2.9, "duration": 0.9}
    assert [w["word"] for w in s["low_confidence_words"]] == ["up"]
    assert s["language_mix"] == {"en": 6, "ru": 4}
    assert s["wpm"] == pytest.approx(64.2, abs=0.1)
    assert r["utterances"][1]["transcript"] == "Я обычно встаю рано."
    assert r["meta"]["model"] == "nova-3"


def test_normalize_detect_mode_has_no_language_mix():
    raw = json.loads(json.dumps(RAW))
    for w in raw["results"]["channels"][0]["alternatives"][0]["words"]:
        w.pop("language", None)
    r = asr.normalize(raw, "x.mp3", "nova-3", "detect")
    assert "language_mix" not in r["stats"]


def test_normalize_bad_shape():
    with pytest.raises(ValueError):
        asr.normalize({"results": {}}, "x.mp3")


def test_transcribe_writes_json(tmp_path, monkeypatch):
    monkeypatch.setattr(asr, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(asr, "call_deepgram",
                        lambda audio, key, lang, model, log=None: RAW)
    f = tmp_path / "clip.wav"
    f.write_bytes(b"RIFF....")
    out = tmp_path / "clip.json"
    r = asr.transcribe(str(f), out_path=str(out), transcode=False)
    assert out.exists()
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["stats"]["words_total"] == 10
    assert r["meta"]["out_path"] == str(out)


def test_transcribe_default_out_path(tmp_path, monkeypatch):
    monkeypatch.setattr(asr, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(asr, "call_deepgram",
                        lambda audio, key, lang, model, log=None: RAW)
    f = tmp_path / "clip2.wav"
    f.write_bytes(b"RIFF....")
    r = asr.transcribe(str(f), transcode=False)
    assert r["meta"]["out_path"] == str(tmp_path / "clip2.json")
    assert (tmp_path / "clip2.json").exists()


def test_transcribe_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(asr, "load_api_key", lambda: "test-key")
    with pytest.raises(RuntimeError):
        asr.transcribe(str(tmp_path / "nope.wav"), transcode=False)


def test_transcribe_url_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(asr, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(asr, "call_deepgram_url",
                        lambda url, key, lang, model, log=None: RAW)
    out = tmp_path / "rec.json"
    r = asr.transcribe("https://cdn.example.com/dir/rec.mp3", out_path=str(out))
    assert out.exists()
    assert r["meta"]["file"] == "rec.mp3"
    assert r["stats"]["words_total"] == 10


def test_transcribe_url_fallback_to_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(asr, "load_api_key", lambda: "test-key")

    def boom(url, key, lang, model, log=None):
        raise RuntimeError("URL mode down")
    monkeypatch.setattr(asr, "call_deepgram_url", boom)

    def fake_fetch(url, dest_dir):
        p = os.path.join(dest_dir, "rec.mp3")
        with open(p, "wb") as f:
            f.write(b"ID3")
        return p
    monkeypatch.setattr(asr, "fetch_url", fake_fetch)
    monkeypatch.setattr(asr, "call_deepgram",
                        lambda audio, key, lang, model, log=None: RAW)

    out = tmp_path / "rec.json"
    r = asr.transcribe("https://cdn.example.com/rec.mp3", out_path=str(out))
    assert out.exists()
    assert r["stats"]["words_total"] == 10


def test_post_with_retry_recovers_from_408(monkeypatch):
    state = {"n": 0}

    class R:
        def __init__(self, code):
            self.status_code = code
            self.text = "SLOW_UPLOAD"

        def json(self):
            return RAW

    def fake_post(url, params=None, headers=None, json=None, data=None,
                  timeout=None):
        state["n"] += 1
        return R(408) if state["n"] < 3 else R(200)

    monkeypatch.setattr(asr.requests, "post", fake_post)
    monkeypatch.setattr(asr.time, "sleep", lambda s: None)
    raw = asr._post_with_retry(params={"model": "nova-3"},
                               headers={"Authorization": "Token x"},
                               data=b"abc")
    assert state["n"] == 3
    assert raw["_request_seconds"] is not None


def test_post_with_retry_hard_error_not_retried(monkeypatch):
    calls = {"n": 0}

    class R:
        status_code = 400
        text = "bad request"

    def fake_post(url, params=None, headers=None, json=None, data=None,
                  timeout=None):
        calls["n"] += 1
        return R()

    monkeypatch.setattr(asr.requests, "post", fake_post)
    with pytest.raises(RuntimeError):
        asr._post_with_retry(params={}, headers={}, data=b"abc", attempts=3)
    assert calls["n"] == 1


def test_format_summary():
    r = asr.normalize(RAW, "x.mp3", "nova-3", "multi")
    txt = asr.format_summary(r)
    assert "fillers" in txt and "um" in txt
    assert "language mix" in txt and "ru:4" in txt
