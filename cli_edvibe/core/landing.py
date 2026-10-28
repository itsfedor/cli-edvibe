"""Teacher landing page («Сайт и заявки») — read/edit the personal site.

Every teacher has a free one-page site at https://edvibe.com/teachers/<slug>
(backend project ``TeacherLandingApi``). This module wraps the private RPCs:

- reads  (verified live Sep 2026): ``SiteSettingsWsController.GetSiteSettings``,
  ``GetSiteBlocks``, ``PupilRegistrationRequestsWsController.ListRegistrationRequests``
- writes (mapped from the education_shell bundles; exercised via the ``site``
  CLI with backup + read-back verification): ``SaveLandingSite`` /
  ``PublishLandingSite`` — both take the WHOLE site
  ``{MetaTags:{Title,Description,ImageUrl}, Blocks:[{Type,OrderIndex,IsEnabled,BlockJson}]}``
  where ``BlockJson`` is the block's ``DataJson`` JSON **string** (byte-preserved
  for untouched blocks). ``PublishLandingSite`` returns ``{Data:{SiteUrlPostfix,IsPublishing}}``.

Safety model: ``GetSiteBlocks`` -> backup -> rebuild full payload -> save ->
read-back diff. A block can be enabled/hidden (``IsEnabled`` + the block's inner
``IsShow``) and its data fields merged (``set``); blocks CANNOT be added or
removed — the server workspace owns the set of blocks.
"""
import copy
import json
import os
import time

from .client import EdvibeError

PROJECT = "TeacherLandingApi"

#: block Type -> canonical name (education_shell TeacherLandingBlockTypeEnum)
BLOCK_TYPES = {
    0: "top", 1: "main", 2: "about", 3: "video", 4: "statistics",
    5: "directions", 6: "examples", 7: "review", 8: "certificates",
    9: "questions", 10: "application", 11: "window", 12: "faq",
}

#: aliases accepted on the CLI / in patches
BLOCK_ALIASES = {
    "header": "top", "site-header": "top", "шапка": "top",
    "stats": "statistics", "statistic": "statistics",
    "prices": "directions", "price": "directions", "прайс": "directions",
    "lessons": "examples", "примеры": "examples",
    "reviews": "review", "отзывы": "review",
    "certs": "certificates", "сертификаты": "certificates",
    "form": "application", "form-block": "application",
    "success": "window", "confirmation": "window",
    "faqs": "faq", "вопросы": "faq",
}

#: patch keys for the Application block's legal documents.
#: NOTE: the RPC field ``PrivacyPolicy`` stores the USER AGREEMENT text and
#: ``PersonalDataPolicy`` stores the personal data processing policy text
#: (the cabinet editor labels them exactly that way).
POLICY_FIELDS = {
    "user_agreement": "PrivacyPolicy",
    "personal_data_policy": "PersonalDataPolicy",
}

BACKUP_DIR_DEFAULT = os.path.join(os.path.expanduser("~"), ".edvibe",
                                  "landing-backups")


# ----------------------------------------------------------------- helpers
def resolve_block_type(value):
    """'faq' / 'FAQ' / 12 -> 12. Raises EdvibeError on unknown names."""
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        t = int(value)
        if t in BLOCK_TYPES:
            return t
        raise EdvibeError(f"unknown block type {t} (known: {sorted(BLOCK_TYPES)})")
    key = str(value).strip().lower()
    key = BLOCK_ALIASES.get(key, key)
    if key in BLOCK_TYPES.values():
        return {v: k for k, v in BLOCK_TYPES.items()}[key]
    raise EdvibeError(f"unknown block name '{value}' "
                      f"(known: {sorted(BLOCK_TYPES.values())})")


def _rpc(sess, controller, method, value=None):
    resp = sess.rpc(controller, method, PROJECT, value if value is not None else {})
    if not resp.get("IsSuccess"):
        raise EdvibeError(f"{controller}.{method} failed: {resp.get('ErrorMessage')}")
    return resp


def _parse_data(block):
    raw = block.get("DataJson")
    if isinstance(raw, dict):  # tolerate an already-parsed model
        return raw
    try:
        return json.loads(raw or "{}")
    except ValueError:
        raise EdvibeError(f"block type {block.get('Type')}: DataJson is not valid JSON")


def _dump_data(data):
    return json.dumps(data, ensure_ascii=False)


# ----------------------------------------------------------------- read
def get_settings(sess):
    """GetSiteSettings -> {Url (slug), IsPublishing, IsLocked, TeacherId, MetaTags}."""
    return _rpc(sess, "SiteSettingsWsController", "GetSiteSettings", {}).get("Value") or {}


def get_blocks(sess):
    """GetSiteBlocks -> raw blocks list [{Type, OrderIndex, IsEnabled, DataJson, ...}]."""
    return _rpc(sess, "SiteSettingsWsController", "GetSiteBlocks", {}).get("Value", {}) \
        .get("Blocks", [])


def read_state(sess):
    """Everything needed to rebuild a save payload: settings + raw blocks."""
    return {"settings": get_settings(sess), "blocks": get_blocks(sess),
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def block_view(block):
    """Normalized, human/JSON friendly view of one block."""
    data = _parse_data(block)
    t = int(block.get("Type"))
    try:
        order = int(block.get("OrderIndex") or 0)
    except (TypeError, ValueError):
        order = 0
    view = {
        "type": t,
        "name": BLOCK_TYPES.get(t, f"type-{t}"),
        "order": order,
        "enabled": bool(block.get("IsEnabled")),
        "show": data.get("IsShow") if "IsShow" in data else None,
        "title": str(data.get("Title") or data.get("Name") or "")[:80],
        "data": data,
    }
    policies = {f: len(block.get(f) or "") for f in POLICY_FIELDS.values()
                if f in block}
    if policies:
        view["policies"] = policies
    return view


def state_view(state):
    """Human/JSON friendly view of the whole state."""
    settings = state.get("settings") or {}
    site_url = settings.get("Url")
    return {
        "url": f"https://edvibe.com/teachers/{site_url}" if site_url else None,
        "slug": site_url,
        "publishing": settings.get("IsPublishing"),
        "locked": settings.get("IsLocked"),
        "teacher_id": settings.get("TeacherId"),
        "meta": settings.get("MetaTags") or {},
        "blocks": [block_view(b) for b in sorted(state.get("blocks") or [],
                                                 key=lambda b: int(b.get("Type")))],
        "captured_at": state.get("captured_at"),
    }


# ----------------------------------------------------------------- payload
def build_payload(meta, blocks):
    """Rebuild the SaveLandingSite payload from (meta, raw blocks).

    BlockJson = the raw DataJson string (byte-preserved for untouched blocks);
    PrivacyPolicy/PersonalDataPolicy are copied when the server sent them.
    """
    out_blocks = []
    for b in blocks:
        item = {
            "Type": int(b.get("Type")),
            "OrderIndex": b.get("OrderIndex"),
            "IsEnabled": bool(b.get("IsEnabled")),
            "BlockJson": b.get("DataJson"),
        }
        for k in ("PrivacyPolicy", "PersonalDataPolicy"):
            if k in b:
                item[k] = b.get(k)
        out_blocks.append(item)
    return {
        "MetaTags": {
            "Title": (meta or {}).get("Title", ""),
            "Description": (meta or {}).get("Description", ""),
            "ImageUrl": (meta or {}).get("ImageUrl", ""),
        },
        "Blocks": out_blocks,
    }


def save_site(sess, meta, blocks):
    return _rpc(sess, "SiteSettingsWsController", "SaveLandingSite",
                build_payload(meta, blocks))


def publish_site(sess, meta, blocks):
    resp = _rpc(sess, "SiteSettingsWsController", "PublishLandingSite",
                build_payload(meta, blocks))
    return resp.get("Value") or resp


# ----------------------------------------------------------------- requests
def list_requests(sess, teacher_id=None, skip=0, take=50):
    """PupilRegistrationRequestsWsController.ListRegistrationRequests (read-only)."""
    if teacher_id is None:
        teacher_id = (get_settings(sess) or {}).get("TeacherId")
    val = _rpc(sess, "PupilRegistrationRequestsWsController", "ListRegistrationRequests",
               {"TeacherId": teacher_id, "Page": {"Skip": skip, "Take": take}}).get("Value") or {}
    items = val.get("Items") or []
    return {"teacher_id": teacher_id, "count": (val.get("Page") or {}).get("Count", len(items)),
            "items": items}


# ----------------------------------------------------------------- patch
def apply_patch(state, patch):
    """Apply a patch spec to a read_state() result; returns (meta, blocks, changes).

    Patch format::

        {
          "meta":   {"Title": "...", "Description": "...", "ImageUrl": "https://..."},
          "blocks": [
            {"type": "faq",      "enabled": true, "show": true},
            {"type": "examples", "set": {"Lessons": [...]}},
            {"type": "top",      "set": {"Name": "Фёдор Молодцов"}},
            {"type": "application", "user_agreement": "<p>…</p>",
                                    "personal_data_policy": {"file": "policy.html"}}
          ]
        }

    ``set`` shallow-merges keys into the block's DataJson; ``enabled``/``show``
    flip IsEnabled / the inner ``IsShow``. ``user_agreement`` (stored in the
    RPC field ``PrivacyPolicy``) and ``personal_data_policy`` set the two
    documents of the Application block — HTML strings, or ``{"file": path}``
    placeholders resolved by :func:`resolve_policy_files`. Blocks cannot be
    added or removed.
    """
    settings = state.get("settings") or {}
    meta = dict(settings.get("MetaTags") or {})
    changes = []
    for k, v in (patch.get("meta") or {}).items():
        if meta.get(k) != v:
            changes.append(f"meta.{k}: {str(meta.get(k))[:60]!r} -> {str(v)[:60]!r}")
            meta[k] = v

    blocks = [dict(b) for b in (state.get("blocks") or [])]
    by_type = {int(b.get("Type")): i for i, b in enumerate(blocks)}

    for item in patch.get("blocks") or []:
        if "type" not in item:
            raise EdvibeError("each block patch needs a 'type'")
        t = resolve_block_type(item["type"])
        if t not in by_type:
            raise EdvibeError(
                f"block '{BLOCK_TYPES.get(t, t)}' (type {t}) is not present on the site; "
                f"blocks cannot be added via patch (present: "
                f"{sorted(BLOCK_TYPES.get(int(b['Type'])) for b in blocks)})")
        idx = by_type[t]
        b = blocks[idx]
        name = BLOCK_TYPES.get(t, t)
        if "enabled" in item and bool(b.get("IsEnabled")) != bool(item["enabled"]):
            changes.append(f"{name}: enabled {bool(b.get('IsEnabled'))} -> {bool(item['enabled'])}")
            b["IsEnabled"] = bool(item["enabled"])
        data = _parse_data(b)
        if "show" in item:
            if data.get("IsShow") != bool(item["show"]):
                changes.append(f"{name}: IsShow {data.get('IsShow')} -> {bool(item['show'])}")
                data["IsShow"] = bool(item["show"])
        elif ("enabled" in item and "IsShow" in data
              and data.get("IsShow") != bool(item["enabled"])):
            # the platform UI keeps IsEnabled and the inner IsShow in sync for
            # blocks that carry IsShow (hidden blocks read back as both=false);
            # mirror it unless the caller passed an explicit "show".
            changes.append(f"{name}: IsShow {data.get('IsShow')} -> "
                           f"{bool(item['enabled'])} (mirrored)")
            data["IsShow"] = bool(item["enabled"])
        for k, v in (item.get("set") or {}).items():
            if data.get(k) != v:
                changes.append(f"{name}.{k}: changed")
                data[k] = v
        for key, field in POLICY_FIELDS.items():
            if key in item:
                v = item[key]
                if not isinstance(v, str):
                    raise EdvibeError(
                        f"{name}.{key}: value must be a string (the document "
                        f"text); {{\"file\": path}} is resolved by "
                        f"resolve_policy_files()")
                if (b.get(field) or "") != v:
                    changes.append(
                        f"{name}.{field}: {len(b.get(field) or '')} -> "
                        f"{len(v)} chars")
                b[field] = v
        b["DataJson"] = _dump_data(data)
        blocks[idx] = b
    return meta, blocks, changes


def resolve_policy_files(patch, base_dir=None):
    """Replace ``{"file": path}`` policy values in a patch with file contents.

    Returns a copy of the patch; ``base_dir`` anchors relative paths (default:
    cwd). Kept separate from :func:`apply_patch` so that stays a pure function.
    """
    out = copy.deepcopy(patch)
    for item in out.get("blocks") or []:
        for key in POLICY_FIELDS:
            v = item.get(key)
            if not isinstance(v, dict):
                continue
            path = v.get("file")
            if not path:
                raise EdvibeError(
                    f"block '{item.get('type')}': {key} object needs a 'file' "
                    f"key, e.g. {{\"file\": \"doc.html\"}}")
            if not os.path.isabs(path):
                path = os.path.join(base_dir or os.getcwd(), path)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    item[key] = fh.read()
            except OSError as exc:
                raise EdvibeError(f"cannot read {key} file: {exc}")
    return out


def diff_blocks(before_blocks, after_blocks):
    """Line diff between two raw block lists (for read-back verification)."""
    def norm(blocks):
        out = {}
        for b in blocks:
            out[int(b.get("Type"))] = {
                "enabled": bool(b.get("IsEnabled")),
                "data": _parse_data(b),
                "PrivacyPolicy": b.get("PrivacyPolicy") or "",
                "PersonalDataPolicy": b.get("PersonalDataPolicy") or "",
            }
        return out
    b1, b2 = norm(before_blocks), norm(after_blocks)
    lines = []
    for t in sorted(set(b1) | set(b2)):
        name = BLOCK_TYPES.get(t, t)
        a, c = b1.get(t), b2.get(t)
        if a is None or c is None:
            lines.append(f"{name}: block {'added' if a is None else 'removed'}")
            continue
        if a["enabled"] != c["enabled"]:
            lines.append(f"{name}: enabled {a['enabled']} -> {c['enabled']}")
        keys = set(a["data"]) | set(c["data"])
        for k in sorted(keys):
            if a["data"].get(k) != c["data"].get(k):
                av, cv = a["data"].get(k), c["data"].get(k)
                lines.append(f"{name}.{k}: {str(av)[:50]!r} -> {str(cv)[:50]!r}")
        for k in ("PrivacyPolicy", "PersonalDataPolicy"):
            if a[k] != c[k]:
                lines.append(f"{name}.{k}: {len(a[k])} -> {len(c[k])} chars")
    return lines


def verify_applied(state_before, state_after, patch):
    """Check that each requested patch change actually landed (read-back gate)."""
    _, _, changes = apply_patch(state_before, patch)
    if not changes:
        return []
    meta, blocks, _ = apply_patch(state_before, patch)
    expected = build_payload(meta, blocks)
    actual = build_payload(
        {"Title": (state_after.get("settings") or {}).get("MetaTags", {}).get("Title", ""),
         "Description": (state_after.get("settings") or {}).get("MetaTags", {}).get("Description", ""),
         "ImageUrl": (state_after.get("settings") or {}).get("MetaTags", {}).get("ImageUrl", "")},
        state_after.get("blocks") or [])
    problems = []
    if expected["MetaTags"] != actual["MetaTags"]:
        problems.append(f"MetaTags mismatch: expected {expected['MetaTags']}, "
                        f"read back {actual['MetaTags']}")
    exp_by = {b["Type"]: b for b in expected["Blocks"]}
    act_by = {b["Type"]: b for b in actual["Blocks"]}
    for t, eb in exp_by.items():
        ab = act_by.get(t)
        if ab is None:
            problems.append(f"{BLOCK_TYPES.get(t, t)}: missing after save")
            continue
        if bool(eb["IsEnabled"]) != bool(ab["IsEnabled"]):
            problems.append(f"{BLOCK_TYPES.get(t, t)}: IsEnabled not applied "
                            f"(expected {eb['IsEnabled']}, got {ab['IsEnabled']})")
        if eb["BlockJson"] != ab["BlockJson"]:
            # compare parsed to ignore key order / whitespace
            if _parse_data({"DataJson": eb["BlockJson"]}) != \
               _parse_data({"DataJson": ab["BlockJson"]}):
                problems.append(f"{BLOCK_TYPES.get(t, t)}: DataJson not applied")
    for item in patch.get("blocks") or []:
        t = resolve_block_type(item["type"])
        eb, ab = exp_by.get(t), act_by.get(t)
        if eb is None or ab is None:
            continue  # a missing block was already reported above
        for key, field in POLICY_FIELDS.items():
            if key in item:
                ev = eb.get(field) or ""
                av = ab.get(field) or ""
                if ev != av:
                    problems.append(
                        f"{BLOCK_TYPES.get(t, t)}: {field} not applied "
                        f"(expected {len(ev)} chars, read back {len(av)})")
    return problems


# ----------------------------------------------------------------- backup / save
def backup(state, out_dir=None, label=""):
    """Write a timestamped backup of settings+blocks; returns the file path."""
    out_dir = out_dir or BACKUP_DIR_DEFAULT
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    fname = f"{ts}{('-'+label) if label else ''}-landing.json"
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"settings": state.get("settings"),
                   "blocks": state.get("blocks"),
                   "captured_at": state.get("captured_at")}, f,
                  ensure_ascii=False, indent=1)
    return path


def save_with_safety(sess, patch, dry_run=False, out_dir=None, publish=False,
                     log=None):
    """backup -> save (or dry-run) -> read-back -> diff; returns a report dict."""
    def _log(msg):
        if log:
            log(msg)

    before = read_state(sess)
    meta, blocks, changes = apply_patch(before, patch)
    if not changes:
        return {"changed": [], "backup": None, "verified": True, "noop": True}
    _log("changes:")
    for c in changes:
        _log(f"  {c}")

    if dry_run:
        return {"changed": changes, "backup": None, "verified": None, "dry_run": True}

    backup_path = backup(before, out_dir=out_dir)
    _log(f"backup: {backup_path}")

    save_site(sess, meta, blocks)
    if publish:
        publish_site(sess, meta, blocks)

    after = read_state(sess)
    problems = verify_applied(before, after, patch)
    diff_lines = diff_blocks(before.get("blocks") or [], after.get("blocks") or [])
    _log("read-back diff:")
    for d in diff_lines or ["  (none)"]:
        _log(f"  {d}")
    if problems:
        for p in problems:
            _log(f"WARNING: {p}")
    else:
        _log("verified: every requested change read back OK")
    return {"changed": changes, "backup": backup_path, "verified": not problems,
            "problems": problems, "diff": diff_lines,
            "url": after.get("settings", {}).get("Url")}


def publish_current(sess, dry_run=False):
    """Publish the CURRENTLY stored site (read -> PublishLandingSite)."""
    state = read_state(sess)
    meta = state.get("settings", {}).get("MetaTags") or {}
    if dry_run:
        return {"dry_run": True, "blocks": len(state.get("blocks") or [])}
    return publish_site(sess, meta, state.get("blocks") or [])
