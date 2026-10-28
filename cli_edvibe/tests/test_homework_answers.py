"""Offline unit tests: core.homework_answers (no network, no WS)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli_edvibe.core import homework_answers as hwa  # noqa: E402

VOICE = {
    "Id": 1601263109, "Number": 5, "Type": 30, "Name": "",
    "AudioRecording": {"Text": "", "RecordingDuration": 60},
    "AnswerVersion1": [{
        "Date": "2026-07-18T04:25:08.631381",
        "JsonAnswerVersion1": {
            "IsTeacher": False,
            "ManyAnswers": [{"Answer":
                "https://media-a.edvibe.com/files/LessonExerciseAudioRecordings/f184ae29.mp3"}],
            "RepeatingManyAnswers": [[]]},
    }],
    "AnswersTeacher": [],
}

ESSAY = {
    "Id": 531911354, "Number": 7, "Type": 26, "Name": "Writing task",
    "AnswerVersion1": [],
    "Essay": {"Text": "1. Charlotte think what Alexander much older.<br>2. She wants to see him.",
              "PrevHashText": "abc"},
    "EssaysPupils": [{"PupilId": 3410766, "Essay": {
        "Text": "1. Charlotte think what Alexander much older.<br>2. She wants to see him.",
        "PrevHashText": "abc"}}],
}

TYPED = {
    "Id": 489431729, "Number": 3, "Type": 13, "Name": "Choose the correct option",
    "AnswerVersion1": [{
        "Date": "2026-06-02T07:53:44.119160",
        "JsonAnswerVersion1": {
            "IsTeacher": False,
            "ManyAnswers": [{"Answer": "goes"}, {"Answer": "Do they play"}],
            "RepeatingManyAnswers": [[], []]},
    }],
}

EMPTY = {"Id": 111, "Number": 1, "Type": 30, "Name": "",
         "AudioRecording": {"Text": "", "RecordingDuration": 60},
         "AnswerVersion1": [], "AnswersTeacher": []}

TEACHER_CHECKED = {
    "Id": 522230829, "Number": 2, "Type": 30, "Name": "Record a monologue",
    "AudioRecording": {"RecordingDuration": 180},
    "AnswerVersion1": [{"Date": "2026-05-05T07:47:47.007482",
        "JsonAnswerVersion1": {
            "ManyAnswers": [{"Answer":
                "https://media-a.edvibe.com/files/LessonExerciseAudioRecordings/x.mp3"}],
            "RepeatingManyAnswers": [[]]}}],
    "AnswersTeacher": [{"Date": "2026-05-11T20:26:25.394666",
        "JsonAnswerVersion1": {"IsTeacher": True,
            "ManyAnswers": [{"Answer":
                "https://media-a.edvibe.com/files/LessonExerciseAudioRecordings/x.mp3"}],
            "AnswerErrorsCount": [[{"ErrorCount": 0, "Id": 0, "IsRightAnswer": True}]]}}],
}


def test_extract_voice():
    e = hwa.extract(VOICE)
    assert e["answered"] is True
    assert e["type_name"] == "AudioRecording"
    assert e["audio_urls"] == [
        "https://media-a.edvibe.com/files/LessonExerciseAudioRecordings/f184ae29.mp3"]
    assert e["submitted_at"] == "2026-07-18T04:25:08.631381"
    assert e["audio_duration_s"] == 60
    assert e["writing_text"] is None


def test_extract_essay():
    e = hwa.extract(ESSAY)
    assert e["answered"] is True
    assert e["type_name"] == "Essay"
    assert e["writing_text"].startswith("1. Charlotte think")
    assert "\n" in e["writing_text"]          # <br> -> newline
    assert e["submitted_at"] is None          # essays carry no timestamp


def test_extract_typed():
    e = hwa.extract(TYPED)
    assert e["answered"] is True
    assert e["typed_answers"] == ["goes", "Do they play"]
    assert e["audio_urls"] == []


def test_extract_empty():
    e = hwa.extract(EMPTY)
    assert e["answered"] is False
    assert e["audio_urls"] == [] and e["writing_text"] is None


def test_extract_teacher_verdict():
    e = hwa.extract(TEACHER_CHECKED)
    assert e["teacher_checked_at"] == "2026-05-11T20:26:25.394666"
    assert e["teacher_right"] is True


class FakeSession:
    def __init__(self):
        self.rpc_calls = []

    def homework_lessons(self, lesson_id, pupil_id, class_id):
        return [
            {"Id": 20275010, "LessonId": 16861203, "Name": "Mount Rushmore",
             "ExercisesCount": 12},
            {"Id": 19566159, "LessonId": 16861193, "Name": "Charlotte",
             "ExercisesCount": 27},
            {"Id": 11111111, "LessonId": 1, "Name": "empty sheet",
             "ExercisesCount": 0},
        ]

    def load_homework_sheet(self, lesson_id, pupil_id, class_id, sheet_id):
        items = {
            20275010: [VOICE, EMPTY],
            19566159: [ESSAY, TYPED],
        }[sheet_id]
        return {"CompleteStatus": 0, "Items": items}


def test_collect_all_sheets_newest_first():
    data = hwa.collect(FakeSession(), 3410766, 2227632)
    # empty sheets are skipped; newest (bigger Id) first
    assert [s["sheet_id"] for s in data["sheets"]] == [20275010, 19566159]
    assert data["sheets"][0]["answered_count"] == 1
    assert data["sheets"][1]["answered_count"] == 2


def test_collect_single_sheet_and_limit():
    data = hwa.collect(FakeSession(), 3410766, 2227632, sheet_id=19566159)
    assert len(data["sheets"]) == 1
    essays = [e for e in data["sheets"][0]["exercises"] if e["writing_text"]]
    assert len(essays) == 1

    data = hwa.collect(FakeSession(), 3410766, 2227632, limit=1)
    assert [s["sheet_id"] for s in data["sheets"]] == [20275010]


def test_collect_missing_sheet():
    with pytest.raises(RuntimeError):
        hwa.collect(FakeSession(), 3410766, 2227632, sheet_id=999)


def test_download_manifest_and_files(tmp_path, monkeypatch):
    def fake_fetch(url, path, force=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"ID3fake")
        return {"status": "downloaded", "bytes": 7}

    monkeypatch.setattr(hwa, "_fetch_to_file", fake_fetch)
    out = tmp_path / "dl"
    m = hwa.download(FakeSession(), 3410766, 2227632, str(out))

    assert m["totals"] == {"audio": 1, "writing": 1, "errors": 0}
    by_kind = {f["kind"]: f for sh in m["sheets"] for f in sh["files"]}
    assert (out / by_kind["audio"]["path"]).read_bytes() == b"ID3fake"
    assert (out / by_kind["writing"]["path"]).read_text().startswith("1. Charlotte")
    saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert saved["totals"] == m["totals"]
    # unanswered exercises stay out of the manifest
    assert all(e["answered"] for sh in saved["sheets"] for e in sh["answers"])


def test_download_skips_cached(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(url, path, force=False):
        calls.append(force)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x")
        return {"status": "downloaded", "bytes": 1}

    monkeypatch.setattr(hwa, "_fetch_to_file", fake_fetch)
    out = tmp_path / "dl"
    hwa.download(FakeSession(), 3410766, 2227632, str(out), sheet_id=20275010)
    assert calls == [False]
    calls.clear()
    m = hwa.download(FakeSession(), 3410766, 2227632, str(out), sheet_id=20275010,
                     force=True)
    assert calls == [True]
    assert m["totals"]["audio"] == 1


def test_format_report_mentions_audio_and_writing():
    data = hwa.collect(FakeSession(), 3410766, 2227632, sheet_id=19566159)
    txt = hwa.format_report(data, only_answered=True)
    assert "SHEET 19566159" in txt
    assert "writing" in txt and "typed" in txt
