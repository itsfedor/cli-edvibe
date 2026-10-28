"""cli-edvibe — Click CLI for edvibe.com materials.

One-shot subcommands plus a REPL when invoked without a subcommand; --json for
machine-readable output. Credentials: --email/--password or EDVIBE_EMAIL /
EDVIBE_PASSWORD env vars, or run `login` for an interactive first-time setup
(password never stored; session token cached in ~/.edvibe/session.json).
"""
import csv
import getpass
import json
import os
import shlex
import sys
import time

import click

from .core.client import SESSION_DEFAULT, EdvibeError, EdvibeSession
from .core import media as media_utils

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _creds(ctx):
    cfg = ctx.obj or {}
    if cfg.get("account") == "school":
        email = cfg.get("email") or os.environ.get("EDVIBE_SCHOOL_EMAIL")
        password = cfg.get("password") or os.environ.get("EDVIBE_SCHOOL_PASSWORD")
        return email, password
    email = cfg.get("email") or os.environ.get("EDVIBE_EMAIL")
    password = cfg.get("password") or os.environ.get("EDVIBE_PASSWORD")
    return email, password


def get_session(ctx, login=True):
    cfg = ctx.obj or {}
    email, password = _creds(ctx)
    session_path = cfg.get("session")
    if not session_path and cfg.get("account") == "school":
        session_path = os.path.join(os.path.dirname(SESSION_DEFAULT), "session_school.json")
    sess = EdvibeSession(email=email, password=password,
                         session_path=session_path)
    if login:
        sess.authenticate()
    return sess


def emit(ctx, data, human=None):
    if (ctx.obj or {}).get("json"):
        click.echo(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        click.echo(human(data) if human else json.dumps(data, ensure_ascii=False))


# ---------------------------------------------------------------------- CLI
@click.group(invoke_without_command=True, context_settings=CONTEXT_SETTINGS)
@click.option("--email", envvar="EDVIBE_EMAIL", help="Edvibe login email")
@click.option("--password", envvar="EDVIBE_PASSWORD", help="Edvibe password")
@click.option("--session", default=None, help="Session cache path (default ~/.edvibe/session.json)")
@click.option("--account", type=click.Choice(["default", "school"]), default="default",
              show_default=True,
              help="Credential set: default (EDVIBE_EMAIL/PASSWORD) or school "
                   "(EDVIBE_SCHOOL_EMAIL/PASSWORD, session_school.json)")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.pass_context
def cli(ctx, email, password, session, account, as_json):
    """CLI-Anything harness for edvibe.com (materials & lessons)."""
    ctx.ensure_object(dict)
    ctx.obj["email"] = email
    ctx.obj["password"] = password
    ctx.obj["session"] = session
    ctx.obj["account"] = account
    ctx.obj["json"] = as_json
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


# ---------------------------------------------------------------- status
@cli.command("whoami")
@click.pass_context
def whoami(ctx):
    """Show the authenticated Edvibe user."""
    sess = get_session(ctx)
    u = sess.user or sess.get_current_user()
    emit(ctx, {"id": u.get("Id"), "name": u.get("FullName"), "email": u.get("Email"),
               "school_id": u.get("SchoolId"), "role": u.get("Role")},
         human=lambda d: f"{d['name']} <{d['email']}> id={d['id']} school={d['school_id']} role={d['role']}")


@cli.command("logout")
@click.pass_context
def logout(ctx):
    """Forget the cached session token."""
    sess = get_session(ctx, login=False)
    sess.logout()
    emit(ctx, {"ok": True}, human=lambda d: "Logged out.")


@cli.command("login")
@click.option("--check", "check_only", is_flag=True, help="Just verify the cached session")
@click.pass_context
def login(ctx, check_only):
    """Log in to Edvibe and cache the session. Run this YOURSELF in your own
    terminal: the password is never stored and never shown to an agent."""
    sess = get_session(ctx, login=False)
    email, password = _creds(ctx)
    if check_only:
        try:
            u = sess.authenticate()
        except EdvibeError as exc:
            emit(ctx, {"ok": False, "error": str(exc)},
                 human=lambda d: f"NOT logged in: {d['error']}")
            raise SystemExit(1)
        emit(ctx, {"ok": True, "id": u.get("Id"), "name": u.get("FullName")},
             human=lambda d: f"Session OK: {d['name']} (id {d['id']})")
        return
    if not (email or password):
        try:
            u = sess.authenticate()
            emit(ctx, {"ok": True, "already": True, "name": u.get("FullName")},
                 human=lambda d: f"Already logged in as {d['name']}. "
                                 f"Run `logout` first to switch accounts.")
            return
        except EdvibeError:
            pass
    else:
        sess.logout()  # explicit creds: force a fresh login
    if not email:
        email = click.prompt("Edvibe email")
    if not password:
        password = getpass.getpass("Edvibe password (hidden, not stored): ")
    sess.email, sess.password = email.strip(), password
    try:
        u = sess.authenticate()
    except EdvibeError as exc:
        emit(ctx, {"ok": False, "error": str(exc)},
             human=lambda d: f"Login failed: {d['error']}")
        raise SystemExit(1)
    emit(ctx, {"ok": True, "id": u.get("Id"), "name": u.get("FullName")},
         human=lambda d: f"Logged in as {d['name']} (id {d['id']}). "
                         f"Session cached in {SESSION_DEFAULT}.")


@cli.command("doctor")
@click.pass_context
def doctor(ctx):
    """Check the local setup: python, dependencies, session, live connection."""
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})

    add("python", sys.version_info >= (3, 9), sys.version.split()[0])
    for mod in ("requests", "websocket", "click"):
        try:
            __import__(mod)
            add(f"dep:{mod}", True, "ok")
        except Exception as exc:
            add(f"dep:{mod}", False, str(exc))
    path = (ctx.obj or {}).get("session") or SESSION_DEFAULT
    add("session-file", os.path.exists(path), path)
    sess = get_session(ctx, login=False)
    try:
        u = sess.authenticate()
        add("login", True, f"{u.get('FullName')} (id {u.get('Id')})")
    except EdvibeError as exc:
        add("login", False, str(exc))
    ok = all(c["ok"] for c in checks)

    def _fmt(d):
        lines = [f"[{'OK' if c['ok'] else 'FAIL'}] {c['check']}: {c['detail']}"
                 for c in d["checks"]]
        if not d["ok"]:
            lines.append("Fix: run `cli-edvibe login` in your own terminal.")
        return "\n".join(lines)

    emit(ctx, {"ok": ok, "checks": checks}, human=_fmt)
    if not ok:
        raise SystemExit(1)


# -------------------------------------------------------------- materials
@cli.group("materials")
@click.pass_context
def materials(ctx):
    """Material (Book) operations."""


@materials.command("list")
@click.option("--take", default=100, show_default=True)
@click.pass_context
def materials_list(ctx, take):
    """List personal materials (folders & books)."""
    sess = get_session(ctx)
    items = sess.list_materials(take=take)
    rows = []
    for it in items:
        if "Folder" in it:
            f = it["Folder"]
            rows.append({"kind": "folder", "id": f.get("Id"), "name": f.get("Name"),
                         "count": f.get("CountMaterials")})
        else:
            b = it["Book"]
            rows.append({"kind": "book", "id": b.get("Id"), "name": b.get("Name"),
                         "school": b.get("IsSchoolBook"), "own": b.get("IsMySelfBook")})
    emit(ctx, {"total": len(rows), "items": rows},
         human=lambda d: "\n".join(
             f"[{r['kind']:6}] {r['id']:>9}  {r['name']}"
             + (f"  ({r['count']} materials)" if r["kind"] == "folder" else "")
             for r in d["items"]))


@materials.command("create")
@click.argument("name")
@click.option("--description", default="")
@click.option("--language", default=1, type=int, help="LanguageId (1 = English)")
@click.pass_context
def materials_create(ctx, name, description, language):
    """Create a new material (Book). Never deletes anything."""
    sess = get_session(ctx)
    book_id = sess.create_material(name, description=description, language_id=language)
    emit(ctx, {"material_id": book_id, "name": name},
         human=lambda d: f"Created material #{d['material_id']}: {d['name']}")


@materials.command("folders")
@click.option("--books", "with_books", is_flag=True,
              help="Also list the books inside each folder")
@click.pass_context
def materials_folders(ctx, with_books):
    """List library folders («папки») with ids and material counts.

    Books inside a folder are hidden from `materials list` - list them with
    `materials folders --books` (or `materials move` / GetSchoolBooks)."""
    sess = get_session(ctx)
    folders = sess.list_folders()
    if with_books:
        for f in folders:
            f["books"] = [{"id": b.get("Id"), "name": b.get("Name")}
                          for b in sess.folder_books(f["id"])]
    emit(ctx, {"total": len(folders), "folders": folders}, human=_fmt_folders)


@materials.command("move")
@click.option("--book", "book_id", required=True, type=int, help="Material (Book) id")
@click.option("--folder", "folder_id", required=True, type=int,
              help="Target folder id (see `materials folders`)")
@click.option("--dry-run", is_flag=True,
              help="Print the plan using the read RPCs only (no write)")
@click.pass_context
def materials_move(ctx, book_id, folder_id, dry_run):
    """Move a material into a library folder (the UI's "move to folder").

    FolderBookWsController.AddBookToFolder {FolderId, BookId}. A book lives in
    ONE folder: it leaves the top level of `materials list` and is listed under
    the folder instead. Read-only with --dry-run."""
    sess = get_session(ctx)
    folder = sess.find_folder(folder_id)
    if not folder:
        raise click.ClickException(f"folder #{folder_id} not found - "
                                   f"run `materials folders` for the ids")
    loc = sess.book_location(book_id)
    book = loc.get("book") or {}
    if not book:
        raise click.ClickException(f"material #{book_id} not found in personal "
                                   f"materials or any folder")
    result = {"book_id": book_id, "name": book.get("Name"),
              "from_folder": loc.get("folder_id") or 0,
              "from_folder_name": loc.get("folder_name"),
              "to_folder": folder["id"], "to_folder_name": folder["name"],
              "already_there": (loc.get("folder_id") or 0) == folder["id"],
              "test_material": bool((book.get("Name") or "").startswith("CLI-HARNESS"))}
    if dry_run:
        result["dry_run"] = True
        emit(ctx, result, human=_fmt_move)
        return
    result["ok"] = sess.move_book_to_folder(book_id, folder["id"])
    after = sess.book_location(book_id)
    result["now_folder"] = after.get("folder_id") or 0
    result["verified"] = result["now_folder"] == folder["id"]
    emit(ctx, result, human=_fmt_move)


# ----------------------------------------------------------------- lesson
@cli.group("lesson")
@click.pass_context
def lesson(ctx):
    """Lesson (unit inside a material) operations."""


@lesson.command("add")
@click.option("--material", "material_id", required=True, type=int)
@click.option("--name", required=True)
@click.pass_context
def lesson_add(ctx, material_id, name):
    """Add a lesson (unit) to a material."""
    sess = get_session(ctx)
    course_id = sess.get_course_id(material_id)
    lesson_id, section_id = sess.create_lesson(material_id, course_id, name)
    emit(ctx, {"material_id": material_id, "course_id": course_id,
               "lesson_id": lesson_id, "section_id": section_id, "name": name},
         human=lambda d: f"Added lesson #{d['lesson_id']} '{d['name']}' "
                         f"(section #{d['section_id']}) to material #{d['material_id']}")


@lesson.command("show")
@click.option("--lesson", "lesson_id", required=True, type=int)
@click.pass_context
def lesson_show(ctx, lesson_id):
    """Show a lesson with its sections and exercises."""
    sess = get_session(ctx)
    les = sess.get_lesson(lesson_id)
    sections = list(les.get("Sections") or [])
    hw = les.get("HomeworkSection")
    if isinstance(hw, dict) and hw.get("Id"):
        sections.append(hw)
    out = {"lesson_id": lesson_id, "name": les.get("Name"), "number": les.get("Number"),
           "sections": []}
    for sec in sections:
        exercises = sess.load_exercises(sec.get("Id"), lesson_id)
        out["sections"].append({"section_id": sec.get("Id"), "name": sec.get("Name"),
                                "exercises": [{"id": e.get("Id"), "type": e.get("Type"),
                                               "name": (e.get("Name") or "")[:60]}
                                              for e in exercises]})
    emit(ctx, out, human=lambda d: _fmt_lesson(d))


@lesson.command("dump")
@click.option("--lesson", "lesson_id", required=True, type=int)
@click.option("--out", "out_path", default=None, type=click.Path(dir_okay=False),
              help="Write the full raw JSON (all exercise views) to this path")
@click.option("--section", "section_sel", default=None,
              help="Dump only this section (name or section id)")
@click.pass_context
def lesson_dump_cmd(ctx, lesson_id, out_path, section_sel):
    """Read-only dump of a lesson for offline review/backup before rebuilds.

    Prints sections (id, name, item counts) + every exercise in compact form;
    --out writes EVERY exercise's full raw JSON, hidden notes and their html
    included. Nothing is modified (no write RPCs)."""
    from .core import lesson_dump as dump_mod
    sess = get_session(ctx)
    try:
        data = dump_mod.dump_lesson(sess, lesson_id, section=section_sel)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        data["out"] = os.path.abspath(out_path)
    emit(ctx, data, human=lambda d: dump_mod.summary_lines(d, d.get("out")))


@lesson.command("build")
@click.option("--file", "spec_file", required=True, type=click.Path(exists=True),
              help="Lesson spec JSON (see teacher-kit references/lesson-spec.md)")
@click.option("--lesson", "lesson_id", type=int, default=None,
              help="Append into an existing lesson id")
@click.option("--material", "material_id", type=int, default=None,
              help="Create a new lesson inside this material (Book) id")
@click.option("--name", default=None, help="Lesson name (for a new lesson)")
@click.option("--description", default=None, help="Lesson description")
@click.option("--dry-run", is_flag=True, help="Validate and show the plan only")
@click.pass_context
def lesson_build(ctx, spec_file, lesson_id, material_id, name, description, dry_run):
    """Build a full lesson (sections + exercises) from a JSON spec. Additive only:
    never edits or deletes anything that already exists."""
    from .core import lesson_spec
    with open(spec_file, "r", encoding="utf-8") as f:
        spec = json.load(f)
    if dry_run:
        try:
            res = lesson_spec.plan(spec)
        except ValueError as exc:
            raise click.ClickException(str(exc))
        emit(ctx, res, human=_fmt_plan)
        return
    if not lesson_id and not material_id:
        raise click.UsageError("pass --material (new lesson) or --lesson (existing)")
    sess = get_session(ctx)
    if name is None:
        name = spec.get("lesson_name")
    if description is None:
        description = spec.get("description")
    try:
        res = lesson_spec.build_lesson(sess, spec, material_id=material_id,
                                       lesson_id=lesson_id, name=name,
                                       description=description)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    emit(ctx, res, human=_fmt_build)


def _fmt_plan(d):
    lines = [f"PLAN: {d.get('lesson_name') or '(existing lesson)'} — "
             f"{d['total_exercises']} exercises / {len(d['sections'])} sections"]
    for s in d["sections"]:
        lines.append(f"  {s['name']} ({len(s['exercises'])}):")
        for e in s["exercises"]:
            lines.append(f"    - {e['type']}: {(e['name'] or '')[:60]}")
    return "\n".join(lines)


def _fmt_build(d):
    total = sum(len(s["exercise_ids"]) for s in d["sections"])
    lines = [f"Lesson #{d['lesson_id']}" + (" (new)" if d["created"] else ""),
             f"Built {total} exercises in {len(d['sections'])} sections:"]
    for s in d["sections"]:
        lines.append(f"  '{s['name']}' #{s['section_id']} — "
                     f"{len(s['exercise_ids'])} exercises")
    if d.get("description_error"):
        lines.append(f"  description update failed: {d['description_error']}")
    return "\n".join(lines)


def _fmt_lesson(d):
    lines = [f"Lesson #{d['lesson_id']}: {d['name']}"]
    for sec in d["sections"]:
        lines.append(f"  Section #{sec['section_id']} '{sec['name']}' "
                     f"({len(sec['exercises'])} exercises)")
        for e in sec["exercises"]:
            lines.append(f"     - #{e['id']} type={e['type']} {e['name']}")
    return "\n".join(lines)


def _fmt_folders(d):
    lines = []
    for f in d["folders"]:
        lines.append(f"[{f['id']:>6}] {f['name']}  ({f['count']} materials)")
        for b in f.get("books") or []:
            lines.append(f"           - #{b['id']} {b['name']}")
    if not lines:
        lines.append("(no folders)")
    return "\n".join(lines)


def _fmt_move(d):
    src = (f"#{d['from_folder']} {d['from_folder_name']!r}" if d.get("from_folder")
           else "top level (no folder)")
    dst = f"#{d['to_folder']} {d['to_folder_name']!r}"
    warn = ("" if d.get("test_material", True)
            else "\n  ! not a CLI-HARNESS-* test material - re-filing a real material")
    if d.get("dry_run"):
        return (f"DRY-RUN: move #{d['book_id']} {d['name']!r} -> folder {dst}\n"
                f"  from: {src}\n"
                f"  {'already in this folder' if d.get('already_there') else 'plan only'}"
                f" (no write RPC was called)" + warn)
    return (f"Moved #{d['book_id']} {d['name']!r} -> folder {dst}\n"
            f"  was: {src} | rpc ok={d['ok']} | verified={d['verified']} "
            f"(now folder #{d['now_folder']})" + warn)


# ---------------------------------------------------------------- content
@cli.group("content")
@click.pass_context
def content(ctx):
    """Exercise/content operations."""


@content.command("add-note")
@click.option("--lesson", "lesson_id", required=True, type=int)
@click.option("--section", "section_id", required=True, type=int)
@click.option("--text", default=None, help="Raw HTML for the note")
@click.option("--file", "html_file", default=None, help="HTML file (whole content)")
@click.option("--name", default="", help="Optional exercise title")
@click.pass_context
def content_add_note(ctx, lesson_id, section_id, text, html_file, name):
    """Add a Note content block (Type 22) with HTML to a lesson section."""
    if text is None and html_file is None:
        raise click.UsageError("Provide --text or --file")
    if html_file:
        with open(html_file, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    sess = get_session(ctx)
    saved = sess.add_note(lesson_id, section_id, text, name=name)
    eid = saved.get("Id") if isinstance(saved, dict) else saved
    emit(ctx, {"exercise_id": eid, "lesson_id": lesson_id, "section_id": section_id},
         human=lambda d: f"Added note exercise #{d['exercise_id']}")


@content.command("upload-image")
@click.argument("file", type=click.Path(exists=True))
@click.option("--type", "file_type", default=8, show_default=True,
              help="MediaFile type (8 = lesson exercise images)")
@click.pass_context
def content_upload_image(ctx, file, file_type):
    """Upload a local image/video to the account media storage; prints its URL
    (use the URL in inline <!--IMG:URL;...--> blocks)."""
    sess = get_session(ctx)
    res = sess.upload_media_file(file, file_type=file_type)
    emit(ctx, {"url": res.get("Url"), "id": res.get("Id"), "key": res.get("Key")},
         human=lambda d: d["url"])


@content.command("upload-audio")
@click.argument("file", type=click.Path(exists=True))
@click.pass_context
def content_upload_audio(ctx, file):
    """Upload an audio file (mp3) to media storage (type 10). Use the id with
    `content attach-audio` / the url in an `audio` lesson-spec exercise."""
    sess = get_session(ctx)
    res = sess.upload_media_file(file, file_type=10)
    emit(ctx, {"url": res.get("Url"), "id": res.get("Id"), "key": res.get("Key")},
         human=lambda d: f"{d['url']}\nid: {d['id']}")


@content.command("attach-audio")
@click.option("--exercise", "exercise_id", required=True, type=int,
              help="Audio exercise (Type 4) id")
@click.argument("files", nargs=-1, type=click.Path(exists=True), required=True)
@click.pass_context
def content_attach_audio(ctx, exercise_id, files):
    """Upload audio file(s) and bind them to an Audio exercise (type 4)."""
    sess = get_session(ctx)
    uploaded = sess.attach_audio_files(exercise_id, list(files))
    emit(ctx, {"exercise_id": exercise_id,
               "files": [{"id": u.get("Id"), "url": u.get("Url")} for u in uploaded]},
         human=lambda d: f"bound {len(d['files'])} file(s) to exercise "
                         f"#{d['exercise_id']}")


@content.command("show")
@click.option("--lesson", "lesson_id", required=True, type=int)
@click.option("--section", "section_id", required=True, type=int)
@click.pass_context
def content_show(ctx, lesson_id, section_id):
    """List exercises in a lesson section."""
    sess = get_session(ctx)
    items = sess.load_exercises(section_id, lesson_id)
    emit(ctx, {"exercises": items},
         human=lambda d: "\n".join(
             f"#{e.get('Id')} type={e.get('Type')} "
             f"name={(e.get('Name') or '')[:70]}" for e in d["exercises"]))


# ------------------------------------------------------------------- book
@cli.group("book")
@click.pass_context
def book(ctx):
    """Book branding: cover image, section & lesson icons."""


@book.command("cover")
@click.option("--book", "book_id", required=True, type=int, help="Book id")
@click.argument("file", type=click.Path(exists=True))
@click.pass_context
def book_cover(ctx, book_id, file):
    """Set the book cover image (UI: Edit material -> Cover -> Upload)."""
    sess = get_session(ctx)
    res = sess.set_book_cover(book_id, file)
    emit(ctx, {"book_id": book_id, **res},
         human=lambda d: f"cover set: {d['Image']}")


@book.command("section-icon")
@click.option("--section", "course_id", required=True, type=int,
              help="Section = course id (see `book sections`)")
@click.argument("file", type=click.Path(exists=True))
@click.pass_context
def book_section_icon(ctx, course_id, file):
    """Set a section icon (gradient/emoji avatar, 64px round in the UI)."""
    sess = get_session(ctx)
    res = sess.set_section_icon(course_id, file)
    emit(ctx, {"section_id": course_id, **res},
         human=lambda d: f"section icon set: {d['Image']}")


@book.command("lesson-icon")
@click.option("--lesson", "lesson_id", required=True, type=int)
@click.argument("file", type=click.Path(exists=True))
@click.pass_context
def book_lesson_icon(ctx, lesson_id, file):
    """Set a lesson icon (40px round in book lists; e.g. gradient + number)."""
    sess = get_session(ctx)
    res = sess.set_lesson_icon(lesson_id, file)
    emit(ctx, {"lesson_id": lesson_id, **res},
         human=lambda d: f"lesson icon set: {d['Image']}")


@book.command("apply-icons")
@click.option("--manifest", "manifest_file", required=True, type=click.Path(exists=True),
              help="JSON list [{kind: section|lesson, id, file}] (manifest.json)")
@click.option("--dry-run", is_flag=True, help="Only print the plan")
@click.pass_context
def book_apply_icons(ctx, manifest_file, dry_run):
    """Upload + apply icons for many sections/lessons in one go.

    File paths inside the manifest are resolved relative to its directory.
    """
    base = os.path.dirname(os.path.abspath(manifest_file))
    data = json.load(open(manifest_file, encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    plan = []
    for it in items:
        path = it["file"]
        if not os.path.isabs(path):
            path = os.path.join(base, path)
        plan.append({"kind": it["kind"], "id": int(it["id"]), "file": path,
                     "exists": os.path.exists(path)})
    missing = [p for p in plan if not p["exists"]]
    if dry_run:
        emit(ctx, {"plan": plan, "missing": missing},
             human=lambda d: "\n".join(f"{p['kind']}:{p['id']} <- {p['file']}"
                                       + ("" if p["exists"] else "  [MISSING]") for p in d["plan"]))
        return
    if missing:
        raise click.UsageError(f"{len(missing)} icon file(s) missing, e.g. {missing[0]['file']}")
    sess = get_session(ctx)
    done, failed = [], []
    for i, p in enumerate(plan, 1):
        try:
            if p["kind"] == "section":
                sess.set_section_icon(p["id"], p["file"])
            elif p["kind"] == "lesson":
                sess.set_lesson_icon(p["id"], p["file"])
            else:
                raise EdvibeError(f"unknown kind {p['kind']!r}")
            done.append(p)
            click.echo(f"  [{i}/{len(plan)}] ok {p['kind']}:{p['id']}", err=True)
        except EdvibeError as exc:
            failed.append({**p, "error": str(exc)})
            click.echo(f"  [{i}/{len(plan)}] FAIL {p['kind']}:{p['id']} {exc}", err=True)
    emit(ctx, {"applied": len(done), "failed": failed, "total": len(plan)},
         human=lambda d: f"applied {d['applied']}/{d['total']}"
                         + (f", {len(d['failed'])} failed" if d["failed"] else ""))


@book.command("gen-icons")
@click.option("--spec", "spec_file", required=True, type=click.Path(exists=True),
              help="JSON: {cell, cols, items:[{kind,id,gradient,emoji|number}]}")
@click.option("--out", "outdir", required=True, type=click.Path(),
              help="Output dir (PNGs + manifest.json)")
@click.pass_context
def book_gen_icons(ctx, spec_file, outdir):
    """Render section/lesson icon tiles from a JSON spec (needs playwright)."""
    spec = json.load(open(spec_file, encoding="utf-8"))
    try:
        manifest = media_utils.generate_icons(spec, outdir)
    except RuntimeError as exc:
        raise click.ClickException(str(exc))
    emit(ctx, {"out": outdir, "count": len(manifest), "manifest": manifest},
         human=lambda d: f"rendered {d['count']} icons into {d['out']} (+manifest.json)")


@book.command("cutout")
@click.argument("src", type=click.Path(exists=True))
@click.argument("dst", type=click.Path())
@click.option("--tol", default=40, show_default=True, help="Background colour tolerance")
@click.option("--no-holes", is_flag=True, help="Do not clean enclosed background blobs")
@click.pass_context
def book_cutout(ctx, src, dst, tol, no_holes):
    """Cut a flat-colour background off a PNG (character cut-out for covers).

    Also removes enclosed background-coloured blobs (e.g. the counter of an
    'A'), which would otherwise show as light patches on a dark cover.
    """
    stats = media_utils.cut_background(src, dst, tol=tol, clean_holes=not no_holes)
    emit(ctx, {"src": src, "dst": dst, **stats},
         human=lambda d: f"cut {d['src']} -> {d['dst']}: removed {d['removed_pct']}% bg, "
                         f"holes cleaned: {d['holes_cleaned']}, size {d['size']}")


@book.command("sections")
@click.option("--book", "book_id", required=True, type=int)
@click.pass_context
def book_sections(ctx, book_id):
    """List a book's sections (courses) with their lessons (ids/numbers/names)."""
    sess = get_session(ctx)
    courses = sess.rpc("CourseWsController", "GetBookCourses", "Books",
                       {"BookId": book_id, "TeacherId": sess.user.get("Id"),
                        "Domain": "edvibe.com"}).get("Value") or []
    courses.sort(key=lambda c: c.get("OrderIndex", 0))
    out = []
    for c in courses:
        lessons = sess.rpc("LessonWsController", "GetCourseLessons", "Books",
                           {"CourseId": c["Id"]}).get("Value") or []
        lessons.sort(key=lambda l: l.get("Number", 0))
        out.append({"course_id": c["Id"], "name": c.get("Name"),
                    "order": c.get("OrderIndex"),
                    "lessons": [{"id": l["Id"], "number": l.get("Number"),
                                 "name": l.get("Name"), "image": l.get("ImageUrl")}
                                for l in lessons]})
    emit(ctx, {"book_id": book_id, "sections": out},
         human=lambda d: "\n".join(
             f"{s['order']} {s['course_id']} {s['name']} ({len(s['lessons'])} lessons)"
             for s in d["sections"]))


# ----------------------------------------------------------- test-english
@cli.group("test-english")
@click.pass_context
def test_english(ctx):
    """Transfer test-english.com lessons into Edvibe books (scrape + build)."""


def _parse_pages(value):
    """'/' -> [1], '/,/2/' or '1,2' -> [1,2]; '' -> () (no exercise pages -
    rebuild just the Explanation)"""
    if value == "":
        return ()
    if not value:
        return (1, 2)
    out = []
    for part in value.split(","):
        part = part.strip()
        if not part or part == "/":
            out.append(1)
        else:
            out.append(int(part.strip("/").split("/")[-1]))
    return tuple(sorted(set(out)))


@test_english.command("fetch")
@click.argument("url")
@click.option("--out", default=None, help="Write scraped data JSON here")
@click.option("--pages", default=None, help="Exercise pages, e.g. '/,/2/' (default all)")
@click.option("--imgdir", default=None, help="Download the explanation images here")
@click.option("--cache-dir", "cache_dir", default=None,
              help="Reuse/save raw page html + submit responses here (fast re-runs)")
@click.pass_context
def test_english_fetch(ctx, url, out, pages, imgdir, cache_dir):
    """Scrape a test-english lesson (questions, answers, explanations, images)."""
    from .core import test_english as te
    data = te.fetch_lesson(url, pages=_parse_pages(pages) if pages else None,
                           imgdir=imgdir, out=out, cache_dir=cache_dir)
    summary = {"source_url": data["source_url"], "title": data.get("lesson_title"),
               "pages": [{"page": p["page"], "label": p["label"],
                          "questions": len(p["questions"]), "url": p["url"]}
                         for p in data["pages"]],
               "images": data["images"], "out": out}

    def human(d):
        lines = [f"{d['title']} — {d['source_url']}"]
        for p in d["pages"]:
            lines.append(f"  page {p['page']}: {p['label']} ({p['questions']} qs)")
        lines.append(f"  images: {len(d['images'])}")
        if d.get("out"):
            lines.append(f"  saved to {d['out']}")
        return "\n".join(lines)

    emit(ctx, summary, human=human)


@test_english.command("import")
@click.argument("url")
@click.option("--book", default=None,
              help="Target book name or id (default: 'test-english <LEVEL>' from the URL)")
@click.option("--section", default="grammar", show_default=True,
              help="Book section (Раздел) to keep the lesson in")
@click.option("--pages", default="/,/2/", show_default=True,
              help="Which exercise pages to transfer")
@click.option("--lesson-name", default=None, help="Override the lesson name")
@click.option("--lesson", "lesson_id", type=int, default=None,
              help="Append into an existing lesson instead of creating a new one")
@click.option("--data", "data_file", default=None, type=click.Path(exists=True),
              help="Use an already-scraped data.json (skips the network)")
@click.option("--cache-dir", "cache_dir", default=None,
              help="Reuse/save raw page html + submit responses here (fast re-runs)")
@click.option("--replace-sections", "replace_sections", default=None,
              help="Comma-separated section names to wipe before importing "
                   "(e.g. 'Explanation,Exercises' - idempotent rebuilds)")
@click.option("--explanation", "explanation", default="single",
              type=click.Choice(["single", "blocks"]), show_default=True,
              help="Explanation layout: one text exercise with inline "
                   "images/links, or the older chart/text blocks")
@click.option("--image-map", "image_map", default=None, type=click.Path(exists=True),
              help="JSON {source_url: {url,w,h}} - swap inline chart images "
                   "for redesigned/self-hosted versions on rebuild")
@click.option("--description", "description", default=None,
              help="Lesson description html (keyword-rich, no source url)")
@click.option("--dry-run", is_flag=True, help="Scrape + validate, no writes")
@click.pass_context
def test_english_import_cmd(ctx, url, book, section, pages, lesson_name, lesson_id,
                            data_file, cache_dir, replace_sections, explanation,
                            image_map, dry_run, description):
    """One-shot transfer: scrape test-english.com lesson -> Edvibe lesson
    (Explanation + Exercises sections + hidden teacher answer keys)."""
    from .core import test_english as te
    pgs = _parse_pages(pages)
    data = json.load(open(data_file, encoding="utf-8")) if data_file else None
    imap = json.load(open(image_map, encoding="utf-8")) if image_map else None
    if dry_run:
        if data is None:
            data = te.fetch_lesson(url, pages=pgs, cache_dir=cache_dir)
        spec = te.build_spec(data, pgs, explanation=explanation)
        if imap:
            te._apply_image_map(spec, imap)
        if lesson_name:
            spec["lesson_name"] = lesson_name
        from .core import lesson_spec
        try:
            res = lesson_spec.plan(spec)
        except ValueError as exc:
            raise click.ClickException(str(exc))
        res["source"] = data["source_url"]
        emit(ctx, res, human=_fmt_plan)
        return
    sess = get_session(ctx)
    rsec = [s.strip() for s in replace_sections.split(",") if s.strip()] \
        if replace_sections else None
    try:
        res = te.import_lesson(sess, url, book=book, section=section, pages=pgs,
                               lesson_name=lesson_name, lesson_id=lesson_id,
                               data=data, cache_dir=cache_dir,
                               replace_sections=rsec,
                               explanation=explanation, image_map=imap,
                               description=description,
                               log=lambda m: click.echo(m, err=True))
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc))
    emit(ctx, res, human=lambda d: (
        f"lesson {d['lesson_id']} in book {d['book_id']} "
        f"(section course {d['section_course_id']}) — "
        f"{sum(len(s['exercise_ids']) for s in d['sections'])} exercises "
        f"in {len(d['sections'])} sections"))


# --------------------------------------------------------------- students
@cli.group("students")
@click.pass_context
def students(ctx):
    """School students (pupils) operations."""


@students.command("list")
@click.option("--search", default=None, help="Search term (student name)")
@click.option("--take", default=25, show_default=True)
@click.pass_context
def students_list(ctx, search, take):
    """List school students (cabinet/school/students)."""
    sess = get_session(ctx)
    val = sess.list_pupils(search=search, take=take)
    pupils = val.get("Pupils") or []
    rows = [{"id": p.get("Id"), "name": p.get("FullName"),
             "email": p.get("Email"), "active": p.get("IsActive")}
            for p in pupils]
    emit(ctx, {"total": val.get("TotalCount"), "count": val.get("Count"),
               "shown": len(rows), "items": rows},
         human=lambda d: "\n".join(
             f"{r['id']:>9}  {r['name']}  <{r['email']}>" for r in d["items"])
         + f"\n({d['shown']} shown / {d.get('total')} total)")


@students.command("show")
@click.argument("pupil_id", type=int)
@click.pass_context
def students_show(ctx, pupil_id):
    """Show a student profile and their classes."""
    sess = get_session(ctx)
    d = sess.get_pupil_detail(pupil_id)
    profile = d.get("Profile") or {}
    groups = d.get("Groups") or []
    out = {"pupil_id": pupil_id, "name": profile.get("Name"),
           "email": profile.get("Email"), "timezone": profile.get("Timezone"),
           "groups": [{"class_id": g.get("GroupId"), "name": g.get("Name"),
                       "lessons_count": g.get("LessonsCount")}
                      for g in groups]}
    emit(ctx, out, human=lambda d: (
        f"{d['name']} <{d['email']}> tz={d['timezone']}\n"
        + "\n".join(f"  class #{g['class_id']} '{g['name']}' "
                    f"({g['lessons_count']} lessons)" for g in d["groups"])))


# ----------------------------------------------------------------- school
@cli.group("school")
@click.pass_context
def school(ctx):
    """School-level analytics: roster, classes, marathons, statistics."""


@school.command("overview")
@click.pass_context
def school_overview(ctx):
    """One-screen summary of the school account."""
    from .core import school as sch

    sess = get_session(ctx)
    pupils = sch.list_pupils(sess)
    classes = sch.list_classes(sess)
    groups = sch.list_groups(sess)
    mar = sch.list_marathons(sess)
    tracks = [m for m in mar["Marathons"] if (m.get("CountLesson") or 0)]
    out = {
        "school_id": (sess.user or {}).get("SchoolId"),
        "pupils": pupils.get("TotalCount") or len(pupils["Pupils"]),
        "classes": len(classes),
        "group_classes": len(groups),
        "marathons": len(mar["Marathons"]),
        "marathons_with_lessons": len(tracks),
        "courses": [{"id": m.get("Id"), "name": m.get("Name"),
                     "lessons": m.get("CountLesson"),
                     "students": m.get("StudentsCount")}
                    for m in sorted(tracks, key=lambda x: -(x.get("CountLesson") or 0))],
    }

    def _fmt(d):
        lines = [f"school #{d['school_id']}: {d['pupils']} pupils, "
                 f"{d['classes']} classes ({d['group_classes']} group), "
                 f"{d['marathons']} marathons",
                 "courses (marathons) by size:"]
        for c in d["courses"]:
            lines.append(f"  #{c['id']:<8} {c['name'][:52]:<52} {c['lessons']:>3} lessons"
                         f"  students={c['students']}")
        return "\n".join(lines)

    emit(ctx, out, human=_fmt)


@school.command("pupils")
@click.option("--type", "list_type", default=0, show_default=True,
              help="GetListType filter (0=all, 1..4 = UI tabs)")
@click.option("--out", default=None, help="Write the roster to a CSV file")
@click.pass_context
def school_pupils(ctx, list_type, out):
    """Full pupil roster (emails, classes, activity flags)."""
    from .core import school as sch

    sess = get_session(ctx)
    val = sch.list_pupils(sess, list_type=list_type)
    pupils = val.get("Pupils") or []
    if out:
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "name", "email", "count_lessons", "count_marathons",
                        "is_active", "date_added", "classes"])
            for p in pupils:
                w.writerow([p.get("Id"), p.get("FullName"), p.get("Email"),
                            p.get("CountLessons"), p.get("CountMarathons"),
                            p.get("IsActive"), p.get("DateAdded"),
                            ";".join(str(g.get("Name")) for g in (p.get("Groups") or []))])
    rows = [{"id": p.get("Id"), "name": p.get("FullName"), "email": p.get("Email"),
             "lessons": p.get("CountLessons"), "marathons": p.get("CountMarathons"),
             "active": p.get("IsActive")} for p in pupils]
    emit(ctx, {"total": val.get("TotalCount"), "items": rows, "csv": out},
         human=lambda d: "\n".join(
             f"{r['id']:>9}  {r['name'] or '':<24} <{r['email'] or ''}>  "
             f"lessons={r['lessons']} marathons={r['marathons']}" for r in d["items"])
         + f"\n({len(rows)} pupils)" + (f"\ncsv: {d['csv']}" if d.get("csv") else ""))


@school.command("classes")
@click.pass_context
def school_classes(ctx):
    """Classes and group classes with pupil counts."""
    from .core import school as sch

    sess = get_session(ctx)
    classes = sch.list_classes(sess)
    groups = sch.list_groups(sess)
    rows = [{"id": c.get("GroupId"), "name": c.get("Name"),
             "kind": "group" if c.get("IsGroup") else "individual",
             "pupils": len(c.get("Pupils") or [])} for c in classes]
    emit(ctx, {"classes": rows, "group_classes": len(groups)},
         human=lambda d: "\n".join(
             f"{r['id']:>9}  {r['kind']:<10} pupils={r['pupils']}  {r['name']}"
             for r in d["classes"]) + f"\n({len(d['classes'])} classes)")


@school.command("marathons")
@click.pass_context
def school_marathons(ctx):
    """Courses stored as marathons (with lesson counts)."""
    from .core import school as sch

    sess = get_session(ctx)
    mar = sch.list_marathons(sess)
    rows = [{"id": m.get("Id"), "name": m.get("Name"),
             "lessons": m.get("CountLesson"), "students": m.get("StudentsCount")}
            for m in mar["Marathons"]]
    emit(ctx, {"marathons": rows, "folders": mar["Folders"]},
         human=lambda d: "\n".join(
             f"{r['id']:>8}  {r['lessons']:>3} lessons  students={r['students']:<3} {r['name']}"
             for r in d["marathons"]))


@school.command("stats")
@click.option("--school-wide", "scope", flag_value="school",
              help="Whole-school statistics export")
@click.option("--class-id", "class_id", type=int, default=None, help="Class statistics export")
@click.option("--marathon-id", "marathon_id", type=int, default=None,
              help="Marathon/course statistics export")
@click.option("--out", default=None, help="Write the raw CSV payload to this file")
@click.pass_context
def school_stats(ctx, scope, class_id, marathon_id, out):
    """Download the server's statistics export (the 'who did what' table)."""
    from .core import school as sch

    sess = get_session(ctx)
    if marathon_id:
        data = sch.marathon_statistics(sess, marathon_id)
    elif class_id:
        data = sch.class_statistics(sess, class_id)
    else:
        data = sch.school_statistics(sess)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(data["payload"] + "\n")
    emit(ctx, {"name": data["name"], "rows": data["rows"], "csv": out},
         human=lambda d: (d["name"] + "\n" + "\n".join(
             "  " + "; ".join(f"{k}={v}" for k, v in r["raw"].items())
             for r in d["rows"]) + f"\n({len(d['rows'])} rows)")
         + (f"\ncsv: {d['csv']}" if d.get("csv") else ""))


@school.command("course")
@click.option("--marathon-id", "marathon_id", required=True, type=int,
              help="Marathon (course) id from `school marathons`")
@click.option("--curve", is_flag=True, help="Print the per-lesson survival curve")
@click.option("--students", is_flag=True, help="Print the per-pupil progress table")
@click.option("--out", default=None, help="Write per-pupil progress to a CSV file")
@click.pass_context
def school_course(ctx, marathon_id, curve, students, out):
    """Per-pupil completion for a course (works without statistics enabled)."""
    from .core import school as sch

    sess = get_session(ctx)
    pupils = sch.marathon_pupils(sess, marathon_id)
    metrics, rows = sch.course_metrics(pupils)
    out_data = {"marathon_id": marathon_id, "metrics": metrics}
    if curve:
        out_data["curve"] = sch.course_curve(rows, metrics["lessons_total"])
    if students:
        out_data["students"] = sorted(rows, key=lambda r: -r["completed"])
    if out:
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["pupil_id", "name", "email", "completed", "lessons_total",
                        "pending", "rework", "activated", "archived", "started"])
            for r in sorted(rows, key=lambda x: -(x["completed"] or 0)):
                w.writerow([r["pupil_id"], r["name"], r["email"], r["completed"],
                            r["lessons_total"], r["pending"], r["rework"],
                            r["activated"], r["archived"], r["started"]])
        out_data["csv"] = out

    def _fmt(d):
        m = d["metrics"]
        lines = [f"course #{d['marathon_id']}: {m['enrolled']} enrolled, "
                 f"{m['lessons_total']} lessons",
                 f"  started (>=1 lesson): {m['started']} ({m['started_pct']}%)",
                 f"  reached halfway     : {m['halfway']} ({m['halfway_pct']}%)",
                 f"  finished the course : {m['finished']} ({m['finished_pct']}%)",
                 f"  lessons completed   : avg {m['completed_avg']}, "
                 f"median {m['completed_median']}, max {m['completed_max']}",
                 f"  average progress    : {m['avg_progress_pct']}% of the course",
                 f"  pending review      : {m['pending_review']}",
                 f"  activated / archived: {m['activated']} / {m['archived']}"]
        if d.get("curve"):
            lines.append("  survival (lesson -> reached):")
            for point in d["curve"]:
                bar = "#" * max(1, int(point["pct"] / 4)) if point["pct"] else ""
                lines.append(f"    {point['lesson']:>3}. {point['reached']:>4} "
                             f"({point['pct']:>5}%) {bar}")
        if d.get("students"):
            lines.append("  per pupil:")
            for r in d["students"]:
                lines.append(f"    {r['pupil_id']:>8}  {r['completed']:>3}/"
                             f"{r['lessons_total']:<3} {r['name'] or '':<24} "
                             f"<{r['email'] or ''}>")
        if d.get("csv"):
            lines.append(f"  csv: {d['csv']}")
        return "\n".join(lines)

    emit(ctx, out_data, human=_fmt)


@school.command("dropoff")
@click.option("--marathon-id", "marathon_id", required=True, type=int,
              help="Marathon (course) id from `school marathons`")
@click.option("--limit", default=None, type=int, help="Sample only the first N pupils")
@click.option("--out", default=None, help="Write the per-lesson table to CSV")
@click.pass_context
def school_dropoff(ctx, marathon_id, limit, out):
    """Exact lesson-by-lesson drop-off (one RPC per pupil - the full sweep)."""
    from .core import school as sch

    os.environ.setdefault("EDVIBE_PACE_MIN", "0.3")
    os.environ.setdefault("EDVIBE_PACE_MAX", "0.6")
    os.environ.setdefault("EDVIBE_PACE_CAP", "2000")
    sess = get_session(ctx)
    pupils = sch.marathon_pupils(sess, marathon_id)
    if limit:
        pupils = pupils[:limit]

    def _progress(done, total):
        if done % 10 == 0 or done == total:
            click.echo(f"  ... {done}/{total}", err=True)

    data = sch.course_dropoff(sess, marathon_id, pupils=pupils, on_progress=_progress)
    data["marathon_id"] = marathon_id
    if out:
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["index", "lesson", "lesson_id", "reached", "pct",
                        "opened", "opened_pct"])
            for r in data["lessons"]:
                w.writerow([r["index"], r["name"], r["lesson_id"], r["reached"],
                            r["pct"], r["opened"], r["opened_pct"]])
        data["csv"] = out

    def _fmt(d):
        lines = [f"course #{d['marathon_id']} drop-off: {d['enrolled']} pupils, "
                 f"{d['never_started']} never completed a lesson"]
        prev = None
        for r in d["lessons"]:
            if prev is None:
                delta = ""
            elif prev >= r["reached"]:
                delta = f"  (-{prev - r['reached']})"
            else:
                delta = f"  (+{r['reached'] - prev})"
            lines.append(f"  {r['index'] + 1:>2}. {str(r['name'])[:32]:<32} "
                         f"{r['reached']:>4}/{d['enrolled']} ({r['pct']:>5}%)"
                         f"{delta}")
            prev = r["reached"]
        lines.append("  stopped after lesson: " + ", ".join(
            f"{'none' if s['after_lesson'] < 0 else s['after_lesson'] + 1}={s['pupils']}"
            for s in d["stops"]))
        if d.get("csv"):
            lines.append(f"  csv: {d['csv']}")
        return "\n".join(lines)

    emit(ctx, data, human=_fmt)


@school.command("retention")
@click.option("--class-id", "class_id", type=int, default=None)
@click.option("--marathon-id", "marathon_id", type=int, default=None)
@click.option("--lessons", "total_lessons", type=int, default=None,
              help="Course length (default: marathon CountLesson)")
@click.option("--curve", is_flag=True, help="Print the per-lesson survival curve")
@click.pass_context
def school_retention(ctx, class_id, marathon_id, total_lessons, curve):
    """Completion / retention metrics for a class or a course."""
    from .core import school as sch

    if marathon_id:
        # Marathons have real per-pupil progress - use it instead of the
        # statistics export (which is empty unless statistics are configured).
        return ctx.invoke(school_course, marathon_id=marathon_id, curve=curve,
                          students=False, out=None)

    sess = get_session(ctx)
    if class_id:
        data = sch.class_statistics(sess, class_id)
        cls = next((c for c in sch.list_classes(sess)
                    if c.get("GroupId") == class_id), {})
        roster = cls.get("Pupils") or []
    else:
        data = sch.school_statistics(sess)
        roster = sch.list_pupils(sess)["Pupils"]
    metrics = sch.summarize(data["rows"], total_lessons=total_lessons, roster=roster)
    out = {"scope": data["name"], "metrics": metrics,
           "skills": sch.skill_breakdown(data["rows"])}
    if curve:
        out["curve"] = sch.survival(data["rows"])

    def _fmt(d):
        m = d["metrics"]
        lines = [d["scope"],
                 f"  students with data : {m['students_with_data']}"
                 f" / enrolled {m['enrolled']} (no data: {m['without_data']})",
                 f"  active (>=1 lesson) : {m['active']} ({m['activation_pct']}%)",
                 f"  lessons completed   : avg {m['lessons_completed_avg']}, "
                 f"median {m['lessons_completed_median']}, max {m['lessons_completed_max']}"]
        if m.get("lessons_total"):
            lines += [f"  course length       : {m['lessons_total']} lessons",
                      f"  average progress    : {m['avg_completion_pct']}% of the course",
                      f"  reached halfway     : {m['halfway']} ({m['halfway_pct']}%)",
                      f"  finished the course : {m['finishers']} ({m['finisher_pct']}%)"]
        lines.append(f"  total score         : avg {m['score_avg']}, max {m['score_max']}")
        if d.get("skills"):
            lines.append("  by skill            : " + ", ".join(
                f"{k}={v['avg_of_scorers']} (n={v['students']})"
                for k, v in d["skills"].items()))
        if d.get("curve"):
            lines.append("  survival (lesson -> reached):")
            for point in d["curve"]:
                bar = "#" * max(1, int(point["pct"] / 4)) if point["pct"] else ""
                lines.append(f"    {point['lesson']:>3}. {point['reached']:>4} "
                             f"({point['pct']:>5}%) {bar}")
        return "\n".join(lines)

    emit(ctx, out, human=_fmt)


@school.command("rating")
@click.option("--class-id", "class_id", type=int, default=None)
@click.option("--marathon-id", "marathon_id", type=int, default=None)
@click.option("--mode", default=0, show_default=True, help="Rating mode")
@click.pass_context
def school_rating(ctx, class_id, marathon_id, mode):
    """Points rating for a class or a course."""
    from .core import school as sch

    sess = get_session(ctx)
    if marathon_id:
        data = sch.marathon_rating(sess, marathon_id, mode=mode)
    elif class_id:
        data = sch.class_rating(sess, class_id, mode=mode)
    else:
        raise click.ClickException("pass --class-id or --marathon-id")
    rows = data.get("Rating") or []
    emit(ctx, {"max_score": data.get("MaxScore"), "rating": rows},
         human=lambda d: "\n".join(
             f"{i + 1:>3}. {r.get('PupilFullName') or '':<24} "
             f"{r.get('Points')} pts  <{r.get('PupilEmail') or ''}>"
             for i, r in enumerate(d["rating"]))
         + (f"\n(max score {d['max_score']})" if d.get("max_score") else ""))


# -------------------------------------------------------------- classroom
@cli.group("classroom")
@click.pass_context
def classroom(ctx):
    """Student classroom (current lesson, homework)."""


@classroom.command("show")
@click.option("--student", required=True,
              help="Student name (as on Edvibe) or pupil id")
@click.option("--class-id", "class_id", type=int, default=None,
              help="Class id (default: the student's first class)")
@click.pass_context
def classroom_show(ctx, student, class_id):
    """Open a student's classroom: current lesson + homework overview."""
    sess = get_session(ctx)
    pupil = sess.resolve_pupil(student)
    if not pupil:
        raise click.ClickException(f"student not found: {student}")
    pid = pupil.get("Id")
    c = sess.classroom(pid, class_id=class_id)
    group = c.get("group") or {}
    gid = group.get("GroupId")
    lesson_id = c.get("current_lesson_id")
    lesson = sess.get_lesson(lesson_id) if lesson_id else None
    hw_item = None
    hw_items = []
    if lesson_id and gid:
        hw_item = sess.find_homework_lesson(lesson_id, pid, gid)
        if hw_item:
            hw_items = sess.load_homework_exercises(lesson_id, pid, gid,
                                                    hw_item.get("Id"))
    hw_section = (lesson or {}).get("HomeworkSection") or {}
    out = {"pupil": {"id": pid, "name": pupil.get("FullName")},
           "class": {"id": gid, "name": group.get("Name")},
           "current_lesson": {"id": lesson_id,
                              "name": (lesson or {}).get("Name")},
           "homework_section_id": hw_section.get("Id"),
           "homework": {"id": (hw_item or {}).get("Id"),
                        "exercises": len(hw_items)},
           "homework_items": [{"number": e.get("Number"), "id": e.get("Id"),
                               "type": e.get("Type"),
                               "name": (e.get("Name") or "")[:70]}
                              for e in hw_items]}

    def _fmt(d):
        lines = [f"{d['pupil']['name']} (id {d['pupil']['id']})",
                 f"class #{d['class']['id']} '{d['class']['name']}'",
                 f"current lesson #{d['current_lesson']['id']} "
                 f"'{d['current_lesson']['name']}'",
                 f"homework #{d['homework']['id']} — "
                 f"{d['homework']['exercises']} exercises "
                 f"(section id {d['homework_section_id']})"]
        for e in d["homework_items"]:
            lines.append(f"   {e['number']:>2}. #{e['id']} type={e['type']} {e['name']}")
        return "\n".join(lines)

    emit(ctx, out, human=_fmt)


# --------------------------------------------------------------- homework
@cli.group("homework")
@click.pass_context
def homework(ctx):
    """Homework microservice (per-student homework sheets)."""


@homework.command("show")
@click.option("--lesson", "lesson_id", required=True, type=int)
@click.option("--pupil", "pupil_id", required=True, type=int)
@click.option("--class-id", "class_id", required=True, type=int)
@click.option("--homework-lesson", "hw_id", type=int, default=None,
              help="Homework object id (default: auto-find for the lesson)")
@click.pass_context
def homework_show(ctx, lesson_id, pupil_id, class_id, hw_id):
    """List the exercises in a student's homework sheet."""
    sess = get_session(ctx)
    if not hw_id:
        item = sess.find_homework_lesson(lesson_id, pupil_id, class_id)
        if not item:
            raise click.ClickException(
                "no homework found for this lesson/pupil; pass --homework-lesson")
        hw_id = item.get("Id")
    items = sess.load_homework_exercises(lesson_id, pupil_id, class_id, hw_id)
    rows = [{"id": i.get("Id"), "number": i.get("Number"), "type": i.get("Type"),
             "name": (i.get("Name") or "")[:70]} for i in items]
    emit(ctx, {"homework_lesson_id": hw_id, "count": len(rows), "items": rows},
         human=lambda d: (
             f"Homework #{d['homework_lesson_id']} — {d['count']} exercises\n"
             + "\n".join(f"  {r['number']:>2}. #{r['id']} type={r['type']} {r['name']}"
                         for r in d["items"])))


@homework.command("add")
@click.option("--file", "spec_file", required=True, type=click.Path(exists=True),
              help="Homework spec JSON (see core/homework_spec.py)")
@click.option("--dry-run", is_flag=True, help="Validate and show the plan only")
@click.pass_context
def homework_add(ctx, spec_file, dry_run):
    """Append exercises from a JSON spec to a student's homework sheet.
    Additive only: existing homework exercises are never touched."""
    from .core import homework_spec
    with open(spec_file, "r", encoding="utf-8") as f:
        spec = json.load(f)
    if dry_run:
        try:
            res = homework_spec.plan(spec)
        except ValueError as exc:
            raise click.ClickException(str(exc))
        emit(ctx, res, human=_fmt_hw_plan)
        return
    sess = get_session(ctx)
    log_lines = []
    try:
        res = homework_spec.build_homework(sess, spec,
                                           log=lambda s: log_lines.append(s))
    except ValueError as exc:
        raise click.ClickException(str(exc))
    res["log"] = log_lines

    def _fmt(d):
        lines = [f"Homework #{d['homework_lesson_id']} — added "
                 f"{len(d['saved'])} exercises ({d['before_count']} -> "
                 f"{d['after_count']})",
                 *d.get("log", []),
                 f"verified: {'OK' if d['verified'] else 'MISSING ' + str(d['missing_ids'])}"]
        return "\n".join(lines)

    emit(ctx, res, human=_fmt)


def _collect_exercise_ids(sess, lesson_id, section_id, exercises_csv):
    """Section exercises (sorted by Number) + extra ids, de-duplicated."""
    ids = []
    if section_id:
        sec_items = sess.load_exercises(section_id, lesson_id)
        ids += [e.get("Id") for e in
                sorted(sec_items, key=lambda e: e.get("Number", 0))]
    if exercises_csv:
        ids += [int(x) for x in exercises_csv.replace(" ", "").split(",") if x]
    # keep order, drop duplicates
    seen = set()
    return [i for i in ids if i and not (i in seen or seen.add(i))]


def _attach_core(sess, lesson_id, pupil_id, class_id, ids, dry_run):
    """Push already-collected exercise ids into the pupil's homework sheet,
    in the given order, then verify. Sheet MUST already exist (the classroom
    unit pin provisions it) — with no sheet the RPC silently no-ops."""
    existing = sess.find_homework_lesson(lesson_id, pupil_id, class_id)
    hw_id = (existing or {}).get("Id")
    already = set()
    if hw_id:
        already = {e.get("Id") for e in
                   sess.load_homework_exercises(lesson_id, pupil_id, class_id, hw_id)}
    new_ids = [i for i in ids if i not in already]

    if dry_run:
        return {"lesson_id": lesson_id, "pupil_id": pupil_id, "class_id": class_id,
                "homework_lesson_id": hw_id, "to_attach": new_ids,
                "already_there": sorted(already), "mode": "dry-run"}

    if new_ids:
        value = sess.add_exercises_to_homework(lesson_id, pupil_id, class_id, new_ids)
        if isinstance(value, dict):
            hw_id = value.get("HomeworkLessonId") or hw_id
        elif isinstance(value, int):
            hw_id = value or hw_id
        if not hw_id:
            item = sess.find_homework_lesson(lesson_id, pupil_id, class_id)
            hw_id = (item or {}).get("Id")
        sess.update_homework_count(hw_id)
        sess.mark_homework_updates(hw_id, pupil_id)

    after = sess.load_homework_exercises(lesson_id, pupil_id, class_id, hw_id)
    have = {e.get("Id") for e in after}
    missing = [i for i in ids if i not in have]
    return {"lesson_id": lesson_id, "pupil_id": pupil_id, "class_id": class_id,
            "homework_lesson_id": hw_id, "attached": new_ids,
            "already_there": sorted(already), "after_count": len(after),
            "verified": not missing, "missing_ids": missing,
            "items": [{"id": e.get("Id"), "number": e.get("Number"),
                       "type": e.get("Type"), "name": (e.get("Name") or "")[:70]}
                      for e in after]}


def _fmt_attach(d):
    lines = [f"Homework #{d['homework_lesson_id']} — attached "
             f"{len(d['attached'])} exercises (now {d['after_count']} total)",
             *[f"  + #{i}" for i in d["attached"]],
             f"verified: {'OK' if d['verified'] else 'MISSING ' + str(d['missing_ids'])}"]
    return "\n".join(lines)


@homework.command("attach")
@click.option("--lesson", "lesson_id", required=True, type=int,
              help="Lesson id the homework belongs to")
@click.option("--pupil", "pupil_id", required=True, type=int, help="Pupil id")
@click.option("--class-id", "class_id", required=True, type=int, help="Class (group) id")
@click.option("--section", "section_id", type=int, default=None,
              help="Attach every exercise of this lesson section (in order)")
@click.option("--exercises", "exercises_csv", default=None,
              help="Comma-separated exercise ids (instead of --section)")
@click.option("--dry-run", is_flag=True,
              help="Show what would be attached; no writes (auth still needed)")
@click.pass_context
def homework_attach(ctx, lesson_id, pupil_id, class_id, section_id,
                    exercises_csv, dry_run):
    """Attach EXISTING lesson exercises to a pupil's homework sheet.

    Unlike `homework add` (which SAVES new exercises), this pushes exercises
    that already live in the lesson section into the pupil's homework —
    the same flow as the editor's "Add to homework". The homework sheet must
    already exist: the classroom's unit pin creates it (see `homework give`);
    without a sheet the server silently no-ops."""
    sess = get_session(ctx)
    ids = _collect_exercise_ids(sess, lesson_id, section_id, exercises_csv)
    if not ids:
        raise click.ClickException("pass --section and/or --exercises")

    if dry_run:
        res = _attach_core(sess, lesson_id, pupil_id, class_id, ids, dry_run=True)
        emit(ctx, res, human=lambda d: (
            f"PLAN: attach {len(d['to_attach'])} exercises to homework "
            f"#{d['homework_lesson_id']} (lesson #{d['lesson_id']}, "
            f"pupil #{d['pupil_id']}, class #{d['class_id']})\n"
            + "\n".join(f"  - #{i}" for i in d["to_attach"])
            + (f"\n  ({len(d['already_there'])} already attached)" if d["already_there"] else "")))
        return

    res = _attach_core(sess, lesson_id, pupil_id, class_id, ids, dry_run=False)
    emit(ctx, res, human=_fmt_attach)


@homework.command("give")
@click.option("--lesson", "lesson_id", required=True, type=int,
              help="Lesson to give homework for (any book, incl. personal/serial)")
@click.option("--class-id", "class_id", required=True, type=int, help="Class (group) id")
@click.option("--pupil", "pupil_id", required=True, type=int,
              help="Pupil id whose homework sheet receives the exercises")
@click.option("--section", "section_id", type=int, default=None,
              help="Lesson section (default: the lesson's main section)")
@click.option("--exercises", "exercises_csv", default=None,
              help="Comma-separated exercise ids (instead of --section)")
@click.option("--file", "spec_file", type=click.Path(exists=True), default=None,
              help="Spec (lesson-spec 'sections' or 'exercises' list): its exercises are "
                   "created in the lesson's Homework section and attached (same type+name reused)")
@click.option("--no-reuse", is_flag=True,
              help="With --file: always create new exercises, never reuse by type+name")
@click.option("--dry-run", is_flag=True, help="Show the plan; no writes")
@click.pass_context
def homework_give(ctx, lesson_id, class_id, pupil_id, section_id, exercises_csv,
                  spec_file, no_reuse, dry_run):
    """Give homework for a lesson end-to-end (one command).

    Step 0 (optional, --file): create the spec's exercises in the lesson's
    Homework section (the same pool as the editor's homework area; same
    type+name is reused, so re-runs for other pupils are idempotent).
    Step 1 pins the lesson as the class's current unit (SelectLesson — the
    classroom's "Pin this unit to use in class"); the FIRST pin provisions
    the pupil material and the homework sheet server-side. Step 2 attaches
    the lesson's exercises to the pupil's homework in lesson order."""
    sess = get_session(ctx)
    from .core import homework_spec
    spec_exs = None
    if spec_file:
        with open(spec_file, "r", encoding="utf-8") as f:
            spec = json.load(f)
        try:
            spec_exs = homework_spec.spec_exercises(spec)
        except ValueError as exc:
            raise click.ClickException(str(exc))
        if not spec_exs:
            raise click.ClickException("spec has no exercises")
    if not section_id and not exercises_csv and not spec_exs:
        section_id = sess.default_section_id(lesson_id)
    ids = _collect_exercise_ids(sess, lesson_id, section_id, exercises_csv)
    pool_plan = None
    if spec_exs:
        try:
            pool_plan = homework_spec.plan_in_lesson(sess, lesson_id, spec_exs,
                                                     reuse=not no_reuse)
        except ValueError as exc:
            raise click.ClickException(str(exc))
        ids = ([x["id"] for x in pool_plan["to_reuse"]] + ids)
    seen = set()
    ids = [i for i in ids if i and not (i in seen or seen.add(i))]
    if not ids and not (pool_plan and pool_plan["to_create"]):
        raise click.ClickException("no exercises found — pass --section/--exercises/--file")

    if dry_run:
        res = _attach_core(sess, lesson_id, pupil_id, class_id, ids, dry_run=True)
        res["would_pin"] = f"lesson #{lesson_id} -> class #{class_id}"
        if pool_plan:
            res["pool_plan"] = pool_plan
        emit(ctx, res, human=lambda d: (
            f"PLAN: pin lesson #{d['lesson_id']} to class #{d['class_id']} (SelectLesson), "
            f"then attach {len(d['to_attach'])} exercises to homework "
            f"#{d['homework_lesson_id']} (pupil #{d['pupil_id']})\n"
            + "\n".join(f"  - #{i}" for i in d["to_attach"])
            + (("\n  pool: " + f"{len(d['pool_plan']['to_create'])} to create, "
                f"{len(d['pool_plan']['to_reuse'])} to reuse")
               if d.get("pool_plan") else "")))
        return

    log_lines = []
    pool_info = None
    if spec_exs:
        try:
            pool_info = homework_spec.create_in_lesson(
                sess, lesson_id, spec_exs, reuse=not no_reuse,
                log=lambda s: log_lines.append(s))
        except ValueError as exc:
            raise click.ClickException(str(exc))
        ids = [i for i in pool_info["ids"]] + [i for i in ids
                                               if i not in set(pool_info["ids"])]
    pin = sess.select_lesson(lesson_id, class_id)
    try:
        sess.link_lesson(lesson_id, class_id)
    except EdvibeError:
        pass
    # the sheet is provisioned by the first pin; give the server a beat
    hw = None
    for _ in range(10):
        hw = sess.find_homework_lesson(lesson_id, pupil_id, class_id)
        if hw:
            break
        time.sleep(1.5)
    if not hw:
        raise click.ClickException(
            f"pinned lesson #{lesson_id} but no homework sheet appeared for "
            f"pupil #{pupil_id} — open the class homework page once, then re-run")

    res = _attach_core(sess, lesson_id, pupil_id, class_id, ids, dry_run=False)
    res["pin"] = pin
    res["is_first_select"] = (pin or {}).get("IsFirstSelect") if isinstance(pin, dict) else None
    if pool_info is not None:
        res["pool"] = pool_info
        res["log"] = log_lines

    def _fmt(d):
        lines = [f"Pinned lesson #{d['lesson_id']} to class #{d['class_id']}"
                 f" (first select: {d['is_first_select']})"]
        if d.get("pool"):
            lines.append(f"Homework pool: {len(d['pool']['created'])} created, "
                         f"{len(d['pool']['reused'])} reused (section #{d['pool']['section_id']})")
            lines.extend(d.get("log") or [])
        lines.append(_fmt_attach(d))
        return "\n".join(lines)

    emit(ctx, res, human=_fmt)


@homework.command("pool")
@click.option("--lesson", "lesson_id", required=True, type=int,
              help="Lesson whose Homework section to list")
@click.pass_context
def homework_pool(ctx, lesson_id):
    """List the lesson's Homework-section exercises (the pool that
    `homework give`/`attach` push to pupils)."""
    sess = get_session(ctx)
    section_id = sess.homework_section_id(lesson_id)
    if not section_id:
        raise click.ClickException(f"lesson #{lesson_id} has no Homework section")
    items = sess.load_exercises(section_id, lesson_id)
    rows = [{"id": e.get("Id"), "number": e.get("Number"), "type": e.get("Type"),
             "name": (e.get("Name") or "")[:70]}
            for e in sorted(items, key=lambda x: x.get("Number", 0))]
    emit(ctx, {"lesson_id": lesson_id, "section_id": section_id,
               "count": len(rows), "items": rows},
         human=lambda d: (
             f"Homework pool of lesson #{d['lesson_id']} (section #{d['section_id']}) "
             f"— {d['count']} exercises\n"
             + "\n".join(f"  {r['number']:>2}. #{r['id']} type={r['type']} {r['name']}"
                         for r in d["items"])))


def _resolve_pupil_class(sess, pupil_id, class_id, student):
    """Resolve (--student NAME) or (--pupil ID + --class-id ID)."""
    if pupil_id:
        if not class_id:
            raise click.ClickException("--class-id is required with --pupil")
        return pupil_id, class_id
    if not student:
        raise click.ClickException("pass --pupil ID --class-id ID or --student NAME")
    p = sess.resolve_pupil(student)
    if not p:
        raise click.ClickException(
            f"student '{student}' not found (see `students list --search`)")
    pid = p.get("Id")
    if class_id:
        return pid, class_id
    c = sess.classroom(pid)
    group = c.get("group") or {}
    if not group:
        raise click.ClickException(f"no class found for {p.get('FullName') or pid}")
    return pid, group.get("GroupId")


@homework.command("answers")
@click.option("--pupil", "pupil_id", type=int, default=None, help="Pupil id")
@click.option("--class-id", "class_id", type=int, default=None, help="Class (group) id")
@click.option("--student", default=None,
              help="Pupil name; resolves pupil + class automatically (alternative to --pupil/--class-id)")
@click.option("--lesson", "lesson_id", type=int, default=None, help="Filter by lesson id")
@click.option("--sheet", "sheet_id", type=int, default=None, help="HomeworkLessonId")
@click.option("--limit", type=int, default=None,
              help="Max sheets, newest first (when --sheet is omitted)")
@click.option("--only-answered", is_flag=True, help="Show answered exercises only")
@click.pass_context
def homework_answers(ctx, pupil_id, class_id, student, lesson_id, sheet_id, limit,
                     only_answered):
    """Read a pupil's SUBMITTED homework answers (voice / writing / typed) — read-only.

    Verified path: one LoadHomeworkGroupExercises call per sheet returns the
    answers themselves — voice-recording mp3 URL (public CDN), writing text,
    typed answers, submission time. Feed the mp3 URLs to `audio transcribe`."""
    sess = get_session(ctx)
    from .core import homework_answers as hwa
    pupil_id, class_id = _resolve_pupil_class(sess, pupil_id, class_id, student)
    try:
        data = hwa.collect(sess, pupil_id, class_id, lesson_id=lesson_id,
                           sheet_id=sheet_id, limit=limit)
    except (EdvibeError, RuntimeError) as exc:
        raise click.ClickException(str(exc))
    emit(ctx, data, human=lambda d: hwa.format_report(d, only_answered=only_answered))


@homework.command("download")
@click.option("--pupil", "pupil_id", type=int, default=None, help="Pupil id")
@click.option("--class-id", "class_id", type=int, default=None, help="Class (group) id")
@click.option("--student", default=None,
              help="Pupil name; resolves pupil + class automatically")
@click.option("--lesson", "lesson_id", type=int, default=None, help="Filter by lesson id")
@click.option("--sheet", "sheet_id", type=int, default=None, help="HomeworkLessonId")
@click.option("--limit", type=int, default=None,
              help="Max sheets, newest first (when --sheet is omitted)")
@click.option("--out", "out_dir", required=True, type=click.Path(file_okay=False),
              help="Target directory (created if missing)")
@click.option("--force", is_flag=True, help="Re-download files that already exist")
@click.pass_context
def homework_download(ctx, pupil_id, class_id, student, lesson_id, sheet_id,
                      limit, out_dir, force):
    """Download a pupil's submitted voice recordings + writing texts into OUT.

    Writes OUT/sheet_<id>/... plus OUT/manifest.json (every answer: audio file
    map, writing texts, typed answers, submission times) — the input for the
    homework auto-check."""
    sess = get_session(ctx)
    from .core import homework_answers as hwa
    pupil_id, class_id = _resolve_pupil_class(sess, pupil_id, class_id, student)
    log_lines = []
    try:
        manifest = hwa.download(sess, pupil_id, class_id, out_dir,
                                lesson_id=lesson_id, sheet_id=sheet_id,
                                limit=limit, force=force,
                                log=lambda s: log_lines.append(s))
    except (EdvibeError, RuntimeError) as exc:
        raise click.ClickException(str(exc))
    emit(ctx, manifest, human=lambda d: hwa.format_download(d, log_lines=log_lines))


def _fmt_hw_plan(d):
    lines = [f"PLAN: homework #{d['homework_lesson_id']} "
             f"(lesson #{d['lesson_id']}, pupil #{d['pupil_id']}, class #{d['class_id']}) "
             f"— append {d['total_exercises']} exercises:"]
    for e in d["exercises"]:
        lines.append(f"  - {e['type']}: {(e['name'] or '')[:60]}")
    return "\n".join(lines)


# ------------------------------------------------------------------ site
@cli.group("site")
@click.pass_context
def site(ctx):
    """Teacher landing page («Сайт и заявки») — read/edit your personal site.

    Public page: https://edvibe.com/teachers/<slug> (cabinet -> «Сайт и заявки»).
    Writes run through backup -> save -> read-back verification; blocks are
    addressed by name (top/main/about/video/statistics/directions/examples/
    review/certificates/questions/application/window/faq)."""


def _site_image_value(sess, image):
    """'--image' value: an http(s) URL, or a local file uploaded (type 33)."""
    if not image:
        return None
    if str(image).startswith("http://") or str(image).startswith("https://"):
        return image
    if os.path.exists(image):
        res = sess.upload_media_file(image, file_type=33)  # TeacherLanding media
        return res.get("Url")
    raise click.UsageError(f"--image must be an http(s) URL or an existing "
                           f"file: {image}")


def _run_site_patch(ctx, patch, dry_run, do_publish, out_dir=None, base_dir=None):
    sess = get_session(ctx)
    from .core import landing
    log_lines = []
    try:
        patch = landing.resolve_policy_files(patch, base_dir=base_dir)
        report = landing.save_with_safety(
            sess, patch, dry_run=dry_run, out_dir=out_dir, publish=do_publish,
            log=lambda s: log_lines.append(s))
    except EdvibeError as exc:
        raise click.ClickException(str(exc))
    report["log"] = log_lines

    def human(d):
        if d.get("dry_run"):
            head = "DRY RUN — nothing written"
        elif d.get("noop"):
            head = "no changes (already up to date)"
        elif d.get("verified"):
            head = "saved + verified ✓"
        else:
            head = "SAVED, but read-back found problems (check the log; backup kept)"
        lines = [head] + log_lines
        if d.get("url"):
            lines.append(f"site: https://edvibe.com/teachers/{d['url']}")
        return "\n".join(lines)
    emit(ctx, report, human=human)


@site.command("show")
@click.pass_context
def site_show(ctx):
    """Show the landing site: meta, publishing state and all blocks."""
    sess = get_session(ctx)
    from .core import landing
    try:
        state = landing.read_state(sess)
    except EdvibeError as exc:
        raise click.ClickException(str(exc))
    view = landing.state_view(state)

    def human(v):
        lines = [f"landing: {v['url']}  (publishing={v['publishing']}, "
                 f"locked={v['locked']})",
                 f"meta.Title:       {v['meta'].get('Title', '')!r}",
                 f"meta.Description: {(v['meta'].get('Description') or '')[:90]!r}",
                 f"meta.ImageUrl:    {v['meta'].get('ImageUrl', '')}",
                 "blocks:"]
        for b in v["blocks"]:
            flags = "ON " if b["enabled"] else "off"
            show = "-" if b["show"] is None else str(bool(b["show"]))
            lines.append(f"  [{flags}] {b['name']:<13} type={b['type']:<2} "
                         f"show={show:<5} {b['title']}")
            pol = b.get("policies")
            if pol:
                def _sz(f):
                    n = pol.get(f) or 0
                    return f"{n} ch" if n else "NOT SET"
                lines.append(f"        docs: user agreement: {_sz('PrivacyPolicy')}, "
                             f"personal data policy: {_sz('PersonalDataPolicy')}")
        return "\n".join(lines)
    emit(ctx, view, human=human)


@site.command("backup")
@click.option("--out", "out_dir", type=click.Path(file_okay=False), default=None,
              help="Backup dir (default ~/.edvibe/landing-backups)")
@click.pass_context
def site_backup(ctx, out_dir):
    """Write a timestamped snapshot (settings + blocks) to the backups dir."""
    sess = get_session(ctx)
    from .core import landing
    try:
        state = landing.read_state(sess)
        path = landing.backup(state, out_dir=out_dir)
    except EdvibeError as exc:
        raise click.ClickException(str(exc))
    emit(ctx, {"backup": path, "blocks": len(state.get("blocks") or [])},
         human=lambda d: f"backup written: {d['backup']} ({d['blocks']} blocks)")


@site.command("requests")
@click.option("--take", default=50, show_default=True, type=int)
@click.option("--skip", default=0, show_default=True, type=int)
@click.pass_context
def site_requests(ctx, take, skip):
    """List student requests («заявки») left on the landing page (read-only)."""
    sess = get_session(ctx)
    from .core import landing
    try:
        res = landing.list_requests(sess, skip=skip, take=take)
    except EdvibeError as exc:
        raise click.ClickException(str(exc))

    def human(d):
        if not d["items"]:
            return f"no requests (total {d['count']})"
        lines = [f"requests: {d['count']}"]
        for it in d["items"]:
            lines.append(f"  #{it.get('Id')} {it.get('DateCreate', '')} | "
                         f"{it.get('PupilName', '')} | {it.get('PupilEmail', '')} | "
                         f"{it.get('PupilPhone', '')}")
            if it.get("PupilComment"):
                lines.append(f"      «{str(it['PupilComment'])[:110]}»")
        return "\n".join(lines)
    emit(ctx, res, human=human)


@site.command("meta")
@click.option("--title", default=None, help="Browser tab / link-preview title")
@click.option("--description", "desc", default=None, help="Link-preview description")
@click.option("--image", default=None,
              help="Preview image: http(s) URL or a local file (uploaded, type 33)")
@click.option("--dry-run", is_flag=True, help="Show the diff only, write nothing")
@click.option("--publish", "do_publish", is_flag=True,
              help="Also PublishLandingSite (make the change live)")
@click.pass_context
def site_meta(ctx, title, desc, image, dry_run, do_publish):
    """Set the site meta tags (shown in the browser tab and link previews)."""
    if title is None and desc is None and image is None:
        raise click.UsageError("pass --title / --description / --image")
    sess = get_session(ctx)
    patch = {}
    if title is not None:
        patch["Title"] = title
    if desc is not None:
        patch["Description"] = desc
    if image is not None:
        patch["ImageUrl"] = _site_image_value(sess, image)
    _run_site_patch(ctx, {"meta": patch}, dry_run, do_publish)


@site.command("block")
@click.argument("state", type=click.Choice(["on", "off"]))
@click.option("--type", "block_type", required=True,
              help="Block name (faq, examples, video, …) or number")
@click.option("--show/--hide", "show", default=None,
              help="Explicitly set the inner IsShow (default: mirror the on/off)")
@click.option("--dry-run", is_flag=True, help="Show the diff only, write nothing")
@click.option("--publish", "do_publish", is_flag=True,
              help="Also PublishLandingSite (make the change live)")
@click.pass_context
def site_block(ctx, state, block_type, show, dry_run, do_publish):
    """Enable/disable a landing block (e.g. `site block on --type examples`)."""
    item = {"type": block_type, "enabled": state == "on"}
    if show is not None:
        item["show"] = show
    _run_site_patch(ctx, {"blocks": [item]}, dry_run, do_publish)


@site.command("policy")
@click.option("--type", "block_type", default="application", show_default=True,
              help="Block carrying the documents (only 'application' has them)")
@click.option("--user-agreement", "user_agreement",
              type=click.Path(exists=True, dir_okay=False),
              help="User agreement file (HTML) -> RPC field 'PrivacyPolicy'")
@click.option("--personal-data", "personal_data",
              type=click.Path(exists=True, dir_okay=False),
              help="Personal data processing policy file (HTML) -> 'PersonalDataPolicy'")
@click.option("--dry-run", is_flag=True, help="Show the diff only, write nothing")
@click.option("--publish", "do_publish", is_flag=True,
              help="Also PublishLandingSite (make the change live)")
@click.pass_context
def site_policy(ctx, block_type, user_agreement, personal_data, dry_run, do_publish):
    """Set the user agreement / personal data policy of the application form.

    These are the two documents behind «Я принимаю пользовательское соглашение
    и политику конфиденциальности» on the landing. Without them the cabinet
    shows the red banner "Set up the user agreement and personal data
    processing policy" (site_link_configuring_...)."""

    if not user_agreement and not personal_data:
        raise click.UsageError(
            "pass --user-agreement and/or --personal-data (file paths)")
    item = {"type": block_type}
    if user_agreement:
        item["user_agreement"] = {"file": os.path.abspath(user_agreement)}
    if personal_data:
        item["personal_data_policy"] = {"file": os.path.abspath(personal_data)}
    _run_site_patch(ctx, {"blocks": [item]}, dry_run, do_publish)


def _site_edit_impl(ctx, patch_file, dry_run, do_publish, out_dir):
    try:
        with open(patch_file, "r", encoding="utf-8") as f:
            patch = json.load(f)
    except ValueError as exc:
        raise click.ClickException(f"patch file is not valid JSON: {exc}")
    if not isinstance(patch, dict) or not (patch.get("meta") or patch.get("blocks")):
        raise click.UsageError("patch must be a JSON object with 'meta' and/or 'blocks'")
    _run_site_patch(ctx, patch, dry_run, do_publish, out_dir,
                    base_dir=os.path.dirname(os.path.abspath(patch_file)))


_patch_file_opt = click.option(
    "--file", "patch_file", required=True, type=click.Path(exists=True),
    help="Patch JSON: {\"meta\": {...}, \"blocks\": [{\"type\": ..., \"enabled\": ..., "
         "\"show\": ..., \"set\": {...}, \"user_agreement\": \"<html>\" or "
         "{\"file\": path}, \"personal_data_policy\": ...}]}")
_dry_opt = click.option("--dry-run", is_flag=True,
                        help="Show the diff only, write nothing")
_publish_opt = click.option("--publish", "do_publish", is_flag=True,
                            help="Also PublishLandingSite (make the change live)")
_out_opt = click.option("--out", "out_dir", type=click.Path(file_okay=False),
                        default=None, help="Backup dir")


@site.command("edit")
@_patch_file_opt
@_dry_opt
@_publish_opt
@_out_opt
@click.pass_context
def site_edit(ctx, patch_file, dry_run, do_publish, out_dir):
    """Apply a patch to the site (backup -> save -> read-back verification).

    {\"meta\": {\"Title\": \"...\", \"ImageUrl\": \"https://...\"},
     \"blocks\": [{\"type\": \"faq\", \"enabled\": true, \"show\": true},
                 {\"type\": \"examples\", \"set\": {\"Lessons\": [...]}},
                 {\"type\": \"application\",
                  \"user_agreement\": {\"file\": \"ua.html\"},
                  \"personal_data_policy\": {\"file\": \"pd.html\"}}]}"""
    _site_edit_impl(ctx, patch_file, dry_run, do_publish, out_dir)


@site.command("save")
@_patch_file_opt
@_dry_opt
@_publish_opt
@_out_opt
@click.pass_context
def site_save(ctx, patch_file, dry_run, do_publish, out_dir):
    """Alias of `site edit` — same patch format, same safety pipeline."""
    _site_edit_impl(ctx, patch_file, dry_run, do_publish, out_dir)


@site.command("publish")
@click.option("--dry-run", is_flag=True,
              help="Show what would be published, write nothing")
@click.pass_context
def site_publish(ctx, dry_run):
    """Push the currently stored site live (PublishLandingSite; prints the slug)."""
    sess = get_session(ctx)
    from .core import landing
    try:
        res = landing.publish_current(sess, dry_run=dry_run)
    except EdvibeError as exc:
        raise click.ClickException(str(exc))
    emit(ctx, res, human=lambda d: (
        "DRY RUN — nothing published"
        if d.get("dry_run") else f"published: {json.dumps(d, ensure_ascii=False)}"))


# --------------------------------------------------------------- audio
@cli.group("audio")
@click.pass_context
def audio(ctx):
    """Audio helpers: transcribe student recordings (Deepgram Nova-3)."""


@audio.command("transcribe")
@click.argument("source")
@click.option("--out", "out_path", type=click.Path(dir_okay=False), default=None,
              help="Output JSON path (default: next to the audio file / cwd for URLs)")
@click.option("--language", default="multi", show_default=True,
              type=click.Choice(["multi", "en", "ru", "detect"]),
              help="multi = RU+EN code-switching (default); "
                   "detect = auto (monolingual — loses the Russian)")
@click.option("--model", default="nova-3", show_default=True)
@click.option("--transcode", is_flag=True,
              help="Convert to 16 kHz mono wav first (for exotic formats; "
                   "off by default — keeps uploads small)")
@click.option("--download", is_flag=True,
              help="For URLs: download locally and upload the bytes "
                   "(default: Deepgram fetches the URL itself)")
@click.option("--keep-raw", is_flag=True, help="Also save the raw Deepgram response")
@click.pass_context
def audio_transcribe(ctx, source, out_path, language, model, transcode,
                     download, keep_raw):
    """Transcribe an audio FILE or https URL (RU+EN aware) -> stats JSON.

    Normalized output: transcript, word timestamps, pauses >= 0.6 s, filler
    counts, speaking rate (wpm), low-confidence words, language mix.
    Deepgram Nova-3 `language=multi`: Russian comes back in Cyrillic."""
    from .core import asr
    try:
        result = asr.transcribe(source, out_path=out_path, language=language,
                                model=model, transcode=transcode,
                                keep_raw=keep_raw, download=download,
                                log=lambda s: click.echo(s, err=True))
    except RuntimeError as exc:
        raise click.ClickException(str(exc))
    emit(ctx, result, human=lambda d: asr.format_summary(d))


# --------------------------------------------------------------- import
@cli.command("import")
@click.option("--html", "html_file", required=True, type=click.Path(exists=True),
              help="Path to a hermes/esl-style HTML handout")
@click.option("--name", default=None, help="Material name (default: <title>)")
@click.option("--description", default="")
@click.option("--lesson", default="Lesson 1", help="Lesson name inside the material")
@click.pass_context
def import_html(ctx, html_file, name, description, lesson):
    """Import an HTML handout as a new Edvibe material with content notes."""
    sess = get_session(ctx)
    res = sess.import_html(html_file, material_name=name,
                           lesson_name=lesson, description=description)
    emit(ctx, res, human=lambda d: _fmt_import(d))


def _fmt_import(d):
    lines = [f"Material #{d['material_id']} (course #{d['course_id']})",
             f"Lesson #{d['lesson_id']} section #{d['section_id']}",
             f"Notes added: {len(d['notes'])}"]
    for n in d["notes"]:
        eid = n.get("Id") if isinstance(n, dict) else n
        lines.append(f"  - note exercise #{eid}")
    return "\n".join(lines)


# ------------------------------------------------------------------ REPL
@cli.command("repl", hidden=True)
@click.pass_context
def repl(ctx):
    """Interactive REPL (default when no subcommand is given)."""
    click.echo("cli-edvibe REPL — type a command, 'help' or 'exit'.")
    while True:
        try:
            line = input("edvibe> ").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break
        if not line:
            continue
        if line in ("exit", "quit"):
            break
        if line in ("help", "?"):
            click.echo("whoami | login | doctor | materials list | "
                       "materials create NAME | "
                       "lesson add --material ID --name N | "
                       "lesson build --file spec.json "
                       "[--material ID | --lesson ID] [--dry-run] | "
                       "lesson show --lesson ID | "
                       "content add-note --lesson ID --section ID --file F | "
                       "test-english fetch URL [--pages /,/2/] [--out F] | "
                       "test-english import URL [--book NAME|ID] [--section grammar] "
                       "[--pages /,/2/] [--dry-run] | "
                       "students list [--search NAME] | students show PUPIL_ID | "
                       "classroom show --student NAME | "
                       "homework show --lesson ID --pupil ID --class-id ID | "
                       "homework add --file spec.json [--dry-run] | "
                       "homework attach --lesson ID --pupil ID --class-id ID "
                       "[--section ID | --exercises 1,2,3] [--dry-run] | "
                       "homework give --lesson ID --class-id ID --pupil ID "
                       "[--section ID | --exercises 1,2,3 | --file spec.json] [--dry-run] | "
                       "homework pool --lesson ID | "
                       "homework answers --pupil ID --class-id ID "
                       "[--sheet ID | --limit N] [--student NAME] | "
                       "homework download --pupil ID --class-id ID --out DIR "
                       "[--sheet ID | --limit N] | "
                       "audio transcribe FILE|URL [--language multi|en|ru|detect] | "
                       "import --html FILE | logout | exit")
            continue
        try:
            args = shlex.split(line)
            cli.main(args=args, standalone_mode=False, obj=ctx.obj)
        except SystemExit:
            pass
        except (click.UsageError, EdvibeError, OSError) as exc:
            click.echo(f"error: {exc}", err=True)
        except Exception as exc:  # keep REPL alive
            click.echo(f"error: {type(exc).__name__}: {exc}", err=True)


def main():
    cli()


if __name__ == "__main__":
    sys.exit(main())
