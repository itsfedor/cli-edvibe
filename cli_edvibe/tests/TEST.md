# TEST.md — cli-edvibe

## Part 1: Test plan (written before implementation)

### Inventory
- `test_core.py` — 6 unit tests (no network):
  - importer: title extraction, lone-h1 drop, h2 split level, sub-heading
    retention inside sections, style/onclick stripping, lead-intro merge
  - client_time format, session role picking, session-file roundtrip
- `test_folders_dump.py` / `test_homework_spec.py` / `test_book_branding.py` /
  `test_test_english.py` — folders/move + dump, homework spec, branding,
  test-english (88 offline tests in total before 2026-09-24)
- `test_homework_answers.py` — 11 unit tests (added 2026-09-24, offline):
  extract() of voice/essay/typed/empty/teacher-verdict items, collect()
  (sheet filter / limit / newest-first / missing sheet), download() manifest +
  files + cached-skip/force
- `test_asr.py` — 11 unit tests (added 2026-09-24, offline): Deepgram normalize
  (pauses / fillers / wpm / low-confidence / language_mix), detect mode, URL
  mode + upload fallback, 408 retry recovery, hard errors not retried
- `test_full_e2e.py` — 5 live-API tests (gated on EDVIBE_EMAIL/EDVIBE_PASSWORD):
  1. login & whoami
  2. create material (BookUpsert) + verify it appears in GetPersonalBooks
  3. add lesson/unit + auto section (LessonUpsert, GetLessonWithId)
  4. add a Note exercise (SaveExerciseWsController) + verify via LoadExercises
  5. full `import_html` pipeline (material + lesson + 3 note blocks) + verify

### E2E safety contract
- Creates only fresh objects named `CLI-HARNESS-E2E …`; never deletes or edits
  pre-existing materials/lessons/exercises. Credentials only via env vars.

## Part 2: Results (appended after runs)

### Unit — run 2026-09-04 (offline)
```
6 passed in 0.07s
```
`test_core.py::test_title_extracted`, `test_sections_split_and_titled`,
`test_style_and_handlers_removed`, `test_client_time_format`,
`test_session_pick_role`, `test_session_file_roundtrip` — PASS

### E2E — run 2026-09-04 against live school 9419
```
5 passed in 14.11s
```
test_001_login_and_whoami, test_002_create_material,
test_003_add_lesson_and_section, test_004_add_note_exercise,
test_005_import_html_end_to_end — PASS

### Manual acceptance — real handout import (2026-09-04)
```
cli-edvibe --json import --html "handout.html"
```
Result: material #1206362, course #2866588, lesson #19490961, section #96130097,
5 Note exercises (Sections 1–4 + ADDITIONAL TEACHER RESOURCES), each carrying
the section's full HTML. Verified via `LoadExercises` and by rendering the
lesson editor page (screenshot `final_lesson_editor.png`).

### Coverage notes
- Exercise types beyond Note (Test, Video, Topic…) are read-only in this
  harness; creation of interactive exercise types is future work.
- Folders: listing works; creating a material *inside* an Edvibe folder is not
  yet exposed (needs FolderBookWsController mapping).

### Offline suite — run 2026-09-24 (homework answers + ASR)

```
110 passed in 0.97s
```
Per file: test_core 6 · test_folders_dump 13 · test_homework_spec 17 ·
test_book_branding 7 · test_test_english 45 · **test_homework_answers 11** ·
**test_asr 11** (the two new files above; run command: `python -m pytest
cli_edvibe/tests/ -q --ignore=cli_edvibe/tests/test_full_e2e.py`).

### Live acceptance — reading pupil answers + ASR (2026-09-24, school 9419)

Read-only live runs on real submissions (teacher user 115251):

| Run | Result |
|---|---|
| `homework answers --pupil 3410766 --class-id 2227632 --limit 2` | the pupil's 2 newest sheets: 11 answered exercises (typed + essay rows) |
| `homework download ... --sheet 20275010` | 2 voice recordings (mp3) downloaded with a manifest |
| `homework download ... --sheet 19566159` | 1 voice recording + 3 writing texts + manifest.json |
| `audio transcribe` (32.3 s recording) | 50 words, 92.9 wpm, 4 pauses, fillers um/uh — 2.6 s request |
| `audio transcribe` (96.3 s recording) | 115 words, 71.7 wpm, 20 pauses (max 2.8 s), en:115 — 2.4 s |
| `audio transcribe` (91.4 s recording) | 82 words, 53.8 wpm, 22 pauses (max 5.6 s) |
| RU+EN mixed clip (gTTS) | Cyrillic transcript + `language_mix {en:12, ru:6}` |
| URL mode vs local upload (same mp3) | identical stats (20 pauses, same fillers) |

Evidence: local recon notes — `answers-ws.md` (fetch contract),
`review-ui.md` (review page + comment contract), `asr-models.md` (ASR
comparison), plus a fixture set of real and synthetic recordings with their
run outputs.

No writes to Edvibe were made in any acceptance run (Get/Load RPCs only).
