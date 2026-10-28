"""Offline tests for the test-english -> Edvibe converter. No network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli_edvibe.core import lesson_spec, test_english as te  # noqa: E402

EXPLANATION = """
<div id="tabli2-cont" class="tab-content">
<h2>The present simple of <strong>be</strong>: Form</h2>
<p><img src="https://test-english.com/staging11/wp-content/uploads/chart-form.png"></p>
<h6><a href="https://www.pinterest.com/pin/1/">Download full-size image</a></h6>
<p>The present simple of the verb<strong>&nbsp;be</strong>&nbsp;has three forms:</p>
<div class="infoblock">
‣ I&nbsp;<strong>am</strong>.<br>
‣ We/You/They<strong>&nbsp;</strong><strong>are</strong>.
</div>
<h4><strong>They</strong>= people and things</h4>
<p>We use <strong>he</strong> for a man.</p>
<p>We always need a <a href="https://test-english.com/grammar-points/a1/object-pronouns/">subject</a> before the verb.</p>
<ul class="grammar-ex">
<li><em><span style="color: #50af31;"><strong>It is</strong></span> cold. <img src="https://test-english.com/staging11/wp-content/uploads/correct.png"></em></li>
<li><em><strong><span>Is</span></strong> cold. <img src="https://test-english.com/staging11/wp-content/uploads/wrong.png"></em></li>
</ul>
<h2>The present simple of <strong>be</strong> – USE</h2>
<p><img src="https://test-english.com/staging11/wp-content/uploads/chart-use.png"></p>
<p>We use the verb&nbsp;<strong>be</strong> to talk about:</p>
<div class="textBox">
<p><strong>Age</strong>:<em> I&nbsp;<strong>am</strong> 24.</em></p>
<p><strong>Job:</strong><em> I&nbsp;<strong>am</strong> a teacher.</em></p>
</div>
<div><a href="https://test-english.pro/"><picture><img src="https://test-english.com/img/upgrade-to-Test-English-PRO-Banner-mobile.webp"></picture></a></div>
</div>
</li>
"""

PAGE_HTML_SELECT = """
<h3>Exercise 1</h3>
<h5>Choose the correct present simple forms of ‘to be’ for the gaps below.</h5>
<div id="watupro_quiz"><form action="" method="post" id="quiz-258">
<input type="hidden" name="quiz_id" value="258">
<input type="hidden" name="start_time" value="2026-09-11 00:56:30">
<input type="hidden" name="start_timestamp" value="1789088190">
<input type="hidden" name="watupro_questions" value="2242: | 2243:">
<div class="watu-question" id="question-1"><div id="questionWrap-1" class="watupro-question-id-2242">
<div class="question-content"><p><span class="watupro_num">1 </span>A: <select name="gap_2242_1" class="watupro-gap"><option value=""></option><option value="is">is</option><option value="Are">Are</option></select> you a teacher?  B: Yes, I <select name="gap_2242_2" class="watupro-gap"><option value=""></option><option value="am">am</option><option value="are">are</option></select>.</p>
<input type="hidden" name="question_id[]" id="qID_1" value="2242" class="watupro-question-id"><input type="hidden" id="answerType2242" value="gaps"><!-- end question-content--></div></div></div>
<div class="watu-question" id="question-2"><div id="questionWrap-2" class="watupro-question-id-2243">
<div class="question-content"><p><span class="watupro_num">2 </span>A: <select name="gap_2243_1" class="watupro-gap"><option value=""></option><option value="Are">Are</option><option value="Is">Is</option></select> your name Marcus?</p>
<input type="hidden" name="question_id[]" id="qID_2" value="2243" class="watupro-question-id"><!-- end question-content--></div></div></div>
</form></div>
"""

PAGE_HTML_TEXT = """
<h3>Exercise 2</h3>
<h5>Rewrite the sentences using the short forms of <em>be</em>.</h5>
<p><em>EXAMPLE: They are good friends ⇒ <span class="textGap">They’re</span> good friends.</em><br>
</p><div id="watupro_quiz"><form action="" method="post" id="quiz-259">
<input type="hidden" name="quiz_id" value="259">
<input type="hidden" name="watupro_questions" value="3584:">
<div class="watu-question" id="question-1"><div id="questionWrap-1" class="watupro-question-id-3584">
<div class="question-content"><p><span class="watupro_num">1 </span>She is fantastic ⇒ <input type="text" size="10" name="gap_3584_1" class="watupro-gap" value=""> fantastic. </p>
<input type="hidden" name="question_id[]" id="qID_1" value="3584" class="watupro-question-id"><!-- end question-content--></div></div></div>
</form></div>
"""

PAGE_SELECT = {
    "page": 1, "url": "u", "label": "Exercise 1",
    "instruction": "Choose the correct present simple forms of ‘to be’ for the gaps below.",
    "example_html": "",
    "questions": [
        {"qid": 2242, "text_html": "<p>A: [[1]] you a teacher?  B: Yes, I [[2]].</p>",
         "gaps": [{"n": 1, "kind": "select", "options": ["is", "Are"]},
                  {"n": 2, "kind": "select", "options": ["am", "are"]}],
         "correct": ["Are", "am"], "explanations": ["We use you + are.", "We use I + am."]},
    ],
}

PAGE_TEXT = {
    "page": 2, "url": "u2", "label": "Exercise 2",
    "instruction": "Rewrite the sentences using the short forms of be.",
    "example_html": "<p><em>EXAMPLE: They are good friends.</em><br></p>",
    "questions": [
        {"qid": 3584, "text_html": "<p>She is fantastic ⇒ [[1]] fantastic.</p>",
         "gaps": [{"n": 1, "kind": "text", "options": []}],
         "correct": ["She's"], "explanations": ["She is = she's"]},
    ],
}

DATA = {
    "source_url": "https://test-english.com/grammar-points/a1/x/",
    "lesson_title": "Present simple forms of ‘to be’: am/is/are",
    "explanation_html": EXPLANATION,
    "images": ["https://test-english.com/staging11/wp-content/uploads/chart-form.png"],
    "pages": [PAGE_SELECT, PAGE_TEXT],
}


def test_parse_quiz_markers_and_gaps():
    q = te.parse_quiz(PAGE_HTML_SELECT)
    assert q["quiz_id"] == 258
    assert q["instruction"].startswith("Choose the correct")
    qs = q["questions"]
    assert [x["qid"] for x in qs] == [2242, 2243]
    assert qs[0]["text_html"].startswith("<p>A: [[1]] you a teacher?")
    assert qs[0]["gaps"][1]["options"] == ["am", "are"]
    assert "watupro_num" not in qs[0]["text_html"]  # numbering span stripped
    t = te.parse_quiz(PAGE_HTML_TEXT)
    assert t["questions"][0]["gaps"][0]["kind"] == "text"
    assert t["example_html"].startswith("<p><em>EXAMPLE:")
    assert t["instruction"] == "Rewrite the sentences using the short forms of be."


def test_parse_feedback_shape():
    resp = ("<div class='watupro-choices-columns show-question watupro-unresolved'>"
            "<div class='show-question-content'>q</div>"
            "<div class='watupro-main-feedback feedback-incorrect'>"
            "<span style=\"color: #50af31;\">Correct answers: Are/am</span><br />"
            "‣ We use you + <strong>are</strong>.<br />‣ We use I + <strong>am</strong>."
            "</div><!--end-watupro-feedback--></div>")
    fb = te.parse_feedback(resp)
    assert fb[0]["gap_answers"] == [["Are"], ["am"]]      # per gap, in order
    assert fb[0]["correct"] == ["Are"]
    assert fb[0]["explanations"] == ["We use you + are.", "We use I + am."]


def test_explanation_exercises_shape():
    exs = te.explanation_exercises(EXPLANATION)
    kinds = [e["type"] for e in exs]
    # chart -> titled text -> chart -> titled text
    assert kinds == ["pictures", "text", "pictures", "text"]
    assert exs[0]["image"].endswith("chart-form.png")
    assert exs[0]["name"] == ""          # pictures must stay unnamed (no number)
    assert exs[1]["name"] == "The present simple of be: Form"
    assert exs[3]["name"] == "The present simple of be – USE"
    body = exs[1]["html"]
    assert "▎ I <b>am</b>." in body                 # infoblock line, site's ‣ dropped
    assert "They = people and things" in body      # '=' spaced
    assert "▎" in body and "background-color" in body  # infoblock callout
    assert te.PAL_HEAD in body                     # h4 in the heading colour
    assert f'<span style="color:{te.PAL_GREEN}">✓</span>' in body
    assert f'<span style="color:{te.PAL_RED}">✗</span>' in body
    assert "upgrade-to-Test-English" not in "".join(e.get("html", "") for e in exs)
    use = exs[3]["html"]
    assert "Age" in use and "Job:" in use
    assert all(e.get("show_number") is False for e in exs)


def test_page_exercise_choose_and_fill():
    choose = te.page_exercise(PAGE_SELECT)
    assert choose["type"] == "chooseoption"
    # a one-question dialogue page: no '1.' prefix, speakers bold
    assert choose["lines"][0].startswith("<b>A:</b> ")
    assert "<b>1.&nbsp;</b>" not in choose["lines"][0]
    assert "<b>B:</b> Yes, I" in choose["lines"][0]
    assert "[is/Are*] you a teacher?" in choose["lines"][0]
    assert "[am*/are]" in choose["lines"][0]
    fill = te.page_exercise(PAGE_TEXT)
    assert fill["type"] == "filltyped"
    # the site's EXAMPLE line is the first body line, styled (house panel)
    first = fill["sentences"][0]
    assert "They are good friends." in first
    assert "background-color: rgb(241, 249, 254)" in first
    assert "Example:" in first
    # case-only variants and straight/curly apostrophe twins are gone
    # (the Edvibe checker is case-insensitive and normalises ’ ‘ -> ')
    assert "[/She's]" in fill["sentences"][1]
    assert "She\u2019s" not in fill["sentences"][1]
    assert "she's" not in fill["sentences"][1]
    assert "EXAMPLE" not in fill["instruction"]
    # a one-question page's text needs no '1.' prefix
    assert "<b>1.&nbsp;</b>" not in fill["sentences"][1]


DLG_PAGE = {          # dialogue page: one numbered site question per turn
    "page": 3, "url": "u3", "label": "Exercise 3",
    "instruction": "Complete this job interview with can, can’t and the words in brackets.",
    "example_html": "",
    "questions": [
        {"qid": 3940, "text_html": "<p>Interviewer: [[1]] (you/drive)?</p>",
         "gaps": [{"n": 1, "kind": "text", "options": []}],
         "correct": ["Can you drive"], "explanations": ["can + subject + verb"]},
        {"qid": 3941,
         "text_html": "<p>Ann: Yes, I [[1]]. I have a driving license and a car.</p>",
         "gaps": [{"n": 1, "kind": "text", "options": []}],
         "correct": ["can"], "explanations": ["short answers"]},
    ],
}

MULTI_PARA_PAGE = {   # one text in several paragraphs (site: <p class=...>)
    "page": 4, "url": "u4", "label": "Exercise 4",
    "instruction": "Complete the postcard with the verbs in brackets.",
    "example_html": "",
    "questions": [
        {"qid": 4000,
         "text_html": ("<p>Dear Kate,</p><p>I [[1]] (write) from New York. "
                       "Right now I [[2]] (sit) in a coffee shop in Manhattan.</p>"),
         "gaps": [{"n": 1, "kind": "text", "options": []},
                  {"n": 2, "kind": "text", "options": []}],
         "correct": ["am writing", "am sitting"], "explanations": []},
    ],
}

LIST_PAGE = {         # ordinary numbered list page: numbering must stay
    "page": 1, "url": "u5", "label": "Exercise 1",
    "instruction": "Fill in the gaps with the verbs in brackets.",
    "example_html": "",
    "questions": [
        {"qid": 4061, "text_html": "<p>I [[1]] (study) all night yesterday.</p>",
         "gaps": [{"n": 1, "kind": "text", "options": []}],
         "correct": ["studied"], "explanations": ["regular past"]},
        {"qid": 4062, "text_html": "<p>We [[1]] (play) poker after dinner.</p>",
         "gaps": [{"n": 1, "kind": "text", "options": []}],
         "correct": ["played"], "explanations": ["regular past"]},
    ],
}


def test_dialogue_page_renders_as_a_script():
    ex = te.page_exercise(DLG_PAGE)
    assert ex["type"] == "filltyped"
    # no per-turn numbers, bold speaker labels, answers intact
    assert ex["sentences"][0].startswith("<b>Interviewer:</b> ")
    assert ex["sentences"][1].startswith("<b>Ann:</b> ")
    assert "<b>1.&nbsp;</b>" not in ex["sentences"][0]
    assert "[/Can you drive]" in ex["sentences"][0]


def test_single_long_text_keeps_paragraphs_without_numbering():
    ex = te.page_exercise(MULTI_PARA_PAGE)
    body = ex["sentences"][0]
    assert "<b>1.&nbsp;</b>" not in body
    assert body.startswith("Dear Kate,<br><br>I ")     # greeting line kept
    assert "[/am writing]" in body


def test_plain_list_pages_keep_numbering():
    ex = te.page_exercise(LIST_PAGE)
    assert ex["sentences"][0].startswith("<b>1.&nbsp;</b> ")
    assert ex["sentences"][1].startswith("<b>2.&nbsp;</b> ")
    assert "<b>" not in ex["sentences"][0].replace("<b>1.&nbsp;</b>", "")


def test_answer_note_hidden_with_explanations():
    note = te.answer_note(PAGE_SELECT)
    assert note["hidden"] is True and note["show_number"] is False
    assert note["name"] == "Answer key — Exercise 1"
    assert f'<span style="color: {te.PAL_GREEN}">Are / am</span>' in note["html"]
    assert "We use you + are. We use I + am." in note["html"]


def test_builders_join_into_one_item():
    """The renderer draws only the FIRST QuestionWithCodingTexts item -
    builders must join every line into one item (verified live)."""
    from cli_edvibe.core import builders as B
    v = B.build_fill_typed("t", ["A [x].", "B [y]."])
    q = v["QuestionWithCodingTexts"]
    assert len(q) == 1
    assert "A [x<em" in q[0]["Text"] and "B [y<em" in q[0]["Text"]
    assert "<br><br>" in q[0]["Text"]
    v2 = B.build_choose_option("t", ["l1 [a*/b]", "l2 [c*/d]"])
    assert len(v2["QuestionWithCodingTexts"]) == 1
    assert "l1 [a*/b<em" in v2["QuestionWithCodingTexts"][0]["Text"]


def test_build_spec_validates():
    spec = te.build_spec(DATA, pages=(1, 2))
    assert [s["name"] for s in spec["sections"]] == ["Explanation", "Exercises"]
    assert lesson_spec.validate(spec) == []
    plan = lesson_spec.plan(spec)
    assert plan["total_exercises"] == 5  # 1 explanation (single) + 4 exercises
    names = [e["name"] for s in spec["sections"] for e in s["exercises"]
             if e["type"] == "note"]
    assert names == ["Answer key — Exercise 1", "Answer key — Exercise 2"]


def test_single_explanation_inline_images_and_links():
    """The default Explanation is ONE text exercise: the site's h2/h4 stay
    inline, both charts become IMG: comment blocks, links stay clickable."""
    spec = te.build_spec(DATA, pages=(1, 2))
    exs = spec["sections"][0]["exercises"]
    assert len(exs) == 1 and exs[0]["type"] == "text"
    body = exs[0]["html"]
    assert body.count("<!--IMG:") == 2
    assert "chart-form.png;CX:;CY:;CW:;CH:;W:" in body
    assert "chart-use.png;CX:;CY:;CW:;CH:;W:" in body
    assert "</span></b>" in body                        # inline headings
    assert "The present simple of be: Form" in body
    assert "The present simple of be – USE" in body
    # links to test-english are never emitted; the label text stays
    assert "{subject|" not in body and "subject</" not in body
    assert "We always need a subject before the verb." in body
    # the site's green span around the key form is preserved
    assert '<span style="color: #50af31"><b>It is</b></span>' in body
    assert "▎ I <b>am</b>." in body                     # infoblock kept
    assert f'<span style="color:{te.PAL_GREEN}">✓</span>' in body
    assert '<span style="color: #1A8EC1">▎</span>' in body        # blue lists
    assert "background-color: rgb(241, 249, 254)" in body          # blue panel fill
    assert '<span style="color: #CDD3DA">▎</span>' in body        # gray use-panel
    assert "background-color: rgb(249, 249, 250)" in body
    assert "upgrade-to-Test-English" not in body
    assert exs[0]["show_number"] is False


def test_split_variants_site_notation():
    assert te._split_variants("She isn't/She's not") == ["She isn't", "She's not"]
    assert te._split_variants("are not (aren't/'re not)") == \
        ["are not", "aren't", "'re not"]
    assert te._split_variants("Are") == ["Are"]


def test_parse_feedback_multigap_groups():
    """Page-3 style: one short feedback block for a 2-gap question; the '...'
    splits the gaps' answer groups."""
    resp = ("<div class='watupro-choices-columns show-question watupro-unresolved'>"
            "<div class='watupro-main-feedback feedback-incorrect'>"
            "<span style='color: #50af31;'>Correct answer: She isn't/She's not"
            " ... Is she</span><br />"
            "‣ She is not= <strong>she isn't</strong>.<br />"
            "‣ In questions we use <strong>be</strong>."
            "</div><!--end-watupro-feedback--></div>")
    fb = te.parse_feedback(resp)
    assert fb[0]["gap_answers"] == [["She isn't", "She's not"], ["Is she"]]
    assert fb[0]["correct"] == ["She isn't", "She's not"]
    assert len(fb[0]["explanations"]) == 2


def test_parse_feedback_numbox_per_gap():
    """Page-4 style: one numbered block per gap, each with its own answer
    and explanation."""
    resp = ("<div class='watupro-choices-columns show-question watupro-unresolved'>"
            "<div class='watupro-main-feedback'><h4>Feedback</h4>"
            "<p><span class=\"numBox\">1</span> "
            "<span style='color: #50af31;'>Correct answer: Are</span></p>"
            "<p>‣ We use you + <strong>are</strong>.</p><hr />"
            "<p><span class=\"numBox\">2</span> "
            "<span style='color: #50af31;'>Correct answer: are not "
            "(aren't/'re not)</span></p>"
            "<p>‣ Are not= <strong>aren't</strong>.</p><hr />"
            "</div><!--end-watupro-feedback--></div>")
    fb = te.parse_feedback(resp)
    assert fb[0]["gap_answers"] == [["Are"], ["are not", "aren't", "'re not"]]
    ge = dict(fb[0]["gap_explanations"])
    assert ge[1] == ["We use you + are."]
    assert ge[2] == ["Are not= aren't."]


def test_gapify_uses_site_variants():
    q = {"text_html": "<p>She is a teacher. ⇒ [[1]] a teacher. ⇒ [[2]] a teacher?</p>",
         "gaps": [{"n": 1, "kind": "text"}, {"n": 2, "kind": "text"}],
         "correct": ["She isn't", "Is she"],
         "gap_answers": [["She isn't", "She's not"], ["Is she"]]}
    t = te._gapify_text(q)
    assert t.count("[/") == 2
    assert "She isn't" in t and "She's not" in t and "Is she" in t


def test_gapify_unwraps_div_wrappers():
    # the site wraps some question sentences in <div> (this/that/these/those
    # Ex 1.2); Edvibe renders <div> as a block, which doubles the blank lines
    # between questions. Wrappers must be unwrapped to inline text.
    q = {"text_html": "<div>'What's [[1]]?' 'It's a calculator.' </div>",
         "gaps": [{"n": 1, "kind": "select", "options": ["this", "these"]}],
         "correct": ["this"], "gap_answers": [["this"]]}
    t = te._gapify_select(q)
    assert "<div" not in t and "</div>" not in t
    assert " <br>" not in t
    assert t == "'What's [this*/these]?' 'It's a calculator.'"
    # adjacent divs keep their intended line break as a single <br>
    assert te._strip_wrappers("<div>a</div><div>b</div>") == "a<br>b"


def test_answer_note_per_gap_rows():
    page = {"page": 4, "label": "Exercise 4", "questions": [
        {"correct": ["Are"], "explanations": [],
         "gap_answers": [["Are"], ["are not", "aren't"]],
         "gap_explanations": [[1, ["We use you + are."]],
                              [2, ["We use we + are."]]]}]}
    note = te.answer_note(page)
    assert '<b>1.&nbsp;</b>' in note["html"] and '<b>2.&nbsp;</b>' in note["html"]
    assert "Are</span> — We use you + are." in note["html"]
    assert "are not / aren't</span> — We use we + are." in note["html"]


def test_variants_single_canonical_form():
    """Typed-gap variants: ONE canonical form per meaning - no straight/curly
    apostrophe twins (the Edvibe checker normalises ’ and ‘ to ' itself,
    verified in the live frontend), no case-only duplicates."""
    assert te._variants("I'm not") == ["I'm not"]
    assert te._variants("She's") == ["She's"]
    assert te._variants("Will she be") == ["Will she be"]
    assert te._variants("won't pass") == ["won't pass"]


PAGE_HTML_RADIO = """
<h3>Exercise 2</h3>
<h5>Choose the correct forms to complete these sentences.</h5>
<div id="watupro_quiz"><form action="" method="post" id="quiz-475">
<input type="hidden" name="watupro_questions" value="4143:">
<div class="watu-question" id="question-1"><div id="questionWrap-1" class="watupro-question-id-4143">
<div class="question-content"><div><span class="watupro_num">1 </span>In my street, _____ a bakery.</div><input type="hidden" name="question_id[]" value="4143"><input type="hidden" id="answerType4143" value="radio"><!-- end question-content--></div><div class="question-choices watupro-choices-columns" id="questionChoices4143"><div class="watupro-question-choice watupro-ansnum" dir="auto"><i>A.</i><input type="radio" name="answer-4143[]" id="answer-id-6012" class="answer answerof-4143" value="6012"><label for="answer-id-6012" id="answer-label-6012" class="answer"><span>there's</span></label></div><div class="watupro-question-choice watupro-ansnum" dir="auto"><i>B.</i><input type="radio" name="answer-4143[]" id="answer-id-6013" class="answer answerof-4143" value="6013"><label for="answer-id-6013" id="answer-label-6013" class="answer"><span>there are</span></label></div><!-- end question-choices--></div><!-- end questionWrap--></div></div>
</form></div>
"""


def test_radio_parse_and_convert():
    q = te.parse_quiz(PAGE_HTML_RADIO)
    qs = q["questions"]
    assert qs[0]["gaps"] == []
    assert qs[0]["choices"] == ["there's", "there are"]
    assert "_____ " in qs[0]["text_html"]
    # feedback: correct-answer li + no "Correct answer:" span -> explanation only
    resp = ("<div class='watupro-choices-columns show-question watupro-unresolved'>"
            "<div class='show-question-content'>q</div>"
            "<div class='show-question-choices'><ul>"
            "<li class='answer correct-answer'><span class='answer'>A. there's</span>"
            "<span class=\"watupro-screen-reader\">correct</span></li>"
            "<li class='answer'><span class='answer'>B. there are</span></li>"
            "</ul></div>"
            "<div class='watupro-main-feedback'>‣ We use <strong>there is</strong> + a singular.</div>"
            "<!--end-watupro-feedback--></div>")
    fb = te.parse_feedback(resp)
    assert fb[0]["correct"] == ["there's"]
    assert fb[0]["explanations"] == ["We use there is + a singular."]
    page = {"page": 2, "label": "Exercise 2", "instruction": "Choose the correct forms.",
            "example_html": "", "questions": qs}
    page["questions"][0]["correct"] = ["there's"]
    page["questions"][0]["explanations"] = ["We use there is + a singular."]
    ex = te.page_exercise(page)
    assert ex["type"] == "chooseoption"
    assert "[there's*/there are]" in ex["lines"][0]
    assert "_____" not in ex["lines"][0]
    note = te.answer_note(page)
    assert "there's" in note["html"] and "We use there is" in note["html"]


def test_level_from_url():
    assert te.level_from_url("https://test-english.com/grammar-points/b1+/x/") == "B1+"
    assert te.level_from_url("https://test-english.com/grammar-points/a1/x/") == "A1"


def test_pictures_builder_shape():
    from cli_edvibe.core import builders as B
    view = B.build_pictures("", "", number=0)
    assert view["Type"] == 27
    assert view["Images"] == [] and view["ImagesJson"] == '{"Images":[]}'
    assert view["Descriptions"] == [""]


def test_chart_img_inside_text_paragraph_is_extracted():
    """The site nests chart imgs inside mixed <p>text…<img chart></p> blocks;
    the splitter must keep BOTH the text runs and the image, in order."""
    html = (
        "<h2>Present simple form</h2>"
        "<p>We use <strong>do/does</strong> in questions.<br> <br>"
        "<img src='https://cdn/x-form.png' width='700'></p>"
        "<p><img src='https://cdn/only-img.png'></p>"
        "<p>Text with an inline icon "
        "<img src='https://cdn/correct.png' width='16'> still one paragraph.</p>"
        "<p>Tail text after the chart.</p>"
    )
    parser = te._TreeBuilder()
    parser.feed(html)
    blocks = te._extract_blocks(parser.root, [])
    kinds = [b["k"] for b in blocks]
    assert kinds == ["h", "p", "img", "img", "p", "p"], kinds
    assert blocks[1]["html"].startswith("We use")
    assert blocks[2]["src"] == "https://cdn/x-form.png"
    assert blocks[3]["src"] == "https://cdn/only-img.png"
    # the icon image must stay inline (rendered as the green ✓ mark)
    assert "✓" in blocks[4]["html"] and "correct.png" not in blocks[4]["html"]


def test_explanation_exercise_keeps_mixed_paragraph_chart():
    html = ("<h2>Form</h2><p>Intro text.<br><br>"
            "<img src='https://cdn/chart.png'></p>")
    ex = te.explanation_exercise(html, dims={"https://cdn/chart.png": (640, 480)})
    assert "<!--IMG:https://cdn/chart.png;" in ex["html"]
    assert "W:640;H:480" in ex["html"]
    assert "Intro text." in ex["html"]


def test_parse_feedback_font_layout():
    """The dominant MISSED layout: <font color="#50af31">Correct answer …</font>."""
    resp = ("<div class='watupro-choices-columns show-question watupro-unresolved'>"
            "<div class='show-question-content'>q</div>"
            "<div class='watupro-main-feedback feedback-incorrect'>"
            "<font color=\"#50af31\">Correct answer: won't pass (will not pass)"
            "</font><br /> ‣ We use <strong>will</strong> for future.</div>"
            "<!--end-watupro-feedback--></div>")
    fb = te.parse_feedback(resp)
    assert fb[0]["gap_answers"] == [["won't pass", "will not pass"]]
    assert fb[0]["explanations"] == ["We use will for future."]


def test_parse_feedback_labeled_gaps_win_over_numbox():
    """Mixed layout: '(Nth gap)' labels live in the same block as a numBox
    marker (page-global numbering must not hijack them)."""
    resp = ("<div class='watupro-choices-columns show-question watupro-unresolved'>"
            "<div class='show-question-content'>q<span class=\"numBox\">11</span>x</div>"
            "<div class='watupro-main-feedback feedback-incorrect'>"
            "<span style=\"color: #50af31;\">Correct answer (1st gap): "
            "have been making ('ve been making)</span></p>"
            "<p>‣ cont expl.</p><p><span class=\"numBox\">11</span> "
            "<span style=\"color: #50af31;\">Correct answer (2nd gap): "
            "have made ('ve made)</span></p>"
            "<p>‣ simple expl.</p></div><!--end-watupro-feedback--></div>")
    fb = te.parse_feedback(resp)
    assert fb[0]["gap_answers"] == [["have been making", "'ve been making"],
                                    ["have made", "'ve made"]]
    assert fb[0]["explanations"] == ["cont expl.", "simple expl."]


def test_parse_feedback_split_span_answer():
    """The answer text can sit in a SEPARATE span right after 'Correct answer: '."""
    resp = ("<div class='watupro-choices-columns show-question watupro-unresolved'>"
            "<div class='watupro-main-feedback'>"
            "<span style=\"color: #50af31;\">Correct answer: </span>"
            "<span style=\"color: #50af31;\">It/it</span><br />"
            "‣ We use it for weather.</div><!--end-watupro-feedback--></div>")
    fb = te.parse_feedback(resp)
    assert fb[0]["gap_answers"] == [["It"], ["it"]]
    assert fb[0]["explanations"] == ["We use it for weather."]


def test_parse_feedback_pool_page_global_numbers():
    """Dialogue pages: the trailing Feedback pool numbers answers across the
    whole page; apply_feedback maps each number to the question whose text
    carries the same numBox mark."""
    resp = ("<div class='watupro-choices-columns show-question watupro-unresolved'>"
            "<div class='show-question-content'>D1 <span class=\"numBox\">1</span> "
            "<span class=\"user-answer wrong-gap-answer\">zzz</span></div>"
            "</div>"
            "<div class='watupro-choices-columns show-question watupro-unresolved'>"
            "<div class='show-question-content'>D2 <span class=\"numBox\">2</span> "
            "<span class=\"user-answer wrong-gap-answer\">zzz</span></div>"
            "<p><!--watupro-feedback--></p>"
            "<div class='watupro-main-feedback'><h4>Feedback</h4>"
            "<p><span class=\"numBox\">1</span> "
            "<span style=\"color: #50af31;\">Correct answer: anyone</span></p>"
            "<p>‣ expl one.</p><hr />"
            "<p><span class=\"numBox\">2</span> "
            "<span style=\"color: #50af31;\">Correct answer: anything</span></p>"
            "<p>‣ expl two.</p></div><!--end-watupro-feedback--></div>")
    fb = te.parse_feedback(resp)
    qs = [{"qid": 1,
           "raw_html": "D1 <span class=\"numBox\">1</span><input name=\"gap_1_1\">"},
          {"qid": 2,
           "raw_html": "D2 <span class=\"numBox\">2</span><input name=\"gap_2_1\">"}]
    te.apply_feedback(qs, fb)
    assert qs[0]["gap_answers"] == [["anyone"]]
    assert qs[1]["gap_answers"] == [["anything"]]


def test_clean_example_script_junk_and_glue_repair():
    ex = ('<script>var s = d.getElementsByTagName(s)[0];</script>'
          '<div class="textBox">be <del>(x2)</del> – come – win (x2)</div>'
          '<p><em>EXAMPLE: Sentence ⇒ <span class="textGap">Will she pass</span>'
          'the exam? (she/pass)</em><br></p>')
    out = te._clean_example(ex)
    assert "<script" not in out
    assert "pass the exam?" in out            # missing space repaired
    assert "passthe" not in out
    assert "<s>(x2)</s>" in out               # <del> -> <s> (renders)
    assert "background-color: rgb(249, 249, 250)" in out   # word box panel
    assert "background-color: rgb(241, 249, 254)" in out   # example panel
    assert "Example:" in out


def test_gapify_radio_multiblank_columns():
    q = {"text_html": "<p>_______ 's cold; _______ 's snowing.</p>",
         "choices": ["It / it", "It / there", "There / it", "There / there"],
         "correct": ["It / there"], "gaps": []}
    t = te._gapify_radio(q)
    assert t.count("[") == 2
    assert "[It*/There]" in t
    assert "[it/there*]" in t


def test_gapify_radio_single_word_two_blanks():
    q = {"text_html": "<p>He paid _____ the meal and she paid _____ the taxi.</p>",
         "choices": ["to", "for", "-", "of"], "correct": ["for"], "gaps": []}
    t = te._gapify_radio(q)
    assert t.count("[") == 2
    assert t.count("for*") == 2


def _radio_page(*qs):
    return {"page": 2, "label": "Exercise 2",
            "instruction": "Choose the correct options.", "example_html": "",
            "questions": list(qs)}


def test_radio_no_blank_page_becomes_test():
    q = {"text_html": "<div>Which sentence is correct?</div>",
         "text": "Which sentence is correct?",
         "choices": ["Our teacher is often late.", "Our teacher often is late.",
                     "Often our teacher is late."],
         "correct": ["Our teacher is often late."], "gaps": []}
    ex = te.page_exercise(_radio_page(q))
    assert ex["type"] == "test"
    assert ex["points"] is False
    assert len(ex["questions"]) == 1
    tq = ex["questions"][0]
    assert tq["q"] == "Which sentence is correct?"
    assert tq["correct"] == [0]
    assert len(tq["options"]) == 3


def test_radio_choose_two_page_becomes_test_with_two_flags():
    q = {"text_html": "<div>We don't have a dog _____. Choose TWO correct answers.</div>",
         "text": "We don't have a dog _____. Choose TWO correct answers.",
         "choices": ["any longer", "anymore", "no longer"],
         "correct": ["any longer", "anymore"], "gaps": []}
    ex = te.page_exercise(_radio_page(q))
    assert ex["type"] == "test"
    assert ex["questions"][0]["correct"] == [0, 1]


def test_radio_mixed_page_is_one_test():
    nb = {"text_html": "<div>Which TWO sentences are correct?</div>",
          "text": "Which TWO sentences are correct?",
          "choices": ["I fixed my watch myself.", "I myself fixed my watch."],
          "correct": ["I fixed my watch myself.", "I myself fixed my watch."],
          "gaps": []}
    wb = {"text_html": "<div>Tom _____ to the radio.</div>",
          "text": "Tom _____ to the radio.",
          "choices": ["never listens", "doesn't never listen"],
          "correct": ["never listens"], "gaps": []}
    ex = te.page_exercise(_radio_page(nb, wb))
    assert ex["type"] == "test"
    assert [q["correct"] for q in ex["questions"]] == [[0, 1], [0]]


def test_radio_pair_option_matching_normalized():
    nb = {"text_html": "<div>Which sentence is correct?</div>",
          "text": "Which sentence is correct?",
          "choices": ["A", "B"], "correct": ["A"], "gaps": []}
    pair = {"text_html": "<div>I usually _________ to work, but this week I_________.</div>",
            "text": "I usually _________ to work, but this week I_________.",
            "choices": ["drive / walk", "drive / 'm walking"],
            "correct": ["drive / 'm walking"], "gaps": []}
    ex = te.page_exercise(_radio_page(nb, pair))
    assert ex["type"] == "test"
    assert ex["questions"][1]["correct"] == [1]


def test_paren_site_answer_raises_without_override():
    import pytest
    q = {"text_html": "<p>She is full of energy. (always) \u21d2 She [[1]].</p>",
         "gaps": [{"n": 1, "kind": "text", "options": []}],
         "gap_answers": [["is ('s) always full of energy"]],
         "correct": ["is ('s) always full of energy"]}
    with pytest.raises(ValueError):
        te._gapify_text(q)
    te._check_no_paren_answers(["clean answer", "'s clean"])
    with pytest.raises(ValueError):
        te._check_no_paren_answers(["clean", "thing (that"])


def test_override_variants_flow_with_apostrophe_twins():
    q = {"text_html": "<p>She is full of energy. (always) \u21d2 She [[1]].</p>",
         "gaps": [{"n": 1, "kind": "text", "options": []}],
         "gap_answers": [["is always full of energy", "'s always full of energy"]],
         "correct": ["is always full of energy"]}
    t = te._gapify_text(q)
    assert "is always full of energy" in t
    assert "'s always full of energy" in t
    assert "\u2019s always full of energy" not in t  # no curly twin
    assert "is ('s)" not in t  # no parenthesized variant survives


# ------- 3fix: instruction extraction / shared-stem / merged radio options -------

PAGE_HTML_NO_H3 = """
<h2>50 common Noun + Preposition collocations</h2>
<h5>Fill in the gaps with a suitable preposition.</h5>
<p><em>EXAMPLE: Tom had an argument <span class="textGap">with</span> his sister.</em><br></p>
<div id="watupro_quiz"><form action="" method="post" id="quiz-999">
<input type="hidden" name="quiz_id" value="999">
<input type="hidden" name="watupro_questions" value="9001:">
<div class="watu-question" id="question-1"><div id="questionWrap-1" class="watupro-question-id-9001">
<div class="question-content"><p><span class="watupro_num">1 </span>The increase <input type="text" size="10" name="gap_9001_1" class="watupro-gap" value=""> fuel prices.</p>
<!-- end question-content--></div></div></div>
</form></div>
"""

PAGE_HTML_H5_AFTER_EXAMPLE = """
<h2>So, such (a), so much, so many</h2>
<h3>Exercise 3</h3>
<p><em>EXAMPLE: He was very boring. I almost fell asleep. &#8658; He was <span class="textGap">so boring</span> that I almost fell asleep.</em></p>
<h5>Rewrite the sentences using so, such (a), so much, so many.</h5>
<div id="watupro_quiz"><form action="" method="post" id="quiz-1000">
<input type="hidden" name="quiz_id" value="1000">
<input type="hidden" name="watupro_questions" value="9002:">
<div class="watu-question" id="question-1"><div id="questionWrap-1" class="watupro-question-id-9002">
<div class="question-content"><p><span class="watupro_num">1 </span>It was a beautiful day. [[1]]</p>
<!-- end question-content--></div></div></div>
</form></div>
"""


def test_parse_quiz_instruction_without_h3():
    q = te.parse_quiz(PAGE_HTML_NO_H3)
    assert q["instruction"] == "Fill in the gaps with a suitable preposition."
    assert q["label"] == ""


def test_parse_quiz_instruction_after_example_block():
    q = te.parse_quiz(PAGE_HTML_H5_AFTER_EXAMPLE)
    assert q["instruction"] == ("Rewrite the sentences using so, such (a), "
                                "so much, so many.")
    assert q["label"] == "Exercise 3"


def test_split_variants_shared_stem_expansion():
    assert te._split_variants("might/may/could have done") == [
        "might have done", "may have done", "could have done"]
    assert te._split_variants("can't/couldn't have been") == [
        "can't have been", "couldn't have been"]
    assert te._split_variants("am/'m going to work") == [
        "am going to work", "'m going to work"]
    assert te._split_variants("is not/isn't/'s not going to pay") == [
        "is not going to pay", "isn't going to pay", "'s not going to pay"]
    # shared 'not' is carried into a bare-aux alternate
    assert te._split_variants("am/'m not going to read") == [
        "am not going to read", "'m not going to read"]


def test_split_variants_twins_and_complete_alternates_untouched():
    assert te._split_variants("couldn't/could not") == ["couldn't", "could not"]
    assert te._split_variants("reached/had reached") == ["reached", "had reached"]
    assert te._split_variants("have/need") == ["have", "need"]
    assert te._split_variants("are not/aren't/'re not") == [
        "are not", "aren't", "'re not"]


def test_split_variants_also_possible_family():
    assert te._split_variants("can't ('m not able to is also possible)") == [
        "can't", "'m not able to"]
    assert te._split_variants("ought to/should is also possible") == [
        "ought to", "should"]
    assert te._split_variants(
        "must have lied (might/may/could also possible)") == [
        "must have lied", "might have lied", "may have lied", "could have lied"]


def test_gap_variants_merged_shared_stem_single_gap():
    q = {"text_html": "<p>I [[1]] some books.</p>",
         "gaps": [{"n": 1, "kind": "text", "options": []}],
         "gap_answers": [["am"], ["'m going to borrow"]],
         "correct": ["am"]}
    vs = te._gap_variants(q, 0, None)
    assert vs[0] == "am going to borrow"
    assert "'m going to borrow" in vs
    assert "\u2019m going to borrow" not in vs   # no apostrophe twin


def test_radio_merged_option_page_becomes_test():
    merged = {"text_html": ("<div>Researchers say they are ______ "
                            "discovering a new form of life.</div>"),
              "text": ("Researchers say they are ______ discovering "
                       "a new form of life."),
              "choices": ["about", "on the verge of", "on the point of",
                          "on the point of / on the verge of"],
              "correct": ["on the point of / on the verge of"], "gaps": []}
    ex = te.page_exercise(_radio_page(merged))
    assert ex["type"] == "test"
    tq = ex["questions"][0]
    assert tq["options"][3] == "on the point of / on the verge of"
    assert tq["correct"] == [3]   # merged option kept as ONE answer, ticked


def test_radio_pair_question_still_dropdowns():
    pair = {"text_html": "<div>When I ______ him, he ______ a picture.</div>",
            "text": "When I ______ him, he ______ a picture.",
            "choices": ["saw / wore", "was seeing / was wearing",
                        "saw / was wearing"],
            "correct": ["saw / was wearing"], "gaps": []}
    ex = te.page_exercise(_radio_page(pair))
    assert ex["type"] == "chooseoption"


def test_split_variants_pipe_alternatives():
    # the site sometimes separates accepted alternatives with '|'
    assert te._split_variants("will ask|'ll ask") == ["will ask", "'ll ask"]
    assert te._split_variants("The Spanish|The Spaniards") == [
        "The Spanish", "The Spaniards"]
    assert te._split_variants("was|were") == ["was", "were"]
    assert te._split_variants("learned|learnt / would try") == [
        "learned", "learnt", "would try"]
    assert te._split_variants("tastes as if|tastes as though|tastes like") == [
        "tastes as if", "tastes as though", "tastes like"]
