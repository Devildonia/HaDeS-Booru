"""
Unit and integration tests for the Offline Tag Dictionary (`hades_booru/tag_dictionary/`).
Covers exact lookup, alias resolution, unknown entries, special characters, SQL wildcard
escaping, strict EN/ES bilingual contract, batch category resolution, and mocked importer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hades_booru.tag_dictionary import (
    TagDictionaryImporter,
    TagDictionaryService,
    normalize_dict_query,
    strip_dtext,
)


@pytest.fixture()
def dict_service(tmp_path: Path) -> TagDictionaryService:
    db_file = tmp_path / "test_tags.sqlite3"
    svc = TagDictionaryService(db_path=db_file, auto_seed=True)
    svc.ensure_initialized()
    return svc


def test_exact_tag_lookup_and_metadata(dict_service: TagDictionaryService) -> None:
    record = dict_service.lookup("hatsune_miku")
    assert record is not None
    assert record.name == "hatsune_miku"
    assert record.category == "character"
    assert record.post_count > 100000
    assert record.resolved_from is None
    assert "miku" in record.aliases
    assert record.wiki_url == "https://danbooru.donmai.us/wiki_pages/hatsune_miku"


def test_alias_resolution_returns_canonical_tag(dict_service: TagDictionaryService) -> None:
    # Querying by alias ("miku" or "Miku Hatsune" or "fgo") resolves to the canonical tag
    rec_miku = dict_service.lookup("  Miku  ")
    assert rec_miku is not None
    assert rec_miku.name == "hatsune_miku"
    assert rec_miku.resolved_from == "miku"

    rec_fgo = dict_service.lookup("FGO")
    assert rec_fgo is not None
    assert rec_fgo.name == "fate/grand_order"
    assert rec_fgo.category == "copyright"
    assert rec_fgo.resolved_from == "fgo"


def test_unknown_and_blank_entries_return_none(dict_service: TagDictionaryService) -> None:
    assert dict_service.lookup("") is None
    assert dict_service.lookup("   ") is None
    assert dict_service.lookup("nonexistent_tag_xyz_99999") is None


def test_special_characters_and_sql_wildcards(dict_service: TagDictionaryService) -> None:
    # Insert a tag with kaomoji / parentheses / slash / percent
    dict_service.upsert_entries(
        [
            {
                "name": "^_^",
                "category": "general",
                "post_count": 42000,
                "body_en": "Happy closed-eye kaomoji expression.",
                "body_es": None,
                "aliases": ["happy_kaomoji"],
            },
            {
                "name": "100%_orange_juice",
                "category": "copyright",
                "post_count": 3200,
                "body_en": "Digital board game developed by Orange_Juice.",
                "body_es": None,
                "aliases": ["oj_100%"],
            },
        ]
    )

    kao = dict_service.lookup("^_^")
    assert kao is not None
    assert kao.name == "^_^"
    assert kao.wiki_url == "https://danbooru.donmai.us/wiki_pages/%5E_%5E"

    oj = dict_service.lookup("oj_100%")
    assert oj is not None
    assert oj.name == "100%_orange_juice"
    assert oj.resolved_from == "oj_100%"

    # SQL wildcard characters in suggest() must be escaped, not match everything
    suggestions = dict_service.suggest("100%_", limit=10)
    assert suggestions == ["100%_orange_juice"]


def test_bilingual_contract_genuine_spanish_vs_english_fallback(
    dict_service: TagDictionaryService,
) -> None:
    # 1girl has a genuine curated Spanish translation
    rec_1girl = dict_service.lookup("1girl")
    assert rec_1girl is not None
    en_text, en_fallback = rec_1girl.definition_for("en")
    es_text, es_fallback = rec_1girl.definition_for("es")
    assert not en_fallback
    assert not es_fallback
    assert "single female character" in en_text
    assert "personaje femenino" in es_text

    # cowboy_shot intentionally has body_es=None (no official Spanish translation)
    rec_cowboy = dict_service.lookup("cowboy_shot")
    assert rec_cowboy is not None
    assert rec_cowboy.body_es is None
    es_cowboy_text, is_fallback = rec_cowboy.definition_for("es")
    assert is_fallback is True
    assert es_cowboy_text == rec_cowboy.body_en


def test_batch_category_lookup_resolves_canonical_and_aliases(
    dict_service: TagDictionaryService,
) -> None:
    cats = dict_service.lookup_categories_batch(
        ["hatsune_miku", "miku", "kantoku", "fgo", "highres", "unknown_tag_abc"]
    )
    assert cats["hatsune_miku"] == "character"
    assert cats["miku"] == "character"
    assert cats["kantoku"] == "artist"
    assert cats["fgo"] == "copyright"
    assert cats["highres"] == "meta"
    assert "unknown_tag_abc" not in cats


def test_strip_dtext_cleans_wiki_markup() -> None:
    raw = (
        "h1. Overview\r\n"
        "[b]Hatsune Miku[/b] is a [[vocaloid|Vocaloid]] developed by "
        '"Crypton Future Media":[https://www.crypton.co.jp] with [[twintails]].\r\n'
        "* List item to skip\r\n"
    )
    cleaned = strip_dtext(raw)
    assert "h1." not in cleaned
    assert "[b]" not in cleaned
    assert "[[" not in cleaned
    assert "Hatsune Miku is a Vocaloid developed by Crypton Future Media with twintails." == cleaned


def test_importer_ingests_tags_wikis_and_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = TagDictionaryService(db_path=tmp_path / "imported.sqlite3", auto_seed=False)
    importer = TagDictionaryImporter(service=svc, base_url="https://danbooru.donmai.us")

    def fake_get_json(url: str, params: dict[str, Any] | None = None, auth: Any = None) -> Any:
        if url.endswith("/tags.json"):
            return [
                {"name": "frieren", "category": 4, "post_count": 95000},
                {"name": "sousou_no_frieren", "category": 3, "post_count": 120000},
            ]
        if url.endswith("/wiki_pages.json"):
            return [
                {
                    "title": "frieren",
                    "body": "h2. Profile\n[[Elven]] mage from [[sousou_no_frieren|Frieren: Beyond Journey's End]].",
                }
            ]
        if url.endswith("/tag_aliases.json"):
            return [
                {"antecedent_name": "frieren_(character)", "consequent_name": "frieren"},
            ]
        return []

    monkeypatch.setattr("hades_booru.tag_dictionary.importer.http_client.get_json", fake_get_json)

    count = importer.import_from_danbooru(max_pages=1, page_size=10)
    assert count == 2

    rec = svc.lookup("frieren_(character)")
    assert rec is not None
    assert rec.name == "frieren"
    assert rec.category == "character"
    assert rec.resolved_from == "frieren_(character)"
    assert "Elven mage from Frieren: Beyond Journey's End." in rec.body_en
    assert rec.body_es is None
    assert normalize_dict_query("Frieren (Character)") == "frieren_(character)"
