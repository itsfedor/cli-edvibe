---
name: "cli-edvibe"
description: "Use when working with Edvibe (edvibe.com) from a shell or an agent — building lessons from JSON specs, giving and reading homework, school analytics, book artwork, the teacher landing page. Never deletes anything."
---

# cli-edvibe

Unofficial CLI for Edvibe's private WebSocket RPC API (there is no public API).
Install: `pipx install git+https://github.com/itsfedor/cli-edvibe`
(or `pip install -e .` from the repo root; add `[branding]` for cover/icon work).

Credentials: `EDVIBE_EMAIL` / `EDVIBE_PASSWORD`, or run `cli-edvibe login` once —
a session token is cached in `~/.edvibe/session.json` (mode 600) and the password
is never stored. `cli-edvibe doctor` checks python, deps, session and a live login.
Second account: `--account school` switches to `EDVIBE_SCHOOL_EMAIL` /
`EDVIBE_SCHOOL_PASSWORD` and `~/.edvibe/session_school.json`.

Vocabulary: material = Book (учебник), lesson = unit inside a book, section =
stage inside a lesson, content block = Note (type 22).

## Start here

```bash
cli-edvibe doctor                       # six checks, incl. live login
cli-edvibe materials list               # books + library folders
cli-edvibe lesson show --lesson ID      # sections + exercises
cli-edvibe lesson dump --lesson ID --out back.json   # read-only backup, run this first
```

`--json` works on any command (place it before the subcommand). A bare
`cli-edvibe` opens a REPL.

## Commands

**Session** — `doctor`, `login [--check]`, `logout`, `whoami`.

**Materials** — `materials list`, `materials folders [--books]`,
`materials create "Name"`, `materials move --book ID --folder ID [--dry-run]`.
Books inside a library folder are hidden from `materials list`; use
`folders --books`.

**Lessons** — `lesson add --material ID --name "Unit 1"`,
`lesson show --lesson ID`,
`lesson build --file spec.json (--material ID | --lesson ID) [--dry-run]`,
`lesson dump --lesson ID [--out FILE] [--section NAME]`,
`content show --lesson ID --section ID`,
`content add-note --lesson ID --section ID --file f.html`,
`content upload-image FILE [--type N]`, `content upload-audio FILE`,
`content attach-audio --exercise ID FILE...`.

**Homework** —
`homework give --lesson ID --class-id ID --pupil ID [--file spec | --section ID | --exercises 1,2,3] [--dry-run]`
(pins the unit, provisions the sheet on first use, attaches in order; with
`--file` it first creates the spec's exercises in the lesson's homework pool and
reuses any exercise with the same type+name),
`homework add --file spec.json [--dry-run]`,
`homework attach --lesson ID --pupil ID --class-id ID [--section ID]`,
`homework show --lesson ID --pupil ID --class-id ID`, `homework pool --lesson ID`,
`homework answers [--student NAME | --pupil ID --class-id ID] [--only-answered]`,
`homework download ... --out DIR`.

**Students / school** — `students list [--search NAME] [--take N]`,
`students show ID`, `classroom show --student NAME`, `school overview`,
`school pupils [--type N]`, `school classes`, `school marathons`,
`school stats [--school-wide | --class-id | --marathon-id]`,
`school course --marathon-id ID [--curve] [--students]`,
`school dropoff --marathon-id ID`, `school retention`, `school rating`.
Names are stored in whatever script the pupil used (often Cyrillic) — search the
full first name, the surname and the e-mail before concluding a pupil is absent,
and pass `--take 100` on a big school.

**Book artwork** *(needs `[branding]`)* — `book sections --book ID`,
`book cover --book ID FILE`, `book section-icon`, `book lesson-icon`,
`book apply-icons --manifest icons/manifest.json`,
`book cutout SRC DST [--tol N]`, `book gen-icons --spec spec.json --out DIR`
*(needs `[render]`: Pillow + Playwright)*. Icon/section/cover commands verify the
uploaded file's md5 against the CDN copy.

**Landing page** — `site show`, `site backup --out DIR`, `site requests`,
`site block on|off --type NAME`, `site meta --title --description`,
`site policy`, `site edit --file patch.json [--dry-run] [--publish]`,
`site publish`. Every write: timestamped backup → save → read-back diff.

**Import / audio** — `import --html handout.html` (one Note per `<h2>`),
`test-english fetch URL`, `test-english import URL --book NAME --section grammar [--pages /,/2/] [--replace-sections S1,S2] [--dry-run]`,
`audio transcribe FILE|URL [--language multi|en|ru] [--out JSON]` (Deepgram
Nova-3; `multi` keeps Russian in Cyrillic; returns transcript, word timings,
pauses ≥0.6 s, fillers, wpm; needs `DEEPGRAM_API_KEY`).

## Specs

`lesson build` takes `{lesson_name, description?, sections:[{name, exercises:[…]}]}`;
a section named `Homework` is written into the lesson's built-in homework section
instead of a stage section. `homework add` takes
`{lesson_id, pupil_id, class_id, homework_lesson_id, exercises:[…]}`.

Exercise types (31): `note text topic video wordlist writing match filltyped
fillbox chooseoption wordorder sortcolumns ordersentences truefalse test voice
button pictures unscramble audio gif label labelfill labelchoose miro googlepdf
wordwall learningapps genially baamboozle quizlet` — aliases `tf quiz gaps
listening pdf board letters` also resolve. Worked example:
`examples/lesson-small-talk.json`.

Gap syntax inside sentences: `[answer]`, `[hint/answer]`, `[/a1/a2]` for
alternatives; choose-option marks the correct one with `*` — `[going*/going on/went]`.

## Rules

- **NEVER delete or edit existing materials/lessons/exercises.** The harness has
  no delete command by design. The only rebuild path is
  `test-english import --replace-sections`, which recreates sections it created.
- **Dump before you rebuild:** `lesson dump --lesson ID --out file.json`.
- **Homework goes to a named pupil.** If a request says "send this homework" with
  no student, ask which one — a wrong guess lands on a real sheet.
- Tests create only `CLI-HARNESS-*` objects. Pacing: 0.8–2.0 s jitter, 150
  calls/hour per process (`EDVIBE_PACE_OFF=1` for tests, `EDVIBE_PACE_CAP` to
  raise the cap for a batch run).
- A Playwright/browser login mints a new token and can invalidate the cached CLI
  session; re-authenticate with `EDVIBE_EMAIL`/`EDVIBE_PASSWORD` in the env.

## Wire notes (short)

WS `wss://proxy-a.edvibe.com/websocket?token=<uuid4>`, frames
`{Controller, Method, ProjectName, RequestId, Value}`; login = two RPCs on
`AccountWsController` (`GetAccountRoles` → `Login`). Books/lessons live in
ProjectName `Books` (`BookWsController.BookUpsert`, `LessonWsController`),
exercises in `Exercises` (`SaveExerciseWsController.SaveExercise` with
`{ClassId, Domain, ExerciseView, AiUsed:false, UsedNewConstructor:false,
ClientTime, DeviceType}`), homework in `Homework`, school analytics in
`School`/`Statistic`/`Marathon*`, landing page in `TeacherLandingApi`.
Full write-up: `EDVIBE.md`.
