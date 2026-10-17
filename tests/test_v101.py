"""
v1.0.1 feature tests: server-side rating filter across adapter families.
"""

from __future__ import annotations

import inspect

import hades_booru.http_client as hc
from hades_booru.adapters.artplatforms import ArtPlatformsAdapter
from hades_booru.adapters.danbooru import DanbooruAdapter
from hades_booru.adapters.e621 import E621Adapter
from hades_booru.adapters.gelbooru import GelbooruAdapter
from hades_booru.adapters.moebooru import MoebooruAdapter
from hades_booru.adapters.philomena import PhilomenaAdapter
from hades_booru.adapters.zerochan import ZerochanAdapter


def _stub_search(monkeypatch, captured: dict):
    """Stubs the shared http_client singleton (get_json + get_text) and captures params.

    Instance-level patching (same style as the v1.0.0 audit tests) is required because
    some tests leave instance attributes on the singleton that would shadow class-level
    patches.
    """

    def fake_get_json(url, params=None, headers=None, auth=None, retries=2):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return []  # Empty batch -> search() stops immediately.

    def fake_get_text(url, params=None, headers=None, auth=None, retries=2):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return ""  # Empty body -> search() stops immediately.

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


def test_danbooru_rating_becomes_server_tag(monkeypatch) -> None:
    captured: dict = {}
    _stub_search(monkeypatch, captured)

    DanbooruAdapter().search("hatsune_miku", limit=10, rating="g")
    assert captured["params"]["tags"].endswith("rating:safe")

    # "u" (unrated) has no Danbooru tag equivalent -> must not inject a rating tag.
    captured.clear()
    DanbooruAdapter().search("hatsune_miku", limit=10, rating="u")
    assert "rating:" not in captured["params"].get("tags", "")


def test_moebooru_rating_uses_query_parameter(monkeypatch) -> None:
    captured: dict = {}
    _stub_search(monkeypatch, captured)

    MoebooruAdapter().search("re:zero", limit=10, rating="s")
    assert captured["params"]["rating"] == "s"

    captured.clear()
    MoebooruAdapter().search("re:zero", limit=10)
    assert "rating" not in captured["params"]


def test_e621_rating_uses_bracketed_parameter(monkeypatch) -> None:
    captured: dict = {}
    _stub_search(monkeypatch, captured)

    E621Adapter().search("hatsune_miku", limit=10, rating="e")
    assert captured["params"]["rating[]"] == "e"

    captured.clear()
    E621Adapter().search("hatsune_miku", limit=10, rating="u")
    assert "rating[]" not in captured["params"]


def test_gelbooru_rating_becomes_dapi_tag(monkeypatch) -> None:
    captured: dict = {}
    _stub_search(monkeypatch, captured)

    GelbooruAdapter().search("hatsune_miku", limit=10, rating="e")
    assert "rating:e" in captured["params"]["tags"]

    # "g" does not exist in the DAPI rating scale -> client-side fallback only.
    captured.clear()
    GelbooruAdapter().search("hatsune_miku", limit=10, rating="g")
    assert "rating:" not in captured["params"].get("tags", "")
