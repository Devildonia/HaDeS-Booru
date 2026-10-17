"""
Unit Tests for Booru Adapters mapping, resolution variants, and edge-case resilience.
"""

from __future__ import annotations

from hades_booru.adapters.danbooru import DanbooruAdapter
from hades_booru.adapters.e621 import E621Adapter
from hades_booru.adapters.gelbooru import GelbooruAdapter
from hades_booru.adapters.philomena import PhilomenaAdapter
from hades_booru.adapters.zerochan import ZerochanAdapter


def test_danbooru_post_mapping_and_variants() -> None:
    adapter = DanbooruAdapter()
    raw = {
        "id": 999111,
        "preview_file_url": "https://cdn.donmai.us/180x180/999111.jpg",
        "large_file_url": "https://cdn.donmai.us/sample/999111.jpg",
        "file_url": "https://cdn.donmai.us/original/999111.png",
        "media_asset": {
            "variants": [
                {"type": "180x180", "url": "https://cdn.donmai.us/180x180/999111.jpg"},
                {"type": "360x360", "url": "https://cdn.donmai.us/360x360/999111.webp"},
                {"type": "720x720", "url": "https://cdn.donmai.us/720x720/999111.webp"},
                {"type": "sample", "url": "https://cdn.donmai.us/sample/999111.jpg"},
                {"type": "original", "url": "https://cdn.donmai.us/original/999111.png"},
            ]
        },
        "image_width": 1600,
        "image_height": 2000,
        "rating": "g",
        "tag_string_copyright": "vocaloid",
        "tag_string_character": "hatsune_miku",
        "tag_string_artist": "artist_x",
        "tag_string_general": "1girl solo ^_^",
        "tag_string_meta": "highres",
        "tag_string": "vocaloid hatsune_miku artist_x 1girl solo ^_^ highres",
    }
    post = adapter._map_post(raw, "danbooru.donmai.us")
    assert post is not None
    assert post.id == "999111"
    assert post.rating == "g"
    assert post.tags.character == ["hatsune_miku"]
    assert "^_^" in post.tags.general
    assert post.url_for_quality("low") == "https://cdn.donmai.us/360x360/999111.webp"
    assert post.url_for_quality("medium") == "https://cdn.donmai.us/720x720/999111.webp"
    assert post.url_for_quality("high") == "https://cdn.donmai.us/sample/999111.jpg"
    assert post.url_for_quality("original") == "https://cdn.donmai.us/original/999111.png"
    assert post.url_for_quality("text") == ""


def test_gelbooru_directory_fallback_mapping() -> None:
    adapter = GelbooruAdapter("safebooru", "Safebooru", "safebooru.org")
    raw = {
        "id": 444222,
        "directory": "4210",
        "image": "sample_hash.png",
        "sample": 1,
        "tags": "1girl solo fate_(series) highres",
        "rating": "safe",
        "width": 1024,
        "height": 768,
    }
    post = adapter._map_post(raw)
    assert post is not None
    assert post.id == "444222"
    assert post.rating == "g"
    assert "fate_(series)" in post.tags.character
    assert "highres" in post.tags.meta
    assert post.file_url == "https://safebooru.org/images/4210/sample_hash.png"
    assert post.sample_url == "https://safebooru.org/samples/4210/sample_sample_hash.jpg"


def test_e621_lore_and_species_mapping() -> None:
    adapter = E621Adapter()
    raw = {
        "id": 777333,
        "rating": "s",
        "file": {"url": "https://static1.e621.net/data/full.png", "width": 1200, "height": 1200},
        "sample": {"url": "https://static1.e621.net/data/sample.jpg"},
        "preview": {"url": "https://static1.e621.net/data/preview.jpg"},
        "tags": {
            "copyright": ["nintendo"],
            "character": ["fox_mccloud"],
            "artist": ["some_artist"],
            "species": ["canid", "fox"],
            "general": ["solo", "pilot"],
            "lore": ["star_fox_(lore)"],
            "meta": ["hi_res"],
        },
    }
    post = adapter._map_post(raw)
    assert post is not None
    assert post.rating == "s"
    assert "canid" in post.tags.general
    assert "star_fox_(lore)" in post.tags.general
    assert post.tags.copyright == ["nintendo"]


def test_philomena_derpibooru_mapping() -> None:
    adapter = PhilomenaAdapter()
    raw = {
        "id": 3100200,
        "width": 1920,
        "height": 1080,
        "score": 142,
        "tags": ["safe", "artist:someone", "oc:custom_char", "solo", "digital art"],
        "representations": {
            "thumb": "https://derpicdn.net/img/thumb.webp",
            "medium": "https://derpicdn.net/img/medium.webp",
            "large": "https://derpicdn.net/img/large.webp",
            "full": "https://derpicdn.net/img/full.png",
        },
    }
    post = adapter._map_post(raw)
    assert post is not None
    assert post.id == "3100200"
    assert post.rating == "g"
    assert post.tags.artist == ["someone"]
    assert post.tags.character == ["oc:custom_char"]
    assert "digital_art" in post.tags.general
    assert post.url_for_quality("high") == "https://derpicdn.net/img/large.webp"
    assert post.url_for_quality("original") == "https://derpicdn.net/img/full.png"


def test_zerochan_mapping_and_url_helpers() -> None:
    from hades_booru.adapters.zerochan import (
        extract_zerochan_post_id,
        extract_zerochan_tag_from_path,
    )

    adapter = ZerochanAdapter()
    raw = {
        "id": 4012345,
        "width": 2000,
        "height": 3000,
        "thumbnail": "https://s3.zerochan.net/240/45/23/4012345.jpg",
        "medium": "https://s3.zerochan.net/600/45/23/4012345.jpg",
        "large": "https://static.zerochan.net/full/45/23/4012345.jpg",
        "tag": "Hatsune Miku",
        "tags": ["VOCALOID", "Twintails", "Solo"],
    }
    post = adapter._map_post(raw)
    assert post is not None
    assert post.id == "4012345"
    assert "hatsune_miku" in post.tags.general
    assert "vocaloid" in post.tags.general
    assert post.url_for_quality("medium") == "https://s3.zerochan.net/600/45/23/4012345.jpg"
    assert post.url_for_quality("high") == "https://static.zerochan.net/full/45/23/4012345.jpg"
    assert post.best_display_url == post.url_for_quality("high")

    assert extract_zerochan_post_id("/4012345") == "4012345"
    assert extract_zerochan_post_id("/240/45/23/4012345.jpg") == "4012345"
    assert extract_zerochan_post_id("/Hatsune.Miku.full.4012345.jpg") == "4012345"
    assert extract_zerochan_post_id("/Hatsune%20Miku") is None
    assert extract_zerochan_tag_from_path("/Hatsune%20Miku") == "Hatsune Miku"
    assert extract_zerochan_tag_from_path("/Hatsune+Miku") == "Hatsune Miku"
    assert extract_zerochan_tag_from_path("/4012345") is None
