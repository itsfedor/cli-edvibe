"""Offline tests for book-branding helpers: media cut-out and client icon RPCs."""
import json
import os
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli_edvibe.core import media  # noqa: E402
from cli_edvibe.core.client import EdvibeSession  # noqa: E402


def _donut_png(path, bg=(99, 167, 252), fg=(230, 80, 60), size=120):
    """Object with an ENCLOSED background-coloured hole (like the counter of an A)."""
    im = Image.new("RGB", (size, size), bg)
    px = im.load()
    for y in range(20, 100):
        for x in range(20, 100):
            px[x, y] = fg
    for y in range(45, 75):
        for x in range(45, 75):
            px[x, y] = bg          # enclosed hole
    im.save(path)


def test_cut_background_cleans_border_and_enclosed_holes():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.png")
        dst = os.path.join(td, "out.png")
        _donut_png(src)
        stats = media.cut_background(src, dst, tol=40)
        assert stats["removed_pct"] > 50
        assert stats["holes_cleaned"], "enclosed background hole should be cleaned"
        out = Image.open(dst).convert("RGBA")
        a = out.split()[3]
        # centre of the donut hole must be transparent now
        cx, cy = out.width // 2, out.height // 2
        assert a.getpixel((cx, cy)) == 0
        # the object ring must stay opaque somewhere along the top edge
        assert any(a.getpixel((cx, y)) > 200 for y in range(6, 26))
        # background pixels near the ring must be gone
        assert a.getpixel((2, out.height // 2)) == 0


def test_cut_background_no_holes_flag_keeps_hole():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.png")
        dst = os.path.join(td, "out.png")
        _donut_png(src)
        stats = media.cut_background(src, dst, tol=40, clean_holes=False)
        assert stats["holes_cleaned"] == []
        out = Image.open(dst).convert("RGBA")
        a = out.split()[3]
        assert a.getpixel((out.width // 2, out.height // 2)) > 0


def test_prepare_emoji_normalises_size():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "e.png")
        dst = os.path.join(td, "o.png")
        im = Image.new("RGBA", (60, 30), (0, 0, 0, 0))
        for y in range(5, 25):
            for x in range(10, 50):
                im.putpixel((x, y), (255, 200, 10, 255))
        im.save(src)
        media.prepare_emoji(src, dst)
        out = Image.open(dst)
        assert out.size == (160, 160)
        bbox = out.split()[3].getbbox()
        assert max(bbox[2] - bbox[0], bbox[3] - bbox[1]) >= 145


class _FakeRpcSession(EdvibeSession):
    """Session double: records rpc calls, fakes uploads."""

    def __init__(self):
        self.calls = []
        self.user = {"Id": 1}

    def upload_media_file(self, path, file_type=8):
        self.calls.append(("upload", {"path": path, "file_type": file_type}))
        return {"Id": 777, "Url": "https://media.example/files/Books/abc.png"}

    def rpc(self, controller, method, project, value=None):
        self.calls.append((controller + "." + method, value))
        return {"IsSuccess": True, "Value": True}


def test_set_book_cover_payload():
    s = _FakeRpcSession()
    res = s.set_book_cover(1224167, "cover.png")
    assert res["ImageId"] == 777
    assert s.calls[0] == ("upload", {"path": "cover.png", "file_type": 24})
    name, value = s.calls[1]
    assert name == "BookWsController.ChangeImageIdBook"
    assert value == {"FileId": 777, "FileUrl": "https://media.example/files/Books/abc.png",
                     "EntityId": 1224167}


def test_set_section_icon_payload():
    s = _FakeRpcSession()
    s.set_section_icon(2916675, "sect.png")
    name, value = s.calls[1]
    assert name == "CourseWsController.ChangeImageIdCourse"
    assert value["EntityId"] == 2916675 and value["FileId"] == 777


def test_set_lesson_icon_payload():
    s = _FakeRpcSession()
    s.set_lesson_icon(19843901, "les.png")
    name, value = s.calls[1]
    assert name == "LessonWsController.ChangeImageLesson"
    assert value["EntityId"] == 19843901 and value["FileId"] == 777


def test_apply_icons_manifest_dry_run_offline():
    """CLI apply-icons --dry-run must work without any network/session."""
    from click.testing import CliRunner
    from cli_edvibe.edvibe_cli import cli

    with tempfile.TemporaryDirectory() as td:
        icon = os.path.join(td, "sect_1.png")
        Image.new("RGB", (4, 4), (255, 0, 0)).save(icon)
        manifest = os.path.join(td, "manifest.json")
        json.dump([{"kind": "section", "id": 1, "file": "sect_1.png"},
                   {"kind": "lesson", "id": 2, "file": "les_2.png"}], open(manifest, "w"))
        runner = CliRunner()
        res = runner.invoke(cli, ["book", "apply-icons", "--manifest", manifest, "--dry-run"])
        assert res.exit_code == 0, res.output
        assert "section:1" in res.output
        assert "MISSING" in res.output          # les_2.png does not exist
