"""School-level analytics: rosters, classes/marathons, statistics CSV exports.

All reads are plain WS RPCs (no writes). Data sources (verified live Oct 2026):

  Statistic / StatisticDownloaderService.DownloadCsvSchoolStatistic   {} 
  Statistic / StatisticDownloaderService.DownloadCsvClassStatistic    {ClassId}
  Statistic / StatisticDownloaderService.DownloadCsvMarathonStatistic {MarathonId}
  Statistic / ClassStatisticService.GetPupilStatistic                 {PupilId, ClassId}
  Statistic / ClassStatisticService.GetPupilLessonStatistic           {PupilId, ClassId, LessonId}
  Statistic / ClassStatisticService.GetClassTopRating                 {Search, ShowAll, Mode, ClassId}
  Statistic / MarathonStatisticService.GetMarathonTopRating           {Search, ShowAll, Mode, MarathonId}
  School    / GroupService.GetClassesList / GetGroupsList
  School    / PupilService.GetPupilsList                              GetListType 0..4
  Marathons / MarathonWsController.GetMarathons                       {Page:{Skip,Take}}

The CSV endpoints return `{Name, Payload}` where Payload is a ';'-separated
table with a trailing ';' and comma decimal separators. Payload is nested
inside the WS `Value`, so the real frame is `{"Value": {"Name": ..., "Payload": ...}}`
-> session.rpc() already unwraps `Value`.

Coverage caveat: Edvibe only counts a lesson as completed when statistics are
configured for it. A pupil with no row may be idle OR simply in a course whose
statistics were never enabled - both look identical server-side.
"""
from __future__ import annotations

import csv
import io
import statistics

# ---------------------------------------------------------------- transports


def _rpc(sess, controller, method, project, value):
    resp = sess.rpc(controller, method, project, value)
    if not resp.get("IsSuccess"):
        raise RuntimeError(f"{controller}.{method} failed: {resp.get('ErrorMessage')}")
    return resp.get("Value")


def list_pupils(sess, list_type=0, take=500):
    """All school pupils (GetListType: 0=all, 1..4 = UI filters)."""
    out, skip = [], 0
    while True:
        val = _rpc(sess, "PupilService", "GetPupilsList", "School",
                   {"Skip": skip, "Take": take, "GetListType": list_type,
                    "IsInversion": False, "SortClass": 1}) or {}
        page = val.get("Pupils") or []
        out.extend(page)
        total = val.get("TotalCount") or 0
        skip += len(page)
        if not page or skip >= total:
            break
    return {"TotalCount": total if out else 0, "Pupils": out}


def list_classes(sess, take=500):
    val = _rpc(sess, "GroupService", "GetClassesList", "School",
               {"Skip": 0, "Take": take}) or {}
    return val.get("Groups") or []


def list_groups(sess, take=500):
    val = _rpc(sess, "GroupService", "GetGroupsList", "School",
               {"Skip": 0, "Take": take}) or {}
    return val.get("Groups") or []


def list_marathons(sess, take=500):
    val = _rpc(sess, "MarathonWsController", "GetMarathons", "Marathons",
               {"Page": {"Skip": 0, "Take": take}}) or {}
    items = val.get("Items") or []
    marathons, folders = [], []
    for it in items:
        if it.get("IsFolder"):
            folders.append(it.get("Folder") or {})
        else:
            marathons.append(it)
    return {"Marathons": marathons, "Folders": folders}


# ---------------------------------------------------------------------- CSV


def _clean_csv(payload: str) -> str:
    """Normalise the server CSV: drop the trailing ';', keep the rest as-is."""
    text = (payload or "").replace("\r\n", "\n").strip("\n")
    text = "\n".join(line.rstrip(";") for line in text.split("\n"))
    return text


def parse_statistics_csv(payload: str) -> list[dict]:
    """Parse a `;`-separated statistics export into typed rows."""
    text = _clean_csv(payload)
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows = []
    for raw in reader:
        row = {}
        for key, value in raw.items():
            if key is None:
                continue
            k = key.strip()
            v = (value or "").strip()
            if k == "Lessons Completed":
                row["lessons_completed"] = int(float(v or 0))
            elif k in ("Total Score",) or k in CATEGORY_COLUMNS:
                row[_snake(k)] = _num(v)
            elif k in ("Student ID", "Class ID"):
                row[_snake(k)] = int(v) if v.isdigit() else None
            else:
                row[_snake(k)] = v
        # Keep the human-facing original columns too.
        row["raw"] = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        rows.append(row)
    return rows


# Score columns of the statistics export (the export has no "_score" suffix on
# skill columns - they are plain names: General, Vocabulary, Grammar, ...).
CATEGORY_COLUMNS = {"General", "Vocabulary", "Speaking", "Grammar", "Listening",
                    "Reading", "Writing", "Use of English"}


def _snake(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _num(text: str):
    if not text:
        return 0.0
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return 0.0


def _export(kind, sess, **kwargs):
    if kind == "school":
        val = _rpc(sess, "StatisticDownloaderService", "DownloadCsvSchoolStatistic",
                   "Statistic", {})
    elif kind == "class":
        val = _rpc(sess, "StatisticDownloaderService", "DownloadCsvClassStatistic",
                   "Statistic", {"ClassId": int(kwargs["class_id"])})
    elif kind == "marathon":
        val = _rpc(sess, "StatisticDownloaderService", "DownloadCsvMarathonStatistic",
                   "Statistic", {"MarathonId": int(kwargs["marathon_id"])})
    else:
        raise ValueError(kind)
    val = val or {}
    payload = val.get("Payload") or ""
    return {"name": val.get("Name") or kind, "payload": _clean_csv(payload),
            "rows": parse_statistics_csv(payload)}


def school_statistics(sess):
    return _export("school", sess)


def class_statistics(sess, class_id):
    return _export("class", sess, class_id=class_id)


def marathon_statistics(sess, marathon_id):
    return _export("marathon", sess, marathon_id=marathon_id)


# ------------------------------------------------------------------- ratings


def class_rating(sess, class_id, mode=0):
    return _rpc(sess, "ClassStatisticService", "GetClassTopRating", "Statistic",
                {"Search": "", "ShowAll": True, "Mode": int(mode),
                 "ClassId": int(class_id)}) or {}


def marathon_rating(sess, marathon_id, mode=0):
    return _rpc(sess, "MarathonStatisticService", "GetMarathonTopRating", "Statistic",
                {"Search": "", "ShowAll": True, "Mode": int(mode),
                 "MarathonId": int(marathon_id)}) or {}


def pupil_statistic(sess, pupil_id, class_id):
    return _rpc(sess, "ClassStatisticService", "GetPupilStatistic", "Statistic",
                {"PupilId": int(pupil_id), "ClassId": int(class_id)}) or {}


# ------------------------------------------------------------ course pupils


def marathon_pupils(sess, marathon_id, take=200):
    """Per-pupil progress inside a marathon/course.

    MarathonPupilsWsController.GetMarathonPupils returns, for every enrolled
    pupil: Progress{CountLesson, CompleteLesson, PendingReviewLesson,
    CountReworkLessons}, IsActivated, IsArchiveUser, DateStartStudyMarathon.
    This is the ONLY completion source that works without statistics being
    configured on the course.
    """
    out, skip = [], 0
    while True:
        val = _rpc(sess, "MarathonPupilsWsController", "GetMarathonPupils",
                   "Marathons", {"MarathonId": int(marathon_id),
                                 "Page": {"Skip": skip, "Take": take}}) or {}
        items = val.get("Items") or []
        out.extend(items)
        page = val.get("Page") or {}
        total = page.get("Count") or val.get("Count") or 0
        skip += len(items)
        if not items or len(items) < take or (total and skip >= total):
            break
    return out


def course_metrics(pupils, total_lessons=None):
    """Activity / completion metrics from marathon pupil progress."""
    rows = []
    for p in pupils:
        prog = p.get("Progress") or {}
        rows.append({
            "pupil_id": p.get("PupilId"),
            "name": p.get("Name"),
            "email": p.get("Email"),
            "lessons_total": prog.get("CountLesson") or 0,
            "completed": prog.get("CompleteLesson") or 0,
            "pending": prog.get("PendingReviewLesson") or 0,
            "rework": prog.get("CountReworkLessons") or 0,
            "activated": p.get("IsActivated"),
            "archived": p.get("IsArchiveUser"),
            "started": p.get("DateStartStudyMarathon"),
        })
    n = len(rows)
    if total_lessons is None:
        total_lessons = max((r["lessons_total"] for r in rows), default=0) or None
    done = [r["completed"] for r in rows]
    started = sum(1 for r in rows if r["completed"] > 0 or r["pending"] > 0)
    finished = sum(1 for r in rows if total_lessons and r["completed"] >= total_lessons)
    halfway = sum(1 for r in rows if total_lessons and r["completed"] >= total_lessons / 2)
    metrics = {
        "enrolled": n,
        "started": started,
        "started_pct": _pct(started, n),
        "activated": sum(1 for r in rows if r["activated"]),
        "archived": sum(1 for r in rows if r["archived"]),
        "lessons_total": total_lessons,
        "completed_avg": round(statistics.fmean(done), 2) if done else 0,
        "completed_median": statistics.median(done) if done else 0,
        "completed_max": max(done) if done else 0,
        "halfway": halfway,
        "halfway_pct": _pct(halfway, n),
        "finished": finished,
        "finished_pct": _pct(finished, n),
        "avg_progress_pct": _pct(sum(done), total_lessons * n) if total_lessons and n else 0,
        "pending_review": sum(r["pending"] for r in rows),
    }
    return metrics, rows


def course_curve(rows, total_lessons=None):
    """How many pupils reached lesson k (cumulative, from CompleteLesson)."""
    top = total_lessons or max((r["completed"] for r in rows), default=0)
    n = len(rows) or 1
    out = []
    for k in range(1, top + 1):
        reached = sum(1 for r in rows if r["completed"] >= k)
        out.append({"lesson": k, "reached": reached, "pct": _pct(reached, n)})
    return out


# --------------------------------------------------------------- drop-off


def pupil_marathon_lessons(sess, marathon_id, pupil_id):
    """Per-lesson completion for ONE pupil.

    Returns [{index, name, lesson_id, marathon_lesson_id, status, completed}]
    in course order. status == 2 means the request was accepted (lesson done);
    a lesson with no request (LastRequest null) was never opened.
    """
    val = _rpc(sess, "MarathonLessonWsController", "GetMarathonLessonsForPupil",
               "Marathons", {"MarathonId": int(marathon_id),
                             "PupilId": int(pupil_id)}) or []
    out = []
    for i, lesson in enumerate(val):
        last = lesson.get("LastRequest") or {}
        status = last.get("Status")
        out.append({"index": i,
                    "number": lesson.get("Number"),
                    "name": lesson.get("Name"),
                    "lesson_id": lesson.get("LessonId"),
                    "marathon_lesson_id": lesson.get("MarathonLessonId"),
                    "status": status,
                    "completed": status == 2,
                    "date": last.get("DateCreate")})
    return out


def course_dropoff(sess, marathon_id, pupils=None, on_progress=None):
    """Exact per-lesson reach across a course (one RPC per pupil).

    Returns lessons [{index, name, lesson_id, reached, pct, completed}] plus
    the stop distribution: how many pupils stopped after lesson k.
    `on_progress(done, total)` is called after every pupil.
    """
    pupils = pupils if pupils is not None else marathon_pupils(sess, marathon_id)
    total = len(pupils)
    lessons, reached, opened = [], [], []
    stops = {}
    never = 0
    for n, p in enumerate(pupils, 1):
        items = pupil_marathon_lessons(sess, marathon_id, p.get("PupilId"))
        if not lessons:
            lessons = [{"index": it["index"], "name": it["name"],
                        "lesson_id": it["lesson_id"]} for it in items]
            reached = [0] * len(items)
            opened = [0] * len(items)
        done_idx = -1
        for it in items:
            i = it["index"]
            if i >= len(reached):
                continue
            if it["status"] is not None:
                opened[i] += 1
            if it["completed"]:
                reached[i] += 1
                done_idx = max(done_idx, i)
        if done_idx < 0:
            never += 1
            stops[-1] = stops.get(-1, 0) + 1
        else:
            stops[done_idx] = stops.get(done_idx, 0) + 1
        if on_progress:
            on_progress(n, total)

    rows = []
    for i, lesson in enumerate(lessons):
        rows.append({**lesson,
                     "reached": reached[i],
                     "opened": opened[i],
                     "pct": _pct(reached[i], total),
                     "opened_pct": _pct(opened[i], total)})
    return {"enrolled": total, "never_started": never,
            "lessons": rows,
            "stops": [{"after_lesson": k, "pupils": v}
                      for k, v in sorted(stops.items(), reverse=True)]}


# ------------------------------------------------------------------ metrics


def _identities(row):
    ids = set()
    if row.get("student_id"):
        ids.add(("id", str(row["student_id"])))
    if row.get("student_email"):
        ids.add(("email", row["student_email"].strip().lower()))
    return ids


def _roster_identities(roster):
    out = []
    for p in roster or []:
        ids = set()
        pid = p.get("Id") or p.get("id")
        email = p.get("Email") or p.get("email")
        if pid:
            ids.add(("id", str(pid)))
        if email:
            ids.add(("email", str(email).strip().lower()))
        out.append(ids)
    return out


def summarize(rows, total_lessons=None, roster=None):
    """Completion / activity metrics over one statistics export.

    `total_lessons` (course length) turns "lessons completed" into a percentage.
    `roster` is the class/school pupil list: pupils missing from the export are
    counted as "no data" (idle OR statistics never enabled - indistinguishable
    server-side).
    """
    row_keys = set()
    for r in rows:
        row_keys |= _identities(r)

    lessons = [int(r.get("lessons_completed") or 0) for r in rows]
    scores = [float(r.get("total_score") or 0) for r in rows]

    denominator = len(rows)
    idle = 0
    if roster:
        roster_keys = _roster_identities(roster)
        idle = sum(1 for keys in roster_keys if not (keys & row_keys))
        denominator = max(denominator, len(roster_keys))

    active = sum(1 for n in lessons if n > 0)
    metrics = {
        "students_with_data": len(rows),
        "enrolled": denominator,
        "without_data": idle,
        "active": active,
        "activation_pct": _pct(active, denominator),
        "lessons_total": total_lessons,
        "lessons_completed_avg": round(statistics.fmean(lessons), 2) if lessons else 0,
        "lessons_completed_median": statistics.median(lessons) if lessons else 0,
        "lessons_completed_max": max(lessons) if lessons else 0,
        "score_avg": round(statistics.fmean(scores), 2) if scores else 0,
        "score_max": max(scores) if scores else 0,
        "finishers": None,
        "finisher_pct": None,
    }
    if total_lessons:
        finished = sum(1 for n in lessons if n >= total_lessons)
        half = sum(1 for n in lessons if n >= total_lessons / 2)
        metrics.update({"finishers": finished, "finisher_pct": _pct(finished, denominator),
                        "halfway": half, "halfway_pct": _pct(half, denominator),
                        "avg_completion_pct": _pct(
                            sum(lessons), total_lessons * denominator) if denominator else 0})
    return metrics


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def survival(rows):
    """Cumulative reach per lesson number: how many pupils completed >= k.

    Only valid when pupils advance linearly through a course (marathons); the
    export has no per-lesson breakdown, so this reads "lessons completed" as a
    highest-lesson index.
    """
    lessons = sorted((int(r.get("lessons_completed") or 0) for r in rows), reverse=True)
    if not lessons:
        return []
    top = lessons[0]
    out = []
    for k in range(1, top + 1):
        reached = sum(1 for n in lessons if n >= k)
        out.append({"lesson": k, "reached": reached,
                    "pct": _pct(reached, len(lessons))})
    return out


def skill_breakdown(rows):
    """Average per-skill score across pupils (Listening / Grammar / ...).

    Returns {skill: {"avg": float, "students": rows having a non-zero score}}.
    Skills nobody was ever assessed in are dropped - an all-zero column means
    "not measured", not "everyone failed".
    """
    buckets = {}
    skip = {"raw", "total_score", "student_id", "class_id", "lessons_completed"}
    for r in rows:
        for key, value in r.items():
            if key in skip or not isinstance(value, (int, float)):
                continue
            buckets.setdefault(key, []).append(float(value))
    out = {}
    for key, values in sorted(buckets.items()):
        non_zero = [v for v in values if v]
        if not non_zero:
            continue
        out[key] = {"avg": round(statistics.fmean(values), 2),
                    "avg_of_scorers": round(statistics.fmean(non_zero), 2),
                    "students": len(non_zero)}
    return out
