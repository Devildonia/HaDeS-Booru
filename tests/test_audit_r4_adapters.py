"""
Audit R4 regression tests: X7 (e621 'General' selection must not be wiped by
the client-side equality filter).

Root cause: on e621 a 'General' selection injects `rating:s` (its safe bucket);
the returned posts are normalized to rating 's'; the old UI safety net then
re-filtered with `p.rating == 'g'` and dropped everything -> zero results.

Fix: adapters expose `server_rating_applied` and the UI skips its client-side
re-filter when the server already applied the rating.
"""

from __future__ import annotations

import pytest

from hades_booru.adapters import e621 as e621_module
from hades_booru.adapters import moebooru as moebooru_module
from hades_booru.http_client import http_client


def _fake_posts():
    return {
        "posts": [
            {
                "id": 1,
                "rating": "s",
                "file": {"url": "https://e621.net/files/1.jpg", "width": 512, "height": 768},
                "tags": {"general": ["1girl"]},
                "score": {"total": 0},
            },
            {
                "id": 2,
                "rating": "s",
                "file": {"url": "https://e621.net/files/2.jpg", "width": 512, "height": 768},
                "tags": {"general": ["smile"]},
                "score": {"total": 0},
            },
        ]
    }


def test_e621_general_selection_keeps_safe_bucket(monkeypatch) -> None:
    """X7: 'General' on e621 must inject `rating:s` AND flag server-side filtering,
    so the UI keeps the 's'-rated posts instead of filtering them to zero."""
    captured: dict[str, object] = {}

    def fake_get_json(url: str, params: dict | None = None, auth=None, **_kw) -> dict:
        captured["tags"] = (params or {}).get("tags")
        return _fake_posts()

    monkeypatch.setattr(http_client, "get_json", fake_get_json)

    adapter = e621_module.E621Adapter()
    posts = adapter.search("1girl", limit=20, rating="g")

    assert captured["tags"] == "1girl rating:s"
    assert adapter.server_rating_applied is True
    # Both posts are e621's safe bucket for a General selection; they must survive.
    assert [p.rating for p in posts] == ["s", "s"]


def test_e621_unmapped_rating_keeps_client_filter_contract(monkeypatch) -> None:
    """Ratings with no server-side equivalent (e.g. 'u') must leave the flag off,
    so the UI's client-side safety filter still applies."""
    monkeypatch.setattr(http_client, "get_json", lambda *a, **k: _fake_posts())

    adapter = e621_module.E621Adapter()
    adapter.search("1girl", limit=20, rating="u")
    assert adapter.server_rating_applied is False


def test_moebooru_general_selection_flag(monkeypatch) -> None:
    """Same contract on Moebooru: 'General' maps to `rating:safe` and flags server-side."""
    captured: dict[str, object] = {}

    def fake_get_json(url: str, params: dict | None = None, auth=None, **_kw) -> dict:
        captured["tags"] = (params or {}).get("tags")
        # Moebooru's post.json returns a bare list, not {'posts': [...]}.
        return [
            {
                "id": 1,
                "rating": "safe",
                "sample_url": "https://tbib.org/s/1.jpg",
                "width": 512,
                "height": 768,
                "tags": ["1girl"],
                "score": 0,
            }
        ]

    monkeypatch.setattr(http_client, "get_json", fake_get_json)

    adapter = moebooru_module.MoebooruAdapter()
    posts = adapter.search("1girl", limit=5, rating="g")

    assert captured["tags"] == "1girl rating:safe"
    assert adapter.server_rating_applied is True
    assert [p.rating for p in posts] == ["g"]


def test_base_adapter_default_flag() -> None:
    """Adapters that never touch the flag must default to False (client filter active)."""
    assert e621_module.E621Adapter().server_rating_applied is False
    assert moebooru_module.MoebooruAdapter().server_rating_applied is False


@pytest.mark.parametrize("rating,expected", [("g", "rating:s"), ("s", "rating:s"), ("q", "rating:q"), ("e", "rating:e")])
def test_e621_rating_mapping_table(rating: str, expected: str) -> None:
    assert e621_module.SERVER_RATING_TAGS[rating] == expected
