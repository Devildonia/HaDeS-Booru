"""
Unit Tests for ConfigManager (corrupt backup, atomic save, session-only credentials),
HttpClient retry resilience, and DiskImageCache.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from http_mocks import DummyClient, make_streamable_response

from hades_booru.config import ConfigManager
from hades_booru.demo_data import DEMO_POSTS
from hades_booru.http_client import HttpClient
from hades_booru.image_cache import DiskImageCache


def test_corrupt_config_creates_backup_and_preserves_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.local.json"
    cfg_file.write_text("{corrupt_json: true", encoding="utf-8")

    mgr = ConfigManager(config_path=cfg_file)
    assert mgr.config.language == "en"
    assert mgr.last_error is not None

    backups = list(tmp_path.glob("config.local.json.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{corrupt_json: true"


def test_config_session_only_credentials_not_written_to_disk(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.local.json"
    mgr = ConfigManager(config_path=cfg_file)

    mgr.set_credentials_many(
        {
            "danbooru": ("user1", "secret_key_123"),
            "e621": ("user2", "secret_key_456"),
        },
        persist_to_disk=False,
    )

    # Available in memory during session
    cred = mgr.get_credentials("danbooru")
    assert cred.user_id == "user1"
    assert cred.api_key == "secret_key_123"
    assert mgr.get_credentials("e621").user_id == "user2"

    # Stripped on disk
    disk_data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk_data["persist_credentials"] is False
    assert disk_data["credentials"]["danbooru"]["api_key"] == ""
    assert disk_data["credentials"]["e621"]["api_key"] == ""


def test_http_client_download_bytes_retries_on_500_and_429(monkeypatch) -> None:
    client = HttpClient(timeout_seconds=2.0)
    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    req = httpx.Request("GET", "https://example.com/image.png")
    responses = [
        make_streamable_response(429, req, headers={"Retry-After": "1"}),
        make_streamable_response(502, req),
        make_streamable_response(200, req, headers={"content-type": "image/png"}, content=b"\x89PNG_DATA"),
    ]
    dummy = DummyClient(responses)
    monkeypatch.setattr("httpx.Client", lambda **kwargs: dummy)
    data, content_type = client.download_bytes("https://example.com/image.png", retries=2)
    assert data == b"\x89PNG_DATA"
    assert content_type == "image/png"
    assert dummy.call_count == 3
    assert len(sleep_calls) == 2


def test_disk_image_cache_stores_prunes_and_falls_back_on_heic(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "gallery_cache"
    cache = DiskImageCache(cache_dir=cache_dir, max_files=1)

    items = cache.build_gallery_items(DEMO_POSTS[:2], "text")
    assert len(items) == 2
    for file_path, caption in items:
        assert Path(file_path).exists()
        assert caption.startswith("#")

    cache.prune_if_needed()
    remaining_files = list(cache_dir.iterdir())
    assert len(remaining_files) <= 1

    # Non-browser-safe format (HEIC) returns a valid PNG placeholder card instead of corrupt .jpg
    heic_bytes = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00"
    monkeypatch.setattr(
        "hades_booru.image_cache.http_client.download_bytes",
        lambda url: (heic_bytes, "image/heic"),
    )
    fallback_path, _ = cache.resolve_post_image(DEMO_POSTS[0], "high")
    assert fallback_path.endswith("_card.png")
    assert Path(fallback_path).read_bytes().startswith(b"\x89PNG")
