"""
Regression tests for the v1.0.0 audit fixes (M1, M2, M4, M5, L1, L2, L3, L5, L10, L12b).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import httpx

from hades_booru.adapters.artplatforms import ArtPlatformsAdapter
from hades_booru.adapters.danbooru import DanbooruAdapter
from hades_booru.adapters.moebooru import MoebooruAdapter
from hades_booru.config import ConfigManager
from hades_booru.exporter import BulkExporter
from hades_booru.http_client import HttpClient
from hades_booru.models import CategorizedTags, Post
from hades_booru.normalizer import PromptNormalizer, is_kaomoji_tag


def test_danbooru_credentials_bound_to_board_id(tmp_path: Path, monkeypatch) -> None:
    """M1: mirrors must not inherit the primary danbooru.donmai.us credentials."""
    mgr = ConfigManager(config_path=tmp_path / "config.local.json")
    mgr.set_credentials_many({"danbooru": ("user1", "key123")}, persist_to_disk=False)
    monkeypatch.setattr("hades_booru.adapters.danbooru.config_manager", mgr)

    primary = DanbooruAdapter()  # adapter_id == "danbooru"
    assert primary._get_auth() == ("user1", "key123")

    mirror = DanbooruAdapter("safebooru", "Safebooru", "safebooru.donmai.us")
    assert mirror._get_auth() is None


def test_danbooru_search_partial_results_warning(monkeypatch) -> None:
    """M2: a mid-pagination failure must keep partial results AND flag the warning."""
    adapter = DanbooruAdapter()
    page_one = [
        {"id": i, "preview_file_url": f"https://cdn.example/{i}.jpg", "tag_string": "solo"}
        for i in range(1, 201)
    ]
    calls = {"n": 0}

    def fake_get_json(url: str, params: dict | None = None, auth: tuple | None = None):
        calls["n"] += 1
        if calls["n"] == 1:
            return page_one
        raise RuntimeError("boom")

    monkeypatch.setattr("hades_booru.adapters.danbooru.http_client.get_json", fake_get_json)
    posts = adapter.search("solo", limit=250)

    assert len(posts) == 200
    assert adapter.last_warning is not None
    assert "page 2" in adapter.last_warning


def test_empty_credential_pair_preserves_existing(tmp_path: Path) -> None:
    """M5: saving the form with untouched (empty) fields must not wipe saved credentials."""
    mgr = ConfigManager(config_path=tmp_path / "config.local.json")
    mgr.set_credentials_many({"danbooru": ("alice", "k1")}, persist_to_disk=False)

    # User fills only the e621 pair and clicks Save.
    mgr.set_credentials_many(
        {"danbooru": ("", ""), "e621": ("bob", "k2")},
        persist_to_disk=False,
    )

    assert mgr.get_credentials("danbooru").user_id == "alice"
    assert mgr.get_credentials("danbooru").api_key == "k1"
    assert mgr.get_credentials("e621").user_id == "bob"
    assert mgr.get_credentials("e621").api_key == "k2"


def test_trainer_zip_writes_errors_manifest_and_sanitizes_names(tmp_path: Path, monkeypatch) -> None:
    """L1+L2: failed image packing must ship errors.txt and entries must be sanitized."""

    def fake_download(url: str, retries: int = 2):
        raise RuntimeError("offline")

    monkeypatch.setattr("hades_booru.exporter.http_client.download_bytes", fake_download)

    weird_id = "a/b c"
    posts = [
        Post(
            id=weird_id,
            source_id="danbooru",
            source_name="Danbooru",
            source_url="https://danbooru.donmai.us/posts/1",
            file_url="https://cdn.example/1.png",
            rating="g",
            tags=CategorizedTags(general=["solo"]),
            raw_tags=["solo"],
        ),
        Post(
            id="22",
            source_id="danbooru",
            source_name="Danbooru",
            source_url="https://danbooru.donmai.us/posts/22",
            file_url="https://cdn.example/22.png",
            rating="g",
            tags=CategorizedTags(general=["1girl"]),
            raw_tags=["1girl"],
        ),
    ]

    exporter = BulkExporter()
    out_path = exporter.create_export_file(
        posts=posts,
        mode="trainer-zip",
        normalizer=PromptNormalizer(),
        output_dir=tmp_path,
        include_images_in_zip=True,
    )

    assert exporter.last_zip_errors and len(exporter.last_zip_errors) == 2
    with zipfile.ZipFile(out_path) as zf:
        names = zf.namelist()
        assert "errors.txt" in names
        # Sanitized: no '/' or spaces in entry names
        assert "danbooru_a_b_c.txt" in names
        error_body = zf.read("errors.txt").decode("utf-8")
        assert "offline" in error_body and "danbooru_a_b_c" in error_body


def test_artplatform_unescape_and_urljoin(monkeypatch) -> None:
    """L5: OpenGraph values must be HTML-unescaped and relative URLs resolved."""

    def fake_get_text(url: str, **kwargs):
        assert url == "https://example.com/artwork/123"
        return (
            "<html><head>"
            '<meta property="og:image" content="/cdn/img/123.jpg">'
            '<meta property="og:title" content="A &amp; B &#8220;Art&#8221; (safe)">'
            "</head><body></body></html>"
        )

    monkeypatch.setattr("hades_booru.adapters.artplatforms.http_client.get_text", fake_get_text)
    post = ArtPlatformsAdapter().fetch_single_by_url("https://example.com/artwork/123")

    assert post.preview_url == "https://example.com/cdn/img/123.jpg"
    assert post.title == "A & B \u201cArt\u201d (safe)"


def test_moebooru_general_rating_maps_to_g() -> None:
    """L12b: moebooru 'g' (general) must map to G, not fall through to unrated."""
    adapter = MoebooruAdapter()
    raw = {
        "id": 123,
        "preview_url": "https://cdn.example/123.jpg",
        "tags": "1girl solo",
        "rating": "g",
    }
    post = adapter._map_post(raw)
    assert post is not None
    assert post.rating == "g"


def test_kaomoji_pattern_accepts_pipe() -> None:
    """L3: pipe characters must be allowed in kaomoji tokens."""
    assert is_kaomoji_tag("(|_|)")
    assert is_kaomoji_tag("(o|_o)")
    assert not is_kaomoji_tag("normal_tag")


def test_http_client_respects_retry_after(monkeypatch) -> None:
    """L10: a Retry-After header must dominate the backoff delay on 429."""
    client = HttpClient(timeout_seconds=1.0)
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    req = httpx.Request("GET", "https://example.com/x")
    responses = [
        httpx.Response(429, headers={"Retry-After": "7"}, request=req),
        httpx.Response(200, text="ok", request=req),
    ]
    call_count = 0

    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def get(self, url: str, **kwargs):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

    monkeypatch.setattr("httpx.Client", DummyClient)
    text = client.get_text("https://example.com/x", retries=1)

    assert text == "ok"
    assert call_count == 2
    assert sleeps[0] >= 7.0


def test_gradio_pin_is_six_major() -> None:
    """M4: the Gradio major pin must be >=6.0,<7 in both dependency manifests."""
    req_txt = Path("requirements.txt").read_text(encoding="utf-8")
    assert "gradio>=6.0,<7" in req_txt

    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"gradio>=6.0,<7"' in pyproject
