"""
Audit R7 (v1.1.0): share-mode host isolation and cross-instance credential safety.

Covers the CRITICAL R7-03 findings (a public `--share` visitor must never wipe,
overwrite, or reach the host's credential store, native folder dialogs, or
arbitrary host paths) and the ALTO R7-01 finding (a second local instance saving
an unrelated setting must not wipe the first instance's persisted credentials).

Also covers the untested handler paths that left handlers.py / desktop.py under
the coverage gate before this round.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hades_booru import ui as ui_module  # noqa: F401  (package import for patching)
from hades_booru.config import MAX_SEARCH_HISTORY, ConfigManager
from hades_booru.models import CategorizedTags, Post
from hades_booru.ui import handlers as handlers_module
from hades_booru.ui.state import PersonalListStore

SEM_ORDER = "copyright > character > artist > general > meta"


def _stub_dispatch(*args, **kwargs):
    return ([], "", "", "", "")


def _make_post() -> Post:
    return Post(
        id="1",
        source_id="danbooru",
        source_name="Danbooru",
        source_url="https://danbooru.donmai.us/posts/1",
        tags=CategorizedTags(general=["1girl", "solo"]),
    )


def _host_with_credentials(cfg_file: Path) -> dict:
    host = ConfigManager(config_path=cfg_file)
    host.set_credentials_many({"danbooru": ("host_user", "host_key")}, persist_to_disk=True)
    return json.loads(cfg_file.read_text(encoding="utf-8"))


@pytest.fixture
def share_handlers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Fresh handlers bound to a share-mode store over an isolated config file."""
    cfg_file = tmp_path / "config.local.json"
    _host_with_credentials(cfg_file)
    monkeypatch.setattr(handlers_module, "config_manager", ConfigManager(config_path=cfg_file))
    store = PersonalListStore(share_mode=True)
    return handlers_module.create_ui_handlers(store, _stub_dispatch)


def test_share_mode_save_credentials_never_touches_host_disk(share_handlers: dict) -> None:
    """R7-03: a visitor's 'Save' must not write or wipe the host's credentials."""
    res = share_handlers["save_credentials_handler"](
        "en",
        True,
        "evil_user",
        "evil_key",
        "evil_user",
        "evil_key",
        "evil_user",
        "evil_key",
        "evil_user",
        "evil_key",
    )
    assert len(res) == 9
    assert "share" in res[0].lower()
    # The shared in-memory store keeps the host's own credentials, untouched.
    assert handlers_module.config_manager.get_credentials("danbooru").api_key == "host_key"
    assert handlers_module.config_manager.get_credentials("danbooru").user_id == "host_user"
    # No cross-session contamination: e621 (never saved by the host) stays empty.
    assert handlers_module.config_manager.get_credentials("e621").api_key == ""


def test_share_mode_clear_credentials_never_wipes_host_disk(share_handlers: dict) -> None:
    """R7-03: a visitor's 'Clear' must not wipe the host's persisted credentials."""
    res = share_handlers["clear_credentials_handler"]("en")
    assert len(res) == 9
    assert "share" in res[0].lower()
    assert handlers_module.config_manager.get_credentials("danbooru").api_key == "host_key"


def test_share_mode_folder_export_refuses_host_write(share_handlers: dict, tmp_path: Path) -> None:
    """R7-03: folder export from a share session must not create host directories."""
    target = tmp_path / "visitor_chosen_dir"
    msg = share_handlers["save_dataset_to_folder_handler"](
        [_make_post()],
        str(target),
        True,
        False,
        "en",
        False,
        False,
        True,
        "",
        SEM_ORDER,
        ", ",
        "dataset",
        [],
        None,
    )
    assert "share" in msg.lower()
    assert not target.exists()


def test_local_mode_save_credentials_still_works(tmp_path: Path) -> None:
    """Guard regression: in local mode the save path is unchanged (N5/M5 contracts)."""
    cfg_file = tmp_path / "config.local.json"
    mgr = ConfigManager(config_path=cfg_file)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(handlers_module, "config_manager", mgr)
    try:
        store = PersonalListStore(share_mode=False)
        handlers = handlers_module.create_ui_handlers(store, _stub_dispatch)
        res = handlers["save_credentials_handler"](
            "en",
            True,
            "alice",
            "k1",
            "",
            "",
            "",
            "",
            "",
            "",
        )
        assert len(res) == 9
        assert mgr.get_credentials("danbooru").api_key == "k1"
        disk = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert disk["credentials"]["danbooru"]["api_key"] == "k1"

        res = handlers["clear_credentials_handler"]("en")
        assert len(res) == 9
        disk = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert disk["credentials"]["danbooru"]["api_key"] == ""
    finally:
        monkey.undo()


def test_second_instance_save_does_not_wipe_first_credentials(tmp_path: Path) -> None:
    """R7-01: an instance that loaded before credentials appeared must keep them."""
    cfg_file = tmp_path / "config.local.json"
    instance_b = ConfigManager(config_path=cfg_file)  # loads first: empty disk
    instance_a = ConfigManager(config_path=cfg_file)
    instance_a.set_credentials_many({"danbooru": ("a_user", "a_key")}, persist_to_disk=True)

    # B now saves an unrelated setting (language) — must not wipe A's credentials.
    instance_b.config.language = "es"
    assert instance_b.save()

    disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk["credentials"]["danbooru"]["api_key"] == "a_key"
    assert disk["credentials"]["danbooru"]["user_id"] == "a_user"
    assert disk["language"] == "es"


def test_clear_credentials_wipes_when_process_had_them(tmp_path: Path) -> None:
    """N5 contract: a process that loaded the credentials still wipes them on clear."""
    cfg_file = tmp_path / "config.local.json"
    instance_a = ConfigManager(config_path=cfg_file)
    instance_a.set_credentials_many({"danbooru": ("u", "k")}, persist_to_disk=True)

    instance_b = ConfigManager(config_path=cfg_file)  # loads the values
    instance_b.clear_credentials()

    disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk["credentials"]["danbooru"]["api_key"] == ""
    assert instance_b.get_credentials("danbooru").api_key == ""


def test_session_only_save_preserves_disk_credentials(tmp_path: Path) -> None:
    """R7-01: persist=False must preserve (not wipe) credentials on disk."""
    cfg_file = tmp_path / "config.local.json"
    instance_a = ConfigManager(config_path=cfg_file)
    instance_a.set_credentials_many({"danbooru": ("a_user", "a_key")}, persist_to_disk=True)

    instance_b = ConfigManager(config_path=cfg_file)
    instance_b.config.persist_credentials = False
    instance_b.save()

    disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk["credentials"]["danbooru"]["api_key"] == "a_key"


def test_history_union_is_capped(tmp_path: Path) -> None:
    """Audit R7 (new): the union of two instances' histories cannot exceed the cap."""
    cfg_file = tmp_path / "config.local.json"
    instance_a = ConfigManager(config_path=cfg_file)
    instance_a.config.search_history = [f"a_{i}" for i in range(MAX_SEARCH_HISTORY)]
    instance_a.save()

    instance_b = ConfigManager(config_path=cfg_file)
    # Most-recent-first, as record_search_history() produces.
    instance_b.config.search_history = [f"b_{i}" for i in reversed(range(MAX_SEARCH_HISTORY))]
    instance_b.save()

    disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert len(disk["search_history"]) <= MAX_SEARCH_HISTORY
    # This process's (B's) entries come first, most-recent first.
    assert disk["search_history"][0] == f"b_{MAX_SEARCH_HISTORY - 1}"


def test_unknown_source_added_by_other_instance_is_kept(tmp_path: Path) -> None:
    """R7-01 edge: a source unknown to this process (added after load) survives saves."""
    cfg_file = tmp_path / "config.local.json"
    instance_b = ConfigManager(config_path=cfg_file)
    instance_b.save()  # materialize the file

    # Simulate another process writing an extra source directly to disk.
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    data["credentials"]["mystery_board"] = {"user_id": "x", "api_key": "y"}
    cfg_file.write_text(json.dumps(data), encoding="utf-8")

    instance_b.config.language = "es"
    instance_b.save()

    disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk["credentials"]["mystery_board"]["api_key"] == "y"
