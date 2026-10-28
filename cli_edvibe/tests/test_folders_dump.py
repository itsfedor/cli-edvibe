"""Offline tests for `materials folders` / `materials move` and `lesson dump`.

No network: the session is a double that answers the read RPCs from local
state and records every call, so payloads and the read-only guarantees can be
asserted without touching the live school.
"""
import json
import os
import sys

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli_edvibe import edvibe_cli  # noqa: E402
from cli_edvibe.core import lesson_dump as dump_mod  # noqa: E402
from cli_edvibe.core.client import EdvibeError, EdvibeSession  # noqa: E402

LESSON = {
    "Id": 5, "Name": "Unit 1", "Number": 1,
    "Sections": [{"Id": 91, "Name": "Warm-Up"}, {"Id": 92, "Name": "Vocabulary"}],
    "HomeworkSection": {"Id": 93, "Name": "Homework", "IsHomework": True},
}

EXERCISES = {
    91: [{"Id": 1001, "Type": 25, "Name": "Warm-up Qs",
          "Text": {"Text": "<b>Warm up</b>"}}],
    92: [{"Id": 1002, "Type": 13, "Name": "Choose",
          "QuestionWithCodingTexts": [{"Text": "[a*/b]"}]},
         {"Id": 1003, "Type": 22, "Name": "Answer key",
          "Note": {"Text": "<p>secret</p>", "ShowToPupil": False,
                   "VisibilityType": 1}}],
    93: [],
}


class FakeSession(EdvibeSession):
    """Session double: folder state in memory, every RPC recorded."""

    def __init__(self, fail_move=False):
        self.calls = []
        self.user = {"Id": 1, "SchoolId": 9419}
        self.domain = "edvibe.com"
        self.fail_move = fail_move
        self.placement = {1206451: 0, 1224556: 1202}      # book -> folder (0 = top level)
        self.names = {1206451: "New Spoken Lessons",
                      1224556: "CLI-HARNESS-E2E test"}
        self.folders = {1201: "Сериалы", 1202: "Старые материалы"}

    def _books(self):
        return [{"Id": b, "Name": n, "FolderId": self.placement[b]}
                for b, n in self.names.items()]

    def rpc(self, controller, method, project, value=None):
        self.calls.append((f"{controller}.{method}", value, project))
        key = (controller, method)
        if key == ("BookWsController", "GetPersonalBooks"):
            items = [{"Book": b} for b in self._books() if not b["FolderId"]]
            items += [{"Folder": {"Id": fid, "Name": name,
                                  "CountMaterials": sum(1 for f in self.placement.values()
                                                        if f == fid)}}
                      for fid, name in self.folders.items()]
            return {"IsSuccess": True, "Value": {"Items": items}}
        if key == ("BookWsController", "GetSchoolBooks"):
            fid = (value or {}).get("FolderId")
            return {"IsSuccess": True,
                    "Value": {"Items": [{"Book": b} for b in self._books()
                                        if b["FolderId"] == fid]}}
        if key == ("LessonWsController", "GetLessonWithId"):
            return {"IsSuccess": True, "Value": LESSON}
        if key == ("GetExerciseWsController", "LoadExercises"):
            sid = (value or {}).get("SectionId")
            return {"IsSuccess": True, "Value": {"Items": EXERCISES.get(sid, [])}}
        if key == ("LessonWsController", "GetLessonPreview"):
            return {"IsSuccess": True, "Value": {"Description": "A unit"}}
        if key == ("FolderBookWsController", "AddBookToFolder"):
            if self.fail_move:
                return {"IsSuccess": False, "ErrorMessage": "no access",
                        "ErrorCode": 403}
            self.placement[value["BookId"]] = value["FolderId"]
            return {"IsSuccess": True, "Value": True}
        return {"IsSuccess": False, "ErrorMessage": f"unexpected {controller}.{method}"}

    def write_calls(self):
        return [c[0] for c in self.calls
                if any(w in c[0] for w in ("Save", "Upsert", "Delete", "Add", "Move"))]


@pytest.fixture
def fake(monkeypatch):
    sess = FakeSession()
    monkeypatch.setattr(edvibe_cli, "get_session", lambda ctx, login=True: sess)
    return sess


# ------------------------------------------------------------------ folders
def test_list_folders_extracts_folder_rows():
    sess = FakeSession()
    folders = sess.list_folders()
    assert [f["id"] for f in folders] == [1201, 1202]
    assert folders[1]["name"] == "Старые материалы"
    assert folders[1]["count"] == 1                       # only the CLI-HARNESS book
    assert sess.find_folder(1201)["name"] == "Сериалы"
    assert sess.find_folder(name="старые материалы")["id"] == 1202
    assert sess.find_folder(9999) is None


def test_folder_books_and_book_location():
    sess = FakeSession()
    assert [b["Id"] for b in sess.folder_books(1202)] == [1224556]
    assert sess.folder_books(1201) == []
    loc = sess.book_location(1224556)
    assert (loc["folder_id"], loc["folder_name"]) == (1202, "Старые материалы")
    top = sess.book_location(1206451)
    assert top["folder_id"] == 0 and top["folder_name"] is None
    assert sess.book_location(1)["book"] is None


def test_move_book_to_folder_payload():
    sess = FakeSession()
    assert sess.move_book_to_folder(1224556, 1202) is True
    name, value, project = sess.calls[-1]
    assert name == "FolderBookWsController.AddBookToFolder"
    assert project == "Books"
    assert value == {"FolderId": 1202, "BookId": 1224556}


def test_move_book_to_folder_error_raises():
    sess = FakeSession(fail_move=True)
    with pytest.raises(EdvibeError):
        sess.move_book_to_folder(1224556, 1202)


# --------------------------------------------------------------- CLI: move
def test_cli_materials_move_dry_run_makes_no_write(fake):
    res = CliRunner().invoke(edvibe_cli.cli, ["materials", "move", "--book",
                                              "1206451", "--folder", "1202",
                                              "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "DRY-RUN" in res.output and "no write RPC" in res.output
    assert fake.write_calls() == []
    assert fake.placement[1206451] == 0                   # unchanged


def test_cli_materials_move_moves_and_verifies(fake):
    res = CliRunner().invoke(edvibe_cli.cli, ["--json", "materials", "move",
                                              "--book", "1206451",
                                              "--folder", "1202"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["from_folder"] == 0 and data["to_folder"] == 1202
    assert data["ok"] is True and data["verified"] is True
    assert fake.placement[1206451] == 1202
    assert data["test_material"] is False       # "New Spoken Lessons" is not test junk
    assert "FolderBookWsController.AddBookToFolder" in fake.write_calls()


def test_cli_materials_move_warns_on_real_material(fake):
    res = CliRunner().invoke(edvibe_cli.cli, ["materials", "move", "--book",
                                              "1206451", "--folder", "1202"])
    assert res.exit_code == 0, res.output
    assert "not a CLI-HARNESS-* test material" in res.output
    res = CliRunner().invoke(edvibe_cli.cli, ["materials", "move", "--book",
                                              "1224556", "--folder", "1202"])
    assert res.exit_code == 0, res.output
    assert "not a CLI-HARNESS" not in res.output


def test_cli_materials_move_unknown_folder_or_book(fake):
    res = CliRunner().invoke(edvibe_cli.cli, ["materials", "move", "--book",
                                              "1206451", "--folder", "9999"])
    assert res.exit_code == 1 and "folder #9999 not found" in res.output
    res = CliRunner().invoke(edvibe_cli.cli, ["materials", "move", "--book",
                                              "424242", "--folder", "1202"])
    assert res.exit_code == 1 and "not found in personal materials" in res.output
    assert fake.write_calls() == []


def test_cli_materials_folders_with_books(fake):
    res = CliRunner().invoke(edvibe_cli.cli, ["materials", "folders", "--books"])
    assert res.exit_code == 0, res.output
    assert "1202" in res.output and "Старые материалы" in res.output
    assert "CLI-HARNESS-E2E test" in res.output
    assert fake.write_calls() == []
    res_json = CliRunner().invoke(edvibe_cli.cli, ["--json", "materials", "folders"])
    data = json.loads(res_json.output)
    assert data["total"] == 2 and data["folders"][0]["id"] == 1201


# ------------------------------------------------------------ lesson dump
def test_is_hidden_covers_both_live_encodings():
    assert dump_mod.is_hidden({"IsHidePupil": True})
    assert dump_mod.is_hidden({"IsHideExercise": True})
    assert dump_mod.is_hidden({"Note": {"ShowToPupil": False}})
    assert dump_mod.is_hidden({"Note": {"VisibilityType": 1}})
    assert not dump_mod.is_hidden({"Note": {"ShowToPupil": True, "VisibilityType": 0}})
    assert not dump_mod.is_hidden({"Type": 13})
    assert dump_mod.type_name(22) == "note" and dump_mod.type_name(999) == "type-999"
    assert dump_mod.content_len({"Note": {"Text": "abcd"}}) == 4


def test_dump_lesson_includes_homework_and_raw_exercises():
    sess = FakeSession()
    dump = dump_mod.dump_lesson(sess, 5)
    assert [s["section_id"] for s in dump["sections"]] == [91, 92, 93]
    assert [s["is_homework"] for s in dump["sections"]] == [False, False, True]
    assert dump["total_exercises"] == 3
    assert dump["description"] == "A unit"
    # raw views are the untouched server dicts (hidden note html included)
    note = dump["sections"][1]["exercises"][1]
    assert note["Note"]["Text"] == "<p>secret</p>"
    summary = dump["sections"][1]["summary"]
    assert summary[0]["type_name"] == "choose-option" and not summary[0]["hidden"]
    assert summary[1]["hidden"] is True and summary[1]["html_chars"] == 13
    assert sess.write_calls() == []                       # dump is read-only


def test_dump_lesson_section_filter_and_errors():
    sess = FakeSession()
    assert [s["name"] for s in dump_mod.dump_lesson(sess, 5, section="93")
            ["sections"]] == ["Homework"]
    assert [s["name"] for s in dump_mod.dump_lesson(sess, 5, section="warm-up")
            ["sections"]] == ["Warm-Up"]
    assert [s["name"] for s in dump_mod.dump_lesson(sess, 5, section="Vocab")
            ["sections"]] == ["Vocabulary"]
    with pytest.raises(ValueError):
        dump_mod.dump_lesson(sess, 5, section="Nope")


def test_cli_lesson_dump_writes_full_json(tmp_path, fake):
    out = tmp_path / "lesson.json"
    res = CliRunner().invoke(edvibe_cli.cli, ["lesson", "dump", "--lesson", "5",
                                              "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert "3 sections / 3 exercises" in res.output
    assert "[hidden]" in res.output and "answer key" in res.output.lower()
    assert str(out) in res.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sections"][1]["exercises"][1]["Note"]["Text"] == "<p>secret</p>"
    assert fake.write_calls() == []
    bad = CliRunner().invoke(edvibe_cli.cli, ["lesson", "dump", "--lesson", "5",
                                              "--section", "Nope"])
    assert bad.exit_code == 1 and "no section matching" in bad.output
