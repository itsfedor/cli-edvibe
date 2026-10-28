"""Teacher workflow: build a complete lesson from a JSON spec.

The assistant (Hermes / Claude Code / Codex) drafts a lesson spec; this module
executes it deterministically: sections + exercises of every supported type,
saved over the verified SaveExercise RPC. Additive-only — never deletes.

Spec v1 (full reference: teacher-kit skill, references/lesson-spec.md):

    {
      "lesson_name": "Present Perfect",          # used when creating a lesson
      "description": "For 7th grade, 45 min.",   # optional lesson description
      "sections": [
        {"name": "Warm-Up", "exercises": [
            {"type": "note",  "html": "<p>...</p>", "name": "Warm-Up"},
            {"type": "match", "instruction": "Match", "pairs": [["a","b"]]}
        ]},
        {"name": "Homework", "exercises": [
            {"type": "writing", "instruction": "Write 5 sentences"}
        ]}
      ]
    }

Section named "Homework" is saved into the lesson's built-in homework section.
String fields named `instruction`/`name` double as the exercise label.
Content exercises (note/text/topic) get their HTML minified automatically
(the UI renders raw whitespace badly — learned live).
"""
import json
import re

from . import builders as B
from .client import EdvibeError, client_time

# ------------------------------------------------------------- type registry
EXERCISE_ALIASES = {
    "fill": "filltyped", "gaps": "filltyped", "fill_gaps": "filltyped",
    "choose": "chooseoption", "choice": "chooseoption", "option": "chooseoption",
    "order": "wordorder", "word_order": "wordorder",
    "sort": "sortcolumns", "columns": "sortcolumns",
    "sentences": "ordersentences", "order_sentences": "ordersentences",
    "tf": "truefalse", "true_false": "truefalse",
    "words": "wordlist", "word_list": "wordlist",
    "quiz": "test",
    "watch": "button", "link": "button", "external": "button",
    # new templates (docs: Lesson Builder 3.0 template list)
    "letters": "unscramble", "build_word": "unscramble",
    "listening": "audio", "audio_block": "audio",
    "gif_block": "gif",
    "label": "label", "labeldrag": "label", "label_drag": "label",
    "labelfill": "labelfill", "label_fill": "labelfill",
    "labelchoose": "labelchoose", "label_choose": "labelchoose",
    "board": "miro", "miro_board": "miro",
    "pdf": "googlepdf", "gdrive": "googlepdf", "gdoc": "googlepdf",
    "word_wall": "wordwall", "learning_apps": "learningapps",
    "learningapp": "learningapps",
    "genially_block": "genially",
    "bamboozle": "baamboozle", "baambozle": "baamboozle",
    "quizlet_block": "quizlet",
}

VALID_TYPES = {
    "note", "text", "topic", "video", "wordlist", "writing", "match",
    "filltyped", "fillbox", "chooseoption", "wordorder", "sortcolumns",
    "ordersentences", "truefalse", "test", "voice", "button", "pictures",
    "unscramble", "audio", "gif", "label", "labelfill", "labelchoose",
    "miro", "googlepdf", "wordwall", "learningapps", "genially",
    "baamboozle", "quizlet",
}

REQUIRED_FIELDS = {
    "note": ["html"], "text": ["html"], "topic": ["html"],
    "video": ["link"], "wordlist": ["entries"], "writing": [],
    "match": ["pairs"], "filltyped": ["sentences"], "fillbox": ["sentences"],
    "chooseoption": ["lines"], "wordorder": ["sentences"],
    "sortcolumns": ["columns"], "ordersentences": ["sentences"],
    "truefalse": ["statements"], "test": ["questions"], "voice": [],
    "button": ["link", "text"], "pictures": [], "unscramble": ["words"],
    "audio": ["audios"], "gif": [], "label": ["items"],
    "labelfill": ["items"], "labelchoose": ["items"],
    "miro": ["link"], "googlepdf": ["link"], "wordwall": ["link"],
    "learningapps": ["link"], "genially": ["link"], "baamboozle": ["link"],
    "quizlet": ["link"],
}

# Exercise types that accept the "Execution Time" setting (TimerMinutes on
# the ExerciseView; verified against the live exercises_shell bundle Sep/Oct 2026).
TIMER_TYPES = {"filltyped", "fillbox", "chooseoption", "wordorder",
               "sortcolumns", "ordersentences", "truefalse", "unscramble",
               "match", "test", "writing", "label", "labelfill",
               "labelchoose"}

HOMEWORK_NAMES = {"homework", "домашка", "домашнее задание", "дз"}


def norm_type(t):
    t = str(t or "").strip().lower().replace(" ", "_").replace("-", "_")
    return EXERCISE_ALIASES.get(t, t)


def minify(html):
    if not html:
        return html
    html = re.sub(r">\s+<", "><", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def label(ex):
    return (ex.get("instruction") or ex.get("name") or "").strip()


# --------------------------------------------------------------- validation
def validate(spec):
    """Return a list of human-readable problems ([] == valid)."""
    errs = []
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections:
        return ["spec needs a non-empty 'sections' list"]
    for i, sec in enumerate(sections):
        where = f"sections[{i}]"
        if not isinstance(sec, dict) or not (sec.get("name") or "").strip():
            errs.append(f"{where}: each section needs a 'name'")
            continue
        where = f"sections[{i}] '{sec.get('name')}'"
        exs = sec.get("exercises")
        if not isinstance(exs, list) or not exs:
            errs.append(f"{where}: needs a non-empty 'exercises' list")
            continue
        for j, ex in enumerate(exs):
            w = f"{where} exercises[{j}]"
            if not isinstance(ex, dict):
                errs.append(f"{w}: must be an object")
                continue
            t = norm_type(ex.get("type"))
            if t not in VALID_TYPES:
                errs.append(f"{w}: unknown type '{ex.get('type')}' "
                            f"(valid: {', '.join(sorted(VALID_TYPES))})")
                continue
            for field in REQUIRED_FIELDS.get(t, []):
                if ex.get(field) in (None, "", []):
                    errs.append(f"{w} ({t}): missing '{field}'")
    return errs


def plan(spec):
    """Dry-run: what would be created. No network, no auth needed."""
    errs = validate(spec)
    if errs:
        raise ValueError("spec invalid: " + "; ".join(errs))
    out = {"ok": True, "lesson_name": spec.get("lesson_name"),
           "sections": [], "total_exercises": 0}
    for sec in spec["sections"]:
        items = []
        for ex in sec["exercises"]:
            items.append({"type": norm_type(ex.get("type")), "name": label(ex)})
        out["sections"].append({"name": sec["name"].strip(), "exercises": items})
        out["total_exercises"] += len(items)
    return out


# ------------------------------------------------------------- view builder
def _build_one(ex, etype, number, lesson_id, section_id):
    """Turn one spec exercise into an ExerciseView (uses verified builders)."""
    name = label(ex)
    hidden = bool(ex.get("hidden", False))
    if etype == "note":
        view = B.build_note(minify(ex["html"]), name=ex.get("name", ""),
                            hidden=hidden, color=ex.get("color"))
    elif etype == "text":
        view = B.build_text(minify(ex["html"]), name=name)
    elif etype == "topic":
        view = B._base(B.EX_TOPIC, name, number)
        view["Topic"] = {"Id": 0, "Name": "", "Text": minify(ex["html"]),
                         "ImageUrl": "", "ImageId": 0, "Images": "",
                         "FullImageUrl": "", "New": False, "ExerciseId": 0}
    elif etype == "video":
        view = B.build_video(name, ex["link"])
    elif etype == "wordlist":
        entries = [(e[0], e[1]) for e in ex["entries"]]
        view = B.build_wordlist(name, entries,
                                voice_language_id=int(ex.get("voice_language_id", 1)))
    elif etype == "writing":
        view = B.build_writing(name)
    elif etype == "match":
        view = B.build_match(name, [(p[0], p[1]) for p in ex["pairs"]])
    elif etype == "filltyped":
        view = B.build_fill_typed(name, ex["sentences"])
    elif etype == "fillbox":
        view = B.build_fill_box(name, ex["sentences"],
                                autocheck=bool(ex.get("autocheck", True)))
    elif etype == "button":
        view = B.build_button(name, ex["link"], ex["text"])
    elif etype == "pictures":
        view = B.build_pictures(name, ex.get("description", ""), number=number,
                                layout=ex.get("layout", "vertical"),
                                descriptions=ex.get("descriptions"))
    elif etype == "chooseoption":
        view = B.build_choose_option(name, ex["lines"])
    elif etype == "wordorder":
        view = B.build_word_order(name, ex["sentences"])
    elif etype == "sortcolumns":
        view = B.build_sort_columns(
            name, [{"title": c["title"], "words": c["words"]}
                   for c in ex["columns"]])
    elif etype == "ordersentences":
        view = B.build_order_sentences(name, ex["sentences"])
    elif etype == "truefalse":
        def _tf_val(v):
            return None if v in (None, "notstated") else bool(v)
        statements = [(s[0], _tf_val(s[1])) for s in ex["statements"]]
        has_ns = bool(ex.get("not_stated")) or any(
            s[1] in (None, "notstated") for s in ex["statements"])
        view = B.build_true_false(name, statements, not_stated=has_ns,
                                  autocheck=bool(ex.get("autocheck", True)))
    elif etype == "test":
        qs = [{"q": q["q"], "options": q["options"], "correct": q["correct"],
               "points": q.get("points", 1.0)}
              for q in ex["questions"]]
        timer = ex.get("timer_min", ex.get("timer"))
        view = B.build_test(name, qs, timer_min=timer,
                            points=bool(ex.get("points", True)))
    elif etype == "voice":
        view = B._base(B.EX_VOICE, name, number)
        seconds = max(30, min(180, int(ex.get("seconds", 120))))  # docs: 3 min max
        rec = {"Text": ex.get("html", ""), "RecordingDuration": seconds}
        jd = json.loads(view["JsonData"])
        jd["AudioRecording"] = rec
        view["JsonData"] = json.dumps(jd, ensure_ascii=False)
        view["AudioRecording"] = rec
    elif etype == "unscramble":
        view = B.build_unscramble(name, ex["words"])
    elif etype == "audio":
        view = B.build_audio(name, ex["audios"])
    elif etype == "gif":
        view = B.build_gif(name, ex.get("description", ""))
    elif etype in ("label", "labelfill", "labelchoose"):
        mode = {"label": "drag", "labelfill": "fill",
                "labelchoose": "choose"}[etype]
        view = B.build_label_pictures(name, ex["items"], mode=mode)
    elif etype in B._LINK_BLOCKS:
        view = B.build_link_block(name, ex["link"], ex.get("text", ""),
                                  block=etype)
    else:  # pragma: no cover - validate() guards this
        raise ValueError(f"unsupported type {etype}")
    timer_min = ex.get("timer_min")
    if timer_min is not None and etype in TIMER_TYPES:
        # Execution Time: locks submission when the countdown ends.
        view["TimerMinutes"] = max(1, min(120, int(timer_min)))
    if "show_number" in ex:
        view["IsShowExerciseNumber"] = bool(ex["show_number"])
    view["Number"] = number
    view["LessonId"] = lesson_id
    view["LessonSectionId"] = section_id
    return view


# ------------------------------------------------------- post-save hooks
def preupload_audio(session, ex, log=None):
    """Upload local audio files of an `audio` spec item (media type 10) and
    return their file ids; sets a['url'] so the saved view carries the URL."""
    ids = []
    for a in ex.get("audios", []):
        path = a.get("file")
        if path:
            data = session.upload_media_file(path, file_type=B.MEDIA_AUDIO)
            a["url"] = data.get("Url")
            ids.append(data.get("Id"))
            if log:
                log(f"   ^ uploaded audio {a.get('title') or path}")
    return ids


def _attach_after_save(session, etype, ex, eid, audio_ids=None, log=None):
    """Post-save bindings: images for pictures/gif/label (display order =
    spec order) and uploaded audio files for the audio template."""
    if not eid:
        return
    images = None
    if etype in ("pictures", "gif"):
        images = ex.get("images") or ([ex["image"]] if ex.get("image") else [])
    elif etype in ("label", "labelfill", "labelchoose"):
        images = [it.get("image") for it in ex.get("items", [])
                  if it.get("image")]
    if images:
        session.change_exercise_images(eid, images)
        if log:
            log(f"   ~ attached {len(images)} image(s) to #{eid}")
    if etype == "audio" and audio_ids:
        session.change_exercise_audios(eid, audio_ids)
        if log:
            log(f"   ~ bound {len(audio_ids)} audio file(s) to #{eid}")


# ----------------------------------------------------------------- executor
def build_lesson(session, spec, material_id=None, lesson_id=None, name=None,
                 description=None, log=None):
    """Execute a lesson spec against an existing or brand-new lesson.

    material_id -> create a new lesson inside that material (Book).
    lesson_id   -> append into an existing lesson.
    Returns a summary dict.
    """
    errs = validate(spec)
    if errs:
        raise ValueError("spec invalid: " + "; ".join(errs))

    created = False
    if not lesson_id:
        if not material_id:
            raise ValueError("pass material_id (new lesson) or lesson_id")
        course_id = session.get_course_id(material_id)
        lesson_name = (name or spec.get("lesson_name") or "Lesson").strip()
        lesson_id, auto_sec = session.create_lesson(material_id, course_id,
                                                    lesson_name)
        created = True
        lesson = session.get_lesson(lesson_id)
    else:
        lesson = session.get_lesson(lesson_id)

    book_id = lesson.get("BookId") or material_id
    if not book_id:
        # GetLessonWithId does not expose BookId; resolve it from the preview
        # (LessonUpsert with a null BookId fails with "Invalid request
        # parameters" and silently drops the description update).
        try:
            prev = session.rpc("LessonWsController", "GetLessonPreview",
                               "Books", {"LessonId": lesson_id})
            book_id = (((prev.get("Value") or {}).get("Book")) or {}).get("Id")
        except Exception:
            book_id = None
    course_id = lesson.get("CourseId")
    existing_sections = lesson.get("Sections") or []
    hw_id = (lesson.get("HomeworkSection") or {}).get("Id")
    by_name = {(s.get("Name") or "").strip().casefold(): s.get("Id")
               for s in existing_sections}

    summary = {"lesson_id": lesson_id, "created": created, "sections": []}
    next_sort = len(existing_sections)
    auto_used = False

    for i, sec in enumerate(spec["sections"]):
        sname = sec["name"].strip()
        key = sname.casefold()
        target = None
        if key in HOMEWORK_NAMES and hw_id:
            target = hw_id
        elif key in by_name:
            target = by_name[key]
        elif created and not auto_used and key not in by_name:
            session.edit_section(lesson_id, auto_sec, sname, 0)
            target = auto_sec
            auto_used = True
        else:
            r = session.add_section(lesson_id, sname, next_sort)
            next_sort += 1
            target = r.get("StageSectionId") if isinstance(r, dict) else r

        existing = session.load_exercises(target, lesson_id)
        counter = max([e.get("Number", 0) for e in existing] + [-1]) + 1
        ids = []
        for j, ex in enumerate(sec["exercises"]):
            etype = norm_type(ex.get("type"))
            audio_ids = []
            try:
                if etype == "audio":
                    audio_ids = preupload_audio(session, ex, log=log)
                view = _build_one(ex, etype, counter, lesson_id, target)
                saved = session.save_exercise(view, lesson_id, target)
            except EdvibeError:
                raise
            except Exception as exc:
                raise ValueError(
                    f"section '{sname}' exercise {j} ({etype}): {exc}") from exc
            eid = saved.get("Id") if isinstance(saved, dict) else saved
            _attach_after_save(session, etype, ex, eid, audio_ids=audio_ids,
                               log=log)
            ids.append(eid)
            counter += 1
            if log:
                log(f"   + #{eid} {etype} " + (label(ex) or "")[:60])
        summary["sections"].append({"name": sname, "section_id": target,
                                    "exercise_ids": ids})

    if description is None and name and not created:
        try:
            prev = session.rpc("LessonWsController", "GetLessonPreview",
                               "Books", {"LessonId": lesson_id})
            description = ((prev.get("Value") or {}).get("Description")) or ""
        except Exception:
            description = ""
    if description or (name and not created):
        payload = {
            "Id": lesson_id, "Number": 0, "NoPhotoColor": 2,
            "Name": (name or lesson.get("Name") or ""), "Text": description or "",
            "CourseId": course_id, "BookId": book_id,
            "Tags": {"TagAge": [], "TagLevel": [], "TagType": [],
                     "TagSkills": [], "TagTime": [], "Vocabulary": "",
                     "Grammar": "", "Functions": "", "Other": ""},
            "DeviceType": "desktop", "ClientTime": client_time(),
        }
        r = session.rpc("LessonWsController", "LessonUpsert", "Books", payload)
        if not r.get("IsSuccess"):
            summary["description_error"] = r.get("ErrorMessage")
        else:
            summary["description_set"] = bool(description)

    return summary
