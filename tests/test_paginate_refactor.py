"""
Unit and regression tests for BooruAdapter.paginate() (Audit R6-24).
Verifies deduplication, partial-page early exit, page-1 exception propagation,
page-2+ warning capture, progress callbacks, and adapter-specific parameters.
"""

from __future__ import annotations

from typing import Any

import pytest

from hades_booru.adapters.base import BooruAdapter
from hades_booru.models import Post


class _DummyAdapter(BooruAdapter):
    id = "dummy"
    name = "DummyBooru"
    default_domain = "dummy.example"

    def can_handle_url(self, url: str) -> bool:
        return False

    def search(self, tags: str, limit: int = 20, progress_cb=None, rating=None) -> list[Post]:
        return []

    def fetch_single_by_url(self, url: str) -> Post:
        raise NotImplementedError


def _make_item(post_id: int | str) -> dict[str, Any]:
    return {"id": str(post_id)}


def _map_dummy(raw: dict[str, Any]) -> Post | None:
    pid = raw.get("id")
    if not pid:
        return None
    return Post(
        id=str(pid),
        source_id="dummy",
        source_name="DummyBooru",
        source_url=f"https://dummy.example/posts/{pid}",
    )


def test_paginate_deduplicates_and_clamps_to_limit(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)
    adapter = _DummyAdapter()
    pages = {
        1: [_make_item(1), _make_item(2), _make_item(2)],
        2: [_make_item(2), _make_item(3), _make_item(4)],
    }
    progress_events: list[tuple[float, str]] = []

    posts = adapter.paginate(
        limit=3,
        max_limit=500,
        max_page_size=2,
        page_delay=0.1,
        fetch_page=lambda page, _size: pages.get(page, []),
        map_item=_map_dummy,
        progress_cb=lambda p, msg: progress_events.append((p, msg)),
    )

    assert [p.id for p in posts] == ["1", "2", "3"]
    assert adapter.last_warning is None
    assert progress_events[-1][0] == 1.0


def test_paginate_raises_on_first_page_failure() -> None:
    adapter = _DummyAdapter()

    def _fail_immediately(_page: int, _size: int):
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError, match="network down"):
        adapter.paginate(
            limit=10,
            max_limit=100,
            max_page_size=5,
            page_delay=0.0,
            fetch_page=_fail_immediately,
            map_item=_map_dummy,
        )
    assert adapter.last_warning is None


def test_paginate_keeps_partial_results_and_sets_warning_on_later_page() -> None:
    adapter = _DummyAdapter()

    def _fetch(page: int, _size: int):
        if page == 1:
            return [_make_item(10), _make_item(11)]
        raise RuntimeError("page 2 timeout")

    posts = adapter.paginate(
        limit=4,
        max_limit=100,
        max_page_size=2,
        page_delay=0.0,
        fetch_page=_fetch,
        map_item=_map_dummy,
    )

    assert [p.id for p in posts] == ["10", "11"]
    assert adapter.last_warning is not None
    assert "page 2" in adapter.last_warning
    assert "page 2 timeout" in adapter.last_warning


def test_paginate_stops_early_when_batch_smaller_than_page_size() -> None:
    adapter = _DummyAdapter()
    called_pages: list[int] = []

    def _fetch(page: int, _size: int):
        called_pages.append(page)
        return [_make_item(1)]  # smaller than page_size=5

    posts = adapter.paginate(
        limit=10,
        max_limit=100,
        max_page_size=5,
        page_delay=0.0,
        fetch_page=_fetch,
        map_item=_map_dummy,
    )

    assert [p.id for p in posts] == ["1"]
    assert called_pages == [1]
