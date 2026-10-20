"""
Regression tests for audit R5 (v1.0.6 follow-up): Y1, Y2, Y3, Y4, Y5.
"""

from __future__ import annotations

import socket
import threading

import pytest

from app import find_free_port
from hades_booru import config as config_module
from hades_booru.adapters.danbooru import DanbooruAdapter
from hades_booru.http_client import BooruNetworkError
from hades_booru.metadata_extractor import _extract_comfyui_prompt
from hades_booru.ui.layout import _scrub_url_credentials, record_search_history


def _post(post_id: int, rating: str) -> dict:
    return {
        "id": post_id,
        "rating": rating,
        "preview_file_url": f"https://cdn.example/{post_id}.jpg",
        "file_url": f"https://cdn.example/{post_id}.png",
        "tag_string": "1girl solo",
        "tag_string_copyright": "",
        "tag_string_character": "",
        "tag_string_artist": "",
        "tag_string_general": "1girl solo",
        "tag_string_meta": "",
    }


class TestY1Danbooru422Fallback:
    """Y1: after the 422 rating-tag fallback the server did NOT filter by rating,
    so server_rating_applied must be False and the UI's client-side filter re-arms."""

    def test_422_fallback_resets_server_rating_applied(self, monkeypatch) -> None:
        adapter = DanbooruAdapter()
        calls = {"n": 0}

        def fake_get_json(url: str, params: dict | None = None, auth: tuple | None = None):
            calls["n"] += 1
            tags = (params or {}).get("tags", "")
            if calls["n"] == 1:
                assert "rating:" in tags  # first attempt carries the server-side rating tag
                raise BooruNetworkError("unprocessable", status_code=422, url=url)
            assert "rating:" not in tags  # fallback must NOT carry the rating tag
            return [_post(1, "g"), _post(2, "e"), _post(3, "q")]

        monkeypatch.setattr("hades_booru.adapters.danbooru.http_client.get_json", fake_get_json)
        posts = adapter.search("1girl", limit=20, rating="g")

        assert calls["n"] == 2
        assert len(posts) == 3  # partial results kept
        assert adapter.server_rating_applied is False  # Y1: client filter must re-arm
        # UI-side safety net: with rating "g" selected, only "g" posts survive.
        kept = [p for p in posts if p.rating == "g"]
        assert len(kept) == 1

    def test_clean_search_keeps_server_rating_applied(self, monkeypatch) -> None:
        adapter = DanbooruAdapter()

        def fake_get_json(url: str, params: dict | None = None, auth: tuple | None = None):
            return [_post(1, "g")]

        monkeypatch.setattr("hades_booru.adapters.danbooru.http_client.get_json", fake_get_json)
        adapter.search("1girl", limit=10, rating="g")
        assert adapter.server_rating_applied is True


class TestY2ServerRatingAppliedThreadLocal:
    """Y2: the flag is per-thread; concurrent searches must not leak it across threads."""

    def test_flag_is_thread_local(self) -> None:
        adapter = DanbooruAdapter()
        adapter.server_rating_applied = False  # known starting state

        def worker(value: bool, seen: list, barrier: threading.Barrier) -> None:
            barrier.wait()
            adapter.server_rating_applied = value
            seen.append(adapter.server_rating_applied)

        barrier = threading.Barrier(3)
        main_seen: list = []
        t_a = threading.Thread(target=worker, args=(True, main_seen, barrier))
        t_b = threading.Thread(target=worker, args=(False, main_seen, barrier))
        t_a.start()
        t_b.start()
        barrier.wait()
        t_a.join()
        t_b.join()

        # Each thread saw exactly the value it set, regardless of the other thread.
        assert sorted(main_seen) == [False, True]
        # The main thread never inherited either thread's value.
        assert adapter.server_rating_applied is False


class TestY3ComfyUIOrphans:
    """Y3: orphaned (unlinked) ComfyUI text nodes are dead nodes and must NOT be
    mixed into the negative prompt when the sampler links are resolved."""

    def test_orphan_text_not_mixed_into_negative(self) -> None:
        graph = (
            '{"1": {"class": "CLIPTextEncode", "inputs": {"text": "1girl, solo"}},'
            ' "2": {"class": "CLIPTextEncode", "inputs": {"text": "lowres, bad hands"}},'
            ' "3": {"class": "CLIPTextEncode", "inputs": {"text": "1girl, smile"}},'
            ' "4": {"class": "KSampler", "inputs": {'
            '   "positive": ["1", 0], "negative": ["2", 0]}}}'
        )
        result = _extract_comfyui_prompt(graph)
        assert result is not None
        positive, negative = result
        assert positive == "1girl, solo"
        assert negative == "lowres, bad hands"
        assert "smile" not in negative  # the Y3 regression

    def test_fallback_without_links_keeps_all_text(self) -> None:
        # No sampler links at all: order-based fallback must not lose any text.
        graph = (
            '{"1": {"class": "CLIPTextEncode", "inputs": {"text": "1girl"}},'
            ' "2": {"class": "CLIPTextEncode", "inputs": {"text": "lowres"}}}'
        )
        result = _extract_comfyui_prompt(graph)
        assert result == ("1girl", "lowres")


class TestY4PortProbe:
    """Y4: without SO_REUSEADDR the probe must report a listening port as busy."""

    def test_busy_port_is_skipped(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        busy_port = listener.getsockname()[1]
        try:
            chosen = find_free_port("127.0.0.1", busy_port, max_tries=5)
        finally:
            listener.close()
        assert chosen > busy_port  # the busy port was not (incorrectly) reported free


class TestY5HistoryCredentialScrub:
    """Y5: pasted URLs with embedded credentials are stored without them."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://user:pass@danbooru.donmai.us/posts?tags=x", "https://danbooru.donmai.us/posts?tags=x"),
            ("https://user@host.com/x", "https://host.com/x"),
            ("http://a:b@ex.org", "http://ex.org"),
            # Non-credential '@' (anchor / path) must stay untouched.
            ("https://host.com/path@anchor", "https://host.com/path@anchor"),
            ("1girl, solo", "1girl, solo"),
            ("https://danbooru.donmai.us/posts/123", "https://danbooru.donmai.us/posts/123"),
        ],
    )
    def test_scrub(self, raw: str, expected: str) -> None:
        assert _scrub_url_credentials(raw) == expected

    def test_record_search_history_stores_scrubbed_url(self, monkeypatch) -> None:
        monkeypatch.setattr(config_module.ConfigManager, "save", lambda self: True)
        cm = config_module.config_manager
        snapshot = cm.config.model_dump(mode="json")
        try:
            cm.config.search_history = []
            result = record_search_history("https://secret:key@rule34.us/index.php?page=post&s=view&id=9")
            assert result[0] == "https://rule34.us/index.php?page=post&s=view&id=9"
            assert not any("secret" in h or "key@" in h for h in cm.config.search_history)
        finally:
            cm.config = cm.config.__class__.model_validate(snapshot)
