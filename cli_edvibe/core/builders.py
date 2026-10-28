"""Transfer builders: content spec -> Edvibe ExerciseView payloads.

Each builder takes a normalized spec (see build_*) and returns an
ExerciseView dict ready for SaveExerciseWsController.SaveExercise.

Content templates:
  note      {html, name, hidden?}
  text      {html, name?}
Topic/article and hidden semantics verified empirically; see
cli_edvibe/tests/test_transfer_e2e.py.
"""
import datetime
import json
import random
import re
import time

EX_IMAGES = 2          # Pictures, carousel gallery layout
EX_VIDEO = 3
EX_AUDIO = 4
EX_TEST = 5
EX_MATCH = 6          # Match the words
EX_FILL_TYPED = 10    # Fill in the gaps (typed) - semantics verified Sep 2026
EX_CHOOSE = 13        # Choose the correct option
EX_TRUE_FALSE = 14
EX_WORD_ORDER = 15
EX_LABEL_DRAG = 17    # Label the pictures: drag and drop
EX_FILL_BOX = 18      # Fill in the gaps from the box
EX_SORT_COLUMNS = 19
EX_WORDLIST = 21
EX_NOTE = 22
EX_UNSCRAMBLE = 23    # Build a word from letters (docs: Template "Unscramble")
EX_TOPIC = 25
EX_WRITING = 26
EX_PICTURES = 27      # Pictures, vertical ("one after another") layout
EX_TEXT = 28
EX_BUTTON = 29       # external-link button ("Watch the episode" block)
EX_VOICE = 30
EX_DIVIDER = 31
EX_GIF = 32
EX_MIRO = 33          # Board by Miro
EX_GPDF = 34          # PDF from Google Drive
EX_WORDWALL = 35
EX_LEARNINGAPPS = 36
EX_ORDER_SENTENCES = 37  # Put the text in order
EX_LABEL_INPUT = 38   # Label the pictures: fill in the gaps
EX_LABEL_SELECT = 39  # Label the pictures: choose from the options
EX_GENIALLY = 41
EX_BAAMBOOZLE = 42
EX_QUIZLET = 43

# MediaFile type ids (media-files REST, verified from the app bundle):
#   8 = LessonExerciseImages, 10 = LessonExerciseAudios, 24 = Books (cover)
MEDIA_IMAGE = 8
MEDIA_AUDIO = 10

# Note background colors (the editor's 5 swatches, verified from the bundle
# AND live render: 0 Blue (--tir-brand), 1 Yellow (--tir-warn), 2 Green
# (--tir-success), 3 Red (--tir-danger), 4 Gray (--tir-second-100)).
NOTE_COLORS = {"blue": 0, "yellow": 1, "green": 2, "red": 3, "gray": 4,
               "grey": 4}

_HTML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                              '"': "&quot;"})

HIDDEN_MARK = ('<em class="hide-id-exercise-item">##{uid}##</em>')


def _esc(s):
    return str(s).translate(_HTML_ESCAPE)


_UID_SEEN = set()


def _uid():
    # unique within a builder process: the plain time+random formula collides
    # when several gaps are generated in the same millisecond (live lesson
    # 20354159 had 2 duplicate markers before this guard).
    while True:
        v = int(time.time() * 1000) + random.randint(0, 999)
        if v not in _UID_SEEN:
            _UID_SEEN.add(v)
            return v


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.datetime.now().microsecond // 1000:03d}"


def _base(etype, name, number, hidden=False, autocheck=False):
    """Shared envelope for an ExerciseView row."""
    view = {
        "Id": 0, "Number": number, "IsShowExerciseNumber": bool(name),
        "Name": name, "IsHideExercise": False, "IsHidePupil": hidden,
        "JsonData": json.dumps({"IsAutoCheck": autocheck}),
        "Type": etype, "Words": [], "PracticeNumber": 0,
        "inHomework": False, "IsLessonPage": False,
        "Images": [], "Videos": [], "VideosUrl": [],
        "Answers": {"Id": 0, "SelfSync": False, "IsSelf": False,
                    "IsReset": False, "IsHomework": False,
                    "IsHidePupil": False, "ExerciseId": 0, "PupilId": 0,
                    "Answers": [], "IsRightAnswer": False, "Status": 1,
                    "Version": 0, "SingleAnswer": {}, "ManyAnswers": [],
                    "RepeatingManyAnswers": []},
        "AnswerVersion1": [], "AnswersTeacher": [], "IsAutoCheck": autocheck,
        "Selections": [], "DateCreateHomeWork": "0001-01-01T00:00:00",
    }
    return view


# ------------------------------------------------------------ content blocks
def build_note(html, name="", hidden=False, number=0, lesson_id=None,
               section_id=None, color=None):
    view = _base(EX_NOTE, name, number, hidden=hidden)
    view["IsHidePupil"] = bool(hidden)  # live hidden notes carry both flags
    note = {"Id": 0, "Name": name, "Text": html,
            "ShowToPupil": not hidden, "VisibilityType": 1 if hidden else 0,
            "NoteType": 0, "Number": number, "ExerciseId": 0}
    if color is not None:
        note["Color"] = (NOTE_COLORS.get(str(color).strip().lower(), color)
                         if isinstance(color, str) else int(color))
    view["Note"] = note
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_text(html, name="", number=0, lesson_id=None, section_id=None):
    view = _base(EX_TEXT, name, number)
    view["Text"] = {"Text": html}
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_writing(instruction, task_html="", number=0, lesson_id=None,
                  section_id=None):
    view = _base(EX_WRITING, instruction, number)
    view["Essay"] = {"Id": 0, "Name": "", "PupilId": 0, "IsByPupil": False,
                     "New": False, "ExerciseId": 0}
    if task_html:
        view["Name"] = instruction  # instruction doubles as task line
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_test(instruction, questions, number=0, timer_min=None, points=True,
               lesson_id=None, section_id=None):
    """questions: [{'q': html, 'options': [html...], 'correct': [idx...],
                    'points': float?}]  (points <= 5, UI cap)

    timer_min: 1..90 (the editor dropdown offers exactly 1-90 minutes; docs).

    Per-question points are stored on Test.Questions[].Points (verified live:
    3/1 persist and read back). The Statistics/ScoringType/ConfigurationJson
    objects are server-managed: SaveExercise silently drops them in every
    form (int enum, string enum, top-level) - don't try to write them."""
    view = _base(EX_TEST, instruction, number, autocheck=True)
    tq = []
    for i, item in enumerate(questions):
        pts = float(item.get("points", 1.0) or 1.0)
        if pts > 5:  # docs + UI cap: max 5 points per answer
            pts = 5.0
        q = {"Id": _uid(), "Question": item["q"], "Points": pts,
             "Answers": item["options"],
             "QuestionAnswers": [("true" if j in item["correct"] else "")
                                 for j in range(len(item["options"]))]}
        tq.append(q)
    if timer_min is not None:
        timer_min = max(1, min(90, int(timer_min)))
    view["Test"] = {"IsEnabledTimer": timer_min is not None,
                    "TimerDuration": timer_min or 1,
                    "IsEnabledPoints": points, "Questions": tq}
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_word_order(instruction, sentences, number=0, lesson_id=None,
                     section_id=None):
    """sentences: list of correct-order token lists or '/'-joined strings."""
    view = _base(EX_WORD_ORDER, instruction, number, autocheck=True)
    items = []
    for s in sentences:
        toks = s.split("/") if isinstance(s, str) else list(s)
        perm = list(range(len(toks)))
        random.shuffle(perm)
        items.append({"Text": "/".join(toks), "Id": _uid(),
                      "SortIndexes": perm})
    view["QuestionWithCodingTexts"] = items
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_sort_columns(instruction, columns, number=0, lesson_id=None,
                       section_id=None):
    """columns: [{'title': str, 'words': [str...]}] - word lists must be
    disjoint across columns."""
    view = _base(EX_SORT_COLUMNS, instruction, number, autocheck=True)
    items = []
    for col in columns:
        items.append({"Group": col["title"],
                      "Words": "/".join(col["words"]),
                      "Ids": [0] * len(col["words"])})
    view["GroupWordsByColumns"] = {"Items": items}
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_order_sentences(instruction, sentences, number=0, lesson_id=None,
                          section_id=None):
    """sentences in correct order."""
    view = _base(EX_ORDER_SENTENCES, instruction, number, autocheck=True)
    items = [{"Id": _uid(), "Text": s} for s in sentences]
    view["SentencesInCorrectOrder"] = {"Items": items}
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


# ------------------------------------------------------ gap-based templates
def _gap_mark(payload, uid=None):
    """Internal Edvibe encoding of one gap: [payload<em>##uid##</em>]."""
    return f"[{payload}{HIDDEN_MARK.format(uid=uid or _uid())}]"


def _find_gaps(text):
    """Split a UI-syntax string with [..] gaps into html chunks + gap payloads.

    Returns list of chunks (html or gap dict) - NOT used for save payloads
    directly; UI-syntax parsing happens in build_fill_* via regex replace.
    """
    parts = []
    pos = 0
    for m in re.finditer(r"\[([^\]]*)\]", text):
        parts.append(text[pos:m.start()])
        parts.append({"payload": m.group(1)})
        pos = m.end()
    parts.append(text[pos:])
    return parts


def convert_gap_syntax(text):
    """Turn UI-paste syntax '[hint/answer]' / '[answer]' / '[a/b]' etc.
    into the internal gap encoding with hidden uid markers.

    UI syntax rules (Edvibe FAQ):
      [answer]            auto-checked gap
      [hint/answer]       hint + one correct answer
      [a1/a2]             several accepted answers
      [hint/a1/a2]        hint + several accepted
      [/a1/a2]            several accepted, no hint
    Internal payload keeps the same slash syntax (the renderer parses it).
    """
    out = []
    pos = 0
    for m in re.finditer(r"\[([^\]]*)\]", text):
        out.append(text[pos:m.start()])
        payload = m.group(1)
        out.append(_gap_mark(payload))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def _join_items(sentences, sep="<br><br>"):
    """All sentence lines live in ONE QuestionWithCodingTexts item (joined with
    <br>): the exercise renderer only draws the FIRST item of a multi-item
    list - verified live (single item + <br> renders every line, like the
    premium lessons do)."""
    return [{"Text": sep.join(sentences)}]


def build_fill_typed(instruction, sentences, number=0, lesson_id=None,
                     section_id=None, autocheck=True):
    """Fill in the gaps (typed). sentences use UI bracket syntax with hints
    or plain answers: 'I [am/be] tired [now].'"""
    view = _base(EX_FILL_TYPED, instruction, number, autocheck=autocheck)
    view["QuestionWithCodingTexts"] = _join_items(
        [convert_gap_syntax(s) for s in sentences])
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_choose_option(instruction, lines, number=0, lesson_id=None,
                        section_id=None):
    """Choose the correct option. lines: html with [opt1/opt2*/opt3] gaps
    (asterisk marks the correct option)."""
    view = _base(EX_CHOOSE, instruction, number, autocheck=True)
    view["QuestionWithCodingTexts"] = _join_items(
        [convert_gap_syntax(s) for s in lines])
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_fill_box(instruction, sentences, number=0, lesson_id=None,
                   section_id=None, autocheck=True):
    """Fill in the gaps from the box. Each [answer] becomes a draggable box
    item; the box is built from all gap answers. SortIndexes are shuffled to
    match live materials (the box items start in random order)."""
    view = _base(EX_FILL_BOX, instruction, number, autocheck=autocheck)
    converted = []
    uids = []
    for s in sentences:
        chunks = []
        pos = 0
        for m in re.finditer(r"\[([^\]]*)\]", s):
            chunks.append(s[pos:m.start()])
            uid = _uid()
            uids.append(uid)
            chunks.append(_gap_mark(m.group(1), uid))
            pos = m.end()
        chunks.append(s[pos:])
        converted.append("".join(chunks))
    sort_idx = list(range(len(uids)))
    random.shuffle(sort_idx)
    view["PasteWordByDrag"] = {"Text": "<br>".join(converted),
                               "SortIndexes": sort_idx}
    if not autocheck:  # live lesson-section shape (lesson "1 Burnt Food")
        view["JsonData"] = json.dumps({"PasteWordByDrag": view["PasteWordByDrag"],
                                       "IsAutoCheck": False}, ensure_ascii=False)
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_match(instruction, pairs, number=0, lesson_id=None, section_id=None):
    """Match the words. pairs: [(left, right), ...]."""
    lefts = [p[0] for p in pairs]
    rights = [p[1] for p in pairs]
    ids = [_uid() for _ in pairs]
    sort_idx = list(range(len(pairs)))
    random.shuffle(sort_idx)
    view = _base(EX_MATCH, instruction, number, autocheck=True)
    view["MappingWords"] = [{"Ids": ids, "LeftWords": lefts,
                             "RightWords": rights, "SortIndexes": sort_idx}]
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_true_false(instruction, statements, number=0, not_stated=False,
                     lesson_id=None, section_id=None, autocheck=True):
    """statements: [(text, True/False), ...] or (text, True/False/None).

    Answer encoding mirrors the live frontend (verified Sep 2026):
    True -> "true", False -> "", NotStated -> "NotStated"."""
    view = _base(EX_TRUE_FALSE, instruction, number, autocheck=autocheck)
    qs = []
    qa = []
    for text, val in statements:
        qs.append({"Question": text, "Id": _uid()})
        qa.append({True: "true", False: "", None: "NotStated"}[val])
    view["Questions"] = qs
    view["QuestionAnswers"] = qa
    view["TrueOrFalse"] = {"EnableNotStated": not_stated}
    if not autocheck:  # live lesson-section shape (lesson "1 Burnt Food")
        view["JsonData"] = json.dumps({
            "Questions": qs, "QuestionAnswers": qa, "IsAutoCheck": False,
            "TrueOrFalse": view["TrueOrFalse"]}, ensure_ascii=False)
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_button(name, link, text, number=0, lesson_id=None, section_id=None):
    """External-link button (Type 29) - the "watch the episode" block.

    Live shape (lesson "1 Burnt Food"): top-level Button {Link, Text} AND the
    same object inside JsonData; IsShowExerciseNumber stays off."""
    view = _base(EX_BUTTON, name, number)
    view["IsShowExerciseNumber"] = False
    btn = {"Link": link, "Text": text}
    view["Button"] = btn
    view["JsonData"] = json.dumps({"Button": btn, "IsAutoCheck": False},
                                  ensure_ascii=False)
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_pictures(name="", description="", number=0, lesson_id=None,
                   section_id=None, layout="vertical", descriptions=None):
    """Pictures block. Saved EMPTY; images attach after save via
    SaveExerciseWsController.ChangeExerciseImages (external-URL flow) -
    the only way a picture renders (raw <img> in note html is sanitized out).

    layout: "vertical" (Type 27, one after another, uncropped, extras behind
    the Show pictures button) or "carousel" (Type 2, horizontal gallery).
    descriptions: optional caption per image (list); `description` = single
    caption shorthand."""
    etype = EX_PICTURES if layout != "carousel" else EX_IMAGES
    view = _base(etype, name, number)
    view["Images"] = []
    view["ImagesJson"] = '{"Images":[]}'
    descs = (list(descriptions) if descriptions
             else ([description] if description else [""]))
    view["Descriptions"] = descs
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


# ------------------------------------------------------------------ wordlist
def build_wordlist(instruction, entries, number=0, lesson_id=None,
                   section_id=None, voice_language_id=1):
    """entries: [(word, translations), ...] (max 50).

    translations: a plain string (translation in the voice language) OR a
    dict/list of {LanguageId: text} for the multilingual mode (docs:
    'enable multilanguage translation'; students see the language of their
    profile). VoiceLanguageId picks the pronunciation voice (LanguageId enum:
    0=Ru 1=En 2=It 3=Es 4=De 5=Fr ... 99=Other)."""
    def _translations(tr):
        if isinstance(tr, dict):
            return [{"LanguageId": int(k), "Text": v} for k, v in tr.items()]
        if isinstance(tr, (list, tuple)) and tr and isinstance(tr[0], (list, tuple)):
            return [{"LanguageId": int(k), "Text": v} for k, v in tr]
        return [{"LanguageId": voice_language_id, "Text": tr}]

    view = _base(EX_WORDLIST, instruction, number)
    view["Words"] = []
    aw = []
    langs = set()
    multilingual = False
    for word, trans in entries:
        tr = _translations(trans)
        langs.update(t["LanguageId"] for t in tr)
        if len({t["LanguageId"] for t in tr}) > 1:
            multilingual = True
        view["Words"].append({"Id": 0, "Word": word, "Translations": tr,
                              "LanguageId": voice_language_id,
                              "ExerciseId": 0, "IsAdded": False})
        aw.append({"Id": 0, "Word": word, "Translations": tr,
                   "LanguageId": 0, "ExcerciseId": 0, "IsAdded": False,
                   "Number": 0})
    view["AddWordsToVocabulary"] = {
        "VoiceLanguageId": voice_language_id, "IsMultilingual": multilingual,
        "TranslationLanguages": sorted(langs) or [voice_language_id],
        "Words": aw}
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_video(instruction, link, number=0, lesson_id=None, section_id=None):
    """Video block (Type 3). link: YouTube share URL (youtu.be/...)."""
    vid = {"Text": "", "Link": link, "Type": 0, "Uploaded": None}
    jd = {
        "Videos": [vid], "VideosUrl": [], "QuestionManyAnswers": None,
        "Questions": None, "Descriptions": None, "QuestionAnswers": None,
        "Audios": None, "Test": None, "MappingWords": None,
        "NumbersByImages": None, "QuestionWithCodingTexts": None,
        "SpaceTextByImages": None, "MappingImageByDrag": None,
        "ImageInputCorrectWord": None, "ImageSelectCorrectWord": None,
        "PasteWordByDrag": None, "GroupWordsByColumns": None,
        "ChoiseExtraWords": None, "BuildWordFromLetters": None,
        "Text": None, "Button": None, "MiroBoard": None, "GooglePDF": None,
        "Wordwall": None, "Learningapps": None, "SentencesInCorrectOrder": None,
        "SelectRightWord": None, "AddWordsToVocabulary": None,
        "Paintings": None, "IsAutoCheck": False, "Note": None,
        "TrueOrFalse": None, "AudioRecording": None, "Pdfs": None,
    }
    view = _base(EX_VIDEO, instruction, number)
    view["JsonData"] = json.dumps(jd, ensure_ascii=False)
    view["Videos"] = [{"Text": "", "Link": link, "Type": 0}]
    view["VideosUrl"] = []
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


# ------------------------------------------------- new exercise templates
# Payload shapes verified from the live app bundles (exercises_shell,
# Sep 2026): save field names match the request class fields exactly.
_LINK_BLOCKS = {
    "miro": (EX_MIRO, "MiroBoard"),
    "googlepdf": (EX_GPDF, "GooglePDF"),
    "wordwall": (EX_WORDWALL, "Wordwall"),
    "learningapps": (EX_LEARNINGAPPS, "Learningapps"),
    "genially": (EX_GENIALLY, "Genially"),
    "baamboozle": (EX_BAAMBOOZLE, "Baamboozle"),
    "quizlet": (EX_QUIZLET, "Quizlet"),
}


def build_link_block(name, link, text="", block="miro", number=0,
                     lesson_id=None, section_id=None):
    """Integration templates (Miro board / Google-Drive PDF / Wordwall /
    LearningApps / Genially / Baamboozle / Quizlet): a link + optional
    description; the block renders as an embedded iframe."""
    etype, key = _LINK_BLOCKS[block]
    view = _base(etype, name, number)
    view[key] = {"Link": link, "Text": text}
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_miro(name, link, text="", number=0, lesson_id=None, section_id=None):
    return build_link_block(name, link, text, "miro", number, lesson_id, section_id)


def build_googlepdf(name, link, text="", number=0, lesson_id=None, section_id=None):
    return build_link_block(name, link, text, "googlepdf", number, lesson_id, section_id)


def build_wordwall(name, link, text="", number=0, lesson_id=None, section_id=None):
    return build_link_block(name, link, text, "wordwall", number, lesson_id, section_id)


def build_learningapps(name, link, text="", number=0, lesson_id=None, section_id=None):
    return build_link_block(name, link, text, "learningapps", number, lesson_id, section_id)


def build_genially(name, link, text="", number=0, lesson_id=None, section_id=None):
    return build_link_block(name, link, text, "genially", number, lesson_id, section_id)


def build_baamboozle(name, link, text="", number=0, lesson_id=None, section_id=None):
    return build_link_block(name, link, text, "baamboozle", number, lesson_id, section_id)


def build_quizlet(name, link, text="", number=0, lesson_id=None, section_id=None):
    return build_link_block(name, link, text, "quizlet", number, lesson_id, section_id)


def build_unscramble(instruction, words, number=0, lesson_id=None,
                     section_id=None, autocheck=True):
    """Unscramble (Type 23, UI: 'Unscramble'): students assemble the word from
    shuffled letters. words: [(word, hint)] or [{'word','hint'}]."""
    view = _base(EX_UNSCRAMBLE, instruction, number, autocheck=autocheck)
    items = []
    for w in words:
        if isinstance(w, dict):
            word, hint = w.get("word"), (w.get("hint") or "")
        else:
            word = w[0]
            hint = w[1] if len(w) > 1 and w[1] else ""
        items.append({"Id": _uid(), "Word": word, "Tip": hint})
    view["BuildWordFromLetters"] = items
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_audio(instruction, audios, number=0, lesson_id=None, section_id=None):
    """Audio block (Type 4). audios: [{'url','title','script'}].

    The Url must already exist in media storage (upload the mp3 with
    media file_type 10 / MEDIA_AUDIO first). After SaveExercise the files are
    bound via SaveExerciseWsController.ChangeExerciseAudios {ExerciseId,
    Ids:[fileId]} - see client.attach_audio_files()."""
    view = _base(EX_AUDIO, instruction, number)
    view["Audios"] = [{"Title": a.get("title", ""), "Url": a.get("url") or
                       a.get("src", ""), "Script": a.get("script", "")}
                      for a in audios]
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def build_gif(instruction, description="", number=0, lesson_id=None,
              section_id=None):
    """GIF block (Type 32). Saved EMPTY; the GIF attaches after save via
    ChangeExerciseImages (same flow as Pictures). Descriptions = caption(s)."""
    view = _base(EX_GIF, instruction, number)
    view["Images"] = []
    view["ImagesJson"] = '{"Images":[]}'
    view["Descriptions"] = [description] if description else []
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


def _escape_slash(s):
    """Label-pictures payloads join words with '/' - a literal slash in a word
    is escaped as &#47; (exactly how the editor does it)."""
    return (s or "").replace("/", "&#47;")


def build_label_pictures(instruction, items, mode="drag", number=0,
                         lesson_id=None, section_id=None):
    """Label the pictures - three variants (docs):

    mode="drag"   Type 17: words are dragged under the pictures.
    mode="fill"   Type 38: gaps under the pictures (typed).
    mode="choose" Type 39: dropdown options under each picture.

    items: [{'image': url, 'answer': 'word',  # drag/fill
             'options': 'a/b*/c'}]             # choose (star = correct)

    Images attach after save via ChangeExerciseImages in item order."""
    if mode == "drag":
        view = _base(EX_LABEL_DRAG, instruction, number, autocheck=True)
        view["MappingImageByDrag"] = {
            "Ids": [_uid() for _ in items],
            "ImagesCount": len(items),
            "Text": "/".join(_escape_slash(it.get("answer", "")) for it in items),
            "ImgIds": []}
    elif mode == "fill":
        view = _base(EX_LABEL_INPUT, instruction, number, autocheck=True)
        view["ImageInputCorrectWord"] = {"Items": [
            {"Id": _uid(), "Text": _escape_slash(it.get("answer", ""))}
            for it in items]}
    elif mode == "choose":
        view = _base(EX_LABEL_SELECT, instruction, number, autocheck=True)
        opts = []
        for it in items:
            o = it.get("options")
            if o is None:  # allow {'choices': [..], 'answer': 'x'}
                correct = it.get("answer", "")
                o = "/".join(f"{v}*" if v == correct else v
                             for v in it.get("choices", []))
            # NOTE: slashes here are the OPTION separators (FAQ star syntax
            # "a/b*/c") - unlike drag mode they are stored plain, exactly as
            # the editor does (verified in the bundle's save mapper).
            opts.append({"Id": _uid(), "Text": o})
        view["ImageSelectCorrectWord"] = {"Items": opts}
    else:  # pragma: no cover - spec validates the mode
        raise ValueError(f"unknown label mode {mode!r}")
    if lesson_id is not None:
        view["LessonId"] = lesson_id
        view["LessonSectionId"] = section_id
    return view


BUILDERS = {
    "note": build_note, "text": build_text, "writing": build_writing,
    "test": build_test, "wordorder": build_word_order,
    "sortcolumns": build_sort_columns, "ordersentences": build_order_sentences,
    "filltyped": build_fill_typed, "chooseoption": build_choose_option,
    "fillbox": build_fill_box, "match": build_match,
    "truefalse": build_true_false, "wordlist": build_wordlist,
    "video": build_video, "button": build_button, "pictures": build_pictures,
    "unscramble": build_unscramble, "audio": build_audio, "gif": build_gif,
    "label": build_label_pictures,
    "miro": build_miro, "googlepdf": build_googlepdf,
    "wordwall": build_wordwall, "learningapps": build_learningapps,
    "genially": build_genially, "baamboozle": build_baamboozle,
    "quizlet": build_quizlet,
}
