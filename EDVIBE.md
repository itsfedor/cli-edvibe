# EDVIBE.md — target analysis (GUI/Web-app -> CLI mapping)

## Software
- **edvibe.com** — "next-gen language teaching platform" (formerly ProgressMe).
  Micro-frontend SPA (module federation). No public API; everything runs over a
  private WebSocket RPC gateway.

## Architecture findings (Sep 2026, live)

### Transport
- Config `https://edvibe.com/appWebSettings.json` is AES-128-ECB encrypted
  (the decryption key is intentionally not reproduced here) — it decrypts to
  shell remotes + `apiUrl`/cloud config.
- Real API = WebSocket `wss://proxy-a.edvibe.com/websocket?token=<Auth-Token>`
  (proxy host differs by data cloud; edvibe.com runs cloud `edb-a`).
- **Auth-Token is a client-minted UUIDv4 cookie** — no server handshake needed
  to mint it.
- WS request: `{"Controller","Method","ProjectName","RequestId","Value":<json string>}`;
  response matches `RequestId`, has `IsSuccess/Value/ErrorMessage/ErrorCode`.

### Auth (all over the same WS, ProjectName "Users")
1. `AccountWsController.GetAccountRoles {Email,Password,Domain}` -> `[roleInt]`
2. `AccountWsController.Login {Email,Password,RememberMe,AuthToken,CurrentDomain,
   AccountRole,UserRole,ClientTime,DeviceType}` -> user profile.
   AccountRole: 0 Admin, 1 TeacherCurator, 2 Student, 3 PublisherAdmin.
   UserRole: 4 SchoolAdmin (teacher-ish), 1 Pupil, 6 PublisherAdmin.

### Materials domain (ProjectName "Books")
- `BookWsController.GetPersonalBooks {Page:{Skip,Take},IsInversion}` ->
  `{Items:[{Folder:{Id,Name,CountMaterials}} | {Book:{Id,Name,...}}]}`
- `BookWsController.GetSchoolBooks {FolderId?,Domain,SortClass,IsInversion}`
- `BookWsController.BookUpsert` -> new material id (a "Book"/учебник)
- `CourseWsController.GetBookCourses {BookId,TeacherId,Domain}` -> courses
- `LessonWsController.LessonUpsert` -> lesson id; lesson auto-creates a
  "Section 1" (`LessonWsController.GetLessonWithId` -> `Sections[]`)
- UI route: `/cabinet/school/materials/personal`, material editor
  `/cabinet/school/materials/book/<id>/content`, lesson editor
  `/lesson-editor/book/<b>/lesson/<l>/section/<s>`.

### Exercises (ProjectName "Exercises")
- `GetExerciseWsController.LoadExercises {IsTeacher,SectionId,LessonId,LessonSection}` ->
  `{SectionId, Items:[exercise]}`
- `SaveExerciseWsController.SaveExercise` with payload
  `{ClassId, Domain, ExerciseView:{...}, AiUsed:false, UsedNewConstructor:false,
   ClientTime, DeviceType}` -> saved exercise. (DTO wrapper `{Data,ClassId}` is
   NOT used by the editor — that combination 500s.)
- Exercise `Type 22` = Note: content block whose `Note.Text` holds arbitrary
  HTML (`<h3>/<p>/<ul>/<ol>/<em>...`), `Note.ShowToPupil:true`. This is the
  vehicle used to import HTML handouts.
- Type map seen: 2 Images (carousel gallery), 3 Videos, 4 Audio, 5 Test,
  6 MappingWords, 10 FillGaps-typed, 13 ChooseOption, 17 LabelPictures-drag,
  21 AddWordsToVocabulary, 22 Note, 23 BuildWordFromLetters (unscramble),
  25 Topic, 27 Pictures (vertical gallery), 30 AudioRecording (voice),
  32 ImagesGif, 33 MiroBoard, 34 GooglePDF, 35 Wordwall, 36 Learningapps,
  38 LabelPictures-fill, 39 LabelPictures-select, 41 Genially, 42 Baamboozle,
  43 Quizlet.

### Templates added Sep 2026 (docs + bundle recon, verified live)
- Full template list from the official help center (intercom.help/edvibe/en,
  "Lesson Builder 3.0"): 9 content templates, 14 exercise templates,
  7 integrations, AI Assistant. Implemented in `core/builders.py`:
  unscramble (23), audio (4), gif (32), label ×3 (17/38/39), integrations
  (33/34/35/36/41/42/43), pictures carousel (2), note colour 0-4
  (Blue/Yellow/Green/Red/Gray), test timer 1-90 min + per-question points ≤5,
  multilingual wordlist, voice `seconds`.
- Post-save attach flow: `ChangeExerciseImages` accepts a LIST of external
  URLs (pictures/gif/label blocks); audio = upload (MediaFile type 10) then
  `ChangeExerciseAudios` with the file ids.
- `Statistics`/`ScoringType`/`ConfigurationJson` on a test exercise are
  server-managed and silently dropped by SaveExercise (verified in three
  shapes) — per-question points live on `Test.Questions[].Points`.
- Label-pictures payload quirks: drag mode joins answers with `/` and escapes
  literal slashes as `&#47;`; select mode keeps plain `/` as the option
  separator with `*` marking the correct option.

## GUI action -> harness command mapping
| UI action | API | CLI |
|---|---|---|
| Log in (email+password) | GetAccountRoles + Login | `whoami` (lazy auth) |
| Materials page list | GetPersonalBooks | `materials list` |
| Create button -> dialog -> Create | BookUpsert | `materials create` |
| Open material -> Add a lesson -> dialog | LessonUpsert (+ auto section) | `lesson add` |
| Lesson editor -> Add exercise -> New/Standard builder -> Article/Note -> Save | SaveExerciseWsController.SaveExercise | `content add-note`, `import --html` |

## Backend rules
- The "real software backend" is the live WS API; no synthetic reimplementation.
- No delete/update commands exist on purpose (user mandate: never delete
  materials). Undo/redo is not supported by the target for these operations.
