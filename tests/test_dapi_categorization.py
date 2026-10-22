"""
Unit and integration tests for 3-layer DAPI tag categorization (`X9` / `R6-13`).
Covers qualifier exemptions (`red_(color)`, `standing_(pose)`, `from_behind_(position)`),
copyright suffixes, artist suffixes, local TagDictionaryService batch resolution,
and per-board `DapiTagCategoryCache` (`s=tag&q=index` JSON + XML).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hades_booru.adapters.gelbooru import (
    DapiTagCategoryCache,
    GelbooruAdapter,
    _categorize_flat_tags,
)


def test_qualifier_parentheses_are_not_misclassified_as_character() -> None:
    raw = [
        "red_(color)",
        "standing_(pose)",
        "from_behind_(position)",
        "school_uniform_(style)",
        "hatsune_miku_(cosplay)",
        "2_(number)",
        "pleated_skirt_(clothing)",
        "sunset_(lighting)",
        "rem_(re:zero)",
    ]
    cat = _categorize_flat_tags(raw)

    assert "rem_(re:zero)" in cat.character
    for tag in raw:
        if tag != "rem_(re:zero)":
            assert tag in cat.general, f"Expected {tag!r} in general, got {cat}"
            assert tag not in cat.character


def test_copyright_and_artist_suffixes_and_dictionary_enrichment() -> None:
    raw = [
        "fate_(series)",
        "blue_archive",  # unparenthesized copyright via local TagDictionaryService
        "hatsune_miku",  # unparenthesized character via local TagDictionaryService
        "kantoku",  # unparenthesized artist via local TagDictionaryService
        "some_creator_(artist)",  # parenthesized artist suffix
        "type-moon_(company)",  # parenthesized copyright suffix
        "highres",
        "1girl",
    ]
    cat = _categorize_flat_tags(raw)

    assert "fate_(series)" in cat.copyright
    assert "blue_archive" in cat.copyright
    assert "type-moon_(company)" in cat.copyright
    assert "hatsune_miku" in cat.character
    assert "kantoku" in cat.artist
    assert "some_creator_(artist)" in cat.artist
    assert "highres" in cat.meta
    assert "1girl" in cat.general


def test_dapi_tag_endpoint_cache_json_and_xml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = DapiTagCategoryCache(cache_path=tmp_path / "dapi_tags.json")
    adapter = GelbooruAdapter("safebooru", "Safebooru", "safebooru.org")

    calls: list[dict[str, Any]] = []

    def fake_get_text(url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> str:
        calls.append(params or {})
        return '{"tag": [{"name": "ciloranko", "type": "1"}, {"name": "azur_lane", "type": 3}]}'

    monkeypatch.setattr("hades_booru.adapters.gelbooru.http_client.get_text", fake_get_text)

    resolved = adapter.resolve_tag_categories(["ciloranko", "azur_lane"], cache=cache)
    assert resolved["ciloranko"] == "artist"
    assert resolved["azur_lane"] == "copyright"
    assert len(calls) == 1

    # Second call hits the cache without firing HTTP
    resolved_again = adapter.resolve_tag_categories(["ciloranko", "azur_lane"], cache=cache)
    assert resolved_again["ciloranko"] == "artist"
    assert len(calls) == 1

    # Verify XML fallback on DAPI `s=tag`
    def fake_get_xml(url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> str:
        calls.append(params or {})
        return '<tags type="array"><tag name="bremerton_(azur_lane)" type="4"/></tags>'

    monkeypatch.setattr("hades_booru.adapters.gelbooru.http_client.get_text", fake_get_xml)
    resolved_xml = adapter.resolve_tag_categories(["bremerton_(azur_lane)"], cache=cache)
    assert resolved_xml["bremerton_(azur_lane)"] == "character"

    cat = _categorize_flat_tags(
        ["ciloranko", "azur_lane", "bremerton_(azur_lane)", "1girl"],
        resolved_overrides=resolved_xml | resolved,
    )
    assert cat.artist == ["ciloranko"]
    assert cat.copyright == ["azur_lane"]
    assert cat.character == ["bremerton_(azur_lane)"]
    assert cat.general == ["1girl"]
