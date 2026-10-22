"""
Regression tests for the R7 audit fixes (R7-A .. R7-H).

Run with:  python -m pytest tests/test_audit_r7_round2.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import hades_booru.http_client as hc
from hades_booru.adapters.registry import registry
from hades_booru.config import ConfigManager
from hades_booru.http_client import BooruNetworkError, HttpClient
from hades_booru.image_cache import DiskImageCache
from hades_booru.tag_dictionary.importer import TagDictionaryImporter
from hades_booru.ui.theme import build_custom_css
from tests.http_mocks import DummyClient, make_streamable_response

# ---------------------------------------------------------------- R7-A: redirects

def _client_with(responses: list[httpx.Response], monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatches httpx.Client in the http_client module so get_text() serves queued responses."""
    monkeypatch.setattr(
        hc,
        "httpx",
        SimpleNamespace(
            Client=lambda **kw: DummyClient(responses),
            Timeout=lambda *a, **kw: object(),
            URL=httpx.URL,
            TimeoutException=httpx.TimeoutException,
        ),
    )


def test_redirect_to_private_host_is_blocked_not_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7-A core: a 302 to http://127.0.0.1 must be refused (old hook-based guard never fired)."""
    first = make_streamable_response(
        302,
        httpx.Request("GET", "https://redirect.example.com/api"),
        headers={"location": "http://127.0.0.1:8080/steal"},
    )
    _client_with([first], monkeypatch)

    with pytest.raises(BooruNetworkError) as excinfo:
        HttpClient().get_text("https://redirect.example.com/api", retries=0)
    assert excinfo.value.retryable is False
    assert "non-public" in str(excinfo.value).lower()


def test_redirect_to_public_host_is_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A legitimate 302 chain to a public host is followed and the body returned."""
    hop1 = make_streamable_response(
        302,
        httpx.Request("GET", "https://example.com/api"),
        headers={"location": "https://cdn.example.com/api"},
    )
    hop2 = make_streamable_response(200, httpx.Request("GET", "https://cdn.example.com/api"), text="OK")
    _client_with([hop1, hop2], monkeypatch)

    assert HttpClient().get_text("https://example.com/api", retries=0) == "OK"


def test_redirect_chain_exceeding_max_hops_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """More than MAX_REDIRECT_HOPS redirects raise a non-retryable error (no infinite loop)."""
    responses = [
        make_streamable_response(
            302,
            httpx.Request("GET", f"https://hop{i}.example.com/x"),
            headers={"location": f"https://hop{i + 1}.example.com/x"},
        )
        for i in range(hc.MAX_REDIRECT_HOPS + 2)
    ]
    _client_with(responses, monkeypatch)

    with pytest.raises(BooruNetworkError) as excinfo:
        HttpClient().get_text("https://hop0.example.com/x", retries=0)
    assert excinfo.value.retryable is False


# ------------------------------------------- R7-B: 3-way config merge (save)

def test_scalar_reversion_to_loaded_value_is_kept(tmp_path: Path) -> None:
    """R7-B case 1b: A changes language, reverts to its loaded value; B's new value survives."""
    cfg_file = tmp_path / "config.local.json"
    instance_a = ConfigManager(config_path=cfg_file)
    instance_a.config.language = "es"
    assert instance_a.save()

    instance_b = ConfigManager(config_path=cfg_file)
    instance_b.config.language = "fr"
    assert instance_b.save()

    # A reverts to the value it had at load ("en") — that reversion must now win,
    # not silently resurrect B's "fr".
    instance_a.config.language = "en"
    assert instance_a.save()

    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["language"] == "en"


def test_clearing_history_is_not_resurrected_by_other_instance(tmp_path: Path) -> None:
    """R7-B case 2b: this process cleared history; a later save by another process must keep it cleared."""
    cfg_file = tmp_path / "config.local.json"
    instance_a = ConfigManager(config_path=cfg_file)
    instance_a.config.search_history = ["a1", "a2"]
    assert instance_a.save()

    instance_b = ConfigManager(config_path=cfg_file)  # loads history [a1, a2]
    instance_b.config.search_history = []  # explicit clear
    assert instance_b.save()

    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["search_history"] == []


def test_removing_a_list_item_is_not_resurrected(tmp_path: Path) -> None:
    """R7-B case 3: removing an individual list item must not be undone by the old union logic."""
    cfg_file = tmp_path / "config.local.json"
    instance_a = ConfigManager(config_path=cfg_file)
    instance_a.config.search_history = ["keep", "drop", "other"]
    assert instance_a.save()

    instance_b = ConfigManager(config_path=cfg_file)
    instance_b.config.search_history = ["keep", "other"]  # removed "drop"
    assert instance_b.save()

    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert "drop" not in data["search_history"]


def test_session_only_mode_wipes_credentials_this_process_set(tmp_path: Path) -> None:
    """R7-B case 4b: switching to session-only must not leave this process's api_key on disk."""
    cfg_file = tmp_path / "config.local.json"
    instance = ConfigManager(config_path=cfg_file)
    instance.set_credentials_many({"danbooru": ("u", "k")}, persist_to_disk=True)

    instance.config.persist_credentials = False
    assert instance.save()

    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["credentials"]["danbooru"]["api_key"] == ""


# ---------------------------------------------- R7-E: CSS long-text clipping

def test_nav_badge_and_status_allow_wrapping() -> None:
    """R7-E: nav badges and status text must wrap instead of overflowing their container."""
    css = build_custom_css()
    assert "overflow-wrap: anywhere" in css
    assert ".hades-nav-badge" in css
    assert "white-space: normal" in css
    assert ".hades-status-text" in css


# --------------------------------------------- R7-G: byte-bounded cache prune

def test_cache_prunes_by_total_bytes_not_only_file_count(tmp_path: Path) -> None:
    """R7-G: with a tiny byte cap, prune_if_needed() removes oldest files until under the cap."""
    cache = DiskImageCache(cache_dir=tmp_path / "cache", max_files=1000, max_bytes=100)
    older = cache._dir / "older.jpg"  # noqa: SLF001
    newer = cache._dir / "newer.jpg"  # noqa: SLF001
    older.write_bytes(b"x" * 60)
    newer.write_bytes(b"x" * 60)
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))

    cache.prune_if_needed()

    assert not older.exists()
    assert newer.exists()


# ------------------------------------- R7-H: importer partial + checkpoints

class _FakeDictionaryService:
    def __init__(self) -> None:
        self.upsert_calls: list[list[dict]] = []

    def upsert_entries(self, entries: list[dict]) -> int:
        self.upsert_calls.append(list(entries))
        return len(entries)

    def all_tag_names(self) -> set[str]:
        return set()


def test_importer_continues_with_partial_catalog_when_tag_list_page_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7-H: a failed tag-list page must not discard the tags already collected."""
    fake_service = _FakeDictionaryService()
    importer = TagDictionaryImporter(service=fake_service)

    def fake_fetch_json(url: str, params: dict, auth: object) -> list:
        if str(params.get("page")) == "1":
            return [{"name": f"tag_{i}", "category": 0, "post_count": i} for i in range(3)]
        raise BooruNetworkError("tag list page failed")

    monkeypatch.setattr(importer, "_fetch_json", fake_fetch_json)

    written = importer.import_from_danbooru(top=100, page_size=3, skip_wiki=True, throttle=0)
    assert written == 3  # partial catalog persisted, not aborted
    assert fake_service.upsert_calls


def test_importer_checkpoints_every_fifty_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """R7-H: enrichment progress is upserted in 50-tag chunks (crash-safe)."""
    fake_service = _FakeDictionaryService()
    importer = TagDictionaryImporter(service=fake_service)

    def fake_fetch_json(url: str, params: dict, auth: object) -> list:
        if "tags.json" in url:
            return [{"name": f"tag_{i}", "category": 0, "post_count": i} for i in range(120)]
        return []  # wiki + aliases: empty is fine

    monkeypatch.setattr(importer, "_fetch_json", fake_fetch_json)

    written = importer.import_from_danbooru(top=120, page_size=200, skip_wiki=True, throttle=0)
    assert written == 120
    # Checkpoints at 50 and 100, plus the final upsert.
    assert len(fake_service.upsert_calls) == 3
    assert all(len(entries) == 120 for entries in fake_service.upsert_calls)


# ----------------------------- v1.1.1: source catalog metadata (Furbooru)


def test_furbooru_registered_with_capability_flags() -> None:
    """v1.1.1: Furbooru joins the Philomena family with explicit capability metadata."""
    specs = {s.id: s for s in registry.get_all_specs()}
    fur = specs["furbooru"]
    assert fur.api_family == "philomena"
    assert fur.auth_required is False
    assert fur.supports_tags is True
    assert fur.supports_rating_filter is False
    assert fur.status == "active"
    # Legacy sources keep working with the new optional fields.
    assert specs["danbooru"].api_family is None
    assert specs["danbooru"].status == "active"
    assert "furbooru" in [value for _, value in registry.get_dropdown_choices()]


# ---------------------------------------------- R7-C: CI ignore list parity

def test_ci_pillow_vuln_ignore_list_is_complete() -> None:
    """R7-C: every Pillow vuln pip-audit reports is in the CI ignore list (documented review)."""
    ci_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
    ci = ci_path.read_text(encoding="utf-8")
    # The 35 known Pillow 12.x CVEs/GHSAs must all be present as --ignore-vuln entries.
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "-r", "requirements.lock"],
        capture_output=True,
        text=True,
        cwd=str(ci_path.parent.parent),
    )
    if result.returncode == 0:
        return  # nothing to ignore
    missing: list[str] = []
    for line in (result.stdout + result.stderr).splitlines():
        for token in line.replace(",", " ").split():
            if token.upper().startswith(("CVE-", "GHSA-")) and f"--ignore-vuln {token}" not in ci:
                missing.append(token)
    assert not missing, f"Vulns missing from CI ignore list: {sorted(set(missing))}"
