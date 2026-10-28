"""Append exercises to a pupil's homework (Edvibe homework microservice).

Spec v1 (JSON) — mirrors the lesson-spec exercise dicts:

    {
      "lesson_id": 19605483,           # the lesson the homework belongs to
      "pupil_id": 3307590,             # student (pupil) id
      "class_id": 2135048,             # class/group id
      "homework_lesson_id": 21038112,  # homework object id (GetHomeworkLessons)
      "exercises": [
        {"type": "match",  "instruction": "Match the words with their definitions.",
         "pairs": [["term", "definition"], ...]},
        {"type": "fillbox", "instruction": "...", "sentences": ["text [gap] text"]},
        {"type": "video",   "instruction": "...", "link": "https://youtube..."},
        {"type": "truefalse", "instruction": "...",
         "statements": [["text", true], ["text", false], ["text", "notstated"]]},
        {"type": "test", "instruction": "...",
         "questions": [{"q": "...", "options": ["a", "b", "c"], "correct": [1]}]},
        {"type": "voice", "instruction": "...", "html": "model answer", "seconds": 60}
      ]
    }

Execution (all verified live Sep 2026):
  1. Save each exercise with ExerciseView.HomeworkLessonId + inHomework=true
     (no LessonSectionId/LessonId), numbered after the current last exercise.
  2. HomeworkWsController.AddExercisesToHomework {LessonId, PupilId, ClassId,
     HomeworkGroupName:"", ExercisesId:[...]} — attaches them in order.
  3. UpdateHomeworkGroupExercisesCount {HomeworkLessonId} — server recompute.
  4. MarkHomeworkLessonHasUpdates {HomeworkLessonId, PupilId, TeacherId}.
  5. Re-load and verify every new id is present.

Field conventions mirror the live homework items: True/False answers
True->"true"/False->""/NotStated->"NotStated"; FillBox keeps
PasteWordByDrag in JsonData with shuffled SortIndexes; Video uses a minimal
JsonData; homework keeps IsAutoCheck=false on fillbox/video/truefalse.
Additive only — never edits or deletes existing exercises.
"""
import json

from . import builders as B
from . import lesson_spec as LS


def validate(spec):
    """Human-readable problems list ([] == valid). Offline, no auth."""
    errs = []
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    for key in ("lesson_id", "pupil_id", "class_id", "homework_lesson_id"):
        if not spec.get(key):
            errs.append(f"missing '{key}'")
    exs = spec.get("exercises")
    if not isinstance(exs, list) or not exs:
        return errs + ["'exercises' must be a non-empty list"]
    for j, ex in enumerate(exs):
        w = f"exercises[{j}]"
        if not isinstance(ex, dict):
            errs.append(f"{w}: must be an object")
            continue
        t = LS.norm_type(ex.get("type"))
        if t not in LS.VALID_TYPES:
            errs.append(f"{w}: unknown type '{ex.get('type')}' "
                        f"(valid: {', '.join(sorted(LS.VALID_TYPES))})")
            continue
        for field in LS.REQUIRED_FIELDS.get(t, []):
            if ex.get(field) in (None, "", []):
                errs.append(f"{w} ({t}): missing '{field}'")
    return errs


def plan(spec):
    """Dry-run summary; raises ValueError when invalid."""
    errs = validate(spec)
    if errs:
        raise ValueError("spec invalid: " + "; ".join(errs))
    out = {"ok": True, "lesson_id": spec["lesson_id"],
           "pupil_id": spec["pupil_id"], "class_id": spec["class_id"],
           "homework_lesson_id": spec["homework_lesson_id"],
           "exercises": [{"type": LS.norm_type(ex.get("type")),
                          "name": LS.label(ex)} for ex in spec["exercises"]]}
    out["total_exercises"] = len(out["exercises"])
    return out


# ------------------------------------------------------------- normalization
def _normalize_for_homework(view, etype, homework_lesson_id, number):
    """Mirror the live homework item conventions for a freshly built view."""
    view.pop("LessonId", None)
    view.pop("LessonSectionId", None)
    view["inHomework"] = True
    view["HomeworkLessonId"] = homework_lesson_id
    view["Number"] = number
    view["IsShowExerciseNumber"] = False
    if etype == "fillbox":
        pwbd = view.get("PasteWordByDrag") or {}
        idx = list(pwbd.get("SortIndexes") or [])
        B.random.shuffle(idx)
        pwbd["SortIndexes"] = idx
        view["PasteWordByDrag"] = pwbd
        view["JsonData"] = json.dumps({"PasteWordByDrag": pwbd,
                                       "IsAutoCheck": False}, ensure_ascii=False)
        view["IsAutoCheck"] = False
    elif etype == "video":
        view["JsonData"] = json.dumps({"Videos": view.get("Videos") or [],
                                       "IsAutoCheck": False}, ensure_ascii=False)
        view["IsAutoCheck"] = False
    elif etype == "truefalse":
        view["JsonData"] = json.dumps({
            "Questions": view.get("Questions"),
            "QuestionAnswers": view.get("QuestionAnswers"),
            "IsAutoCheck": False,
            "TrueOrFalse": view.get("TrueOrFalse")}, ensure_ascii=False)
        view["IsAutoCheck"] = False
    elif etype == "test":
        t = view.get("Test") or {}
        t["IsEnabledPoints"] = False
        view["Test"] = t
    return view


# ------------------------------------------------- lesson homework pool
def spec_exercises(spec):
    """Exercises of an `homework add` spec OR a `lesson build` spec.

    Accepts {"exercises": [...]} (homework-spec shape) or {"sections":
    [{"name": "Homework"|"...", "exercises": [...]}]} (lesson-spec shape;
    the Homework-named section is preferred, else every section is merged).
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be a JSON object")
    if isinstance(spec.get("exercises"), list) and spec["exercises"]:
        return spec["exercises"]
    sections = spec.get("sections") or []
    if not isinstance(sections, list) or not sections:
        raise ValueError("spec needs 'exercises' or a 'sections' list")
    hw = [s for s in sections
          if (s.get("name") or "").strip().casefold() in ("homework", "home work")]
    chosen = hw[0] if hw else None
    if chosen is None:
        out = []
        for s in sections:
            out.extend(s.get("exercises") or [])
        return out
    return chosen.get("exercises") or []


def plan_in_lesson(session, lesson_id, exercises, reuse=True):
    """Read-only: what would create_in_lesson do? (no writes)"""
    section_id = session.homework_section_id(lesson_id)
    if not section_id:
        raise ValueError(f"lesson {lesson_id} has no Homework section")
    existing = session.load_exercises(section_id, lesson_id)
    by_key = {}
    for e in existing:
        by_key.setdefault((e.get("Type"), (e.get("Name") or "").strip()), e.get("Id"))
    plan = {"lesson_id": lesson_id, "section_id": section_id,
            "existing_count": len(existing), "to_create": [], "to_reuse": []}
    for ex in exercises:
        etype = LS.norm_type(ex.get("type"))
        view = LS._build_one(ex, etype, 0, lesson_id, section_id)
        key = (view.get("Type"), (view.get("Name") or "").strip())
        if reuse and key in by_key:
            plan["to_reuse"].append({"id": by_key[key], "type": etype,
                                     "name": LS.label(ex)})
        else:
            plan["to_create"].append({"type": etype, "name": LS.label(ex)})
    return plan


def create_in_lesson(session, lesson_id, exercises, reuse=True, log=None):
    """Save spec exercises into the lesson's Homework section (the pool that
    `homework give`/`attach` push to pupils).

    With reuse=True (default) an exercise whose (Type, Name) already exists in
    the homework section is REUSED instead of duplicated — re-running the same
    spec for another pupil attaches the same exercises. Idempotent."""
    errs = [f"exercises[{j}]: unknown type '{ex.get('type')}'"
            for j, ex in enumerate(exercises)
            if not isinstance(ex, dict) or LS.norm_type(ex.get("type")) not in LS.VALID_TYPES]
    if errs:
        raise ValueError("spec invalid: " + "; ".join(errs))
    section_id = session.homework_section_id(lesson_id)
    if not section_id:
        raise ValueError(f"lesson {lesson_id} has no Homework section "
                         f"(open the lesson editor once to provision it)")
    existing = session.load_exercises(section_id, lesson_id)
    by_key = {}
    for e in existing:
        by_key.setdefault((e.get("Type"), (e.get("Name") or "").strip()), e.get("Id"))
    counter = max([e.get("Number", 0) for e in existing] + [-1]) + 1
    out = {"lesson_id": lesson_id, "section_id": section_id, "created": [],
           "reused": [], "ids": []}
    for j, ex in enumerate(exercises):
        etype = LS.norm_type(ex.get("type"))
        view = LS._build_one(ex, etype, counter, lesson_id, section_id)
        key = (view.get("Type"), (view.get("Name") or "").strip())
        if reuse and key in by_key:
            eid = by_key[key]
            out["reused"].append({"id": eid, "type": etype, "name": LS.label(ex)})
            out["ids"].append(eid)
            if log:
                log(f"   = reused #{eid} {etype} " + (LS.label(ex) or "")[:60])
            continue
        saved = session.save_exercise(view, lesson_id, section_id)
        eid = saved.get("Id") if isinstance(saved, dict) else saved
        out["created"].append({"id": eid, "type": etype, "name": LS.label(ex)})
        out["ids"].append(eid)
        counter += 1
        if log:
            log(f"   + #{eid} {etype} " + (LS.label(ex) or "")[:60])
    return out


# --------------------------------------------------------------- executor
def build_homework(session, spec, log=None):
    """Append the spec's exercises to the pupil's homework. Returns a summary.

    Additive only: existing homework items are never touched. Numbers are
    assigned after the current last exercise.
    """
    errs = validate(spec)
    if errs:
        raise ValueError("spec invalid: " + "; ".join(errs))

    lesson_id = int(spec["lesson_id"])
    pupil_id = int(spec["pupil_id"])
    class_id = int(spec["class_id"])
    hw_id = int(spec["homework_lesson_id"])

    existing = session.load_homework_exercises(lesson_id, pupil_id, class_id, hw_id)
    counter = max([e.get("Number", 0) for e in existing] + [0]) + 1

    summary = {"homework_lesson_id": hw_id, "lesson_id": lesson_id,
               "pupil_id": pupil_id, "class_id": class_id,
               "before_count": len(existing), "saved": [], "verified": False}
    ids = []
    for j, ex in enumerate(spec["exercises"]):
        etype = LS.norm_type(ex.get("type"))
        try:
            view = LS._build_one(ex, etype, counter, None, None)
            view = _normalize_for_homework(view, etype, hw_id, counter)
            saved = session.save_homework_exercise(view, hw_id, number=counter)
        except Exception as exc:
            raise ValueError(
                f"exercise {j} ({etype}): {exc}") from exc
        eid = saved.get("Id") if isinstance(saved, dict) else saved
        ids.append(eid)
        summary["saved"].append({"id": eid, "type": etype,
                                 "number": counter, "name": LS.label(ex)})
        counter += 1
        if log:
            log(f"   + #{eid} {etype} n={counter - 1} "
                + (LS.label(ex) or "")[:60])

    session.add_exercises_to_homework(lesson_id, pupil_id, class_id, ids)
    if log:
        log(f"   attached {len(ids)} exercises to homework #{hw_id}")
    try:
        session.update_homework_count(hw_id)
    except Exception as exc:  # non-fatal, verified below regardless
        summary["count_update_error"] = str(exc)
    try:
        session.mark_homework_updates(hw_id, pupil_id)
    except Exception as exc:
        summary["mark_update_error"] = str(exc)

    # verify
    after = session.load_homework_exercises(lesson_id, pupil_id, class_id, hw_id)
    have = {e.get("Id") for e in after}
    missing = [i for i in ids if i not in have]
    summary["after_count"] = len(after)
    summary["verified"] = not missing
    summary["missing_ids"] = missing
    summary["items"] = [{"id": e.get("Id"), "number": e.get("Number"),
                         "type": e.get("Type"),
                         "name": (e.get("Name") or "")[:70]} for e in after]
    return summary
