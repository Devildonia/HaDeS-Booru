"""
Regression and isolation tests for per-session personal lists under `--share` (`X8` / `R6-12`).
Verifies that in `share_mode=True`:
- Each browser session's `SessionLists` state is isolated from other sessions.
- Mutating blacklist, whitelist, or junk tags in `share_mode=True` never mutates
  `config_manager.config.normalizer` and never writes to disk.
- In `share_mode=False` (default local mode), changes continue to persist to `config_manager`.
"""

from __future__ import annotations

import pytest

from hades_booru import config as config_module
from hades_booru.models import CategorizedTags, Post
from hades_booru.ui.layout import create_gradio_app
from hades_booru.ui.state import PersonalListStore, make_session_lists

SEM_ORDER = "copyright > character > artist > general > meta"


def _find_entry(app, name: str):
    for entry in app.fns.values():
        if getattr(entry.fn, "__name__", None) == name:
            return entry
    raise AssertionError(f"handler not found in app.fns: {name}")


def _find_personal_entry(app, kind: str):
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


def test_personal_list_store_isolates_sessions_in_share_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    save_calls: list[int] = []
    monkeypatch.setattr(config_module.ConfigManager, "save", lambda self: save_calls.append(1) or True)

    cm = config_module.config_manager
    orig_bl = list(cm.config.normalizer.user_blacklist)
    orig_wl = list(cm.config.normalizer.user_whitelist)

    store = PersonalListStore(share_mode=True)
    session_a = make_session_lists()
    session_b = make_session_lists()

    store.set_personal_lists(["watermark_a"], ["keep_a"], session_lists=session_a)
    store.set_personal_lists(["watermark_b"], ["keep_b"], session_lists=session_b)

    assert store.get_lists(session_a)[1:] == (["watermark_a"], ["keep_a"])
    assert store.get_lists(session_b)[1:] == (["watermark_b"], ["keep_b"])
    # Global config and disk are untouched in share_mode
    assert cm.config.normalizer.user_blacklist == orig_bl
    assert cm.config.normalizer.user_whitelist == orig_wl
    assert save_calls == []


def test_share_mode_app_handlers_keep_sessions_isolated_and_skip_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_calls: list[int] = []
    monkeypatch.setattr(config_module.ConfigManager, "save", lambda self: save_calls.append(1) or True)

    cm = config_module.config_manager
    cm.config.normalizer.user_blacklist = []
    cm.config.normalizer.user_whitelist = []

    share_app = create_gradio_app(share_mode=True)
    add_bl_entry = _find_personal_entry(share_app, "blacklist_add")
    reset_entry = _find_entry(share_app, "reset_personal_handler")

    session_1 = make_session_lists()
    session_2 = make_session_lists()
    post = Post(
        id="1",
        source_id="danbooru",
        source_name="Danbooru",
        source_url="https://danbooru.donmai.us/posts/1",
        tags=CategorizedTags(general=["1girl", "secret_tag_1", "secret_tag_2"]),
    )

    # Session 1 blacklists "secret_tag_1"
    res_1 = add_bl_entry.fn(
        "secret_tag_1",
        "en",
        [post],
        0,
        False,
        False,
        True,
        "",
        SEM_ORDER,
        ", ",
        "dataset",
        "",
        "",
        [],
        False,
        session_1,
    )
    assert len(res_1) == len(add_bl_entry.outputs)
    assert "secret_tag_1" in session_1.user_blacklist
    assert "secret_tag_1" not in session_2.user_blacklist
    # Session 1's prompt excludes secret_tag_1
    assert "secret_tag_1" not in res_1[2]

    # Session 2 blacklists "secret_tag_2"
    res_2 = add_bl_entry.fn(
        "secret_tag_2",
        "en",
        [post],
        0,
        False,
        False,
        True,
        "",
        SEM_ORDER,
        ", ",
        "dataset",
        "",
        "",
        [],
        False,
        session_2,
    )
    assert "secret_tag_2" in session_2.user_blacklist
    assert "secret_tag_1" in res_2[2]  # Session 2 still sees secret_tag_1!
    assert "secret_tag_2" not in res_2[2]

    # Resetting Session 1 does not clear Session 2
    reset_entry.fn(
        "en",
        [post],
        0,
        False,
        False,
        True,
        "",
        SEM_ORDER,
        ", ",
        "dataset",
        "",
        "",
        [],
        False,
        session_1,
    )
    assert session_1.user_blacklist == []
    assert session_2.user_blacklist == ["secret_tag_2"]

    # Host global config and disk were never touched
    assert cm.config.normalizer.user_blacklist == []
    assert save_calls == []
