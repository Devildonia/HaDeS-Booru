"""
Unit Tests for AdapterRegistry and URL Auto-Detection across all 28 registered sources.
"""

from __future__ import annotations

from hades_booru.adapters.registry import registry


def test_registry_has_all_28_sources() -> None:
    specs = registry.get_all_specs()
    assert len(specs) == 28
    ids = {s.id for s in specs}
    expected_ids = {
        "danbooru",
        "safebooru_donmai",
        "hijiribe",
        "sonohara",
        "aibooru",
        "atfbooru",
        "safebooru",
        "gelbooru",
        "rule34",
        "rule34_us",
        "tbib",
        "xbooru",
        "realbooru",
        "konachan",
        "konachan_net",
        "yandere",
        "sakugabooru",
        "lolibooru",
        "e621",
        "e926",
        "derpibooru",
        "furbooru",
        "zerochan",
        "deviantart",
        "artstation",
        "pawoo",
        "ehentai",
        "generic",
    }
    assert ids == expected_ids


def test_direct_post_url_detection() -> None:
    d1 = registry.detect_source_from_url("https://danbooru.donmai.us/posts/8492011")
    assert d1 is not None
    assert d1.adapter.id == "danbooru"
    assert d1.is_direct_post is True

    d_hijiribe = registry.detect_source_from_url("https://hijiribe.donmai.us/posts/8492011")
    assert d_hijiribe is not None
    assert d_hijiribe.adapter.id == "hijiribe"
    assert d_hijiribe.is_direct_post is True

    d_aibooru = registry.detect_source_from_url("https://aibooru.online/posts/12044")
    assert d_aibooru is not None
    assert d_aibooru.adapter.id == "aibooru"
    assert d_aibooru.is_direct_post is True

    d2 = registry.detect_source_from_url("https://safebooru.org/index.php?page=post&s=view&id=4991234")
    assert d2 is not None
    assert d2.adapter.id == "safebooru"
    assert d2.is_direct_post is True

    d3 = registry.detect_source_from_url("https://konachan.com/post/show/349120")
    assert d3 is not None
    assert d3.adapter.id == "konachan"
    assert d3.is_direct_post is True

    d_derpi = registry.detect_source_from_url("https://derpibooru.org/images/3100200")
    assert d_derpi is not None
    assert d_derpi.adapter.id == "derpibooru"
    assert d_derpi.is_direct_post is True

    d_fur = registry.detect_source_from_url("https://furbooru.org/images/4100000")
    assert d_fur is not None
    assert d_fur.adapter.id == "furbooru"
    assert d_fur.is_direct_post is True

    d_zero = registry.detect_source_from_url("https://www.zerochan.net/4012345")
    assert d_zero is not None
    assert d_zero.adapter.id == "zerochan"
    assert d_zero.is_direct_post is True

    d_zero_cdn = registry.detect_source_from_url("https://s3.zerochan.net/240/45/23/4012345.jpg")
    assert d_zero_cdn is not None
    assert d_zero_cdn.adapter.id == "zerochan"
    assert d_zero_cdn.is_direct_post is True


def test_listing_url_tag_extraction() -> None:
    l1 = registry.detect_source_from_url("https://danbooru.donmai.us/posts?tags=hatsune_miku+solo")
    assert l1 is not None
    assert l1.adapter.id == "danbooru"
    assert l1.is_direct_post is False
    assert l1.extracted_tags == "hatsune_miku solo"

    l2 = registry.detect_source_from_url(
        "https://safebooru.org/index.php?page=post&s=list&tags=1girl+blue_eyes"
    )
    assert l2 is not None
    assert l2.adapter.id == "safebooru"
    assert l2.is_direct_post is False
    assert l2.extracted_tags == "1girl blue_eyes"

    l3 = registry.detect_source_from_url("https://pawoo.net/web/timelines/tag/illust")
    assert l3 is not None
    assert l3.adapter.id == "pawoo"
    assert l3.is_direct_post is False
    assert l3.extracted_tags == "illust"

    l_zero = registry.detect_source_from_url("https://www.zerochan.net/Hatsune%20Miku")
    assert l_zero is not None
    assert l_zero.adapter.id == "zerochan"
    assert l_zero.is_direct_post is False
    assert l_zero.extracted_tags == "Hatsune Miku"


def test_art_platform_host_isolation() -> None:
    artstation = registry.get_adapter("artstation")
    deviantart = registry.get_adapter("deviantart")
    pawoo = registry.get_adapter("pawoo")
    ehentai = registry.get_adapter("ehentai")

    assert artstation.can_handle_url("https://www.artstation.com/artwork/1234") is True
    assert artstation.can_handle_url("https://www.deviantart.com/art/1234") is False
    assert deviantart.can_handle_url("https://www.deviantart.com/art/1234") is True
    assert pawoo.can_handle_url("https://pawoo.net/web/statuses/999") is True
    assert ehentai.can_handle_url("https://e-hentai.org/g/123456/abcdef0123/") is True
