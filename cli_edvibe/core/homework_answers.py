"""Read (and download) a pupil's SUBMITTED homework answers — READ-ONLY.

Teacher-side contract, verified live against real submissions:

  HomeworkWsController.GetHomeworkLessons  {LessonId, PupilId, ClassId, UserId}
      -> Value.Items[]: the pupil's homework sheets (Id = HomeworkLessonId)
  HomeworkWsController.LoadHomeworkGroupExercises
      {LessonId, PupilId, ClassId, HomeworkLessonId}
      -> Value.Items[]: the sheet's exercises WITH the pupil's answers embedded:
         * voice recording (Type 30): AnswerVersion1[0].JsonAnswerVersion1
           .ManyAnswers[0].Answer  = full mp3 URL (public CDN, no auth)
         * writing (Type 26):          Essay.Text / EssaysPupils[0].Essay.Text
         * typed:                      ManyAnswers[].Answer /
                                       RepeatingManyAnswers[][].Text
         * submission time:            AnswerVersion1[0].Date

This module never calls a Save/Delete/Comment RPC.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import os
import posixpath
import re
from urllib.parse import urlparse

import requests

AUDIO_MEDIA = "LessonExerciseAudioRecordings"

# ExerciseTypeEnum (from the shell bundles)
TYPE_NAMES = {
    2: "Images", 3: "Video", 4: "Audio", 5: "Test", 6: "MappingWords",
    7: "ImageCaption", 10: "InputCorrectFormWord", 11: "AddToDialogue",
    12: "TranslateSentences", 13: "SelectCorrectFormWord", 14: "TrueOrFalse",
    15: "MakeSentenceByWords", 17: "MappingImageByDrag", 18: "PasteWordByDrag",
    19: "GroupWordsByColumns", 20: "ChoiseExtraWords", 21: "AddWordsToVocabulary",
    22: "Note", 23: "BuildWordFromLetters", 24: "Rules", 25: "Topic", 26: "Essay",
    27: "GalleryOpeningDown", 28: "Text", 29: "Button", 30: "AudioRecording",
    31: "DividingLine", 32: "ImagesGif", 33: "MiroBoard", 34: "GooglePDF",
    35: "Wordwall", 36: "Learningapps", 37: "SentencesInCorrectOrder",
    38: "ImageInputCorrectWord", 39: "ImageSelectCorrectWord", 41: "Genially",
    42: "Baamboozle", 43: "Quizlet",
}

TYPE_AUDIO = 30    # AudioRecording — student voice recording
TYPE_ESSAY = 26    # Essay — writing exercise


def type_name(t):
    return TYPE_NAMES.get(t, "Type%s" % t)


def strip_html(s):
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).replace("\xa0", " ").strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "item"


def list_sheets(session, pupil_id, class_id, lesson_id=None):
    """The pupil's homework sheets that have exercises (newest first).

    LessonId is effectively ignored by the server when PupilId is set, so the
    optional lesson filter is applied client-side."""
    items = session.homework_lessons(lesson_id or 0, pupil_id, class_id)
    items = [it for it in items if it.get("ExercisesCount")]
    if lesson_id:
        items = [it for it in items if it.get("LessonId") == lesson_id]
    return sorted(items, key=lambda it: it.get("Id") or 0, reverse=True)


def extract(item):
    """Normalize one homework exercise row (with the pupil's answer) into a
    check-ready dict."""
    out = {
        "exercise_id": item.get("Id"),
        "number": item.get("Number"),
        "type": item.get("Type"),
        "type_name": type_name(item.get("Type")),
        "name": strip_html(item.get("Name")),
        "answered": False,
        "submitted_at": None,
        "audio_urls": [],
        "audio_duration_s": None,
        "writing_text": None,
        "typed_answers": [],
        "teacher_checked_at": None,
        "teacher_right": None,
    }
    avs = item.get("AnswerVersion1") or []
    if avs:
        av = avs[0] or {}
        j = av.get("JsonAnswerVersion1") or {}
        out["submitted_at"] = av.get("Date")
        many = j.get("ManyAnswers") or []
        rep = j.get("RepeatingManyAnswers") or []
        for m in many:
            val = (m or {}).get("Answer")
            if isinstance(val, str) and val.strip():
                if val.startswith("http") and AUDIO_MEDIA in val:
                    out["audio_urls"].append(val)
                else:
                    out["typed_answers"].append(strip_html(val))
        for grp in rep:
            for m in grp or []:
                txt = (m or {}).get("Text")
                if txt:
                    out["typed_answers"].append(strip_html(txt))
        out["answered"] = bool(out["audio_urls"] or out["typed_answers"]) or (
            any((m or {}).get("Answer") for m in many))

    # teacher verdict, when present
    teacher = item.get("AnswersTeacher") or []
    if teacher:
        t0 = teacher[0] or {}
        out["teacher_checked_at"] = t0.get("Date")
        aec = (t0.get("JsonAnswerVersion1") or {}).get("AnswerErrorsCount") or []
        try:
            out["teacher_right"] = bool(aec[0][0].get("IsRightAnswer"))
        except (IndexError, KeyError, TypeError):
            pass

    # voice-recording prompt/duration
    ar = item.get("AudioRecording") or {}
    if ar.get("RecordingDuration"):
        out["audio_duration_s"] = ar.get("RecordingDuration")

    # Writing exercise (Type 26): pupil text lives in Essay/EssaysPupils
    essay = item.get("Essay") or {}
    ep = item.get("EssaysPupils") or []
    if ep:
        essay = (ep[0] or {}).get("Essay") or essay
    if essay:
        txt = strip_html(essay.get("Text") or "")
        if txt:
            out["writing_text"] = txt
            out["answered"] = True
        if not out["submitted_at"] and essay.get("PrevHashText"):
            out["answered"] = True  # submitted; no timestamp in this view
    return out


def collect(session, pupil_id, class_id, lesson_id=None, sheet_id=None,
            limit=None):
    """Pupil's sheets + normalized answers. One LoadHomeworkGroupExercises
    call per sheet (2 RPCs total for a single-sheet read)."""
    sheets = list_sheets(session, pupil_id, class_id, lesson_id=lesson_id)
    if sheet_id:
        sheets = [s for s in sheets if s.get("Id") == sheet_id]
        if not sheets:
            raise RuntimeError(
                "sheet %s not found for pupil %s (class %s)"
                % (sheet_id, pupil_id, class_id))
    elif limit:
        sheets = sheets[:limit]

    out = []
    for sheet in sheets:
        value = session.load_homework_sheet(sheet.get("LessonId"), pupil_id,
                                            class_id, sheet.get("Id"))
        items = value.get("Items") or []
        exercises = [extract(it) for it in items]
        out.append({
            "sheet_id": sheet.get("Id"),
            "lesson_id": sheet.get("LessonId"),
            "name": strip_html(sheet.get("Name")),
            "complete_status": value.get("CompleteStatus"),
            "exercises_count": len(exercises),
            "answered_count": sum(1 for e in exercises if e["answered"]),
            "exercises": exercises,
        })
    return {"pupil_id": pupil_id, "class_id": class_id,
            "lesson_id": lesson_id, "sheets": out}


# ------------------------------------------------------------------ download
def _fetch_to_file(url, path, force=False):
    """Stream-download `url` to `path`. Returns {status, bytes}."""
    if not force and os.path.exists(path) and os.path.getsize(path) > 0:
        return {"status": "cached", "bytes": os.path.getsize(path)}
    tmp = path + ".part"
    try:
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            n = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
                    n += len(chunk)
        os.replace(tmp, path)
        return {"status": "downloaded", "bytes": n}
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def download(session, pupil_id, class_id, out_dir, lesson_id=None, sheet_id=None,
             limit=None, force=False, log=None):
    """Download every submitted voice recording + writing text into out_dir.

    Layout:
        <out_dir>/sheet_<id>/ex<NN>_<exid>_<type>[_aN].mp3
        <out_dir>/sheet_<id>/ex<NN>_<exid>_<type>.writing.txt
        <out_dir>/manifest.json          (all answers + file map)
    """
    data = collect(session, pupil_id, class_id, lesson_id=lesson_id,
                   sheet_id=sheet_id, limit=limit)
    os.makedirs(out_dir, exist_ok=True)

    manifest = {
        "pupil_id": pupil_id,
        "class_id": class_id,
        "out_dir": os.path.abspath(out_dir),
        "downloaded_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "sheets": [],
    }
    tot_audio = tot_writing = tot_errors = 0
    for sheet in data["sheets"]:
        sdir = os.path.join(out_dir, "sheet_%s" % sheet["sheet_id"])
        files = []
        for ex in sheet["exercises"]:
            if not ex["answered"]:
                continue
            stem = "ex%s_%s_%s" % (ex.get("number") or "x", ex["exercise_id"],
                                   slug(ex["type_name"]))
            for i, url in enumerate(ex["audio_urls"]):
                ext = posixpath.splitext(urlparse(url).path)[1] or ".mp3"
                suffix = "" if len(ex["audio_urls"]) == 1 else "_a%d" % (i + 1)
                path = os.path.join(sdir, stem + suffix + ext)
                os.makedirs(sdir, exist_ok=True)
                try:
                    r = _fetch_to_file(url, path, force=force)
                    status = r["status"]
                except (requests.RequestException, OSError) as exc:
                    status = "error: %s" % exc
                    tot_errors += 1
                if status == "downloaded" or status == "cached":
                    tot_audio += 1
                if log:
                    log("%s  %s" % (status, os.path.relpath(path, out_dir)))
                files.append({"kind": "audio", "url": url,
                              "path": os.path.relpath(path, out_dir),
                              "status": status})
            if ex["writing_text"]:
                wpath = os.path.join(sdir, stem + ".writing.txt")
                os.makedirs(sdir, exist_ok=True)
                with open(wpath, "w", encoding="utf-8") as f:
                    f.write(ex["writing_text"] + "\n")
                tot_writing += 1
                files.append({"kind": "writing",
                              "path": os.path.relpath(wpath, out_dir),
                              "status": "written"})
        manifest["sheets"].append({
            "sheet_id": sheet["sheet_id"],
            "lesson_id": sheet["lesson_id"],
            "name": sheet["name"],
            "answered_count": sheet["answered_count"],
            "answers": [e for e in sheet["exercises"] if e["answered"]],
            "files": files,
        })
    manifest["totals"] = {"audio": tot_audio, "writing": tot_writing,
                          "errors": tot_errors}

    mpath = os.path.join(out_dir, "manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    manifest["manifest_path"] = mpath
    return manifest


# ------------------------------------------------------------------ reports
def format_report(data, only_answered=False):
    lines = ["Pupil %s | class %s — %d sheet(s) with exercises"
             % (data["pupil_id"], data["class_id"], len(data["sheets"]))]
    for sheet in data["sheets"]:
        lines.append("")
        lines.append("SHEET %s | lesson %s | %s | exercises: %d answered: %d"
                     % (sheet["sheet_id"], sheet["lesson_id"],
                        (sheet["name"] or "")[:50], sheet["exercises_count"],
                        sheet["answered_count"]))
        for e in sheet["exercises"]:
            if only_answered and not e["answered"]:
                continue
            mark = "ANSWERED" if e["answered"] else "        "
            lines.append("  [%s] %s #%s %-16s %s"
                         % (mark, e.get("number") or "-", e["exercise_id"],
                            e["type_name"], (e["name"] or "")[:48]))
            if not e["answered"]:
                continue
            if e["submitted_at"]:
                lines.append("        submitted : %s" % e["submitted_at"])
            dur = (" (%ss)" % e["audio_duration_s"]) if e["audio_duration_s"] else ""
            for u in e["audio_urls"]:
                lines.append("        audio%s : %s" % (dur, u))
            if e["writing_text"]:
                txt = e["writing_text"]
                lines.append("        writing   : %s"
                             % (txt[:400] + ("..." if len(txt) > 400 else "")))
            if e["typed_answers"]:
                lines.append("        typed     : %s"
                             % json.dumps(e["typed_answers"],
                                          ensure_ascii=False)[:400])
            if e["teacher_checked_at"]:
                lines.append("        teacher   : %s right=%s"
                             % (e["teacher_checked_at"], e["teacher_right"]))
    if not data["sheets"]:
        lines.append("(no homework sheets with exercises found)")
    return "\n".join(lines)


def format_download(manifest, log_lines=None):
    lines = ["Downloaded pupil %s (class %s) -> %s"
             % (manifest["pupil_id"], manifest["class_id"], manifest["out_dir"])]
    if log_lines:
        lines.extend("  " + l for l in log_lines)
    for sheet in manifest["sheets"]:
        lines.append("  sheet %s | %s | answered: %d | files: %d"
                     % (sheet["sheet_id"], (sheet["name"] or "")[:40],
                        sheet["answered_count"], len(sheet["files"])))
        for f in sheet["files"]:
            lines.append("      %-9s %s" % (f["status"].split(":")[0], f["path"]))
    t = manifest["totals"]
    lines.append("Totals: %d audio, %d writing, %d errors -> %s"
                 % (t["audio"], t["writing"], t["errors"],
                    manifest["manifest_path"]))
    return "\n".join(lines)
