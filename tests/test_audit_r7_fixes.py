"""
Regression tests for the R7 audit fixes (v1.1.0):

- R7-02: URL-aware `add_top_tag_to_query` (tags merged into `tags` param, not comma-joined).
- R7-08a: memoized dictionary category lookup (no SQLite connection per post).
- R7-08d: `search()` resolves query-tag categories via DAPI `s=tag` in production.
- R7-09: AVIF accepted at the image gate; gallery cache writes atomically.
- R7-10: deterministic post IDs in the art-platforms adapter (cache-friendly).
- R7-11: tag counters respect the user's custom separator.
- R7-12: fatal HTTP errors are not retried; HTML/XML detected case-insensitively;
         no response-body echo in JSON errors.
- R7-13: `paginate()` `min_batch_size` floor surfaces a truncation warning.
- R7-14: theme JS binds a live OS color-scheme change listener in "system" mode.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from http_mocks import DummyClient, make_streamable_response

from hades_booru.adapters.artplatforms import ArtPlatformsAdapter
from hades_booru.adapters.base import BooruAdapter
from hades_booru.adapters.gelbooru import DapiTagCategoryCache, GelbooruAdapter
from hades_booru.adapters.zerochan import ZerochanAdapter
from hades_booru.exporter import looks_like_image
from hades_booru.http_client import BooruNetworkError, HttpClient, assert_public_host
from hades_booru.image_cache import DiskImageCache
from hades_booru.ui.components import render_export_stats_html, render_inspector_nav_badge_html
from hades_booru.ui.state import add_top_tag_to_query

# ---------------------------------------------------------------------------
# R7-02: URL-aware add_top_tag_to_query
# ---------------------------------------------------------------------------


def _query_params(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(url).query))


def test_add_top_tag_merges_into_existing_tags_param() -> None:
    base = "https://safebooru.org/index.php?page=dapi&s=post&q=index&tags=miku"
    q, _reset = add_top_tag_to_query(base, "1girl")
    params = _query_params(q)
    assert params["tags"].split() == ["miku", "1girl"]
    assert params["page"] == "dapi"  # other params preserved


def test_add_top_tag_adds_missing_tags_param() -> None:
    q, _reset = add_top_tag_to_query("https://gelbooru.com/index.php?page=post&s=view", "cat")
    assert _query_params(q)["tags"] == "cat"


def test_add_top_tag_to_url_dedups_case_insensitively() -> None:
    q, _reset = add_top_tag_to_query("https://x.org/a?tags=MIKU", "miku")
    assert _query_params(q)["tags"].split() == ["MIKU"]


def test_add_top_tag_plain_query_behavior_unchanged() -> None:
    q, _reset = add_top_tag_to_query("miku, solo", "1girl")
    assert q == "miku, solo, 1girl"


# ---------------------------------------------------------------------------
# R7-08a / R7-08d: gelbooru dictionary memo + production DAPI categorization
# ---------------------------------------------------------------------------


def test_gelbooru_dict_lookup_memoizes_across_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    from hades_booru.adapters import gelbooru as g

    batch_calls: list[list[str]] = []

    class StubDict:
        def lookup_categories_batch(self, tags):
            batch_calls.append(list(tags))
            return {t.lower(): "character" for t in tags}

    monkeypatch.setattr(g, "get_tag_dictionary", lambda: StubDict())

    first = g._categorize_flat_tags(["r7memo_tag_one", "r7memo_shared"])
    second = g._categorize_flat_tags(["r7memo_shared", "r7memo_tag_two"])
    assert first.character == ["r7memo_tag_one", "r7memo_shared"]
    assert second.character == ["r7memo_shared", "r7memo_tag_two"]
    # Second call only batched the tag unknown to the memo (R7-08a).
    assert len(batch_calls) == 2
    assert batch_calls[1] == ["r7memo_tag_two"]


def test_gelbooru_dict_lookup_failure_degrades_to_heuristics(monkeypatch: pytest.MonkeyPatch) -> None:
    from hades_booru.adapters import gelbooru as g

    class BrokenDict:
        def lookup_categories_batch(self, tags):
            raise RuntimeError("db gone")

    monkeypatch.setattr(g, "get_tag_dictionary", lambda: BrokenDict())
    res = g._categorize_flat_tags(["r7broken_tag"])
    assert res.general == ["r7broken_tag"]


def test_gelbooru_search_resolves_query_tag_categories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R7-08d: search() feeds DAPI `s=tag` categories into post categorization."""
    from hades_booru.adapters import gelbooru as g

    fresh_cache = DapiTagCategoryCache(cache_path=tmp_path / "dapi_cache.json")
    monkeypatch.setattr(g, "dapi_tag_cache", fresh_cache)

    s_tag_calls = 0

    def fake_get_text(url, params=None, **kwargs):
        nonlocal s_tag_calls
        if (params or {}).get("s") == "tag":
            s_tag_calls += 1
            names = (params or {}).get("names", "")
            return json.dumps([{"name": n, "type": "4"} for n in names.split()])  # character
        return json.dumps(
            {
                "post": [
                    {
                        "id": 555,
                        "tags": "r7test_querychar 1girl",
                        "file_url": "https://cdn.example/f.jpg",
                        "preview_url": "https://cdn.example/p.jpg",
                        "width": 100,
                        "height": 100,
                        "rating": "s",
                    }
                ]
            }
        )

    monkeypatch.setattr(g, "http_client", SimpleNamespace(get_text=fake_get_text))
    adapter = g.GelbooruAdapter("safebooru", "Safebooru", "safebooru.org")

    posts = adapter.search("r7test_querychar", limit=10)
    assert len(posts) == 1
    assert s_tag_calls == 1
    assert "r7test_querychar" in posts[0].tags.character
    assert fresh_cache.get_many("safebooru", ["r7test_querychar"]).get("r7test_querychar") == "character"


def test_gelbooru_search_empty_query_skips_tag_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from hades_booru.adapters import gelbooru as g

    monkeypatch.setattr(g, "dapi_tag_cache", DapiTagCategoryCache(cache_path=tmp_path / "c.json"))
    calls: list[dict] = []

    def fake_get_text(url, params=None, **kwargs):
        calls.append(dict(params or {}))
        return json.dumps({"post": []})

    monkeypatch.setattr(g, "http_client", SimpleNamespace(get_text=fake_get_text))
    adapter = g.GelbooruAdapter("safebooru", "Safebooru", "safebooru.org")
    assert adapter.search("", limit=5) == []
    assert all(c.get("s") != "tag" for c in calls)


# ---------------------------------------------------------------------------
# R7-13: paginate min_batch_size truncation warning
# ---------------------------------------------------------------------------


def _raw_items(n: int) -> list[dict]:
    # IDs start at 1: zerochan's `_map_post` discards falsy IDs (0 included).
    return [{"id": i, "thumbnail": f"https://cdn.example/{i}.jpg", "tag": "test"} for i in range(1, n + 1)]


def test_paginate_warns_below_min_batch_size() -> None:
    adapter = ZerochanAdapter()
    posts = adapter.paginate(
        limit=100,
        max_limit=200,
        max_page_size=50,
        page_delay=0,
        fetch_page=lambda page, size: _raw_items(20) if page == 1 else [],
        map_item=adapter._map_post,
        min_batch_size=25,
    )
    assert len(posts) == 20
    assert adapter.last_warning is not None
    assert "truncated" in adapter.last_warning


def test_paginate_no_warning_above_min_batch_size_floor() -> None:
    adapter = ZerochanAdapter()
    adapter.paginate(
        limit=100,
        max_limit=200,
        max_page_size=50,
        page_delay=0,
        fetch_page=lambda page, size: _raw_items(30) if page == 1 else [],
        map_item=adapter._map_post,
        min_batch_size=25,
    )
    assert adapter.last_warning is None


def test_paginate_default_min_batch_size_keeps_legacy_behavior() -> None:
    adapter = ZerochanAdapter()
    posts = adapter.paginate(
        limit=100,
        max_limit=200,
        max_page_size=50,
        page_delay=0,
        fetch_page=lambda page, size: _raw_items(10) if page == 1 else [],
        map_item=adapter._map_post,
    )
    assert len(posts) == 10
    assert adapter.last_warning is None


# ---------------------------------------------------------------------------
# R7-12: http_client retry policy, HTML/XML detection, no body echo
# ---------------------------------------------------------------------------


def test_http_client_fatal_size_cap_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HttpClient(timeout_seconds=2.0)
    monkeypatch.setattr("hades_booru.http_client.TEXT_MAX_BYTES", 16)
    req = httpx.Request("GET", "https://example.com/big.txt")
    dummy = DummyClient([make_streamable_response(200, req, content=b"x" * 64)])
    monkeypatch.setattr("httpx.Client", lambda **kwargs: dummy)

    with pytest.raises(BooruNetworkError) as excinfo:
        client.get_text("https://example.com/big.txt", retries=2)
    assert dummy.call_count == 1  # no re-download of the oversized payload
    assert "safety limit" in str(excinfo.value)
    assert excinfo.value.retryable is False


def test_ssrf_guard_errors_are_flagged_non_retryable() -> None:
    with pytest.raises(BooruNetworkError) as excinfo:
        assert_public_host("http://127.0.0.1/admin")
    assert excinfo.value.retryable is False


def test_get_json_detects_lowercase_doctype_without_echoing_body(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HttpClient(timeout_seconds=2.0)
    req = httpx.Request("GET", "https://example.com/api")
    body = b"<!doctype html><html><body>TOP_SECRET_PAGE_CONTENT</body></html>"
    dummy = DummyClient([make_streamable_response(200, req, content=body)])
    monkeypatch.setattr("httpx.Client", lambda **kwargs: dummy)

    with pytest.raises(BooruNetworkError) as excinfo:
        client.get_json("https://example.com/api")
    msg = str(excinfo.value)
    assert "non-JSON page" in msg
    assert "TOP_SECRET_PAGE_CONTENT" not in msg  # R6-04 no-echo policy held


def test_get_json_invalid_json_does_not_echo_body(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HttpClient(timeout_seconds=2.0)
    req = httpx.Request("GET", "https://example.com/api")
    body = b"weird {partial SECRET_MARKER"
    dummy = DummyClient([make_streamable_response(200, req, content=body)])
    monkeypatch.setattr("httpx.Client", lambda **kwargs: dummy)

    with pytest.raises(BooruNetworkError) as excinfo:
        client.get_json("https://example.com/api")
    msg = str(excinfo.value)
    assert "not valid JSON" in msg
    assert "SECRET_MARKER" not in msg


def test_get_json_detects_xml_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HttpClient(timeout_seconds=2.0)
    req = httpx.Request("GET", "https://example.com/api")
    body = b'<?xml version="1.0"?><posts><secret/></posts>'
    dummy = DummyClient([make_streamable_response(200, req, content=body)])
    monkeypatch.setattr("httpx.Client", lambda **kwargs: dummy)

    with pytest.raises(BooruNetworkError) as excinfo:
        client.get_json("https://example.com/api")
    msg = str(excinfo.value)
    assert "non-JSON page" in msg
    assert "secret" not in msg


def test_get_json_detects_challenge_page_not_starting_with_html_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """v1.1.0 live-incident guard (safebooru.donmai.us).

    A Cloudflare challenge page was served with HTTP 200 and a body that did
    not start with <!doctype>/<html>, so the old strict prefix check fell
    through to the unhelpful generic 'not valid JSON' message. HTML structure
    markers anywhere in the first 512 chars must still be classified as a
    non-JSON page (with the actionable bot-protection message) and the body
    must never be echoed.
    """
    client = HttpClient(timeout_seconds=2.0)
    req = httpx.Request("GET", "https://example.com/api")
    body = (
        b"<!-- cf challenge -->\n"
        b"<html><head><title>Just a moment... CHALLENGE_SECRET_MARKER</title></head>\n"
        b"<body><div>Checking your browser</div></body></html>"
    )
    dummy = DummyClient([make_streamable_response(200, req, content=body)])
    monkeypatch.setattr("httpx.Client", lambda **kwargs: dummy)

    with pytest.raises(BooruNetworkError) as excinfo:
        client.get_json("https://example.com/api")
    msg = str(excinfo.value)
    assert "non-JSON page" in msg
    assert "bot protection" in msg
    assert "CHALLENGE_SECRET_MARKER" not in msg  # R6-04 no-echo policy held
    assert excinfo.value.retryable is False


def test_get_json_detects_cloudflare_challenge_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JS orchestration body that carries the challenges.cloudflare.com
    signature but none of the usual structural tags in its first 512 chars
    must still be classified as a non-JSON page (v1.1.0 live incident)."""
    client = HttpClient(timeout_seconds=2.0)
    req = httpx.Request("GET", "https://example.com/api")
    body = (
        b"<!-- js -->"
        b'<meta http-equiv="Content-Security-Policy" content="script-src https://challenges.cloudflare.com">'
        b"\n<script>var CHALLENGE_TOKEN='secret';a.src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1';</script>"
    )
    dummy = DummyClient([make_streamable_response(200, req, content=body)])
    monkeypatch.setattr("httpx.Client", lambda **kwargs: dummy)

    with pytest.raises(BooruNetworkError) as excinfo:
        client.get_json("https://example.com/api")
    msg = str(excinfo.value)
    assert "non-JSON page" in msg
    assert "secret" not in msg  # R6-04 no-echo policy held
    assert excinfo.value.retryable is False


# ---------------------------------------------------------------------------
# v1.1.0 live incident: Content-Encoding (gzip) bodies must be decoded
# ---------------------------------------------------------------------------


def test_get_json_decodes_gzip_content_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """safebooru.donmai.us served the API JSON gzip-compressed (Content-Encoding:
    gzip). The old iter_raw() read consumed the compressed bytes and produced a
    garbage 'not valid JSON' / 'Unexpected response' error. iter_bytes() must
    transparently decode the payload so get_json() parses it cleanly."""
    import gzip

    client = HttpClient(timeout_seconds=2.0)
    req = httpx.Request("GET", "https://example.com/api")
    plain = b'{"post": [{"id": 123, "tags": "1girl"}]}'
    dummy = DummyClient(
        [make_streamable_response(200, req, headers={"content-encoding": "gzip"}, content=gzip.compress(plain))]
    )
    monkeypatch.setattr("httpx.Client", lambda **kwargs: dummy)

    payload = client.get_json("https://example.com/api")
    assert payload == {"post": [{"id": 123, "tags": "1girl"}]}


def test_download_bytes_decodes_gzip_content_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compressed media bodies must come back fully decoded (v1.1.0)."""
    import gzip

    client = HttpClient(timeout_seconds=2.0)
    req = httpx.Request("GET", "https://example.com/image.png")
    plain = b"\x89PNG_GZIPPED_BODY"
    dummy = DummyClient(
        [
            make_streamable_response(
                200,
                req,
                headers={"content-type": "image/png", "content-encoding": "gzip"},
                content=gzip.compress(plain),
            )
        ]
    )
    monkeypatch.setattr("httpx.Client", lambda **kwargs: dummy)

    data, content_type = client.download_bytes("https://example.com/image.png")
    assert data == plain
    assert content_type == "image/png"


# ---------------------------------------------------------------------------
# R7-10: deterministic art-platforms post IDs
# ---------------------------------------------------------------------------


def test_deviantart_search_ids_are_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    from hades_booru.adapters import artplatforms as ap

    rss = (
        "<rss><channel><item>"
        "<title>Miku Miku Adventure</title>"
        "<link>https://www.deviantart.com/user1/deviation123</link>"
        '<media:thumbnail url="https://th.deviantart.com/thumb1.jpg" width="120"/>'
        '<media:content url="https://deviantart.com/orig1.jpg" width="1024"/>'
        "<media:credit role=\"author\">Artist Name</media:credit>"
        "<media:category>Characters/Hatsune Miku</media:category>"
        "</item></channel></rss>"
    )
    monkeypatch.setattr(ap, "http_client", SimpleNamespace(get_text=lambda url, params=None: rss))
    adapter = ArtPlatformsAdapter("deviantart", "DeviantArt (RSS)", "deviantart.com")

    first = adapter.search("miku", limit=5)
    second = adapter.search("miku", limit=5)
    assert len(first) == 1
    assert first[0].id == second[0].id
    expected = "da_" + hashlib.sha1(b"https://www.deviantart.com/user1/deviation123").hexdigest()[:16]
    assert first[0].id == expected
    assert first[0].tags.artist == ["artist_name"]
    assert "miku" in first[0].tags.general


def test_artstation_search_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    from hades_booru.adapters import artplatforms as ap

    payload = {
        "data": [
            {
                "id": 42,
                "title": "Neon City Dreams",
                "smaller_square_cover_url": "https://cdn.artstation.com/crops/123/4096px/4096_square.jpg",
                "user": {"username": "neo_artist"},
                "url": "https://www.artstation.com/artwork/42",
            }
        ]
    }
    monkeypatch.setattr(ap, "http_client", SimpleNamespace(get_json=lambda url, params=None: payload))
    adapter = ArtPlatformsAdapter("artstation", "ArtStation", "artstation.com")
    posts = adapter.search("neon city", limit=5)
    assert len(posts) == 1
    assert posts[0].id == "as_42"
    assert posts[0].tags.artist == ["neo_artist"]
    assert "neon" in posts[0].tags.general


def test_pawoo_search_mapping_and_multi_tag_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    from hades_booru.adapters import artplatforms as ap

    payload = [
        {
            "id": "st1",
            "media_attachments": [
                {
                    "preview_url": "https://pawoo.net/media/p.jpg",
                    "url": "https://pawoo.net/media/f.jpg",
                    "meta": {"original": {"width": 800, "height": 600}},
                }
            ],
            "tags": [{"name": "miku"}],
            "account": {"username": "singer"},
        }
    ]
    monkeypatch.setattr(ap, "http_client", SimpleNamespace(get_json=lambda url, params=None: payload))
    adapter = ArtPlatformsAdapter("pawoo", "Pawoo (Mastodon)", "pawoo.net")
    posts = adapter.search("#miku #other", limit=5)
    assert len(posts) == 1
    assert posts[0].id == "pawoo_st1"
    assert adapter.last_warning is not None  # single-hashtag limitation surfaced


def test_generic_adapter_refuses_tag_search_and_scrapes_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hades_booru.adapters import artplatforms as ap

    adapter = ArtPlatformsAdapter("generic", "Generic (OpenGraph)", "booru.io")
    with pytest.raises(BooruNetworkError):
        adapter.search("miku")

    html = (
        "<html><head>"
        "<title>Hidden Gem</title>"
        '<meta property="og:image" content="/img/art.jpg">'
        '<meta name="keywords" content="fantasy, sword">'
        '<meta property="og:description" content="A dark fantasy sword piece">'
        "</head><body>nsfw art</body></html>"
    )
    monkeypatch.setattr(ap, "http_client", SimpleNamespace(get_text=lambda url: html))
    url = "https://booru.io/gallery/123"
    p1 = adapter.fetch_single_by_url(url)
    p2 = adapter.fetch_single_by_url(url)
    assert p1.id == p2.id
    expected = "scraped_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    assert p1.id == expected
    assert p1.preview_url == "https://booru.io/img/art.jpg"  # relative og:image resolved
    assert p1.rating == "e"  # 'nsfw' detected in the page
    assert "fantasy" in p1.tags.general


# ---------------------------------------------------------------------------
# R7-11: separator-aware tag counters
# ---------------------------------------------------------------------------


def test_nav_badge_counts_tags_with_custom_separator() -> None:
    out = render_inspector_nav_badge_html(0, 3, "tagA ; tagB ; tagC", lang="en", separator="; ")
    assert "3 TAGS" in out


def test_export_stats_counts_unique_tags_with_custom_separator() -> None:
    out = render_export_stats_html(
        [],
        "tagA ; tagB\ntagB ; tagC",
        "dataset",
        lang="en",
        separator="; ",
    )
    assert "3 tags" in out


def test_on_copy_prompt_feedback_uses_custom_separator() -> None:
    from hades_booru.ui import handlers as handlers_module
    from hades_booru.ui.state import PersonalListStore

    handlers = handlers_module.create_ui_handlers(PersonalListStore(share_mode=True), lambda *a, **k: (None,))
    out_custom = handlers["on_copy_prompt_feedback"]("a ; b ; c", "en", "; ")
    out_default = handlers["on_copy_prompt_feedback"]("a ; b ; c", "en", ", ")
    assert "3 tags" in out_custom
    assert "1 tags" in out_default or "1 tag" in out_default


# ---------------------------------------------------------------------------
# R7-09: AVIF gate + atomic gallery writes
# ---------------------------------------------------------------------------


def test_looks_like_image_accepts_avif_and_rejects_heic() -> None:
    avif = b"\x00\x00\x00\x20ftypavif\x00\x00\x00\x00\x01\x02\x03\x04"
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00"
    assert looks_like_image(avif)
    assert not looks_like_image(heic)


def test_gallery_cache_writes_avif_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hades_booru.models import CategorizedTags, Post

    cache_dir = tmp_path / "gallery"
    cache = DiskImageCache(cache_dir=cache_dir, max_files=100)
    post = Post(
        id="777",
        source_id="danbooru",
        source_name="Danbooru",
        source_url="https://danbooru.donmai.us/posts/777",
        preview_url="https://cdn.donmai.us/preview/777.avif",
        sample_url="https://cdn.donmai.us/sample/777.avif",
        file_url="https://cdn.donmai.us/original/777.avif",
        tags=CategorizedTags(general=["1girl"]),
    )
    avif_bytes = b"\x00\x00\x00\x20ftypavif\x00\x00\x00\x00\x01\x02\x03\x04\x05"
    monkeypatch.setattr(
        "hades_booru.image_cache.http_client.download_bytes",
        lambda url: (avif_bytes, "image/avif"),
    )
    path, _caption = cache.resolve_post_image(post, "high")
    assert path.endswith(".avif")
    assert Path(path).read_bytes() == avif_bytes
    assert not list(cache_dir.glob("*.part"))  # temp file replaced, not left behind


# ---------------------------------------------------------------------------
# R7-14: live OS theme-change listener in "system" mode
# ---------------------------------------------------------------------------


def test_theme_apply_js_binds_live_os_scheme_listener() -> None:
    from hades_booru.ui.theme import THEME_APPLY_JS

    assert "matchMedia" in THEME_APPLY_JS
    assert "addEventListener('change'" in THEME_APPLY_JS
    assert "__hb_theme_mode" in THEME_APPLY_JS
    assert "__hb_theme_mql_bound" in THEME_APPLY_JS  # singleton binding guard


def test_gelbooru_adapter_is_a_booru_adapter() -> None:
    """Sanity: adapter still satisfies the base contract after the R7 edits."""
    assert issubclass(GelbooruAdapter, BooruAdapter)
