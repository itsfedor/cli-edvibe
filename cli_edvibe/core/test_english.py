"""Transfer a test-english.com lesson into an Edvibe lesson.

Pipeline (all over the verified Edvibe WS RPC via client.EdvibeSession):

  fetch_lesson(url)        scrape a lesson: every exercise page (questions,
                           options, correct answers, the site's feedback
                           explanations) + the Explanation tab html + images
  build_spec(data, pages)  convert into the lesson-spec format executed by
                           core/lesson_spec.build_lesson:
                             section 1 "Explanation": Pictures charts + Text
                             notes (site structure preserved)
                             section 2 "Exercises": one exercise per page
                             (choose-option / fill-typed) + a HIDDEN teacher
                             note with the per-question answer key and the
                             site's short explanations
  import_lesson(...)       one-shot: scrape -> book/section scaffold ->
                           lesson -> build -> verify

Scraping notes (see also the test-english-to-edvibe skill):
  - test-english.com sits behind Cloudflare: fetch raw html via
    https://r.jina.ai/<url> with X-Return-Format: html and a curl-like UA.
  - correct answers are NOT in the page html: POST a dummy attempt to
    /wp-admin/admin-ajax.php (action=watupro_submit) and parse the feedback.
  - images are downloadable directly (CDN not Cloudflare-challenged); charts
    are hot-linked into Edvibe Pictures blocks (external-URL flow), so no
    upload is needed.
"""
import html as _html
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 "
      "Safari/604.1")
JINA_UA = "curl/8.0"
SKIP_IMG = ("loading.gif", "upgrade-to-Test-English", "Video-explainter",
            "ico-", "logo-")
_DIM_CACHE = {}


def _img_dim(url):
    """Natural pixel size of an image (png/gif/jpeg header) - needed for the
    editor's inline IMG comment blocks so the charts keep their ratio."""
    if url in _DIM_CACHE:
        return _DIM_CACHE[url]
    w = h = 0
    try:
        import struct
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        raw = urllib.request.urlopen(req, timeout=25).read()
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", raw[16:24])
        elif raw[:3] == b"GIF":
            w, h = struct.unpack("<HH", raw[6:10])
        elif raw[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(raw):
                if raw[i] != 0xFF:
                    i += 1
                    continue
                mk = raw[i + 1]
                if mk in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB):
                    h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                    break
                if mk in (0xD8, 0xD9) or 0xD0 <= mk <= 0xD7:
                    i += 2
                    continue
                seg = struct.unpack(">H", raw[i + 2:i + 4])[0]
                i += 2 + seg
    except Exception:  # noqa: BLE001 - fall back to a sane ratio
        pass
    if not w or not h:
        w, h = 1200, 900
    _DIM_CACHE[url] = (w, h)
    return w, h


def _img_block(url, w, h, align=""):
    """The Edvibe block-editor's inline image node - a special HTML comment
    the exercise renderer parses into an image block."""
    return "<!--IMG:%s;CX:;CY:;CW:;CH:;W:%d;H:%d;A:%s;-->" % (
        url, int(w), int(h), align)

# test-english palette (from their live CSS) re-used inside Edvibe text:
#   heading blue, the green/red key-form colors, the gray infoblock background
PAL_GREEN = "#50af31"          # --c-testenglish: key forms in examples + 'Correct answer'
PAL_RED = "#e03131"            # the ✗ mark
PAL_HEAD = "rgb(26, 142, 193)"  # h2/h4 headings on the site (blue)
PAL_GRAY_BG = "rgb(246, 246, 246)"  # .infoblock background
# the site's panel treatments (Edvibe has no borders - a colored bar + a light
# fill emulate the site's bordered boxes, same as the gray infoblock):
PAL_BLUE_BAR = "#1A8EC1"            # ul.grammar-ex border-left: 3px solid
PAL_BLUE_BG = "rgb(241, 249, 254)"  # ul.grammar-ex panel fill
PAL_GRAY_BAR = "#CDD3DA"            # .textBox border-left: 1px solid
PAL_GRAY_BG2 = "rgb(249, 249, 250)"  # .textBox panel fill


def _c(text, color=PAL_HEAD, bold=True):
    t = f'<span style="color: {color}">{_html.escape(text or "", quote=False)}</span>'
    return f"<b>{t}</b>" if bold else t


def _hl(line):
    """One line of the site's .infoblock: gray background + a left bar."""
    return (f'<span style="background-color: {PAL_GRAY_BG}">'
            f'▎ {line.strip()}</span>')


def _bar(line, bar_color, bg_color):
    """One line of a site-style panel (the site uses 1-3px left borders Edvibe
    cannot draw - a coloured bar + a light fill stands in for them)."""
    return ('<span style="background-color: %s">'
            '<span style="color: %s">▎</span>&nbsp;%s</span>'
            % (bg_color, bar_color, line.strip()))


# ------------------------------------------------------------------- http
def _http(url, data=None, headers=None, retries=5):
    url = urllib.parse.quote(url, safe=":/?&=#%[]!$'()*+,;@~")
    last = None
    for i in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=90, context=SSL_CTX) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:  # noqa: PERF203 - retry any error
            last = e
            # 429 (jina rate limit) needs a LONG cool-down, not a short backoff
            wait = 20 * (i + 1) if e.code == 429 else 3 * (i + 1)
            time.sleep(min(wait, 90))
        except Exception as e:  # noqa: BLE001 - retry any transport error
            last = e
            time.sleep(3 * (i + 1))
    raise last


def _jina(url, cache_dir=None):
    key = re.sub(r"[^a-zA-Z0-9]+", "-", url)[-90:] + ".html"
    if cache_dir:
        fn = os.path.join(cache_dir, "jina-" + key)
        if os.path.exists(fn):
            with open(fn, encoding="utf-8", errors="replace") as f:
                return f.read()
    html = _http("https://r.jina.ai/" + url,
                 headers={"X-Return-Format": "html", "User-Agent": JINA_UA})
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        with open(fn, "w", encoding="utf-8") as f:
            f.write(html)
    return html


def _strip_tags(s):
    s = re.sub(r"<br\s*/?>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return _html.unescape(s).replace("\xa0", " ").strip()


# -------------------------------------------------------------- quiz parse
def parse_quiz(page_html):
    q = {}
    m = re.search(r'<form[^>]*id="quiz-(\d+)"', page_html)
    q["quiz_id"] = int(m.group(1)) if m else None
    m = re.search(r'name="watupro_questions"\s+value="([^"]*)"', page_html)
    q["questions_field"] = _html.unescape(m.group(1)) if m else ""
    m = re.search(r'name="start_time"\s+value="([^"]*)"', page_html)
    q["start_time"] = m.group(1) if m else ""
    m = re.search(r'name="start_timestamp"\s+value="([^"]*)"', page_html)
    q["start_timestamp"] = m.group(1) if m else ""
    # Instruction = the <h5> directly above the quiz container. The site
    # sometimes drops the <h3>Exercise N</h3> label entirely or puts an
    # EXAMPLE block between the h3 and the h5 - both broke the old
    # h3+h5-adjacency regex (6 pages shipped a nameless exercise).
    quiz_at = page_html.find('<div id="watupro_quiz"')
    head = page_html[:quiz_at] if quiz_at > 0 else page_html
    last_h2 = head.rfind("</h2>")
    region = head[last_h2:] if last_h2 >= 0 else head
    h5s = re.findall(r"<h5>(.*?)</h5>", region, re.S)
    q["instruction"] = _strip_tags(h5s[-1]) if h5s else ""
    h3s = re.findall(r"<h3>(.*?)</h3>", region, re.S)
    q["label"] = _strip_tags(h3s[-1]) if h3s else ""
    m = re.search(r"</h5>(.*?)<div id=\"watupro_quiz\"", page_html, re.S)
    q["example_html"] = m.group(1).strip() if m else ""

    questions = []
    for blk in re.split(r'<div class="watu-question"', page_html)[1:]:
        m = re.search(r"watupro-question-id-(\d+)", blk)
        if not m:
            continue
        qid = int(m.group(1))
        cm = re.search(r'<div class="question-content">(.*?)'
                       r'<!-- end question-content', blk, re.S)
        content = cm.group(1) if cm else ""
        item = {"qid": qid, "raw_html": content.strip(), "gaps": []}
        for gm in re.finditer(
                r'<select name="gap_%d_(\d+)"[^>]*>(.*?)</select>' % qid,
                content, re.S):
            opts = [_html.unescape(o) for o in
                    re.findall(r"<option[^>]*>([^<]*)</option>", gm.group(2))]
            item["gaps"].append({"n": int(gm.group(1)), "kind": "select",
                                 "options": [o for o in opts if o.strip()]})
        for gm in re.finditer(
                r'<input type="text"[^>]*name="gap_%d_(\d+)"' % qid, content):
            item["gaps"].append({"n": int(gm.group(1)), "kind": "text",
                                 "options": []})
        item["gaps"].sort(key=lambda g: g["n"])
        # radio/choice options: <label class="answer"><span>text</span></label>
        item["choices"] = [_strip_tags(m.group(1)) for m in re.finditer(
            r'<label[^>]*class="answer"[^>]*>\s*<span>(.*?)</span>\s*</label>',
            blk, re.S)]
        text = content
        text = re.sub(r'<select name="gap_%d_(\d+)".*?</select>' % qid,
                      lambda mm: "[[%s]]" % mm.group(1), text, flags=re.S)
        text = re.sub(r'<input type="text"[^>]*name="gap_%d_(\d+)"[^>]*>' % qid,
                      lambda mm: "[[%s]]" % mm.group(1), text)
        text = re.sub(r'<span class="watupro_num">\s*\d+\s*</span>', "", text)
        text = re.sub(r"<input type=\"hidden\".*", "", text, flags=re.S)
        item["text_html"] = text.strip()
        item["text"] = _strip_tags(item["text_html"])
        questions.append(item)
    q["questions"] = questions
    return q


def submit_quiz(base_url, q, page_url, cache_dir=None):
    """POST a dummy attempt (guaranteed wrong: empty selects / 'zzz' text);
    the response reveals the correct answers + the site's explanations."""
    ck = None
    if cache_dir:
        ck = os.path.join(cache_dir, "quiz-%s.html" % q.get("quiz_id"))
        if os.path.exists(ck):
            with open(ck, encoding="utf-8", errors="replace") as f:
                return f.read()
    fields = [("action", "watupro_submit"), ("quiz_id", str(q["quiz_id"]))]
    for item in q["questions"]:
        fields.append(("question_id[]", str(item["qid"])))
    fields.append(("watupro_questions", q["questions_field"]))
    fields.append(("start_time", q["start_time"]))
    fields.append(("start_timestamp", q["start_timestamp"]))
    fields.append(("no_ajax", "0"))
    for item in q["questions"]:
        for g in item["gaps"]:
            fields.append(("gap_%d_%d" % (item["qid"], g["n"]),
                           "" if g["kind"] == "select" else "zzz"))
    data = urllib.parse.urlencode(fields).encode()
    html = _http(base_url + "/staging11/wp-admin/admin-ajax.php", data=data,
                 headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest",
                          "Referer": page_url, "Origin": base_url,
                          "Content-Type":
                          "application/x-www-form-urlencoded; charset=UTF-8"})
    if ck:
        with open(ck, "w", encoding="utf-8") as f:
            f.write(html)
    return html


# The site writes "shared-stem" compact answers ("might/may/could have done",
# "is not/isn't/'s not going to pay") that naive '/'-splitting turns into
# fragments ("might", "may", "could have done") - a student typing the full
# correct form then gets marked WRONG while a bare "might" passes. The
# helpers below expand those compacts into full variants, while leaving
# contraction twins ("couldn't/could not"), complete alternates
# ("reached/had reached") and synonym pairs ("can't"/"'m not able to") alone.
_AUX_SHARDS = {
    "might", "may", "could", "can", "can't", "can’t", "couldn't", "couldn’t",
    "must", "mustn't", "mustn’t", "should", "shouldn't", "shouldn’t",
    "will", "won't", "won’t", "would", "wouldn't", "wouldn’t",
    "shall", "shan't", "shan’t", "'ll", "’ll", "'m", "’m", "'d", "’d",
    "'s", "’s", "'re", "’re",
    "am", "is", "are", "was", "were", "have", "has", "had",
    "isn't", "isn’t", "aren't", "aren’t", "wasn't", "wasn’t",
    "weren't", "weren’t", "don't", "don’t", "doesn't", "doesn’t",
    "didn't", "didn’t", "haven't", "haven’t", "hasn't", "hasn’t",
    "hadn't", "hadn’t",
}
_NEG_WORDS = {"not", "n't", "n’t"}
_ALSO_POSSIBLE_RE = re.compile(r"\s*(?:(?:is|are)\s+)?also\s+possible\s*$", re.I)


def _strip_also_possible(text):
    """Drop the site's 'is also possible' tail; return (text, had_marker)."""
    m = _ALSO_POSSIBLE_RE.search(text or "")
    if not m:
        return (text or "").strip(), False
    return _ALSO_POSSIBLE_RE.sub("", text).strip(), True


def _norm_variant(s):
    """Case/apostrophe/contraction-blind key for twin detection."""
    s = (s or "").strip().casefold().replace("\u2019", "'")
    s = s.replace("n't", " not")
    for c, full in (("'m", "am"), ("'re", "are"), ("'ll", "will"),
                    ("'ve", "have"), ("'d", "would")):
        s = s.replace(c, full)
    return re.sub(r"\s+", " ", s).strip()


def _apos_key(s):
    """Case + apostrophe-STYLE blind key (curly -> straight) for payload
    dedupe: collapses "isn't"/"isn’t" but keeps meaningfully different
    forms distinct ('am' != "'m", 'is not' != "isn't")."""
    return (s or "").strip().casefold().replace("\u2019", "'").replace("\u2018", "'")


def _is_shard(s):
    """A one-word auxiliary or 'aux not' fragment (am / is not / aren't)."""
    toks = (s or "").split(" ")
    if len(toks) == 1:
        return toks[0].casefold() in _AUX_SHARDS
    if len(toks) == 2:
        return (toks[0].casefold() in _AUX_SHARDS
                and toks[1].casefold() in _NEG_WORDS)
    return False


def _split_aux_tail(s):
    """'could have done' -> (False, 'have done'); \"'m not going\" -> (True, 'going').
    None when the string does not start with an auxiliary."""
    toks = (s or "").split(" ")
    if not toks or toks[0].casefold() not in _AUX_SHARDS:
        return None
    i = 1
    neg = bool(re.search(r"n[’']t$", toks[0], re.I))
    if i < len(toks) and toks[i].casefold() in _NEG_WORDS:
        neg = True
        i += 1
    return neg, " ".join(toks[i:])


def _has_neg(s):
    toks = (s or "").split(" ")
    return (bool(re.search(r"n[’']t$", toks[0], re.I))
            or any(t.casefold() in _NEG_WORDS for t in toks))


def _expand_shared_stem(parts):
    """Expand shared-stem compacts in a flat variant list; idempotent.

    ['might', 'may', 'could have done'] -> full forms for all three;
    [\"am\", \"'m not going to read\"] -> inserts the shared 'not';
    anything else (twins / complete alternates / synonyms) stays as-is."""
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return parts
    if len({_norm_variant(p) for p in parts}) == 1:      # contraction twins
        return parts
    if not all(_is_shard(p) for p in parts[:-1]):
        return parts
    st = _split_aux_tail(parts[-1])
    if not st:
        return parts
    neg, tail = st
    if not tail:
        return parts
    last = parts[-1]
    if any(_norm_variant(p) in (_norm_variant(last), _norm_variant(tail))
           for p in parts[:-1]):
        return parts
    out = []
    for p in parts[:-1]:
        out.append(p + " not " + tail if (neg and not _has_neg(p))
                   else p + " " + tail)
    out.append(last)
    seen, res = set(), []
    for x in out:
        k = _apos_key(x)
        if k not in seen:
            seen.add(k)
            res.append(x)
    return res


def _split_variants(txt):
    """The site's per-gap answer notation:
      "She isn't/She's not"        -> ["She isn't", "She's not"]
      "are not (aren't/'re not)"   -> ["are not", "aren't", "'re not"]
      "might/may/could have done"  -> ["might have done", "may have done",
                                       "could have done"]
      "can't ('m not able to is also possible)" -> ["can't", "'m not able to"]
    Parenthesised bits are extra accepted forms, not part of the answer;
    shared-stem compacts are expanded into full variants."""
    txt = (txt or "").strip()
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", txt, re.S)
    base_txt, paren_txt = (m.group(1), m.group(2)) if m else (txt, None)
    base_parts, paren_parts = [], []
    had_marker = False

    def _push(lst, chunk):
        """Add one '/'-chunk as variant(s); '|' inside a chunk separates
        accepted alternatives ('will ask|'ll ask' -> both full forms)."""
        chunk, mk = _strip_also_possible(chunk)
        for sub in re.split(r"\s*\|\s*", chunk):
            sub = sub.strip()
            if sub and sub not in lst:
                lst.append(sub)
        return mk

    for part in re.split(r"\s*/\s*", base_txt or ""):
        had_marker = _push(base_parts, part) or had_marker
    if paren_txt is not None:
        for part in re.split(r"\s*/\s*", paren_txt):
            had_marker = _push(paren_parts, part) or had_marker
    if not had_marker:
        return _expand_shared_stem(base_parts + paren_parts) or \
            ([txt] if txt else [])
    # marker family ('... is also possible'): the marker already tells us
    # these are additional accepted forms - never re-expand the synonyms.
    # The one shape that DOES need the tail: an aux-only parenthetical
    # ('must have lied (might/may/could also possible)').
    if paren_parts and all(_is_shard(p) for p in paren_parts) \
            and any(" " in b for b in base_parts):
        cand = [b for b in base_parts if " " in b][-1]
        st = _split_aux_tail(cand)
        if st and st[1]:
            out = list(base_parts)
            for p in paren_parts:
                x = f"{p} {st[1]}"
                if x not in out:
                    out.append(x)
            return out
    out = base_parts + [p for p in paren_parts if p not in base_parts]
    return out or ([txt] if txt else [])


_ANS_TAG_RE = re.compile(
    r"<(?:font|span)[^>]*>\s*Correct answers?\s*"
    r"(?:\(\s*(\d+)(?:st|nd|rd|th)?\s*gaps?\s*\))?\s*:\s*"
    r"(?:</(?:font|span)\s*>\s*<(?:font|span)[^>]*>)?(.*?)"
    r"</(?:font|span)\s*>",
    re.S | re.I)
_ANS_LINE_RE = re.compile(
    r"^Correct answers?\s*(?:\(\s*(\d+)(?:st|nd|rd|th)?\s*gaps?\s*\))?\s*:",
    re.I)


def _fb_lines(html):
    """Split a feedback block into text lines, dropping 'Feedback' noise and
    leftover numBox numbers."""
    out = []
    for part in re.split(r"<br\s*/?>|</p>|<hr\s*/?>", html or ""):
        t = _strip_tags(part).lstrip("‣").strip()
        if t and t.lower() != "feedback" and not t.isdigit():
            out.append(t)
    return out


def _gap_num_nums(html, qid=None):
    """numBox number preceding each gap input, in gap order.

    Gap numbers can be page-global, and a leading '<numBox>0</numBox>' marks
    an example (a highlighted word), NOT a gap - mapping by 'nearest numBox
    before the input' keeps every answer on its own gap."""
    marks = [(m.start(), int(m.group(1))) for m in
             re.finditer(r'<span class="numBox">\s*(\d+)\s*</span>', html or "")]
    pat = r'name="gap_%s_(\d+)"' % qid if qid else r'name="gap_\d+_(\d+)"'
    out = []
    for gm in re.finditer(pat, html or ""):
        prev = [n for pos, n in marks if pos < gm.start()]
        out.append(prev[-1] if prev else None)
    if not out:
        out = [n for _, n in marks]
    return out


def _block_gap_nums(blk):
    """Numbers of the numBox marks that denote REAL gaps inside a feedback
    block: a gap mark is directly followed by the user's answer span, an
    example mark by a highlighted word (<span class=\"textGap\">)."""
    out = []
    for m in re.finditer(r'<span class="numBox">\s*(\d+)\s*</span>(.{0,40})',
                         blk or "", re.S):
        n, tail = int(m.group(1)), m.group(2)
        if "textGap" in tail:
            continue                       # an example highlight, not a gap
        out.append(n)
    return out


def parse_feedback(resp_html):
    """-> [{correct: [...], explanations: [...],
           gap_answers: [[variants per gap], ...],
           gap_explanations: [[gap_no, [lines]], ...]}] in question order.

    Feedback layouts seen live on the site (they MIX within one quiz):
      * tagged statement : <span style="color: #50af31">Correct answer: A/B … C</span>
                           or <font color="#50af31">Correct answer: X</font>;
                           also 'Correct answer (1st gap): X' per gap.
                           '...' separates the gaps' groups, '/' separates
                           alternatives inside a gap;
      * numBox           : one <span class="numBox">N</span> block per gap with
                           its own answer + explanation lines (long dialogues).
                           N can run ACROSS questions (page-global) - the
                           blocks are mapped onto the question's OWN gaps in
                           order of appearance, never by the absolute N;
      * li list          : select quizzes list options as <li> items, the
                           correct one carries a 'correct-answer' class.
    """
    out = []
    for blk in re.split(r"watupro-choices-columns show-question", resp_html)[1:]:
        item = {"correct": [], "explanations": [], "gap_answers": [],
                "gap_explanations": [], "pool_answers": []}
        for am in re.finditer(r"<li class='answer([^']*)'[^>]*>(.*?)</li>",
                              blk, re.S):
            if "correct-answer" in am.group(1):
                t = re.sub(r'<span class="watupro-screen-reader">.*?</span>',
                           "", am.group(2))
                t = re.sub(r"^[A-Z]\.\s*", "", _strip_tags(t))  # drop the A. letter
                item["correct"].append(t)
        fb = re.search(r"watupro-main-feedback[^>]*>(.*?)<!--end-watupro-feedback",
                       blk, re.S)
        if not fb:
            out.append(item)
            continue
        fbt = fb.group(1)

        # statements of any wrapper: 'Correct answer (Nth gap): X' (authoritative,
        # local to the question) or a plain 'Correct answer: X'
        stmts = []
        for m in _ANS_TAG_RE.finditer(fbt):
            n = int(m.group(1)) if m.group(1) else None
            txt = _strip_tags(m.group(2)).strip()
            if txt:
                stmts.append((n, txt))
        expl_lines = []
        for t in _fb_lines(_ANS_TAG_RE.sub("", fbt)):
            lm = _ANS_LINE_RE.match(t)
            if lm:
                n = int(lm.group(1)) if lm.group(1) else None
                txt = t[lm.end():].strip()
                if txt:
                    stmts.append((n, txt))
            else:
                expl_lines.append(t)
        seen = set()
        stmts = [s for s in stmts if not (s in seen or seen.add(s))]
        labeled = [(n, txt) for n, txt in stmts if n]
        if labeled:
            # '(Nth gap)' labels win over numBox numbering (which can be
            # page-global and is unreliable when both layouts appear mixed)
            for n, txt in labeled:
                idx = n - 1
                while len(item["gap_answers"]) <= idx:
                    item["gap_answers"].append([])
                for v in _split_variants(txt):
                    if v not in item["gap_answers"][idx]:
                        item["gap_answers"][idx].append(v)
            item["correct"] = (item["gap_answers"][0]
                               if item["gap_answers"] else item["correct"])
            item["explanations"] = expl_lines
            out.append(item)
            continue

        # ---- numBox layout: numbered answer blocks, one per gap.
        # Numbers can run ACROSS the page ('dialogue' pages carry a trailing
        # Feedback pool with ALL the numbered answers) - answers whose number
        # belongs to THIS block's own question go to its gaps by position,
        # the rest ride along as a page-level pool (see apply_feedback()).
        chunks = re.split(r'<span class="numBox">\s*(\d+)\s*</span>', fbt)[1:]
        if chunks:
            content = blk.split("<!--watupro-feedback-->")[0]
            content = content.split("watupro-main-feedback")[0]
            own_nums = _block_gap_nums(content)
            pairs = []
            for k in range(0, len(chunks) - 1, 2):
                n = int(chunks[k])
                body = chunks[k + 1]
                am = re.search(r"Correct answers?\s*(?:\([^)]*\))?\s*:\s*"
                               r"(.*?)</(?:span|font)>", body, re.S)
                ans = _strip_tags(am.group(1)) if am else ""
                tail = body[am.end():] if am else body
                expl = _fb_lines(tail)
                if not ans:  # unwrapped plain answer line fallback
                    for t in expl:
                        lm = _ANS_LINE_RE.match(t)
                        if lm and t[lm.end():].strip():
                            ans = t[lm.end():].strip()
                            expl = [x for x in expl if x != t]
                            break
                pairs.append((n, ans, expl))
            if not own_nums:
                # no own gap marks in the block (legacy/synthetic markup):
                # fall back to the pairs' own order (= previous behaviour)
                own_nums = [n for n, _ans, _e in pairs]
            for n, ans, expl in pairs:
                variants = _split_variants(ans)
                if n in own_nums:
                    idx = own_nums.index(n)
                    while len(item["gap_answers"]) <= idx:
                        item["gap_answers"].append([])
                    cur = item["gap_answers"][idx] or []
                    for v in variants:
                        if v not in cur:
                            cur.append(v)
                    item["gap_answers"][idx] = cur
                    if expl:
                        item["gap_explanations"].append([idx + 1, expl])
                else:
                    item["pool_answers"].append([n, variants, expl])
            if item["gap_answers"]:
                item["correct"] = item["gap_answers"][0]
                item["explanations"] = [t for _, xs in
                                        item["gap_explanations"] for t in xs]
            out.append(item)
            continue

        # ---- tagged + plain answer statements (per gap, optional '(Nth gap)')
        stmts = []
        for m in _ANS_TAG_RE.finditer(fbt):
            n = int(m.group(1)) if m.group(1) else None
            txt = _strip_tags(m.group(2)).strip()
            if txt:
                stmts.append((n, txt))
        expl_lines = []
        for t in _fb_lines(_ANS_TAG_RE.sub("", fbt)):
            lm = _ANS_LINE_RE.match(t)
            if lm:
                n = int(lm.group(1)) if lm.group(1) else None
                txt = t[lm.end():].strip()
                if txt:
                    stmts.append((n, txt))
            else:
                expl_lines.append(t)
        seen = set()
        stmts = [s for s in stmts if not (s in seen or seen.add(s))]

        if stmts:
            numbered = [(n, txt) for n, txt in stmts if n]
            if numbered:
                for n, txt in numbered:
                    idx = n - 1
                    while len(item["gap_answers"]) <= idx:
                        item["gap_answers"].append([])
                    for v in _split_variants(txt):
                        if v not in item["gap_answers"][idx]:
                            item["gap_answers"][idx].append(v)
            else:
                un = [txt for _, txt in stmts]
                if len(un) == 1:
                    ans = un[0]
                    if re.search(r"\.{3,}|…", ans):
                        # 'She isn't/She's not ... Is she' / 'The spicier... the
                        # more': '...' splits the gaps' groups ('/' separates
                        # alternatives inside a group) - spacing optional.
                        groups = [g.strip() for g in
                                  re.split(r"\s*\.{3,}\s*|\s*…\s*", ans)
                                  if g.strip()]
                        item["gap_answers"] = [_split_variants(g)
                                               for g in groups]
                    else:
                        # 'Are/am': answers for the gaps in order
                        item["gap_answers"] = [
                            _split_variants(a) for a in
                            re.split(r"\s*/\s*", ans) if a.strip()]
                else:
                    # several unnumbered statements: one per gap, in order
                    for txt in un:
                        item["gap_answers"].append(_split_variants(txt))
            item["correct"] = (item["gap_answers"][0]
                               if item["gap_answers"] else item["correct"])
        item["explanations"] = expl_lines
        out.append(item)
    return out


def apply_feedback(questions, fb):
    """Attach parsed feedback to a page's questions (positional), then
    distribute any page-level 'Feedback' pool: numbered answers whose numBox
    number appears in a question's own text (page-global numbering on
    'dialogue' pages) go to that question's gap by order of appearance."""
    pool = [p for f in fb for p in (f.get("pool_answers") or [])]
    for q, f in zip(questions, fb):
        q["correct"] = f.get("correct") or []
        q["explanations"] = f.get("explanations") or []
        if f.get("gap_answers"):
            q["gap_answers"] = f["gap_answers"]
        if f.get("gap_explanations"):
            q["gap_explanations"] = f["gap_explanations"]
    if not pool:
        return questions
    for q in questions:
        nums = [n for n in _gap_num_nums(q.get("raw_html") or "",
                                         q.get("qid")) if n is not None]
        if not nums:
            continue
        ge = dict(q.get("gap_explanations") or [])
        ga = list(q.get("gap_answers") or [])
        changed = False
        for n, variants, expl in pool:
            if n not in nums:
                continue
            idx = nums.index(n)
            while len(ga) <= idx:
                ga.append([])
            cur = ga[idx] or []
            for v in variants:
                if v not in cur:
                    cur.append(v)
            ga[idx] = cur
            if expl:
                ge.setdefault(idx + 1, [])
                ge[idx + 1] = list(ge[idx + 1]) + [e for e in expl
                                                   if e not in ge[idx + 1]]
            changed = True
        if changed:
            q["gap_answers"] = ga
            if ge:
                q["gap_explanations"] = sorted(([k, v] for k, v in ge.items()),
                                               key=lambda x: x[0])
            if not q.get("correct") and ga:
                q["correct"] = ga[0]
    return questions


def parse_explanation(page_html):
    i = page_html.find('<div id="tabli2-cont"')
    if i == -1:
        return ""
    j = page_html.find('<li id="tabli3"', i)
    if j == -1:
        j = page_html.find('<li id="tabli4"', i)
    if j == -1:
        j = len(page_html)
    return page_html[i:j]


def parse_images(explanation_html):
    urls = []
    for m in re.finditer(r'<img[^>]*src="([^"]+\.(?:png|jpe?g|webp))"',
                         explanation_html):
        u = _html.unescape(m.group(1))
        if u not in urls and not any(s in u for s in SKIP_IMG):
            urls.append(u)
    return urls


# ------------------------------------------------------------------- fetch
def fetch_lesson(url, pages=None, imgdir=None, out=None, cache_dir=None,
                 workers=4):
    """Scrape a whole test-english lesson - pages fetched and quiz attempts
    submitted in PARALLEL (several times faster than the sequential version).
    pages: iterable of page numbers (1 = the lesson root, 2 = /2/, ...) or
    None for all. cache_dir: reuse saved page html / submit responses and
    save new ones (retry-friendly, skips the network on re-runs)."""
    m = re.match(r"(https?://[^/]+)(/.*?)/?$", url)
    if not m:
        raise ValueError(f"bad url: {url}")
    base, path = m.group(1), m.group(2)
    base_path = re.sub(r"/\d+$", "", path)
    lesson_url = base + base_path + "/"

    p1 = _jina(lesson_url, cache_dir)
    if "watupro" not in p1:
        raise RuntimeError("page fetch failed or no quiz found")
    hrefs = re.findall(r'href="(https?://[^"]+%s)/(\d+)/"' % re.escape(base_path),
                       p1)
    page_urls = [lesson_url] + [u + "/" + str(n) + "/"
                                for u, n in sorted({(a, int(b)) for a, b in hrefs},
                                                   key=lambda x: x[1])]
    if pages is not None:
        want = {int(p) for p in pages}
        page_urls = [u for k, u in enumerate(page_urls, 1) if k in want]

    data = {"source_url": lesson_url, "title": None, "lesson_title": None,
            "pages": [], "explanation_html": "", "images": []}
    m = re.search(r"<title>(.*?)</title>", p1, re.S)
    if m:
        data["title"] = _strip_tags(m.group(1)).split("|")[0].strip()
    m = re.search(r"<h2>(.*?)</h2>", p1, re.S)
    if m:
        data["lesson_title"] = _strip_tags(m.group(1))

    # 1) fetch every requested page in parallel (page 1 is already in hand)
    to_fetch = [u for u in page_urls if u != lesson_url]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        fetched = list(ex.map(lambda u: _jina(u, cache_dir), to_fetch))
    htmls = {lesson_url: p1}
    htmls.update(dict(zip(to_fetch, fetched)))

    # 2) parse all quizzes, then submit the dummy attempts in parallel
    quizzes = {u: parse_quiz(htmls[u]) for u in page_urls}
    targets = [u for u in page_urls if quizzes[u]["questions"]]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        responses = list(ex.map(
            lambda u: submit_quiz(base, quizzes[u], u, cache_dir), targets))
    for k, u in enumerate(page_urls, 1):
        q = quizzes[u]
        if not q["questions"]:
            continue
        if u in targets:
            fb = parse_feedback(responses[targets.index(u)])
            apply_feedback(q["questions"], fb)
        data["pages"].append({"page": k, "url": u, "label": q["label"],
                              "instruction": q["instruction"],
                              "example_html": q["example_html"],
                              "quiz_id": q["quiz_id"],
                              "questions": q["questions"]})

    data["explanation_html"] = parse_explanation(p1)
    data["images"] = parse_images(data["explanation_html"])

    if imgdir:
        os.makedirs(imgdir, exist_ok=True)
        for u in data["images"]:
            fn = os.path.join(imgdir, u.split("/")[-1])
            if not os.path.exists(fn):
                raw = _http(u, headers={"User-Agent": UA})
                with open(fn, "w", encoding="utf-8", errors="replace") as f:
                    f.write(raw)
    if out:
        import json
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    return data


# ------------------------------------------------- explanation → exercises
class _Node:
    def __init__(self, tag, attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.kids = []


class _Text:
    def __init__(self, text):
        self.text = text


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root")
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
            return
        if self.skip:
            return
        node = _Node(tag, attrs)
        self.stack[-1].kids.append(node)
        if tag not in ("br", "img", "input", "source", "meta", "link"):
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if not self.skip:
            self.stack[-1].kids.append(_Node(tag, attrs))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if len(self.stack) > 1 and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, data):
        if not self.skip:
            self.stack[-1].kids.append(_Text(data))


_ICON = {"correct.png": ("✓", PAL_GREEN), "wrong.png": ("✗", PAL_RED)}
# images that are NOT charts: skipped entirely / rendered as inline marks
_CHART_SKIP = tuple(SKIP_IMG) + ("correct.png", "wrong.png")


def _is_chart_img(node):
    return (not isinstance(node, _Text) and node.tag == "img"
            and node.attrs.get("src")
            and not any(s in node.attrs["src"] for s in _CHART_SKIP))


def _contains_chart_img(node):
    if isinstance(node, _Text):
        return False
    return any(_is_chart_img(k) or _contains_chart_img(k) for k in node.kids)


def _split_para(node):
    """Split a <p>'s children into ('p', html) / ('img', src) segments in
    document order. The site often puts a chart image INSIDE a text paragraph
    (<p>text<br><br><img chart.png></p>) - without this split the image is
    silently dropped by the renderer."""
    segs = []
    run = []

    def flush():
        if run:
            html = _tidy("".join(_render(x) for x in run))
            if _strip_tags(html).strip() or re.search(r"[✓✗]", html):
                segs.append(("p", html))
            run.clear()

    for k in node.kids:
        if isinstance(k, _Text):
            run.append(k)
            continue
        if k.tag == "img":
            src = k.attrs.get("src", "")
            if src and not any(s in src for s in _CHART_SKIP):
                flush()
                segs.append(("img", _html.unescape(src)))
                continue
            run.append(k)
            continue
        if _contains_chart_img(k):     # e.g. <a><img chart></a>
            flush()
            segs.extend(_split_para(k))
            continue
        run.append(k)
    flush()
    return segs


def _render(node, drop=()):
    """Serialize a node back to (tidied) html: strong->b, em->i, colored
    spans preserved (site's green key forms / red errors), links -> the
    editor's {label|url} inline links EXCEPT test-english.com ones (never
    link to test-english inside a transferred lesson), check/cross icons ->
    colored marks."""
    if isinstance(node, _Text):
        t = node.text.replace("\xa0", " ")
        t = re.sub(r"(?<=\S)=", " =", t)
        return _html.escape(t, quote=False)
    if node.tag in drop:
        return ""
    if node.tag == "br":
        return "<br>"
    if node.tag == "img":
        src = node.attrs.get("src", "")
        for key, (mark, color) in _ICON.items():
            if key in src:
                return f'<span style="color:{color}">{mark}</span>'
        return ""
    if node.tag == "a":
        href = _html.unescape(node.attrs.get("href", ""))
        label = _tidy(_strip_tags("".join(_render(k, drop)
                                          for k in node.kids)))
        if (href.startswith("http") and label
                and "test-english" not in href and "pinterest" not in href):
            return "{%s|%s}" % (label, href)
        return label
    if node.tag == "span":
        inner = "".join(_render(k, drop) for k in node.kids)
        props = re.findall(r"(background-color|color)\s*:\s*([^;\"]+)",
                           node.attrs.get("style", ""))
        if props and inner:
            st = "; ".join("%s: %s" % (k, v.strip()) for k, v in props)
            return '<span style="%s">%s</span>' % (st, inner)
        return inner
    inner = "".join(_render(k, drop) for k in node.kids)
    tag = {"strong": "b", "em": "i"}.get(node.tag, node.tag)
    if tag in ("picture", "source", "div", "li", "p", "ul", "ol",
               "h1", "h2", "h3", "h4", "h5", "#root"):
        return inner
    return f"<{tag}>{inner}</{tag}>" if tag in ("b", "i", "u") else inner


def _tidy(text):
    """Whitespace normalisation for rendered fragments."""
    t = _html.unescape(text or "")
    t = t.replace("\xa0", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _plain(node):
    if isinstance(node, _Text):
        return node.text.replace("\xa0", " ")
    return "".join(_plain(k) for k in node.kids)


def _extract_blocks(node, out, group=None):
    """Flatten the explanation tree into ordered blocks."""
    for kid in node.kids:
        if isinstance(kid, _Text):
            continue
        tag = kid.tag
        if tag in ("script", "style", "h6"):
            continue
        if tag in ("h2", "h3", "h4", "h5"):
            htxt = re.sub(r"(?<=\S)=", " =", _plain(kid))
            out.append({"k": "h", "level": int(tag[1]),
                        "text": _tidy(htxt)})
        elif tag == "img":
            src = kid.attrs.get("src", "")
            if src and not any(s in src for s in SKIP_IMG):
                out.append({"k": "img", "src": _html.unescape(src)})
        elif tag == "p":
            segs = _split_para(kid)
            if any(kind == "img" for kind, _v in segs):
                for kind, val in segs:
                    if kind == "img":
                        out.append({"k": "img", "src": val})
                    else:
                        out.append({"k": "p", "html": val,
                                    "group": group or id(kid)})
                continue
            html = _tidy(_render(kid))
            if html:
                out.append({"k": "p", "html": html,
                            "group": group or id(kid)})
        elif tag == "ul" or tag == "ol":
            items = []
            for li in kid.kids:
                if not isinstance(li, _Text) and li.tag == "li":
                    items.append(_tidy(_render(li)))
            if items:
                out.append({"k": "ul", "items": items, "group": group or id(kid)})
        elif tag == "div":
            # infoblock / use-list containers: <br>-separated inline content
            cls = (kid.attrs.get("class") or "").lower()
            if "textbox" in cls:
                # the site's .textBox panel (the USE list): <p> lines in a box
                lines = []
                for k in kid.kids:
                    if not isinstance(k, _Text) and k.tag == "p":
                        h = _tidy(_render(k))
                        if h:
                            lines.append(h)
                if lines:
                    out.append({"k": "textbox", "items": lines,
                                "group": id(kid)})
                continue
            has_block_kids = any((not isinstance(k, _Text))
                                 and k.tag in ("p", "ul", "ol", "div", "h2",
                                               "h3", "h4", "h5")
                                 for k in kid.kids)
            if has_block_kids:
                _extract_blocks(kid, out, group=id(kid))
            else:
                html = _tidy(_render(kid))
                if html:
                    kind = ("infoblock"
                            if "infoblock" in (kid.attrs.get("class") or "")
                            else "p")
                    out.append({"k": kind, "html": html, "group": id(kid)})
        elif tag == "a":
            continue  # stray links (banner etc.)
    return out


def explanation_exercises(explanation_html):
    """Turn the Explanation tab html into lesson-spec exercises:
      [Pictures chart]  (unnamed - a named Pictures block would get a number)
      [Text block titled with the site's h2, body styled with Edvibe colors:
       h4 sub-headings in the site's heading colour, the .infoblock rendered
       as a gray-background callout, check/cross marks green/red]
    Numbering off (show_number False)."""
    parser = _TreeBuilder()
    parser.feed(explanation_html or "")
    blocks = _extract_blocks(parser.root, [])

    exercises = []
    buf = []          # [(group, html), ...]; same group -> joined with <br>
    title = None      # pending h2 - becomes the next Text block's name
    soft = None       # current sub-heading group (keeps its text tight)

    def flush():
        nonlocal buf, soft, title
        if not buf:
            return
        html = buf[0][1]
        prev = buf[0][0]
        for g, h in buf[1:]:
            html += ("<br>" if (g == prev and g is not None)
                     else "<br><br>") + h
            prev = g
        exercises.append({"type": "text", "html": html,
                          "name": title or "", "show_number": False})
        buf = []
        soft = None
        title = None

    for b in blocks:
        if b["k"] == "h":
            if b["level"] == 2:
                flush()
                title = b["text"]
            else:
                soft = ("soft", id(b))
                buf.append((soft, _c(b["text"])))
        elif b["k"] == "img":
            flush()
            exercises.append({"type": "pictures", "name": "",
                              "image": b["src"], "show_number": False})
        else:
            g = soft or b.get("group")
            if b["k"] == "ul":
                buf.append((g, "<br>".join(
                    _bar(it, PAL_BLUE_BAR, PAL_BLUE_BG) for it in b["items"])))
            elif b["k"] == "textbox":
                buf.append((g, "<br>".join(
                    _bar(it, PAL_GRAY_BAR, PAL_GRAY_BG2) for it in b["items"])))
            elif b["k"] == "infoblock":
                lines = []
                for x in re.split(r"<br\s*/?>", b["html"]):
                    t = x.strip()
                    t = re.sub(r"^‣\s*", "", t)   # the ▎ bar already marks it
                    if _strip_tags(t):
                        lines.append(_hl(t))
                buf.append((id(b), "<br>".join(lines)))
            else:
                buf.append((g, b["html"]))
    flush()
    return exercises


def explanation_exercise(explanation_html, dims=None):
    """The whole Explanation tab as ONE Text exercise:
    - the site's h2/h4 headings stay inline (coloured, the block look)
    - both Pinterest charts go in as inline image blocks (IMG: comments)
    - links keep working ({label|url}) - as in the text editor
    - blocks are separated by blank-line spacers (<p><br></p> = one empty
      line; paragraphs carry NO margins in the renderer, so the rhythm must
      come from explicit spacers or everything looks squished).
    Returns a single {'type': 'text'} spec item."""
    parser = _TreeBuilder()
    parser.feed(explanation_html or "")
    blocks = _extract_blocks(parser.root, [])
    parts = []

    def add(html):
        if html:
            parts.append(html)

    for b in blocks:
        if b["k"] == "h":
            add("<p>%s</p>" % _c(b["text"]))
        elif b["k"] == "img":
            w, h = (dims or {}).get(b["src"]) or _img_dim(b["src"])
            add(_img_block(b["src"], w, h))
        elif b["k"] == "ul":
            # site's ul.grammar-ex: light-blue panel + blue left bar
            add("<p>%s</p>" % "<br>".join(
                _bar(it, PAL_BLUE_BAR, PAL_BLUE_BG) for it in b["items"]))
        elif b["k"] == "textbox":
            # site's .textBox (USE list): light fill + gray left bar
            add("<p>%s</p>" % "<br>".join(
                _bar(it, PAL_GRAY_BAR, PAL_GRAY_BG2) for it in b["items"]))
        elif b["k"] == "infoblock":
            lines = []
            for x in re.split(r"<br\s*/?>", b["html"]):
                t = re.sub(r"^‣\s*", "", x.strip())
                if _strip_tags(t):
                    lines.append(_hl(t))
            add("<p>%s</p>" % "<br>".join(lines))
        else:
            add("<p>%s</p>" % b["html"])
    spacer = "<p><br></p>"          # one blank line between blocks
    return {"type": "text", "html": spacer.join(parts), "name": "",
            "show_number": False}


def html_escape(s):
    return _html.escape(s or "", quote=False)


# ------------------------------------------------- exercises → edvibe items
def _variants(ans):
    """Typed-gap accepted answers: ONE canonical form per meaning.

    No straight/curly apostrophe twins - the Edvibe checker itself
    normalises ' and ' to ' before comparing (verified in the live
    frontend code: SpecialSymbols maps both curly forms to \x27), so a
    twin is pure display noise in the payload. Case-only duplicates are
    also skipped (the checker is case-insensitive). Meaningfully different
    forms the site lists (e.g. 'is not' / "isn't") are kept by the CALLER
    (_gap_variants)."""
    ans = (ans or "").strip()
    return [ans] if ans else []


_PAREN_ANS_RE = re.compile(r"[()]")


def _check_no_paren_answers(site_values):
    """The site prints some accepted answers with parenthesized alternatives
    ('is ('s) always full of energy'). Students cannot type those literally -
    every such question needs an explicit answer_overrides.json entry
    (slug/page/question) with the split variants. Fail loudly instead of
    shipping untypeable answers."""
    for v in site_values or []:
        if isinstance(v, str) and _PAREN_ANS_RE.search(v):
            raise ValueError(
                "site answer contains a parenthesized alternative: %r - "
                "add an answer_overrides.json entry (slug/page/question) "
                "with the split variants" % v)


def _strip_num_boxes(text):
    """The site numbers the gaps of long dialogues with numBox spans."""
    return re.sub(r'<span class="numBox">\s*\d+\s*</span>\s?', "", text or "")


# --- dialogue & single-text presentation (owner request, Sep 2026) ---------
#
# Two site conventions look wrong in Edvibe and are corrected at build time:
#  * dialogues (site: one numbered question per turn) read as a script in
#    Edvibe -> the per-line numbers go, the speaker labels get bold;
#  * a page whose whole body is ONE text/dialogue still carried a leading
#    '<b>1.&nbsp;</b>' -> a one-item list needs no numbering.

BOLD_SPEAKERS = True    # bold dialogue speaker labels ("A:", "Interviewer:")

# one speaker label: Ann / Interviewer / A / PHILLIP / REAL ESTATE AGENT
_LBL = (r"(?:[A-Z][\w\u2019'.\-]*"
        r"|[A-Z]{2,}(?:\s+[A-Z]{2,}){0,2})")
_LBL_HEAD_RE = re.compile(r"^\s*(?:<[^>]+>\s*)*(?P<lbl>%s)\s*:" % _LBL)
_LBL_MID_RE = re.compile(
    r"(?:(?<=[.!?\u2019\u201d'\"])[ \t]+|(?<=>)[ \t]*)(?P<lbl>%s)\s*:" % _LBL)
# '<strong>Dialogue 1</strong>' / 'Dialogue 2 (taste)' - a question titled as
# a dialogue block (each question of the page is one mini-dialogue)
_DLG_HEAD_RE = re.compile(r"^\s*(?:<[^>]+>\s*)*Dialogue\s*\d+\b", re.I)


def _speaker_label(text):
    """True when a text segment opens with a speaker label ('A:', 'ANN:')."""
    return bool(_LBL_HEAD_RE.match(text or ""))


def _bold_speakers(text):
    """Bold the speaker labels of a dialogue text (labels only, nothing else).

    Labels sit at the start of a line/turn (optionally inside the site's
    styling spans / after a closing tag) or right after a sentence end /
    closing quote ('...TV.' B: 'No...')."""
    if not BOLD_SPEAKERS or not text:
        return text
    segs = re.split(r"(<br\s*/?>(?:\s*<br\s*/?>)*)", text)
    for i, seg in enumerate(segs):
        if i % 2 or not seg or seg.lstrip().startswith("<b>"):
            continue
        m = _LBL_HEAD_RE.match(seg)
        if m:
            seg = (seg[:m.start("lbl")] + "<b>" + m.group("lbl") + ":</b>"
                   + seg[m.end():])

        def _wrap(mm, _s=seg):
            if _s[max(0, mm.start() - 3):mm.start()].lower().endswith("<b>"):
                return mm.group(0)          # already bolded by the head pass
            return (mm.group(0)[:mm.start("lbl") - mm.start()] + "<b>"
                    + mm.group("lbl") + ":</b>")

        segs[i] = _LBL_MID_RE.sub(_wrap, seg)
    return "".join(segs)


def _text_is_dialogue(processed_html):
    """True when a processed text reads as a dialogue (>=2 speaker turns,
    whether the turns sit on their own lines or share one line)."""
    t = processed_html or ""
    segs = re.split(r"<br\s*/?>(?:\s*<br\s*/?>)*", t)
    n = sum(1 for s in segs if _speaker_label(s)) + len(_LBL_MID_RE.findall(t))
    return n >= 2


def _is_dialogue_page(qs):
    """True when the page's questions are dialogue turns (>=80% speaker-led or
    'Dialogue N'-titled): the site renders one numbered question per turn,
    Edvibe should not."""
    if len(qs) < 2:
        return False
    led = 0
    for q in qs:
        t = q.get("text") or re.sub(r"<[^>]+>", " ", q.get("text_html") or "")
        t = re.sub(r"\[\[\d+\]\]", "", t)
        if _speaker_label(t) or _DLG_HEAD_RE.match(t):
            led += 1
    return led >= 0.8 * len(qs)


def _gap_variants(q, idx, g):
    """Accepted answers for one gap: site variants (gap_answers) when known,
    else the flat correct list; always expanded with apostrophe forms.

    When the site printed 'A/B' for a SINGLE-gap question those are
    alternatives for the same gap - merge them instead of dropping all but
    the first."""
    ga = q.get("gap_answers") or []
    corr = q.get("correct") or []
    if len(q.get("gaps") or []) == 1 and len(ga) > 1:
        site = [v for grp in ga for v in grp if v]
    elif idx < len(ga) and ga[idx]:
        site = ga[idx]
    elif idx < len(corr) and corr[idx]:
        site = [corr[idx]]
    else:
        site = []
    _check_no_paren_answers(site)
    # merged single-gap lists (the site's per-numBox answer groups) can hold
    # shared-stem compacts too - expand before building the payload
    site = _expand_shared_stem(list(site))
    out = []
    seen = set()
    for v in site:
        for x in _variants(v):
            k = _apos_key(x)
            if x and k not in seen:
                seen.add(k)
                out.append(x)
    return out


def _strip_scripts(html):
    """Drop raw <script>…</script> blocks (WordPress/Facebook junk leaks into
    example_html in some lessons and must never reach student text)."""
    return re.sub(r"<script\b.*?</script\s*>", "", html or "", flags=re.S | re.I)


_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)


def _inline_imgs(html):
    """Raw <img> tags do not render in Edvibe exercise text - convert them to
    IMG-comment blocks (W/H taken from the tag's own width/height attrs).
    Site icon images become the tick/cross marks; banners are dropped."""
    def rep(m):
        tag = m.group(0)
        src = re.search(r'src="([^"]+)"', tag)
        if not src:
            return ""
        url = _html.unescape(src.group(1))
        if url.startswith("data:") or any(s in url for s in SKIP_IMG):
            return ""
        if "correct.png" in url:
            return '<span style="color: %s">✓</span>' % PAL_GREEN
        if "wrong.png" in url:
            return '<span style="color: %s">✗</span>' % PAL_RED
        w = re.search(r'width="(\d+)"', tag)
        h = re.search(r'height="(\d+)"', tag)
        return ("<!--IMG:%s;CX:;CY:;CW:;CH:;W:%s;H:%s;A:;-->"
                % (url, w.group(1) if w else "", h.group(1) if h else ""))
    return _IMG_TAG_RE.sub(rep, html or "")


def _strip_wrappers(html):
    """Unwrap the site's <p>/<div> wrappers around question/answer lines.

    The quiz markup wraps most question sentences in <div>...</div>. Edvibe's
    renderer draws a <div> as its own block, and the <br><br> question join
    then stacks on top of it - result: huge blank gaps between questions.
    Unwrap both wrappers; two adjacent divs become one intended <br>.

    Paragraph boundaries INSIDE one question (multi-paragraph texts: letters,
    dialogues, stimulus+prompt items - the site's <p class="double-line-height">)
    become a real blank line (<br><br>): without it every turn glued into one
    run of text ('PHILLIP: Good morning. REAL ESTATE AGENT: Yes...').

    Raw <script> blocks are dropped and raw <img> tags become IMG comments."""
    html = _strip_scripts(html)
    html = _inline_imgs(html)
    html = re.sub(r"</p>\s*<p\b[^>]*>", "<br><br>", html, flags=re.I)
    html = re.sub(r"</div>\s*<div[^>]*>", "<br>", html)
    html = re.sub(r"\s*</div>", "", html)
    html = re.sub(r"</?p[^>]*>", "", html)
    html = re.sub(r"</?div[^>]*>", "", html)
    return re.sub(r"[ \t]+<br>", "<br>", html)


def _gapify_select(q, bold=False):
    text = _strip_num_boxes(_strip_wrappers(q["text_html"]))
    if bold:
        text = _bold_speakers(text)
    for idx, g in enumerate(q["gaps"]):
        opts = list(g["options"])
        variants = _gap_variants(q, idx, g)
        correct = variants[0] if variants else ""
        hit = None
        for j, o in enumerate(opts):
            if o.strip().casefold() == (correct or "").strip().casefold():
                hit = j
                break
        if hit is not None:
            opts[hit] = opts[hit] + "*"
        elif correct:
            opts.append(correct + "*")
        text = text.replace("[[%s]]" % g["n"], "[" + "/".join(opts) + "]")
    return _del_to_s(_tidy(text))


def _gapify_text(q, bold=False):
    text = _strip_num_boxes(_strip_wrappers(q["text_html"]))
    if bold:
        text = _bold_speakers(text)
    for idx, g in enumerate(q["gaps"]):
        variants = _gap_variants(q, idx, g)
        payload = "[/" + "/".join(variants) + "]" if variants else "[]"
        text = text.replace("[[%s]]" % g["n"], payload)
    return _del_to_s(_tidy(text))


EXAMPLE_STYLE = "panel"   # "panel" (blue bar) | "label" | "gray" — owner-selectable


def _del_to_s(html):
    """<del> does not render in Edvibe exercise text; <s> renders (strikethrough)."""
    return (html or "").replace("<del>", "<s>").replace("</del>", "</s>")


def _box_line(box_html):
    """The site's word box (div.textBox) -> gray panel line(s)."""
    lines = [l.strip() for l in re.split(r"<br\s*/?>", box_html or "") if l.strip()]
    if not lines:
        return ""
    return "<br>".join(
        '<span style="background-color: rgb(249, 249, 250)">'
        '<span style="color: #CDD3DA">▎</span> ' + l + '</span>' for l in lines)


def _style_example(text, label="Example:"):
    """Wrap the EXAMPLE sentence in the house style (EXAMPLE_STYLE), per line."""
    lines = [l.strip() for l in re.split(r"<br\s*/?>", text or "") if l.strip()]
    out = []
    for i, l in enumerate(lines):
        if EXAMPLE_STYLE == "gray":
            out.append('<span style="background-color: rgb(246, 246, 246)">'
                       '<span style="color: #8b929a">▎</span> '
                       + ('<b>%s</b> ' % label if i == 0 else '') + l + '</span>')
        elif EXAMPLE_STYLE == "label":
            out.append(('<b><span style="color: #1A8EC1">%s</span></b> '
                        '<i>' % label + l + '</i>') if i == 0 else ('<i>' + l + '</i>'))
        else:  # "panel"
            out.append('<span style="background-color: rgb(241, 249, 254)">'
                       '<span style="color: #1A8EC1">▎</span> '
                       + ('<b><span style="color: #1A8EC1">%s</span></b> ' % label
                          if i == 0 else '') + l + '</span>')
    return "<br>".join(out)


def _unspan_textgap(html):
    """Drop the site's <span class="textGap"> highlights, repairing a missing
    space at a word boundary ('pass</span>the' -> 'pass the')."""
    html = re.sub(r'(?<=[A-Za-z0-9])<span class="textGap">(?=[A-Za-z0-9])',
                  ' <span class="textGap">', html)
    html = re.sub(r'<span class="textGap">(.*?)</span>(?=[A-Za-z0-9])',
                  lambda m: m.group(1) + " ", html, flags=re.S)
    return re.sub(r'<span class="textGap">(.*?)</span>', r"\1", html, flags=re.S)


def _clean_example(example_html):
    """The page's example block (word box + EXAMPLE: line) -> styled exercise
    lines: script junk dropped, word box -> gray panel, EXAMPLE -> house
    highlight. Returns '' when nothing usable is left."""
    if not example_html:
        return ""
    t = _strip_scripts(example_html)
    box = ""
    bm = re.search(r'<(p|div|span)\b[^>]*class="[^"]*textBox[^"]*"[^>]*>'
                   r"(.*?)</\1>", t, re.S)
    if bm:
        box = bm.group(2)
        t = t[:bm.start()] + " " + t[bm.end():]
    t = _strip_wrappers(t)
    t = _unspan_textgap(t)
    t = t.replace("<em>", "<i>").replace("</em>", "</i>")
    t = _tidy(t)
    t = re.sub(r"^(?:\s*<br>\s*)+", "", t)
    t = re.sub(r"(?:\s*<br>\s*)+$", "", t).strip()
    parts = []
    box = _del_to_s(_tidy(box)) if box else ""
    if box:
        parts.append(_box_line(box))
    # per-line: labels with their sentence(s) get the house style; a label on
    # its own line ('EXAMPLE:<br>A: ...<br>B: ...') styles the lines after it
    label, lines = None, []

    def _flush():
        if not lines:
            return
        if label:
            parts.append(_style_example("<br>".join(lines), label))
        else:
            parts.extend(lines)

    for seg in re.split(r"<br\s*/?>", t):
        seg = seg.strip()
        if not seg:
            continue
        seg = re.sub(r"^\s*<i>\s*", "", seg)
        m = re.match(r"\s*EXAMPLE\s*(\([^)]*\))?\s*[:\-–—]?\s*", seg, re.I)
        if m:
            _flush()
            label = "Example" + (" " + m.group(1) if m.group(1) else "") + ":"
            rest = re.sub(r"\s*</i>\s*$", "", seg[m.end():]).strip()
            if rest:
                lines.append(_del_to_s(rest))
            continue
        seg = re.sub(r"\s*</i>\s*$", "", seg).strip()
        if seg:
            lines.append(_del_to_s(seg))
            if not label:      # plain run outside any example -> emit as-is
                _flush()
    _flush()
    return "<br>".join(p for p in parts if p)


def _gapify_radio(q, bold=False):
    """Radio-MCQ question -> dropdown(s) at the blank(s).

    The site's 'choose the correct option' radios come in two flavours:
      * ONE blank, options are plain words -> a single dropdown (as before);
      * SEVERAL blanks with PAIR options ('It / it', 'mine/hers') -> one
        dropdown PER blank, options taken column-wise from the pairs (the
        2x2 combination space is identical to the site's pair choice, but
        the student can answer every gap and the auto-check works per gap)."""
    text = _strip_wrappers(q["text_html"])
    if bold:
        text = _bold_speakers(text)
    opts = list(q.get("choices") or [])
    corr = (q["correct"] or [""])[0].strip()
    parts = [p.strip() for p in re.split(r"\s*/\s*", corr) if p.strip()]
    blanks = len(re.findall(r"_{3,}", text))
    if blanks >= 2 and parts:
        if len(parts) == 1:
            parts = parts * blanks          # same word into every blank
        if len(parts) == blanks:
            rows = [[p.strip() for p in re.split(r"\s*/\s*", c)] for c in opts]
            cols = None
            if rows and all(len(r) == blanks for r in rows):
                cols = []
                for k in range(blanks):
                    col, seen = [], set()
                    for r in rows:
                        v = r[k]
                        if v and v.lower() not in seen:
                            seen.add(v.lower())
                            col.append(v)
                    cols.append(col)
            new = text
            for k, part in enumerate(parts):
                popts = list(cols[k]) if cols and cols[k] else list(opts)
                hit = None
                for j, o in enumerate(popts):
                    if o.strip().casefold() == part.casefold():
                        hit = j
                        break
                if hit is not None:
                    popts[hit] = popts[hit] + "*"
                else:
                    popts.append(part + "*")
                new = re.sub(r"_{3,}", "[" + "/".join(popts) + "]", new,
                             count=1)
            return _del_to_s(_tidy(new))
    hit = None
    for j, o in enumerate(opts):
        if o.strip().casefold() == corr.casefold():
            hit = j
            break
    if hit is not None:
        opts[hit] = opts[hit] + "*"
    elif corr:
        opts.append(corr + "*")
    payload = "[" + "/".join(opts) + "]"
    new, n = re.subn(r"_{3,}", payload, text, count=1)
    if n == 0:
        new = text.rstrip() + " " + payload
    return _del_to_s(_tidy(new))


def _radio_testable(q):
    """Radio question that a dropdown cannot render faithfully: no blank in
    the sentence (the dropdown would dangle after the text), several
    correct options (a dropdown admits exactly one star), or a merged
    multi-variant option ('on the point of / on the verge of' - the '/'
    would split it into two duplicate dropdown entries)."""
    if not (q.get("choices") and not q.get("gaps")):
        return False
    text = q.get("text") or ""
    if not re.search(r"_{3,}", text):
        return True
    if len([c for c in (q.get("correct") or []) if c]) >= 2:
        return True
    if len(re.findall(r"_{3,}", text)) == 1:
        return any(" / " in (c or "") for c in (q.get("choices") or []))
    return False


def _norm_opt(s):
    """Option/correct matching key: case-blind, space-blind, slash-blind
    (pair options like 'drive / 'm walking' == 'drive/'m walking')."""
    s = re.sub(r"\s+", " ", (s or "").strip()).casefold()
    return re.sub(r"\s*/\s*", "/", s)


def build_radio_test(page, bold=False):
    """Radio-MCQ page -> ONE Edvibe Test (type 5, untimed): questions with
    clickable options - the UI closest to the site's radio quizzes. A
    dropdown dangling after 'Which sentence is correct?' is unreadable, and
    choose-TWO questions need 2 correct options (a dropdown admits one).
    Multi-blank pair questions keep the site's pair options verbatim
    (e.g. 'drive / 'm walking') as single options."""
    questions = []
    for q in page["questions"]:
        opts = [o for o in (q.get("choices") or []) if o.strip()]
        corr = [c.strip() for c in (q.get("correct") or []) if c and c.strip()]
        hit = []
        for c in corr:
            for j, o in enumerate(opts):
                if _norm_opt(o) == _norm_opt(c):
                    hit.append(j)
                    break
        text = _del_to_s(_tidy(_strip_num_boxes(_strip_wrappers(q["text_html"]))))
        if bold:
            text = _bold_speakers(text)
        questions.append({"q": text, "options": opts, "correct": hit})
    return {"type": "test", "instruction": page["instruction"],
            "questions": questions, "points": False}


def page_exercise(page):
    qs = page["questions"]
    kinds = {g["kind"] for q in qs for g in q["gaps"]}
    has_radio = any(q.get("choices") for q in qs)
    if not kinds and not has_radio:
        raise ValueError(
            "page %s (%s): no gaps found - this exercise type is "
            "not supported by the converter yet; pick another --pages set or "
            "build this exercise by hand" % (page.get("page"), page.get("label")))
    # presentation: a one-text page needs no '1.' prefix; a dialogue page is a
    # script (no per-turn numbers, speakers bold) - see the helpers above.
    dialogue = _is_dialogue_page(qs)
    numbered = len(qs) > 1 and not dialogue
    if not kinds and has_radio and any(_radio_testable(q) for q in qs):
        # radio-MCQ with dangling-dropdown / choose-TWO questions -> Test
        return build_radio_test(page, bold=dialogue)
    if kinds <= {"select"}:
        lines = []
        ex = _clean_example(page.get("example_html"))
        if ex:
            # word box / EXAMPLE line, same treatment as fill-typed exercises
            lines.append(ex)
        for i, q in enumerate(qs, 1):
            bold = dialogue or (len(qs) == 1 and _text_is_dialogue(
                _strip_num_boxes(_strip_wrappers(q["text_html"]))))
            text = _gapify_radio(q, bold=bold) \
                if (q.get("choices") and not q["gaps"]) else _gapify_select(q, bold=bold)
            lines.append(("<b>%d.&nbsp;</b> %s" % (i, text)) if numbered else text)
        return {"type": "chooseoption", "instruction": page["instruction"],
                "lines": lines}
    if kinds <= {"text"} and not has_radio:
        sentences = []
        for i, q in enumerate(qs, 1):
            bold = dialogue or (len(qs) == 1 and _text_is_dialogue(
                _strip_num_boxes(_strip_wrappers(q["text_html"]))))
            text = _gapify_text(q, bold=bold)
            sentences.append(("<b>%d.&nbsp;</b> %s" % (i, text)) if numbered else text)
        ex = _clean_example(page.get("example_html"))
        if ex:
            # the site's EXAMPLE line goes right under the instruction,
            # as the first line of the body (not into the 20px title)
            sentences = [ex] + sentences
        return {"type": "filltyped", "instruction": page["instruction"],
                "sentences": sentences}
    raise ValueError(
        "page %s (%s): mixed gap kinds %s%s are not supported by the converter "
        "yet; build this exercise by hand" % (
            page.get("page"), page.get("label"), sorted(kinds),
            " + radio" if has_radio else ""))


def answer_note(page):
    label = page.get("label") or ("Exercise %s" % page.get("page"))
    rows = []
    n = 0

    def _expl(xs):
        parts = []
        for e in (xs or []):
            e = re.sub(r"(?<=\S)=", " =", e or "").strip()
            if e and e[-1] not in ".!?":
                e += "."
            if e:
                parts.append(e)
        return " ".join(parts)

    def _vs(vs):
        """Display variants: drop the case-only twins (Edvibe is case-blind)."""
        out, seen = [], set()
        for v in vs:
            k = (v or "").strip().casefold()
            if k and k not in seen:
                seen.add(k)
                out.append(v)
        return out

    for q in page["questions"]:
        ga = q.get("gap_answers") or []
        ge = dict(q.get("gap_explanations") or [])
        if ge:
            # one row per gap (long dialogues: each gap has its own note)
            for i, variants in enumerate(ga, 1):
                n += 1
                expl = _expl(ge.get(i))
                rows.append('<b>%d.&nbsp;</b><span style="color: %s">%s</span>%s'
                            % (n, PAL_GREEN, html_escape(" / ".join(_vs(variants))),
                               (" — " + html_escape(expl)) if expl else ""))
        else:
            n += 1
            if len(ga) > 1:
                corr = " · ".join(" / ".join(_vs(v)) for v in ga)
            else:
                corr = " / ".join(_vs(ga[0] if ga else q.get("correct") or []))
            expl = _expl(q.get("explanations"))
            rows.append('<b>%d.&nbsp;</b><span style="color: %s">%s</span>%s'
                        % (n, PAL_GREEN, html_escape(corr),
                           (" — " + html_escape(expl)) if expl else ""))
    return {"type": "note", "hidden": True, "show_number": False,
            "name": "Answer key — %s" % label, "html": "<br>".join(rows)}


def build_spec(data, pages=(1, 2), explanation="single"):
    """data (fetch_lesson output) -> lesson-spec dict for build_lesson.
    explanation: 'single' - the whole Explanation tab as ONE Text exercise
    with inline images/links (default); 'blocks' - the older layout
    (chart/text/chart/text as separate items)."""
    dims = {}
    for u in (data.get("images") or []):
        try:
            dims[u] = _img_dim(u)
        except Exception:  # noqa: BLE001
            pass
    if explanation == "single":
        expl = [explanation_exercise(data.get("explanation_html"), dims)]
    else:
        expl = explanation_exercises(data.get("explanation_html"))
    spec = {
        "lesson_name": data.get("lesson_title") or "test-english lesson",
        "sections": [
            {"name": "Explanation", "exercises": expl},
        ],
    }
    exs = []
    for pno in pages or ():
        page = next((p for p in data.get("pages") or []
                     if p.get("page") == int(pno)), None)
        if page:
            exs.append(page_exercise(page))
            exs.append(answer_note(page))
    if exs:
        spec["sections"].append({"name": "Exercises", "exercises": exs})
    return spec


def level_from_url(url):
    m = re.search(r"/(a1|a2|b1\+?|b2|c1)(?:/|$)", url, re.I)
    return m.group(1).upper() if m else ""


def _apply_image_map(spec, mapping):
    """Rewrite inline chart images (<!--IMG:src;...--> comments) per mapping
    {source_url: {"url": new_url, "w": px, "h": px}} - used to keep the
    redesigned Notion-style charts when rebuilding from scrape data."""
    n = 0
    for sec in spec.get("sections") or []:
        for ex in sec.get("exercises") or []:
            html = ex.get("html")
            if not html:
                continue
            for src, rep in (mapping or {}).items():
                html, k = re.subn(
                    r'<!--IMG:%s;CX:[^>]*?-->' % re.escape(src),
                    '<!--IMG:%s;CX:;CY:;CW:;CH:;W:%s;H:%s;A:;-->'
                    % (rep["url"], rep.get("w", ""), rep.get("h", "")),
                    html)
                n += k
            ex["html"] = html
    return n


def import_lesson(session, url, book=None, section="grammar", pages=(1, 2),
                  lesson_name=None, lesson_id=None, dry_run=False, log=print,
                  data=None, cache_dir=None, replace_sections=None,
                  explanation="single", image_map=None, description=None):
    """One-shot transfer: scrape -> book/section scaffold -> lesson -> build.
    Returns a summary dict. dry_run=True validates and shows the plan only.
    data: use an already-scraped data.json instead of re-scraping.
    cache_dir: reuse/save raw page html + submit responses (fast re-runs).
    replace_sections: list of section names whose exercises are deleted before
    the import (idempotent rebuilds - e.g. ['Explanation', 'Exercises']).
    image_map: {source_chart_url: {'url','w','h'}} - replaces inline chart
    images (redesigned/self-hosted versions) instead of the source hot-links.
    description: lesson description html (default: the neutral legacy one-liner
    with the source url - pass a clean keyword-rich text for delivered books)."""
    if data is None:
        log("scraping %s ..." % url)
        data = fetch_lesson(url, pages=pages, cache_dir=cache_dir)
        if cache_dir:
            import json as _json
            os.makedirs(cache_dir, exist_ok=True)
            with open(os.path.join(cache_dir, "data.json"), "w",
                      encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=1)
    spec = build_spec(data, pages, explanation=explanation)
    if image_map:
        k = _apply_image_map(spec, image_map)
        log("image map applied: %d inline chart(s) swapped" % k)
    if lesson_name:
        spec["lesson_name"] = lesson_name
    if dry_run:
        from . import lesson_spec
        return {"dry_run": True, "plan": lesson_spec.plan(spec),
                "source": data["source_url"], "images": data["images"]}

    level = level_from_url(url)
    if book is None:
        book = "test-english %s" % level if level else "test-english"
    if str(book).strip().isdigit():
        book_id = int(str(book).strip())
    else:
        obj = session.find_book(book)
        if obj:
            book_id = obj.get("Id")
        else:
            book_id = session.create_material(book)
            log("created book '%s' -> %s" % (book, book_id))
    section_course = session.ensure_book_section(book_id, section)
    log("book %s, section '%s' -> course %s" % (book_id, section, section_course))

    created_lesson = lesson_id is None
    if created_lesson:
        lesson_id, auto_sec = session.create_lesson(book_id, section_course,
                                                    spec["lesson_name"])
        session.edit_section(lesson_id, auto_sec,
                             spec["sections"][0]["name"], 0)
        log("created lesson %s" % lesson_id)
    else:
        log("appending into lesson %s" % lesson_id)
        if replace_sections:
            les = session.get_lesson(lesson_id)
            byname = {s.get("Name"): s.get("Id")
                      for s in (les.get("Sections") or [])}
            for sname in replace_sections:
                sid = byname.get(sname)
                if not sid:
                    log("section '%s' not found - skipped" % sname)
                    continue
                removed = 0
                for ex in session.load_exercises(sid, lesson_id):
                    session.delete_exercise(ex.get("Id"), lesson_id, sid)
                    removed += 1
                log("section '%s' rebuilt: removed %d old item(s)"
                    % (sname, removed))

    desc = description or (
        "<b>Source:</b> %s<br><b>Structure:</b> Explanation + Exercises"
        % data["source_url"])
    from . import lesson_spec
    summary = lesson_spec.build_lesson(session, spec, lesson_id=lesson_id,
                                       material_id=book_id,
                                       name=spec["lesson_name"],
                                       description=desc, log=log)
    summary.update({"book_id": book_id, "section_course_id": section_course,
                    "lesson_id": lesson_id, "created_lesson": created_lesson,
                    "source_url": data["source_url"]})
    return summary
