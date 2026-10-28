"""Deepgram Nova-3 transcription for ESL student recordings (RU+EN aware).

Proven recipe:
  - model=nova-3, language=multi  -> code-switching, Russian comes back in
    CYRILLIC, per-word language tags (use for mix stats, not hard routing)
  - verbatim=true + filler_words=true, punctuate=true, smart_format=false
  - utterances=true, diarize=true, paragraphs=true
  - `detect_language=true` collapses to ONE language (loses the Russian) -
    never use it for student recordings; `multi` is the right mode.
  - CRITICAL sandbox quirk: upload the audio as a RAW BODY with an explicit
    Content-Type. The sandbox egress proxy corrupts multipart uploads.

Normalized output JSON:
  {meta, transcript, words[], utterances[], stats{words_total, wpm, pauses
   (gaps >= 0.6 s), fillers, low_confidence_words (< 0.7), language_mix}}
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
DEFAULT_MODEL = "nova-3"
DEFAULT_LANGUAGE = "multi"
PAUSE_THRESHOLD_S = 0.6
LOW_CONFIDENCE = 0.7

# Reference .env files that hold DEEPGRAM_API_KEY (values are never printed).
ENV_CANDIDATES = [
    Path.home() / ".edvibe_env",
    Path.home() / ".env",
]

# Non-lexical filler tokens worth counting (EN + RU), lowercase, stripped.
FILLERS = {
    "um", "uh", "uhm", "uhh", "erm", "er", "eh", "ah", "mm", "mmm", "hmm",
    "mhm", "uhhuh",
    "э", "ээ", "эээ", "мм", "ммм", "мгм",
}

CONTENT_TYPES = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".mp4": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".opus": "audio/opus", ".flac": "audio/flac",
    ".webm": "audio/webm", ".aiff": "audio/aiff", ".amr": "audio/amr",
}


def load_api_key():
    for candidate in ENV_CANDIDATES:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8",
                                            errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "DEEPGRAM_API_KEY":
                    return v.strip().strip('"').strip("'")
    v = os.environ.get("DEEPGRAM_API_KEY", "")
    if not v:
        raise RuntimeError(
            "DEEPGRAM_API_KEY not found in ~/.edvibe_env, ~/.env or the environment")
    return v


def guess_content_type(path):
    return CONTENT_TYPES.get(Path(path).suffix.lower(), "audio/wav")


def fetch_url(url, dest_dir):
    name = Path(urlparse(url).path).name or "download"
    dest = Path(dest_dir) / name
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    return dest


def to_wav_16k(src, dest):
    """Transcode any (browser-recorded) format to 16 kHz mono WAV."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(dest)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return dest


def _request_params(language, model):
    params = {
        "model": model,
        "punctuate": "true",
        "filler_words": "true",
        "verbatim": "true",
        "smart_format": "false",   # mutually exclusive with verbatim
        "utterances": "true",
        "diarize": "true",
        "paragraphs": "true",
    }
    if language == "detect":
        params["detect_language"] = "true"   # cannot combine with `language`
    else:
        params["language"] = language
    return params


def _post_with_retry(params, headers, json_body=None, data=None, attempts=3,
                     log=None):
    """POST to Deepgram with retries on transient failures (408 SLOW_UPLOAD /
    429 / 5xx / connection aborts — the sandbox egress proxy throttles
    uploads intermittently)."""
    last_err = None
    for i in range(attempts):
        try:
            t0 = time.time()
            resp = requests.post(DEEPGRAM_URL, params=params, headers=headers,
                                 json=json_body, data=data, timeout=1800)
            elapsed = time.time() - t0
            if resp.status_code == 200:
                raw = resp.json()
                raw["_request_seconds"] = round(elapsed, 2)
                return raw
            last_err = ("Deepgram returned %s (%.1fs): %s"
                        % (resp.status_code, elapsed, resp.text[:300]))
            if resp.status_code in (408, 429) or resp.status_code >= 500:
                if log:
                    log("retry %d/%d: %s" % (i + 1, attempts, last_err))
                if i < attempts - 1:
                    time.sleep(2.0 * (i + 1))
                    continue
            raise RuntimeError(last_err)
        except requests.exceptions.RequestException as exc:
            last_err = "Deepgram request failed: %s" % exc
            if log:
                log("retry %d/%d: %s" % (i + 1, attempts, last_err))
            if i < attempts - 1:
                time.sleep(2.0 * (i + 1))
                continue
            raise RuntimeError(last_err)
    raise RuntimeError(last_err or "Deepgram request failed")


def call_deepgram(audio, api_key, language, model=DEFAULT_MODEL, log=None):
    """Upload audio to Deepgram /v1/listen as a RAW body (multipart is
    corrupted by the sandbox egress proxy). Returns the raw JSON."""
    with open(audio, "rb") as f:
        data = f.read()
    return _post_with_retry(
        params=_request_params(language, model),
        headers={
            "Authorization": "Token %s" % api_key,
            "Content-Type": guess_content_type(audio),  # raw body, NOT multipart
        },
        data=data, log=log)


def call_deepgram_url(url, api_key, language, model=DEFAULT_MODEL, log=None):
    """Let Deepgram FETCH the audio itself (JSON `{"url": ...}` body) — for
    public CDN links (e.g. the Edvibe recording mp3s) this skips the sandbox
    upload path entirely."""
    return _post_with_retry(
        params=_request_params(language, model),
        headers={"Authorization": "Token %s" % api_key,
                 "Content-Type": "application/json"},
        json_body={"url": url}, log=log)


def _clean_token(text):
    return re.sub(r"[^\w\s\u0400-\u04FF-]", "", (text or "").lower()).strip()


def normalize(raw, file_label, model=DEFAULT_MODEL, language_mode=DEFAULT_LANGUAGE):
    """Pure function: Deepgram response -> normalized stats JSON."""
    try:
        alt = raw["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError, TypeError):
        raise ValueError("unexpected Deepgram response shape: "
                         "missing results.channels[0].alternatives[0]")

    words = []
    for w in alt.get("words") or []:
        start, end = w.get("start"), w.get("end")
        text = _clean_token(w.get("punctuated_word") or w.get("word"))
        if start is None or end is None or not text:
            continue
        entry = {
            "word": text,
            "start": round(float(start), 3),
            "end": round(float(end), 3),
            "confidence": round(float(w.get("confidence", 0.0)), 4),
        }
        lang = w.get("language")
        if lang:
            entry["language"] = str(lang).split("-")[0].lower()
        if w.get("speaker") is not None:
            entry["speaker"] = int(w["speaker"])
        if w.get("filler"):
            entry["filler"] = True
        words.append(entry)

    utterances = []
    for u in raw["results"].get("utterances") or []:
        utterances.append({
            "start": round(float(u.get("start", 0)), 3),
            "end": round(float(u.get("end", 0)), 3),
            "transcript": (u.get("transcript") or "").strip(),
        })

    duration = raw.get("metadata", {}).get("duration")
    if duration:
        duration = round(float(duration), 3)
    elif words:
        duration = words[-1]["end"]
    else:
        duration = 0.0

    words_total = len(words)
    wpm = round(words_total / (duration / 60.0), 1) if duration > 0 else 0.0

    pauses = []
    for prev, cur in zip(words, words[1:]):
        gap = cur["start"] - prev["end"]
        if gap >= PAUSE_THRESHOLD_S:
            pauses.append({
                "start": round(prev["end"], 3),
                "end": round(cur["start"], 3),
                "duration": round(gap, 3),
            })

    fillers = {}
    for w in words:
        tok = w["word"]
        if w.get("filler") or tok in FILLERS:
            fillers[tok] = fillers.get(tok, 0) + 1

    low_conf = [{"word": w["word"], "start": w["start"],
                 "confidence": w["confidence"]}
                for w in words if w["confidence"] < LOW_CONFIDENCE]

    language_mix = {}
    for w in words:
        if w.get("language"):
            language_mix[w["language"]] = language_mix.get(w["language"], 0) + 1

    stats = {
        "words_total": words_total,
        "wpm": wpm,
        "pauses": pauses,
        "fillers": fillers,
        "low_confidence_words": low_conf,
    }
    if language_mix:
        stats["language_mix"] = language_mix

    return {
        "meta": {
            "file": file_label,
            "model": raw.get("metadata", {}).get("model_info", {}).get("name", model),
            "language_mode": language_mode,
            "duration_s": duration,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "request_seconds": raw.get("_request_seconds"),
        },
        "transcript": alt.get("transcript", "").strip(),
        "words": words,
        "utterances": utterances,
        "stats": stats,
    }


def transcribe(source, out_path=None, language=DEFAULT_LANGUAGE,
               model=DEFAULT_MODEL, transcode=False, keep_raw=False,
               api_key=None, log=None, download=False):
    """Transcribe a local file path or an http(s) URL.

    For http(s) sources Deepgram fetches the URL server-side by default
    (`download=True` forces the local download + upload path; that path is
    also the automatic fallback). Returns the normalized result dict; writes
    it to `out_path` (default: <audio>.json next to the file / cwd for URLs)."""
    def _log(msg):
        if log:
            log(msg)

    api_key = api_key or load_api_key()
    src_is_url = str(source).startswith(("http://", "https://"))
    file_label = None
    raw = None

    if src_is_url:
        file_label = Path(urlparse(str(source)).path).name or "audio"
        if not download:
            try:
                _log("calling Deepgram (%s, language=%s) via URL fetch"
                     % (model, language))
                raw = call_deepgram_url(str(source), api_key, language, model,
                                        log=log)
            except RuntimeError as exc:
                _log("URL mode failed (%s) — falling back to download+upload"
                     % exc)

    if raw is None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            if src_is_url:
                _log("downloading %s" % source)
                src = fetch_url(str(source), tmpdir)
            else:
                src = Path(source).expanduser().resolve()
                if not src.exists():
                    raise RuntimeError("file not found: %s" % src)
                file_label = src.name

            upload = src
            if transcode and src.suffix.lower() != ".wav":
                if shutil.which("ffmpeg"):
                    _log("transcoding to 16 kHz mono wav")
                    upload = to_wav_16k(src, tmpdir / (src.stem + ".wav"))
                else:
                    _log("note: ffmpeg missing, uploading original format")

            _log("calling Deepgram (%s, language=%s)" % (model, language))
            raw = call_deepgram(upload, api_key, language, model, log=log)

    result = normalize(raw, file_label, model, language)

    if out_path is None:
        if src_is_url:
            out_path = Path(file_label).with_suffix(".json")
        else:
            out_path = Path(source).expanduser().resolve().with_suffix(".json")
    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    result["meta"]["out_path"] = str(out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    if keep_raw:
        out.with_suffix(".raw.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    result["meta"]["out_path"] = str(out)
    return result


def format_summary(result):
    m, s = result["meta"], result["stats"]
    lines = [
        "file           : %s" % m["file"],
        "model/lang     : %s / %s   (request %ss)"
        % (m["model"], m["language_mode"], m.get("request_seconds")),
        "duration       : %s s" % m["duration_s"],
        "words          : %s  (%s wpm)" % (s["words_total"], s["wpm"]),
        "pauses >=0.6s  : %d  %s" % (
            len(s["pauses"]),
            "[" + ", ".join("%ss@%s" % (p["duration"], p["start"])
                            for p in s["pauses"]) + "]" if s["pauses"] else ""),
        "fillers        : %s" % (s["fillers"] or "none"),
    ]
    if "language_mix" in s:
        lines.append("language mix   : %s"
                     % ", ".join("%s:%s" % (k, v)
                                 for k, v in sorted(s["language_mix"].items())))
    lines.append("low-conf (<0.7): %d" % len(s["low_confidence_words"]))
    lines.append("first lines    :")
    if result["utterances"]:
        for u in result["utterances"][:3]:
            lines.append("  [%6.2f-%6.2f] %s" % (u["start"], u["end"],
                                                 u["transcript"]))
    else:
        lines.append("  " + (result["transcript"][:200] or "(empty)"))
    return "\n".join(lines)
