"""Offline unit tests: core.school (parsing + metrics, no network)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli_edvibe.core import school as sch  # noqa: E402

SCHOOL_CSV = (
    "Student ID;Student Email;Student;Class ID;Class Name;Class Type;"
    "Lessons Completed;Total Score;General Score;Vocabulary;Speaking;Grammar;"
    "Listening;Reading;\r\n"
    "1;a@x.com;Ann;10;Class A;Individual;3;30,50;0,00;10,00;0,00;0,00;20,50;0,00;\r\n"
    "2;b@x.com;Bob;;; ;12;120,00;0,00;100,00;0,00;0,00;20,00;0,00;\r\n"
)

CLASS_CSV = (
    "Student Email;Student;Lessons Completed;Total Score;Listening;\r\n"
    "a@x.com;Ann;2;15,00;15,00;\r\n"
)

MARATHON_CSV = "Student Email;Student;Lessons Completed;Total Score;\r\n"


def test_parse_school_csv_types():
    rows = sch.parse_statistics_csv(SCHOOL_CSV)
    assert len(rows) == 2
    assert rows[0]["student_id"] == 1
    assert rows[0]["lessons_completed"] == 3
    assert rows[0]["total_score"] == 30.5
    assert rows[0]["listening"] == 20.5
    assert rows[0]["student_email"] == "a@x.com"
    assert rows[1]["class_id"] is None


def test_parse_empty_payload():
    assert sch.parse_statistics_csv(MARATHON_CSV) == []
    assert sch.parse_statistics_csv("") == []


def test_summarize_with_roster_email_match():
    rows = sch.parse_statistics_csv(CLASS_CSV)
    roster = [{"Id": 999, "Email": "a@x.com", "FullName": "Ann"}]
    m = sch.summarize(rows, roster=roster)
    assert m["students_with_data"] == 1
    assert m["enrolled"] == 1
    assert m["without_data"] == 0
    assert m["active"] == 1
    assert m["activation_pct"] == 100.0


def test_summarize_counts_pupils_missing_from_export():
    rows = sch.parse_statistics_csv(CLASS_CSV)
    roster = [{"Id": 1, "Email": "a@x.com"}, {"Id": 2, "Email": "nobody@x.com"}]
    m = sch.summarize(rows, roster=roster)
    assert m["enrolled"] == 2
    assert m["without_data"] == 1
    assert m["activation_pct"] == 50.0


def test_summarize_course_percentages():
    rows = sch.parse_statistics_csv(SCHOOL_CSV)
    m = sch.summarize(rows, total_lessons=12)
    assert m["finishers"] == 1            # Bob did all 12
    assert m["halfway"] == 1              # only Bob passed 6
    assert m["finisher_pct"] == 50.0
    assert m["avg_completion_pct"] == round(100 * (3 + 12) / (12 * 2), 1)


def test_skill_breakdown_ignores_all_zero_columns():
    rows = sch.parse_statistics_csv(SCHOOL_CSV)
    skills = sch.skill_breakdown(rows)
    assert "listening" in skills and skills["listening"]["students"] == 2
    assert "vocabulary" in skills and skills["vocabulary"]["students"] == 2
    assert "reading" not in skills        # zero for everybody = not measured
    assert "total_score" not in skills


def test_survival_curve():
    rows = [{"lessons_completed": 3}, {"lessons_completed": 1}, {"lessons_completed": 0}]
    curve = sch.survival(rows)
    assert [p["reached"] for p in curve] == [2, 1, 1]
    assert curve[0]["pct"] == 66.7


def test_course_metrics_and_curve():
    pupils = [
        {"PupilId": 1, "Name": "A", "Email": "a@x", "IsActivated": True,
         "IsArchiveUser": False, "Progress": {"CountLesson": 4, "CompleteLesson": 4,
                                              "PendingReviewLesson": 0}},
        {"PupilId": 2, "Name": "B", "Email": "b@x", "IsActivated": True,
         "IsArchiveUser": False, "Progress": {"CountLesson": 4, "CompleteLesson": 2,
                                              "PendingReviewLesson": 1}},
        {"PupilId": 3, "Name": "C", "Email": "c@x", "IsActivated": False,
         "IsArchiveUser": True, "Progress": {"CountLesson": 4, "CompleteLesson": 0,
                                             "PendingReviewLesson": 0}},
    ]
    m, rows = sch.course_metrics(pupils)
    assert m["enrolled"] == 3
    assert m["lessons_total"] == 4
    assert m["started"] == 2            # C never opened anything
    assert m["finished"] == 1
    assert m["halfway"] == 2
    assert rows[1]["pending"] == 1
    curve = sch.course_curve(rows, 4)
    assert [p["reached"] for p in curve] == [2, 2, 1, 1]


class _StubSession:
    """Minimal rpc() stub: controller.method -> canned Value."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def rpc(self, controller, method, project, value=None):
        self.calls.append((controller, method, value))
        val = self.mapping[(controller, method)]
        if callable(val):
            val = val(value)
        return {"IsSuccess": True, "Value": val}


def _pupil(pid, completed):
    return {"PupilId": pid, "Name": f"P{pid}", "Email": f"{pid}@x",
            "IsActivated": True, "IsArchiveUser": False,
            "Progress": {"CountLesson": 2, "CompleteLesson": completed,
                         "PendingReviewLesson": 0}}


def test_course_dropoff_uses_last_request_status():
    def lessons(value):
        pid = value["PupilId"]
        if pid == 1:
            return [
                {"MarathonLessonId": 1, "LessonId": 10, "Name": "One", "Number": 0,
                 "LastRequest": {"Status": 2}},
                {"MarathonLessonId": 2, "LessonId": 11, "Name": "Two", "Number": 3,
                 "LastRequest": None},
            ]
        return [
            {"MarathonLessonId": 1, "LessonId": 10, "Name": "One", "Number": 0,
             "LastRequest": None},
            {"MarathonLessonId": 2, "LessonId": 11, "Name": "Two", "Number": 3,
             "LastRequest": None},
        ]

    sess = _StubSession({
        ("MarathonPupilsWsController", "GetMarathonPupils"):
            {"Items": [_pupil(1, 1), _pupil(2, 0)], "Page": {"Count": 2}},
        ("MarathonLessonWsController", "GetMarathonLessonsForPupil"): lessons,
    })
    data = sch.course_dropoff(sess, 5)
    assert data["enrolled"] == 2
    assert data["never_started"] == 1
    assert data["lessons"][0]["reached"] == 1
    assert data["lessons"][0]["opened"] == 1
    assert data["lessons"][1]["reached"] == 0
    assert data["lessons"][1]["opened"] == 0
    stops = {s["after_lesson"]: s["pupils"] for s in data["stops"]}
    assert stops[0] == 1 and stops[-1] == 1
