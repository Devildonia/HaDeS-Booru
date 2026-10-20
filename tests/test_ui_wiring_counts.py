"""Runtime regression tests: handler return arity vs wired Gradio outputs (v1.0.3).

Gradio only detects output-count mismatches at event time:
- fewer values than outputs  -> ValueError raised in the browser (error UI never renders)
- more values than outputs  -> warning logged, extra values dropped, and every value
  after the first surplus lands on the WRONG component (silent label/content swap)

These tests build the real app, invoke the real (closure) handlers with mock inputs,
and assert that every return path produces exactly as many values as the wired
`outputs` list, and that the personal/extract sections are aligned component-by-component.
"""

from __future__ import annotations

import json
import pathlib

import gradio as gr
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from hades_booru import config as config_module
from hades_booru.models import CategorizedTags, Post
from hades_booru.ui.layout import (
    MAX_SEARCH_HISTORY,
    add_top_tag_to_query,
    compute_top_tags,
    create_gradio_app,
    record_search_history,
)

SEM_ORDER = "general > character > copyright > artist > meta"


@pytest.fixture(scope="module")
def app():
    # Building does not launch a server; handlers stay accessible via app.fns.
    return create_gradio_app()


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    """Handlers may persist config; tests must never write to the user's disk config,
    and must leave the in-memory singleton exactly as they found it."""
    monkeypatch.setattr(config_module.ConfigManager, "save", lambda self: True)
    cm = config_module.config_manager
    snapshot = cm.config.model_dump(mode="json")
    yield
    cm.config = cm.config.__class__.model_validate(snapshot)


def _find_entry(app, name: str):
    for entry in app.fns.values():
        if getattr(entry.fn, "__name__", None) == name:
            return entry
    raise AssertionError(f"handler not found in app.fns: {name}")


def _find_personal_entry(app, kind: str):
    """Finds the BlockFunction wired with `lambda text, *args: personal_list_handler(kind, ...)`.

    The kind string is baked into each lambda, so the wrapper's first positional
    argument is the tag text and the kind must NOT be passed again.
    """
    for entry in app.fns.values():
        fn = entry.fn
        if getattr(fn, "__name__", "") != "<lambda>":
            continue
        if kind not in getattr(fn.__code__, "co_consts", ()): 
            continue
        for cell in getattr(fn, "__closure__", None) or []:
            if getattr(cell.cell_contents, "__name__", None) == "personal_list_handler":
                return entry
    raise AssertionError(f"lambda for personal_list_handler({kind!r}) not found in app.fns")


def _make_png(path: pathlib.Path, **texts: str) -> pathlib.Path:
    img = Image.new("RGB", (8, 8), "white")
    info = PngInfo()
    for key, value in texts.items():
        info.add_text(key, value)
    img.save(path, pnginfo=info)
    return path


# ---------------------------------------------------------------- on_language_change


def test_on_language_change_return_matches_wired_outputs(app):
    entry = _find_entry(app, "on_language_change")
    result = entry.fn(
        "en",  # new_lang
        [],  # posts
        0,  # sel_idx
        "all",  # cur_rating
        "high",  # cur_quality
        "dataset",  # cur_exp_mode
        [],  # cur_excl_cats
        False,  # replace_u
        False,  # escape_p
        False,  # filter_j
        "",  # junk_str
        SEM_ORDER,  # sem_order
        ", ",  # sep
        "",  # trig_word
        "",  # prefix_str
        False,  # inc_header
    )
    assert isinstance(result, tuple)
    # 1) Arity: a mismatch breaks the whole language switch at runtime.
    assert len(result) == len(entry.outputs)
    # 2) Personal section alignment: chips box, then Blacklist header, then Whitelist header.
    chips, bl_hdr, wl_hdr = result[56], result[57], result[58]
    assert "hades-chip-row" in chips
    assert "Blacklist" in bl_hdr
    assert "Whitelist" in wl_hdr
    assert type(entry.outputs[56]).__name__ == "HTML"
    assert type(entry.outputs[57]).__name__ == "HTML"
    assert type(entry.outputs[58]).__name__ == "HTML"
    # 3) Extract section alignment: button label, status pill, three box labels, cleared tags.
    assert type(entry.outputs[73]).__name__ == "Button"
    assert result[73] == {"__type__": "update", "value": "Extract Metadata"}
    assert "hades-status-box" in result[74]  # ready pill lands on the HTML status box
    assert result[75] == ""  # info markdown cleared
    assert result[76]["label"] == "Positive Prompt"
    assert result[77]["label"] == "Negative Prompt"
    assert result[78]["label"] == "Generation Settings"
    assert result[79] == ""  # tags html cleared


# ---------------------------------------------------------------- extract_handler


def _extract_args(file_val, trig: str = ""):
    return (file_val, "en", trig, False, False, False, "", SEM_ORDER, ", ")


def test_extract_handler_no_file_skips_update(app):
    entry = _find_entry(app, "extract_handler")
    result = entry.fn(*_extract_args(None))
    assert result == gr.skip()


def test_extract_handler_error_path_keeps_full_arity(app, tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"this is definitely not a PNG")
    entry = _find_entry(app, "extract_handler")
    result = entry.fn(*_extract_args(str(bad)))
    # Pre-v1.0.3-fix this path returned 4 values for 6 outputs -> ValueError in the browser.
    assert len(result) == len(entry.outputs)
    assert "Could not extract metadata" in result[0]
    assert result[1:] == ("", "", "", "", "")


def test_extract_handler_clean_image_warns_not_crashes(app, tmp_path):
    clean = _make_png(tmp_path / "clean.png")
    entry = _find_entry(app, "extract_handler")
    result = entry.fn(*_extract_args(str(clean)))
    assert len(result) == len(entry.outputs)
    assert "No embedded prompt metadata" in result[0]


def test_extract_handler_sd_blob_renders_three_sections(app, tmp_path):
    blob = (
        "masterpiece, 1girl, solo, hatsune miku, "
        "Negative prompt: bad hands, lowres, "
        "Steps: 20, Sampler: Euler a, Seed: 42"
    )
    sd_png = _make_png(tmp_path / "sd.png", parameters=blob)
    entry = _find_entry(app, "extract_handler")
    status, _info, positive, negative, settings, tags_html = entry.fn(
        *_extract_args(str(sd_png), trig="trigword")
    )
    assert len(entry.outputs) == 6
    assert "Extracted" in status
    assert positive == "trigword, masterpiece, 1girl, solo, hatsune miku"
    assert negative == "bad hands, lowres"
    assert settings == "Steps: 20\nSampler: Euler a\nSeed: 42"
    assert "hatsune miku" in tags_html


def test_extract_handler_comfyui_graph_split(app, tmp_path):
    graph = {
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl, solo"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad hands, lowres"}},
    }
    comfy_png = _make_png(tmp_path / "comfy.png", prompt=json.dumps(graph))
    entry = _find_entry(app, "extract_handler")
    _status, _info, positive, negative, settings, _tags = entry.fn(*_extract_args(str(comfy_png)))
    assert positive == "1girl, solo"
    assert negative == "bad hands, lowres"
    assert settings == ""


# ---------------------------------------------------------------- personal list handlers


def _personal_args(tag_text: str):
    """Arguments for the personal-list lambda wrapper: tag text + personal_common_inputs."""
    return (
        tag_text,
        "en",  # cur_lang
        [],  # posts
        0,  # sel_idx
        False,  # replace_u
        False,  # escape_p
        False,  # filter_j
        "",  # junk_str
        SEM_ORDER,  # sem_order
        ", ",  # sep
        "dataset",  # exp_mode
        "",  # trig_word
        "",  # prefix_str
        [],  # excl_cats
        False,  # inc_header
    )


def test_personal_list_empty_input_keeps_full_arity(app):
    entry = _find_personal_entry(app, "blacklist_add")
    result = entry.fn(*_personal_args(""))
    # Pre-v1.0.3-fix this path returned 2 values for 7 outputs -> ValueError in the browser.
    assert len(result) == len(entry.outputs)
    chips, status, *views = result
    assert "hades-chip-row" in chips
    assert "Not found in the list" in status
    # No-op views: current gallery/inspector/export must remain untouched.
    assert views == [gr.skip()] * 5


def test_personal_list_add_blacklist_persists_in_memory(app):
    entry = _find_personal_entry(app, "blacklist_add")
    result = entry.fn(*_personal_args("commission"))
    assert len(result) == len(entry.outputs)
    blacklist = config_module.config_manager.config.normalizer.user_blacklist
    assert any(tag.lower() == "commission" for tag in blacklist)


def test_personal_list_whitelist_add_persists_in_memory(app):
    entry = _find_personal_entry(app, "whitelist_add")
    result = entry.fn(*_personal_args("yandere"))
    assert len(result) == len(entry.outputs)
    whitelist = config_module.config_manager.config.normalizer.user_whitelist
    assert any(tag.lower() == "yandere" for tag in whitelist)


def test_blacklist_post_handler_no_posts_full_arity(app):
    entry = _find_entry(app, "blacklist_post_handler")
    args = ("en", [], 0, False, False, False, "", SEM_ORDER, ", ", "dataset", "", "", [], False)
    result = entry.fn(*args)
    assert len(result) == len(entry.outputs)
    assert "no filtered tags" in result[1].lower()


def test_reset_personal_handler_full_arity(app):
    entry = _find_entry(app, "reset_personal_handler")
    args = ("en", [], 0, False, False, False, "", SEM_ORDER, ", ", "dataset", "", "", [], False)
    result = entry.fn(*args)
    assert len(result) == len(entry.outputs)


# ---------------------------------------------------------------- navigate_post_handler


def _make_nav_post(post_id: str) -> Post:
    return Post(
        id=post_id,
        source_id="danbooru",
        source_name="Danbooru",
        source_url=f"https://danbooru.donmai.us/posts/{post_id}",
        tags=CategorizedTags(general=["blue_eyes", "twintails"], character=["hatsune_miku"]),
    )


def _find_navigate_entry(app, direction: int):
    """Finds the prev/next lambda wrapper whose closure is `navigate_post_handler`.

    The direction int (-1 / 1) is baked into each lambda's co_consts.
    """
    for entry in app.fns.values():
        fn = entry.fn
        if getattr(fn, "__name__", "") != "<lambda>":
            continue
        if direction not in getattr(fn.__code__, "co_consts", ()): 
            continue
        for cell in getattr(fn, "__closure__", None) or []:
            if getattr(cell.cell_contents, "__name__", None) == "navigate_post_handler":
                return entry
    raise AssertionError(f"lambda for navigate_post_handler(direction={direction}) not found in app.fns")


def _navigate_args(posts: list, idx: int):
    return (posts, idx, "en", False, False, False, "", SEM_ORDER, ", ", "", [])


def test_navigate_empty_posts_keeps_full_arity_and_gallery_output(app):
    entry = _find_navigate_entry(app, -1)
    result = entry.fn(*_navigate_args([], 0))
    # Pre-v1.0.5-fix this returned 4 values for 4 outputs that excluded the gallery:
    # the prompt changed but the selected image stayed frozen.
    assert len(result) == len(entry.outputs)
    assert type(entry.outputs[-1]).__name__ == "Gallery"
    assert result[-1] == {"__type__": "update", "selected_index": 0}


@pytest.mark.parametrize("direction, start_idx, expected_idx", [(-1, 1, 0), (1, 0, 1), (1, 1, 0), (-1, 0, 1)])
def test_navigate_moves_gallery_selection(app, direction, start_idx, expected_idx):
    entry = _find_navigate_entry(app, direction)
    posts = [_make_nav_post("1"), _make_nav_post("2")]
    result = entry.fn(*_navigate_args(posts, start_idx))
    assert len(result) == len(entry.outputs)
    assert type(entry.outputs[-1]).__name__ == "Gallery"
    next_idx, _prompt, _badge, _inspector, gallery_update = result
    assert next_idx == expected_idx
    assert gallery_update == {"__type__": "update", "selected_index": expected_idx}


def test_navigate_prompt_follows_selected_post(app):
    entry = _find_navigate_entry(app, 1)
    posts = [_make_nav_post("1"), _make_nav_post("2")]
    _next_idx, prompt, *_rest = entry.fn(*_navigate_args(posts, 0))
    # Default config keeps underscores (replace_underscores=False); ordering: general > character.
    assert "hatsune_miku" in prompt
    assert "blue_eyes, twintails" in prompt


# ---------------------------------------------------------------- v1.0.6: search history

def test_record_search_history_dedup_and_most_recent_first(app):
    cm = config_module.config_manager
    cm.config.search_history = []
    assert record_search_history("hatsune_miku 1girl") == ["hatsune_miku 1girl"]
    r = record_search_history("new_query")
    assert r[0] == "new_query" and "hatsune_miku 1girl" in r
    # Re-adding an existing query moves it to the front without duplicating.
    r = record_search_history("hatsune_miku 1girl")
    assert r[0] == "hatsune_miku 1girl"
    assert r.count("hatsune_miku 1girl") == 1


def test_record_search_history_respects_cap(app):
    cm = config_module.config_manager
    cm.config.search_history = []
    for i in range(MAX_SEARCH_HISTORY + 5):
        record_search_history(f"query_{i}")
    h = cm.config.search_history
    assert len(h) == MAX_SEARCH_HISTORY
    assert h[0] == f"query_{MAX_SEARCH_HISTORY + 4}"  # most recent survives, oldest dropped


def test_record_search_history_ignores_blank_and_persists(app):
    cm = config_module.config_manager
    cm.config.search_history = ["kept"]
    assert record_search_history("   ") == ["kept"]
    assert cm.config.search_history == ["kept"]
    assert record_search_history("fresh") == ["fresh", "kept"]


def test_execute_search_wires_recent_and_top_tags_outputs(app):
    entry = _find_entry(app, "execute_search_handler")
    # v1.0.6 added the recent-searches dropdown and the top-tags dropdown as the final
    # two wired outputs (both Dropdowns, in that order).
    assert len(entry.outputs) == 13
    assert type(entry.outputs[-2]).__name__ == "Dropdown"
    assert type(entry.outputs[-1]).__name__ == "Dropdown"


def test_recent_dropdown_populates_search_bar_and_clear_is_inert(app):
    """v1.0.6 (revised): selecting a recent search fills the Search-tags bar (no auto-run);
    Clear (dropdown -> None) maps to gr.skip() so it neither wipes the bar nor runs a search."""
    entry = _find_entry(app, "populate_query_from_recent")
    assert entry.fn("hatsune miku 1girl") == "hatsune miku 1girl"  # real selection -> text
    assert entry.fn(None) == gr.skip()  # Clear / empty -> no change, no search
    assert entry.fn("") == gr.skip()
    assert len(entry.inputs) == 1 and len(entry.outputs) == 1
    assert type(entry.inputs[0]).__name__ == "Dropdown"
    assert type(entry.outputs[0]).__name__ == "Textbox"


def test_clear_search_history_handler_resets_both_lists(app):
    entry = _find_entry(app, "clear_search_history_handler")
    config_module.config_manager.config.search_history = ["a b", "b c", "c d"]
    result = entry.fn()
    # Two updates: recent-searches dropdown + top-tags dropdown, both cleared.
    assert len(result) == 2
    assert result[0]["choices"] == []
    assert result[0]["value"] is None
    assert result[1]["choices"] == []
    # Audit v1.0.6: the top-tags picker must also reset its selection, never stale.
    assert result[1]["value"] is None
    assert config_module.config_manager.config.search_history == []


def test_recent_dropdown_is_selection_only(app):
    """Audit v1.0.6: the recent-searches dropdown is a strict picker over recorded
    history (no free-text typing); free text belongs in the Search-tags bar.
    The dropdown object is the input of populate_query_from_recent."""
    entry = _find_entry(app, "populate_query_from_recent")
    dropdown = entry.inputs[0]
    assert type(dropdown).__name__ == "Dropdown"
    assert dropdown.allow_custom_value is False


def test_compute_top_tags_ranks_by_frequency_then_recency(app):
    cm = config_module.config_manager
    cm.config.search_history = [
        "miku 1girl blue_eyes",
        "1girl solo",
        "1girl",
        "miku",
    ]
    tags = compute_top_tags(cm.config.search_history)
    assert tags[0] == "1girl"  # appears 3 times -> top
    assert "miku" in tags  # appears 2 times
    assert len(tags) <= 8


def test_compute_top_tags_empty_and_capped(app):
    assert compute_top_tags([]) == []
    assert compute_top_tags(None) == []
    cm = config_module.config_manager
    cm.config.search_history = [f"tag_{i} unique_{i}" for i in range(30)]
    # 30 queries x 2 unique tags = 60 distinct tags, capped to 8.
    assert len(compute_top_tags(cm.config.search_history)) == 8


def test_add_top_tag_appends_and_dedups(app):
    fn = add_top_tag_to_query
    q, _reset = fn("miku", "1girl")
    assert q == "miku, 1girl"
    q2, _ = fn("miku, 1girl", "1girl")  # dedup (case-insensitive)
    assert q2 == "miku, 1girl"
    q3, _ = fn("", "solo")
    assert q3 == "solo"
    q4, _ = fn("miku", None)  # empty selection -> query unchanged
    assert q4 == "miku"


def test_on_language_change_relabels_v106_components(app):
    entry = _find_entry(app, "on_language_change")
    result = entry.fn(
        "en", [], 0, "all", "high", "dataset", [],
        False, False, False, "", SEM_ORDER, ", ", "", "", False,
    )
    assert len(result) == len(entry.outputs)
    # Robust to ordering: assert every v1.0.6 control is relabeled on language switch.
    observed = set()
    for comp, upd in zip(entry.outputs, result, strict=True):
        if isinstance(upd, dict) and upd.get("__type__") == "update":
            for field in ("label", "value"):
                val = upd.get(field)
                if isinstance(val, str):
                    observed.add((type(comp).__name__, field, val))
    expected = {
        ("Dropdown", "label", "Recent searches"),
        ("Button", "value", "Clear"),
        ("Button", "value", "Clear Image"),
        ("Dropdown", "label", "Top tags"),
        ("Button", "value", "Add"),
    }
    missing = expected - observed
    assert not missing, f"v1.0.6 relabels missing on language switch: {missing}"


# ---------------------------------------------------------------- v1.0.6: drop-to-replace

def test_extract_handler_drop_to_replace_picks_latest(app, tmp_path):
    old = _make_png(tmp_path / "old.png")  # no metadata -> would warn if chosen
    new = _make_png(tmp_path / "new.png", parameters="masterpiece, 1girl, solo")
    entry = _find_entry(app, "extract_handler")
    # A list of [old, new] must analyze the LATEST file (drop-to-replace).
    status, _info, positive, _negative, _settings, _tags = entry.fn(
        *_extract_args([str(old), str(new)])
    )
    assert "Extracted" in status
    assert positive == "masterpiece, 1girl, solo"
