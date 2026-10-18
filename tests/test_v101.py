"""
v1.0.1 & Audit R3 feature/regression tests:
- Server-side rating metatags across adapter families (N6, N7)
- Zero credential leakage in Gradio /config JSON (N1)
- Cross-platform open_folder_in_explorer on Linux/macOS/Windows without Popen check= bug (N2)
- Thread-local adapter.last_warning isolation across concurrent searches (N3)
- Capped Retry-After delay (<= 30s) on HTTP 429 (N4)
- Clear credentials from memory and disk (N5)
- Pawoo multi-tag truncation warning (L13)
"""

from __future__ import annotations

import concurrent.futures
import inspect
import json
from pathlib import Path

import hades_booru.http_client as hc
from hades_booru.adapters.artplatforms import ArtPlatformsAdapter
from hades_booru.adapters.danbooru import DanbooruAdapter
from hades_booru.adapters.e621 import E621Adapter
from hades_booru.adapters.gelbooru import GelbooruAdapter
from hades_booru.adapters.moebooru import MoebooruAdapter
from hades_booru.adapters.philomena import PhilomenaAdapter
from hades_booru.adapters.zerochan import ZerochanAdapter
from hades_booru.config import ConfigManager
from hades_booru.http_client import MAX_RETRY_AFTER_SECONDS, _retry_after_seconds
from hades_booru.ui.layout import create_gradio_app, open_folder_in_explorer


def _stub_search(monkeypatch, captured: dict):
    """Stubs the shared http_client singleton (get_json + get_text) and captures params."""

    def fake_get_json(url, params=None, headers=None, auth=None, retries=2):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return []

    def fake_get_text(url, params=None, headers=None, auth=None, retries=2):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return ""

    monkeypatch.setattr(hc.http_client, "get_json", fake_get_json)
    monkeypatch.setattr(hc.http_client, "get_text", fake_get_text)


def test_all_adapters_expose_rating_parameter() -> None:
    """Contract: every adapter's search() must accept a `rating` keyword."""
    for cls in (
        DanbooruAdapter,
        MoebooruAdapter,
        E621Adapter,
        GelbooruAdapter,
        PhilomenaAdapter,
        ZerochanAdapter,
        ArtPlatformsAdapter,
    ):
        assert "rating" in inspect.signature(cls.search).parameters, cls.__name__


def test_danbooru_rating_becomes_server_tag_and_respects_2_tag_anon_limit(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}
    _stub_search(monkeypatch, captured)

    # Ensure anonymous state (no credentials)
    mgr = ConfigManager(config_path=tmp_path / "config.local.json")
    monkeypatch.setattr("hades_booru.adapters.danbooru.config_manager", mgr)

    # 1 user tag + rating -> safe to inject rating:safe (total 2 tags)
    DanbooruAdapter().search("hatsune_miku", limit=10, rating="g")
    assert captured["params"]["tags"] == "hatsune_miku rating:safe"

    # N6: 2 user tags + anonymous on danbooru -> must NOT inject 3rd tag to avoid HTTP 422
    captured.clear()
    DanbooruAdapter().search("hatsune_miku solo", limit=10, rating="g")
    assert captured["params"]["tags"] == "hatsune_miku solo"

    # With credentials configured, 2 user tags + rating is allowed
    mgr.set_credentials("danbooru", "user1", "key1", persist_to_disk=False)
    captured.clear()
    DanbooruAdapter().search("hatsune_miku solo", limit=10, rating="g")
    assert captured["params"]["tags"] == "hatsune_miku solo rating:safe"

    # "u" (unrated) has no Danbooru tag equivalent -> must not inject a rating tag.
    captured.clear()
    DanbooruAdapter().search("hatsune_miku", limit=10, rating="u")
    assert "rating:" not in captured["params"].get("tags", "")


def test_moebooru_rating_uses_server_tag(monkeypatch) -> None:
    captured: dict = {}
    _stub_search(monkeypatch, captured)

    MoebooruAdapter().search("re:zero", limit=10, rating="s")
    assert captured["params"]["tags"] == "re:zero rating:safe"

    captured.clear()
    MoebooruAdapter().search("re:zero", limit=10, rating="q")
    assert captured["params"]["tags"] == "re:zero rating:questionable"

    captured.clear()
    MoebooruAdapter().search("re:zero", limit=10)
    assert "rating:" not in captured["params"].get("tags", "")


def test_e621_rating_uses_server_tag(monkeypatch) -> None:
    captured: dict = {}
    _stub_search(monkeypatch, captured)

    E621Adapter().search("hatsune_miku", limit=10, rating="e")
    assert captured["params"]["tags"] == "hatsune_miku rating:e"

    captured.clear()
    E621Adapter().search("hatsune_miku", limit=10, rating="g")
    assert captured["params"]["tags"] == "hatsune_miku rating:s"

    captured.clear()
    E621Adapter().search("hatsune_miku", limit=10, rating="u")
    assert "rating:" not in captured["params"].get("tags", "")


def test_gelbooru_rating_becomes_dapi_tag(monkeypatch) -> None:
    captured: dict = {}
    _stub_search(monkeypatch, captured)

    GelbooruAdapter().search("hatsune_miku", limit=10, rating="e")
    assert "rating:e" in captured["params"]["tags"]

    # "g" does not exist in the DAPI rating scale -> client-side fallback only.
    captured.clear()
    GelbooruAdapter().search("hatsune_miku", limit=10, rating="g")
    assert "rating:" not in captured["params"].get("tags", "")


def test_n1_credentials_never_leak_into_gradio_config(tmp_path: Path, monkeypatch) -> None:
    """N1: neither user_id nor api_key may appear in app.get_config_file() (neither value nor placeholder)."""
    mgr = ConfigManager(config_path=tmp_path / "config.local.json")
    mgr.set_credentials_many(
        {
            "danbooru": ("SECRET_USER_DAN", "SECRET_KEY_XYZ_999"),
            "e621": ("SECRET_USER_E621", "SECRET_KEY_E621_888"),
        },
        persist_to_disk=False,
    )
    monkeypatch.setattr("hades_booru.ui.layout.config_manager", mgr)

    app = create_gradio_app()
    serialized_cfg = json.dumps(app.get_config_file(), default=str)
    assert "SECRET_KEY_XYZ_999" not in serialized_cfg
    assert "SECRET_USER_DAN" not in serialized_cfg
    assert "SECRET_KEY_E621_888" not in serialized_cfg
    assert "SECRET_USER_E621" not in serialized_cfg
    assert "(saved)" in serialized_cfg


def test_n2_open_folder_in_explorer_linux_and_darwin(tmp_path: Path, monkeypatch) -> None:
    """N2: open_folder_in_explorer must call subprocess.Popen without invalid check= kwarg on Linux/macOS."""
    popen_calls: list[tuple[list[str], dict]] = []

    def fake_popen(cmd, **kwargs):
        if "check" in kwargs:
            raise TypeError("Popen.__init__() got an unexpected keyword argument 'check'")
        popen_calls.append((list(cmd), kwargs))

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    monkeypatch.setattr("sys.platform", "linux")
    msg_linux = open_folder_in_explorer(str(tmp_path), lang="en")
    assert "Opened directory:" in msg_linux
    assert popen_calls[-1][0][0] == "xdg-open"

    monkeypatch.setattr("sys.platform", "darwin")
    msg_mac = open_folder_in_explorer(str(tmp_path), lang="en")
    assert "Opened directory:" in msg_mac
    assert popen_calls[-1][0][0] == "open"


def test_n3_thread_local_last_warning_isolation() -> None:
    """N3: concurrent threads sharing a singleton adapter must have isolated last_warning values."""
    adapter = DanbooruAdapter()

    def worker(val: str | None) -> str | None:
        adapter.last_warning = val
        return adapter.last_warning

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        f1 = pool.submit(worker, "warn-thread-1")
        f2 = pool.submit(worker, None)
        f3 = pool.submit(worker, "warn-thread-3")
        assert f1.result() == "warn-thread-1"
        assert f2.result() is None
        assert f3.result() == "warn-thread-3"


def test_n4_retry_after_is_capped_at_30_seconds() -> None:
    """N4: Retry-After header must never sleep longer than MAX_RETRY_AFTER_SECONDS (30s)."""
    assert _retry_after_seconds({"Retry-After": "3600"}) == MAX_RETRY_AFTER_SECONDS == 30.0
    assert _retry_after_seconds({"Retry-After": "5"}) == 5.0
    assert _retry_after_seconds({"Retry-After": "-10"}) == 0.0
    assert _retry_after_seconds({"Retry-After": "invalid"}) == 0.0


def test_n5_clear_credentials_wipes_memory_and_disk(tmp_path: Path) -> None:
    """N5: clear_credentials must wipe all saved credentials from session memory and disk."""
    cfg_path = tmp_path / "config.local.json"
    mgr = ConfigManager(config_path=cfg_path)
    mgr.set_credentials("danbooru", "alice", "secret_123", persist_to_disk=True)
    assert mgr.get_credentials("danbooru").api_key == "secret_123"

    mgr.clear_credentials()
    assert mgr.get_credentials("danbooru").user_id == ""
    assert mgr.get_credentials("danbooru").api_key == ""
    disk_data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert disk_data["credentials"]["danbooru"]["api_key"] == ""


def test_l13_pawoo_warns_when_multiple_tags_are_truncated(monkeypatch) -> None:
    """L13: Pawoo timeline search must set last_warning when extra tags are ignored."""
    captured: dict = {}
    _stub_search(monkeypatch, captured)

    adapter = ArtPlatformsAdapter("pawoo", "Pawoo", "pawoo.net")
    adapter.search("hatsune_miku 1girl solo", limit=10)
    assert adapter.last_warning is not None
    assert "hatsune_miku" in adapter.last_warning
    assert "1girl" in adapter.last_warning
