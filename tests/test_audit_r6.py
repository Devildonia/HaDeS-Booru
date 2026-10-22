"""
Regression tests for the v1.0.7 (audit R6) security hardening.

Covers the verified findings fixed in this release:
R6-01 host-matching credential leak, R6-03 lying-extension rejection,
R6-04 SSRF guard (+ env override), R6-05 history credential scrub,
R6-06 cache-poisoning guard, R6-07 concurrent config save merge,
R6-09 rating flag reset on direct post, R6-10 href allowlist,
R6-11 stale zip-error reset, R6-19 launcher CWD pin, R6-22 filename
collision handling, R6-23 magic-first extension, R6-26 schema version.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hades_booru.adapters.base import host_matches
from hades_booru.adapters.danbooru import DanbooruAdapter
from hades_booru.adapters.registry import registry
from hades_booru.config import ConfigManager
from hades_booru.exporter import BulkExporter, guess_media_extension
from hades_booru.http_client import BooruNetworkError, assert_public_host
from hades_booru.image_cache import DiskImageCache
from hades_booru.metadata_extractor import MetadataExtractionError, extract_image_metadata
from hades_booru.models import AppConfig, CategorizedTags, Post
from hades_booru.normalizer import PromptNormalizer
from hades_booru.ui import layout as layout_module
from hades_booru.ui.components import render_post_inspector_html

REPO_ROOT = Path(__file__).resolve().parent.parent

MALICIOUS_URLS = [
    "https://danbooru.donmai.us.evil.example/posts/123",
    "https://evil.example/posts/123?ref=danbooru.donmai.us",
    "https://evil.example/posts/123#danbooru.donmai.us",
]


def _make_post(source_url: str = "https://danbooru.donmai.us/posts/123") -> Post:
    return Post(
        id="123",
        source_id="danbooru",
        source_name="Danbooru",
        source_url=source_url,
        file_url="https://cdn.example/123.jpg",
        sample_url="https://cdn.example/123.jpg",
        preview_url="https://cdn.example/123.jpg",
        rating="g",
        tags=CategorizedTags(general=["1girl"]),
        raw_tags=["1girl"],
    )


# --- R6-01: exact host matching, no credential leak to lookalike domains ----


def test_r601_host_matches_exact_and_subdomain_only() -> None:
    assert host_matches("https://danbooru.donmai.us/posts/1", "danbooru.donmai.us")
    assert host_matches("https://cdn.donmai.us/x", "donmai.us")
    assert not host_matches("https://danbooru.donmai.us.evil.example/x", "danbooru.donmai.us")
    assert not host_matches("https://evil.example/?ref=danbooru.donmai.us", "danbooru.donmai.us")
    assert not host_matches("not a url", "danbooru.donmai.us")


def test_r601_no_adapter_claims_lookalike_urls() -> None:
    for url in MALICIOUS_URLS:
        claiming = [adapter for adapter in registry._adapters.values() if adapter.can_handle_url(url)]
        assert claiming == []


def test_r601_danbooru_fetch_pins_its_own_board(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_get_json(url: str, **kwargs):
        seen["url"] = url
        return {
            "id": 123,
            "preview_file_url": "https://cdn.example/123.jpg",
            "tag_string": "1girl",
        }

    monkeypatch.setattr("hades_booru.adapters.danbooru.http_client.get_json", fake_get_json)
    adapter = DanbooruAdapter("danbooru", "Danbooru", "danbooru.donmai.us")
    post = adapter.fetch_single_by_url("https://danbooru.donmai.us.evil.example/posts/123")
    assert post.id == "123"
    # Credentials must be sent to the real board, never to the pasted hostname.
    assert seen["url"].startswith("https://danbooru.donmai.us/posts/123.json")


# --- R6-03: lying extensions must not engage foreign decoders ----------------


def test_r603_gif_named_png_is_rejected(tmp_path: Path) -> None:
    lying = tmp_path / "fake.png"
    lying.write_bytes(b"GIF89a" + b"\x01\x00\x01\x00\x80\x00\x00" + b";")
    with pytest.raises(MetadataExtractionError):
        extract_image_metadata(str(lying))


# --- R6-04: SSRF guard for private/loopback targets --------------------------


def test_r604_loopback_requests_blocked_by_default() -> None:
    with pytest.raises(BooruNetworkError):
        assert_public_host("http://127.0.0.1:5000/admin")


def test_r604_private_hosts_allowed_with_env_override(monkeypatch) -> None:
    monkeypatch.setenv("HADES_ALLOW_PRIVATE_HOSTS", "1")
    assert_public_host("http://127.0.0.1:5000/admin")  # must not raise


# --- R6-05: persisted history must never carry credentials -------------------


def test_r605_scrub_strips_secrets_and_keeps_safe_params() -> None:
    scrubbed = layout_module._scrub_url_credentials(
        "https://user:pass@gelbooru.com/index.php?page=dapi&api_key=sekret&json=1"
    )
    assert "user:pass@" not in scrubbed
    assert "api_key" not in scrubbed
    assert "page=dapi" in scrubbed
    assert "json=1" in scrubbed

    assert layout_module._scrub_url_credentials("1girl solo") == "1girl solo"


# --- R6-06: HTML served as an image must never poison the gallery cache ------


def test_r606_poisoned_cache_entry_is_rejected_and_deleted(tmp_path: Path) -> None:
    cache = DiskImageCache(cache_dir=tmp_path / "gallery_cache")
    key = "danbooru_1_high_abc123def0"
    poisoned = cache._dir / f"{key}.jpg"
    poisoned.write_bytes(b"<!DOCTYPE html><html><body>error</body></html>")

    assert cache._find_existing(key) is None
    assert not poisoned.exists()


def test_r606_html_downloaded_as_image_yields_placeholder(tmp_path: Path, monkeypatch) -> None:
    import hades_booru.image_cache as image_cache_module

    def fake_download(url: str, retries: int = 2):
        return (b"<!DOCTYPE html><html>blocked</html>", "text/html")

    monkeypatch.setattr(image_cache_module.http_client, "download_bytes", fake_download)
    cache = DiskImageCache(cache_dir=tmp_path / "gallery_cache")

    path, _caption = cache.resolve_post_image(_make_post(), "high")
    resolved = Path(path)
    assert resolved.exists()
    assert resolved.name.endswith("_card.png")
    assert resolved.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# --- R6-07: two running instances must not clobber each other's config -------


def test_r607_two_instances_do_not_clobber_each_other(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.local.json"

    first = ConfigManager(config_path=cfg_path)
    first.config.search_history = ["1girl solo"]
    assert first.save()

    second = ConfigManager(config_path=cfg_path)
    assert second.config.search_history == ["1girl solo"]
    second.config.language = "es"
    assert second.save()

    fresh = ConfigManager(config_path=cfg_path)
    assert fresh.config.search_history == ["1girl solo"]
    assert fresh.config.language == "es"


# --- R6-09: pasted single post must always pass the client-side filter -------


def test_r609_direct_post_branch_resets_rating_flag_before_fetch() -> None:
    src = (REPO_ROOT / "hades_booru" / "ui" / "layout.py").read_text(encoding="utf-8")
    branch = src.split("if detected.is_direct_post:", 1)[1]
    reset_idx = branch.find("server_rating_applied = False")
    fetch_idx = branch.find("fetch_single_by_url")
    assert reset_idx != -1 and fetch_idx != -1
    assert reset_idx < fetch_idx


# --- R6-10: non-http(s) source URLs must never become clickable --------------


def test_r610_javascript_source_url_is_not_clickable() -> None:
    evil = _make_post(source_url="javascript:alert(1)")
    html_out = render_post_inspector_html(evil, PromptNormalizer(), lang="en")
    assert 'href="javascript:' not in html_out
    assert 'href="#"' in html_out


# --- R6-11: a text-mode export must not inherit stale zip errors -------------


def test_r611_txt_export_resets_stale_zip_errors(tmp_path: Path) -> None:
    exporter = BulkExporter()
    exporter.last_zip_errors = ["stale_failure_from_previous_export"]
    exporter.create_export_file(
        posts=[_make_post()],
        mode="unified",
        normalizer=PromptNormalizer(),
        output_dir=tmp_path,
    )
    assert exporter.last_zip_errors == []


# --- R6-19: the launcher must pin its own directory --------------------------


def test_r619_start_bat_pins_its_own_directory() -> None:
    bat = (REPO_ROOT / "start.bat").read_text(encoding="utf-8")
    assert 'cd /d "%~dp0"' in bat


# --- R6-22: export filenames include the time and never overwrite ------------


def test_r622_export_filename_includes_time() -> None:
    exporter = BulkExporter()
    name = exporter.generate_filename("Danbooru", "1girl", "unified")
    assert re.search(r"_20\d{2}-\d{2}-\d{2}_\d{4}\.txt$", name)


def test_r622_second_export_same_day_gets_numeric_suffix(tmp_path: Path) -> None:
    exporter = BulkExporter()
    kwargs = dict(
        posts=[_make_post()],
        mode="unified",
        normalizer=PromptNormalizer(),
        output_dir=tmp_path,
    )
    first = exporter.create_export_file(**kwargs)
    second = exporter.create_export_file(**kwargs)
    assert first != second
    assert second.name == first.name[: -len(".txt")] + "_2.txt"
    assert first.read_text(encoding="utf-8")  # first export untouched


# --- R6-23: magic bytes are ground truth over URL and Content-Type -----------


def test_r623_magic_bytes_win_over_url_and_content_type() -> None:
    webp_bytes = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16
    assert (
        guess_media_extension("https://cdn.example/pic.jpg", "image/jpeg", webp_bytes)
        == ".webp"
    )
    assert (
        guess_media_extension("https://cdn.example/pic", "application/octet-stream", webp_bytes)
        == ".webp"
    )


# --- R6-26: the config schema is versioned -----------------------------------


def test_r626_config_declares_schema_version() -> None:
    assert AppConfig().schema_version == 1
