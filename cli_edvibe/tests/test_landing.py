"""Unit tests: landing site patch/merge/payload/verification. No network."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli_edvibe.core import landing  # noqa: E402
from cli_edvibe.core.client import EdvibeError  # noqa: E402


def _block(t, order, enabled, data):
    return {"Type": t, "OrderIndex": order, "IsEnabled": enabled,
            "DataJson": json.dumps(data, ensure_ascii=False)}


def _state():
    return {
        "settings": {"Url": "abc123", "IsPublishing": True, "IsLocked": False,
                     "TeacherId": 115251,
                     "MetaTags": {"Title": "edvibe.com", "Description": "old",
                                  "ImageUrl": "http://old/img.png"}},
        "blocks": [
            _block(0, 0, True, {"Img": {"Url": "x"}, "Name": "Name",
                                "ButtonText": "b"}),
            _block(6, 8, False, {"Title": "📖 Примеры уроков", "TextButton": "",
                                 "Lessons": [{"Value": {"Title": "old"}}],
                                 "IsShow": False}),
            _block(12, 9, False, {"Title": "FAQ", "Faqs": [], "IsShow": False}),
        ],
    }


# ------------------------------------------------------------------ resolve
def test_resolve_block_type():
    assert landing.resolve_block_type("faq") == 12
    assert landing.resolve_block_type("FAQ") == 12
    assert landing.resolve_block_type("прайс") == 5
    assert landing.resolve_block_type("examples") == 6
    assert landing.resolve_block_type(6) == 6
    with pytest.raises(EdvibeError):
        landing.resolve_block_type("nope")
    with pytest.raises(EdvibeError):
        landing.resolve_block_type(99)


# ------------------------------------------------------------------ patch
def test_toggle_mirrors_isshow():
    st = _state()
    _, blocks, changes = landing.apply_patch(
        st, {"blocks": [{"type": "faq", "enabled": True}]})
    faq = [b for b in blocks if b["Type"] == 12][0]
    data = json.loads(faq["DataJson"])
    assert faq["IsEnabled"] is True
    assert data["IsShow"] is True
    assert any("faq" in c for c in changes)


def test_explicit_show_overrides_mirror():
    st = _state()
    _, blocks, _ = landing.apply_patch(
        st, {"blocks": [{"type": "faq", "enabled": True, "show": False}]})
    data = json.loads([b for b in blocks if b["Type"] == 12][0]["DataJson"])
    assert data["IsShow"] is False


def test_block_without_isshow_not_polluted():
    st = _state()
    _, blocks, _ = landing.apply_patch(
        st, {"blocks": [{"type": "top", "set": {"Name": "X"}}]})
    data = json.loads([b for b in blocks if b["Type"] == 0][0]["DataJson"])
    assert data["Name"] == "X"
    assert "IsShow" not in data


def test_absent_block_rejected():
    st = _state()
    with pytest.raises(EdvibeError):
        landing.apply_patch(st, {"blocks": [{"type": "video", "enabled": True}]})


def test_meta_patch_and_replacement_of_list():
    st = _state()
    new_lessons = [{"Value": {"Title": "new", "Img": "u", "LessonId": "G"}}]
    meta, blocks, changes = landing.apply_patch(st, {
        "meta": {"Title": "new title"},
        "blocks": [{"type": "examples", "enabled": True,
                    "set": {"Lessons": new_lessons}}]})
    assert meta["Title"] == "new title"
    ex = [b for b in blocks if b["Type"] == 6][0]
    data = json.loads(ex["DataJson"])
    assert data["Lessons"] == new_lessons and data["IsShow"] is True
    # untouched blocks keep their EXACT DataJson string (byte-preserved)
    assert blocks[0]["DataJson"] == st["blocks"][0]["DataJson"]


def test_noop_patch_reports_no_changes():
    st = _state()
    _, _, changes = landing.apply_patch(
        st, {"blocks": [{"type": "faq", "enabled": False, "show": False}]})
    assert changes == []


def test_original_state_not_mutated():
    st = _state()
    landing.apply_patch(st, {"blocks": [{"type": "faq", "enabled": True}],
                             "meta": {"Title": "z"}})
    assert st["blocks"][2]["IsEnabled"] is False
    assert st["settings"]["MetaTags"]["Title"] == "edvibe.com"


# ------------------------------------------------------------------ payload
def test_payload_shape():
    st = _state()
    meta, blocks, _ = landing.apply_patch(st, {"meta": {"Title": "t2"}})
    payload = landing.build_payload(meta, blocks)
    assert set(payload) == {"MetaTags", "Blocks"}
    assert set(payload["MetaTags"]) == {"Title", "Description", "ImageUrl"}
    b0 = payload["Blocks"][0]
    assert set(b0) == {"Type", "OrderIndex", "IsEnabled", "BlockJson"}
    assert isinstance(b0["BlockJson"], str)  # DataJson travels as the raw string
    assert b0["BlockJson"] == st["blocks"][0]["DataJson"]


def test_payload_carries_policy_fields_when_present():
    st = _state()
    st["blocks"][0]["PrivacyPolicy"] = None
    st["blocks"][0]["PersonalDataPolicy"] = {"Text": "x"}
    meta, blocks, _ = landing.apply_patch(st, {"meta": {"Title": "t"}})
    payload = landing.build_payload(meta, blocks)
    assert payload["Blocks"][0]["PersonalDataPolicy"] == {"Text": "x"}


# ------------------------------------------------------------------ verify
def test_verify_applied_ok():
    st = _state()
    patch = {"blocks": [{"type": "faq", "enabled": True}]}
    meta, blocks, _ = landing.apply_patch(st, patch)
    after = {"settings": st["settings"], "blocks": blocks}
    assert landing.verify_applied(st, after, patch) == []


def test_verify_applied_catches_missing_change():
    st = _state()
    patch = {"blocks": [{"type": "faq", "enabled": True}]}
    bad_after = {"settings": st["settings"], "blocks": st["blocks"]}
    problems = landing.verify_applied(st, bad_after, patch)
    assert problems and "faq" in problems[0]


def test_diff_blocks_reports_enabled_and_fields():
    st = _state()
    meta, blocks, _ = landing.apply_patch(
        st, {"blocks": [{"type": "faq", "enabled": True}]})
    lines = landing.diff_blocks(st["blocks"], blocks)
    assert any("faq: enabled" in l for l in lines)
    assert any("IsShow" in l for l in lines)


def test_backup_roundtrip(tmp_path):
    st = _state()
    path = landing.backup(st, out_dir=str(tmp_path), label="test")
    assert os.path.exists(path)
    loaded = json.load(open(path, encoding="utf-8"))
    assert loaded["blocks"] == st["blocks"]
    assert loaded["settings"]["Url"] == "abc123"


def test_state_view_shape():
    st = _state()
    view = landing.state_view(st)
    assert view["url"] == "https://edvibe.com/teachers/abc123"
    assert [b["name"] for b in view["blocks"]] == ["top", "examples", "faq"]
    assert view["blocks"][2]["show"] is False


# ------------------------------------------------------------------ policies
def _state_app():
    st = _state()
    st["blocks"].append(_block(10, 10, True, {
        "Title": "Заявка на пробный урок", "TextButton": "Отправить",
        "PlaceholderName": "Ваше имя", "PlaceholderEmail": "Ваш e-mail",
        "PlaceholderPhone": "Телефон"}))
    st["blocks"][-1]["PrivacyPolicy"] = ""
    st["blocks"][-1]["PersonalDataPolicy"] = ""
    return st


def test_set_policies_via_patch():
    st = _state_app()
    ua, pd = "<p>AGREEMENT</p>", "<p>POLICY</p>"
    _, blocks, changes = landing.apply_patch(st, {"blocks": [{
        "type": "application", "user_agreement": ua,
        "personal_data_policy": pd}]})
    app = [b for b in blocks if b["Type"] == 10][0]
    assert app["PrivacyPolicy"] == ua
    assert app["PersonalDataPolicy"] == pd
    assert any("PrivacyPolicy" in c for c in changes)
    assert any("PersonalDataPolicy" in c for c in changes)
    # the source state is not mutated
    assert st["blocks"][-1]["PrivacyPolicy"] == ""
    assert st["blocks"][-1]["PersonalDataPolicy"] == ""


def test_policy_value_must_be_string():
    st = _state_app()
    with pytest.raises(EdvibeError):
        landing.apply_patch(st, {"blocks": [{
            "type": "application", "user_agreement": {"file": "x.html"}}]})


def test_policy_is_noop_when_unchanged():
    st = _state_app()
    st["blocks"][-1]["PrivacyPolicy"] = "<p>same</p>"
    _, _, changes = landing.apply_patch(st, {"blocks": [{
        "type": "application", "user_agreement": "<p>same</p>"}]})
    assert changes == []


def test_policies_travel_in_payload_and_verify():
    st = _state_app()
    patch = {"blocks": [{"type": "application",
                         "user_agreement": "<p>A</p>",
                         "personal_data_policy": "<p>B</p>"}]}
    meta, blocks, _ = landing.apply_patch(st, patch)
    payload = landing.build_payload(meta, blocks)
    app = [b for b in payload["Blocks"] if b["Type"] == 10][0]
    assert app["PrivacyPolicy"] == "<p>A</p>"
    assert app["PersonalDataPolicy"] == "<p>B</p>"
    after = {"settings": st["settings"], "blocks": blocks}
    assert landing.verify_applied(st, after, patch) == []
    # server dropped the policies -> caught by the read-back gate
    dropped = [dict(b) for b in blocks]
    for b in dropped:
        if b["Type"] == 10:
            b["PrivacyPolicy"] = ""
            b["PersonalDataPolicy"] = ""
    problems = landing.verify_applied(
        st, {"settings": st["settings"], "blocks": dropped}, patch)
    assert problems and "PrivacyPolicy" in problems[0]


def test_diff_blocks_reports_policy_change():
    st = _state_app()
    _, blocks, _ = landing.apply_patch(st, {"blocks": [{
        "type": "application", "user_agreement": "<p>hello</p>"}]})
    lines = landing.diff_blocks(st["blocks"], blocks)
    assert any("PrivacyPolicy" in l and "chars" in l for l in lines)


def test_state_view_reports_policy_lengths():
    st = _state_app()
    st["blocks"][-1]["PrivacyPolicy"] = "<p>12345</p>"
    view = landing.state_view(st)
    app = [b for b in view["blocks"] if b["type"] == 10][0]
    assert app["policies"]["PrivacyPolicy"] == 12
    assert app["policies"]["PersonalDataPolicy"] == 0


def test_resolve_policy_files(tmp_path):
    f = tmp_path / "ua.html"
    f.write_text("<p>from file</p>", encoding="utf-8")
    patch = {"blocks": [{"type": "application",
                         "user_agreement": {"file": str(f)}}]}
    out = landing.resolve_policy_files(patch)
    assert out["blocks"][0]["user_agreement"] == "<p>from file</p>"
    # the input patch is not mutated
    assert patch["blocks"][0]["user_agreement"] == {"file": str(f)}
    with pytest.raises(EdvibeError):
        landing.resolve_policy_files({"blocks": [{
            "type": "application",
            "user_agreement": {"file": str(tmp_path / "missing.html")}}]})


def test_resolve_policy_files_relative_to_base_dir(tmp_path):
    (tmp_path / "doc.html").write_text("<p>rel</p>", encoding="utf-8")
    out = landing.resolve_policy_files(
        {"blocks": [{"type": "application",
                     "personal_data_policy": {"file": "doc.html"}}]},
        base_dir=str(tmp_path))
    assert out["blocks"][0]["personal_data_policy"] == "<p>rel</p>"
