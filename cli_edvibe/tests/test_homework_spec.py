"""Offline unit tests for homework_spec (validate / plan / normalize).

No network, no auth: exercises are built and inspected in memory only.
Live end-to-end flow (Save -> Add -> count update -> verify) is exercised by
the `homework add` CLI against a real pupil's sheet, not in this suite.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli_edvibe.core import homework_spec as HS  # noqa: E402
from cli_edvibe.core import lesson_spec as LS  # noqa: E402


def base_spec():
    return {
        "lesson_id": 111, "pupil_id": 222, "class_id": 333,
        "homework_lesson_id": 444,
        "exercises": [
            {"type": "match", "instruction": "Match.",
             "pairs": [["a", "1"], ["b", "2"]]},
            {"type": "truefalse", "instruction": "TF.",
             "statements": [["t", True], ["f", False], ["ns", "notstated"]]},
        ],
    }


def test_validate_ok():
    assert HS.validate(base_spec()) == []


def test_validate_requires_ids():
    spec = base_spec()
    del spec["pupil_id"]
    errs = HS.validate(spec)
    assert any("pupil_id" in e for e in errs)


def test_validate_requires_exercises():
    spec = base_spec()
    spec["exercises"] = []
    assert any("non-empty" in e for e in HS.validate(spec))


def test_validate_unknown_type_and_missing_field():
    spec = base_spec()
    spec["exercises"] = [{"type": "nope"}, {"type": "video", "instruction": "x"}]
    errs = HS.validate(spec)
    assert any("unknown type" in e for e in errs)
    assert any("link" in e for e in errs)


def test_plan():
    plan = HS.plan(base_spec())
    assert plan["ok"] and plan["total_exercises"] == 2
    assert plan["exercises"][0]["type"] == "match"


def _norm(ex, etype, number):
    view = LS._build_one(ex, etype, number, None, None)
    return HS._normalize_for_homework(view, etype, 444, number)


def test_normalize_truefalse_encoding():
    spec = base_spec()
    view = _norm(spec["exercises"][1], "truefalse", 8)
    # frontend encoding: True -> "true", False -> "", NotStated -> "NotStated"
    assert view["QuestionAnswers"] == ["true", "", "NotStated"]
    assert view["TrueOrFalse"]["EnableNotStated"] is True
    jd = json.loads(view["JsonData"])
    assert jd["QuestionAnswers"] == view["QuestionAnswers"]
    assert jd["IsAutoCheck"] is False
    assert view["inHomework"] is True
    assert view["HomeworkLessonId"] == 444
    assert "LessonSectionId" not in view and "LessonId" not in view


def test_normalize_fillbox_shuffled_and_json():
    ex = {"type": "fillbox", "instruction": "Gaps.",
          "sentences": ["A [one] and a [two] and a [three]."]}
    view = _norm(ex, "fillbox", 6)
    pw = view["PasteWordByDrag"]
    assert pw["Text"].count("hide-id-exercise-item") == 3
    assert sorted(pw["SortIndexes"]) == [0, 1, 2]
    jd = json.loads(view["JsonData"])
    assert set(jd.keys()) == {"PasteWordByDrag", "IsAutoCheck"}
    assert jd["IsAutoCheck"] is False


def test_normalize_video_minimal_json():
    ex = {"type": "video", "instruction": "Watch.", "link": "https://youtu.be/x"}
    view = _norm(ex, "video", 7)
    jd = json.loads(view["JsonData"])
    assert list(jd.keys()) == ["Videos", "IsAutoCheck"]
    assert view["Videos"][0]["Link"] == "https://youtu.be/x"


def test_normalize_test_points_off():
    ex = {"type": "test", "instruction": "Choose.",
          "questions": [{"q": "Q", "options": ["a", "b"], "correct": [1]}]}
    view = _norm(ex, "test", 9)
    assert view["Test"]["IsEnabledPoints"] is False
    assert view["Test"]["Questions"][0]["QuestionAnswers"] == ["", "true"]


# ------------------------------------------- lesson homework pool (give --file)
class _StubSession:
    """Minimal session stub: no network, in-memory exercises."""

    def __init__(self, section_id=97795572, existing=None):
        self.section_id = section_id
        self.existing = list(existing or [])
        self.saved = []

    def homework_section_id(self, lesson_id):
        return self.section_id

    def load_exercises(self, section_id, lesson_id):
        return list(self.existing)

    def save_exercise(self, view, lesson_id, section_id):
        eid = 9000 + len(self.saved)
        self.saved.append({"view": view, "id": eid})
        stored = dict(view)
        stored["Id"] = eid
        self.existing.append(stored)
        return {"Id": eid}


def _pool_spec():
    return {"sections": [{"name": "Homework", "exercises": [
        {"type": "chooseoption", "instruction": "Choose.",
         "lines": ["<b>1.&nbsp;</b>He could [vest*/gamble/proxy]."]},
        {"type": "wordorder", "instruction": "Order.",
         "sentences": ["a/b/c"]},
    ]}]}


def test_spec_exercises_lesson_spec_shape():
    exs = HS.spec_exercises(_pool_spec())
    assert [e["type"] for e in exs] == ["chooseoption", "wordorder"]


def test_spec_exercises_flat_shape():
    exs = HS.spec_exercises({"exercises": [
        {"type": "match", "instruction": "m", "pairs": [["a", "b"]]}]})
    assert len(exs) == 1


def test_plan_in_lesson_read_only():
    sess = _StubSession()
    plan = HS.plan_in_lesson(sess, 111, HS.spec_exercises(_pool_spec()))
    assert len(plan["to_create"]) == 2 and plan["to_reuse"] == []
    assert sess.saved == []  # no writes


def test_create_in_lesson_then_reuse_is_idempotent():
    sess = _StubSession()
    exs = HS.spec_exercises(_pool_spec())
    first = HS.create_in_lesson(sess, 111, exs)
    assert len(first["created"]) == 2 and first["reused"] == []
    second = HS.create_in_lesson(sess, 111, exs)
    assert len(second["reused"]) == 2 and second["created"] == []
    assert second["ids"] == first["ids"]
    assert len(sess.saved) == 2  # second run wrote nothing


def test_create_in_lesson_no_reuse_duplicates():
    sess = _StubSession()
    exs = HS.spec_exercises(_pool_spec())
    HS.create_in_lesson(sess, 111, exs, reuse=False)
    out = HS.create_in_lesson(sess, 111, exs, reuse=False)
    assert len(out["created"]) == 2 and len(sess.saved) == 4


def test_create_in_lesson_numbering_follows_existing():
    sess = _StubSession(existing=[{"Id": 1, "Type": 6, "Name": "old",
                                   "Number": 4}])
    HS.create_in_lesson(sess, 111, HS.spec_exercises(_pool_spec()))
    assert [s["view"]["Number"] for s in sess.saved] == [5, 6]


def test_create_in_lesson_requires_homework_section():
    sess = _StubSession(section_id=None)
    try:
        HS.create_in_lesson(sess, 111, HS.spec_exercises(_pool_spec()))
    except ValueError as exc:
        assert "Homework section" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_create_in_lesson_rejects_unknown_type():
    sess = _StubSession()
    try:
        HS.create_in_lesson(sess, 111, [{"type": "nope"}])
    except ValueError as exc:
        assert "unknown type" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
