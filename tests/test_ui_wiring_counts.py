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
from hades_booru.ui.layout import create_gradio_app

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
