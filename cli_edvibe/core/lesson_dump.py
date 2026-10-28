"""Read-only lesson dump: sections, item counts and EVERY exercise's full raw JSON.

Used by `lesson dump` for offline review/backup before rebuilds. The dump is
the server's ground truth: exercises are copied verbatim out of LoadExercises,
so hidden teacher notes (and their html) are included - rebuilding helpers can
read text back from the dump instead of poking the live lesson.

Read-only: this module never saves anything.
"""

# Exercise type codes -> readable names (verified against live materials).
TYPE_NAMES = {
    3: "video", 4: "audio", 5: "test", 6: "match", 10: "fill-typed",
    13: "choose-option", 14: "true-false", 15: "word-order",
    17: "label-pictures", 18: "fill-box", 19: "sort-columns", 21: "wordlist",
    22: "note", 25: "topic", 26: "writing", 27: "pictures", 28: "text",
    29: "button", 30: "voice", 31: "divider", 32: "gif", 37: "order-sentences",
}


def type_name(t):
    """Readable name for an exercise Type code ('type-42' when unmapped)."""
    return TYPE_NAMES.get(t, f"type-{t}")


def is_hidden(ex):
    """Teacher-only exercise (hidden note/text). Two live encodings exist:

    - exercise-level IsHidePupil / IsHideExercise;
    - Note.ShowToPupil == False + Note.VisibilityType == 1 (older lessons).
    Both mean "students don't see it" - do not "fix" either one."""
    ex = ex or {}
    if ex.get("IsHidePupil") or ex.get("IsHideExercise"):
        return True
    note = ex.get("Note")
    if isinstance(note, dict):
        if note.get("ShowToPupil") is False or note.get("VisibilityType") == 1:
            return True
    return False


def content_len(ex):
    """Characters of exercise text (note/text bodies + gap-carrying items)."""
    ex = ex or {}
    total = 0
    for key in ("Note", "Text"):
        blk = ex.get(key)
        if isinstance(blk, dict):
            total += len(blk.get("Text") or "")
    items = ex.get("QuestionWithCodingTexts")
    for it in (items if isinstance(items, list) else []):
        if isinstance(it, dict):
            total += len(it.get("Text") or "")
    return total


def exercise_summary(index, ex, section_id=None):
    """Compact, JSON-safe view of one exercise (id/type/name/hidden/html size)."""
    ex = ex or {}
    return {
        "n": index,
        "id": ex.get("Id"),
        "type": ex.get("Type"),
        "type_name": type_name(ex.get("Type")),
        "number": ex.get("Number"),
        "name": ex.get("Name") or "",
        "hidden": is_hidden(ex),
        "html_chars": content_len(ex),
        "section_id": ex.get("LessonSectionId") or section_id,
    }


def lesson_description(session, lesson_id):
    """Lesson description (LessonWsController.GetLessonPreview); None if the
    preview call is unavailable - a dump must never fail because of it."""
    try:
        resp = session.rpc("LessonWsController", "GetLessonPreview", "Books",
                           {"LessonId": lesson_id})
    except Exception:                                    # pragma: no cover
        return None
    val = resp.get("Value") if isinstance(resp, dict) else None
    if isinstance(val, dict):
        return val.get("Description") or ""
    return None


def sections_of(lesson):
    """Lesson sections (incl. the built-in Homework section) as a list."""
    lesson = lesson or {}
    sections = [s for s in (lesson.get("Sections") or []) if isinstance(s, dict)]
    hw = lesson.get("HomeworkSection")
    if isinstance(hw, dict) and hw.get("Id"):
        if not any(s.get("Id") == hw.get("Id") for s in sections):
            sections.append(hw)
    return sections


def match_sections(sections, selector):
    """Sections addressed by `selector` (None = all, id, or name/substring).

    Raises ValueError when nothing matches - callers turn that into a clean
    CLI error instead of dumping an empty lesson."""
    if selector is None or str(selector).strip() == "":
        return sections
    sel = str(selector).strip()
    if sel.isdigit():
        sid = int(sel)
        picked = [s for s in sections if s.get("Id") == sid]
        if not picked:
            raise ValueError(f"lesson has no section #{sid}")
        return picked
    needle = sel.casefold()
    exact = [s for s in sections if (s.get("Name") or "").strip().casefold() == needle]
    if exact:
        return exact
    partial = [s for s in sections if needle in (s.get("Name") or "").casefold()]
    if not partial:
        names = ", ".join(repr(s.get("Name")) for s in sections) or "(none)"
        raise ValueError(f"no section matching '{selector}' (sections: {names})")
    return partial


def dump_lesson(session, lesson_id, section=None):
    """Full read-only dump of a lesson: metadata + sections + raw exercises.

    Exercises are the untouched LoadExercises views (hidden notes and their
    html included); `summary` carries the same exercise list in compact form."""
    lesson = session.get_lesson(lesson_id) or {}
    sections = match_sections(sections_of(lesson), section)
    out = {
        "lesson_id": lesson_id,
        "name": lesson.get("Name"),
        "number": lesson.get("Number"),
        "description": lesson_description(session, lesson_id),
        "section_filter": section,
        "sections": [],
        "total_exercises": 0,
    }
    for sec in sections:
        sid = sec.get("Id")
        items = session.load_exercises(sid, lesson_id) or []
        out["sections"].append({
            "section_id": sid,
            "name": sec.get("Name"),
            "is_homework": bool(sec.get("IsHomework")),
            "item_count": len(items),
            "exercises": items,                       # FULL raw JSON, verbatim
            "summary": [exercise_summary(i, e, sid) for i, e in enumerate(items, 1)],
        })
        out["total_exercises"] += len(items)
    return out


def summary_lines(dump, out_path=None):
    """Human-readable dump summary (stdout)."""
    lines = [f"Lesson #{dump.get('lesson_id')}: {dump.get('name')}"
             f" - {len(dump.get('sections') or [])} sections / "
             f"{dump.get('total_exercises')} exercises"]
    if dump.get("description"):
        desc = " ".join(str(dump["description"]).split())
        lines.append(f"  description: {desc[:100]}{'…' if len(desc) > 100 else ''}")
    for sec in dump.get("sections") or []:
        hw = " [homework]" if sec.get("is_homework") else ""
        lines.append(f"  Section #{sec.get('section_id')} '{sec.get('name')}'{hw}"
                     f" - {sec.get('item_count')} exercises")
        for s in sec.get("summary") or []:
            flags = " [hidden]" if s["hidden"] else ""
            size = f" html:{s['html_chars']}c" if s["html_chars"] else ""
            lines.append(f"    {s['n']:>2}. #{s['id']} {s['type_name']}"
                         f"{flags}{size} {s['name'][:60]}")
    if out_path:
        lines.append(f"Full JSON written: {out_path}")
    else:
        lines.append("(no --out: raw exercise JSON not written; use --json to pipe it)")
    return "\n".join(lines)
