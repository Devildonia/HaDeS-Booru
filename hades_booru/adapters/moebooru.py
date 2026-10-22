"""
Moebooru Family Adapter.
Supports konachan.com, konachan.net, yande.re, sakugabooru.com, and lolibooru.moe (/post.json).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from hades_booru.adapters.base import BooruAdapter, ProgressCallback, host_matches
from hades_booru.http_client import BooruNetworkError, http_client
from hades_booru.models import COMMON_META_TAGS, CategorizedTags, Post, Rating

# Moebooru filters ratings via `rating:safe`, `rating:questionable`, `rating:explicit` metatags inside `tags`.
SERVER_RATING_TAGS: dict[str, str] = {
    "g": "rating:safe",
    "s": "rating:safe",
    "q": "rating:questionable",
    "e": "rating:explicit",
}


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_rating(raw: str | None) -> Rating:
    if not raw:
        return "u"
    lower = raw.lower()
    if lower in ("g", "general", "s", "safe"):
        return "g"
    if lower in ("q", "questionable"):
        return "q"
    if lower in ("e", "explicit"):
        return "e"
    return "u"


class MoebooruAdapter(BooruAdapter):
    """Adapter for Moebooru-based boards (Konachan, Yande.re, Sakugabooru, Lolibooru)."""

    def __init__(
        self,
        adapter_id: str = "konachan",
        name: str = "Konachan",
        domain: str = "konachan.com",
    ) -> None:
        self.id = adapter_id
        self.name = name
        self.default_domain = domain

    def can_handle_url(self, url: str) -> bool:
        # Audit R6-01: exact-host matching (no substring).
        return host_matches(url, self.default_domain)

    def _map_post(self, raw: dict[str, Any]) -> Post | None:
        post_id = raw.get("id")
        if not post_id:
            return None

        tags_str = str(raw.get("tags") or "")
        raw_tags = [t for t in tags_str.strip().split() if t]

        general: list[str] = []
        meta: list[str] = []
        for tag in raw_tags:
            if tag.lower() in COMMON_META_TAGS:
                meta.append(tag)
            else:
                general.append(tag)

        preview_url = str(raw.get("preview_url") or raw.get("sample_url") or raw.get("file_url") or "")
        sample_url = str(raw.get("sample_url") or raw.get("jpeg_url") or raw.get("file_url") or preview_url)
        file_url = str(raw.get("file_url") or raw.get("jpeg_url") or sample_url)

        if not preview_url and not file_url:
            return None

        return Post(
            id=str(post_id),
            source_id=self.id,
            source_name=self.name,
            source_url=f"https://{self.default_domain}/post/show/{post_id}",
            preview_url=preview_url,
            medium_url=sample_url,
            sample_url=sample_url,
            file_url=file_url,
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            rating=_normalize_rating(str(raw.get("rating") or "")),
            tags=CategorizedTags(general=general, meta=meta),
            raw_tags=raw_tags,
            author=str(raw.get("author") or "") or None,
            score=_safe_int(raw.get("score")),
        )

    def search(
        self,
        tags: str,
        limit: int = 20,
        progress_cb: ProgressCallback | None = None,
        rating: str | None = None,
    ) -> list[Post]:
        clean_tags = " ".join(tags.strip().split())
        rating_tag = SERVER_RATING_TAGS.get(rating or "")
        if rating_tag:
            clean_tags = f"{clean_tags} {rating_tag}".strip()
        self.server_rating_applied = bool(rating_tag)
        url = f"https://{self.default_domain}/post.json"

        def _fetch_page(page: int, page_size: int) -> Any:
            params: dict[str, Any] = {"limit": page_size, "page": page}
            if clean_tags:
                params["tags"] = clean_tags
            return http_client.get_json(url, params=params)

        return self.paginate(
            limit=limit,
            max_limit=500,
            max_page_size=100,
            page_delay=0.18,
            fetch_page=_fetch_page,
            map_item=self._map_post,
            progress_cb=progress_cb,
        )

    def fetch_single_by_url(self, url: str) -> Post:
        parsed = urlparse(url)
        match = re.search(r"/post/show/(\d+)", parsed.path)
        if not match:
            raise BooruNetworkError(f"Could not extract post ID from {self.name} URL: {url}", url=url)

        post_id = match.group(1)
        api_url = f"https://{self.default_domain}/post.json"
        batch = http_client.get_json(api_url, params={"tags": f"id:{post_id}"})
        if not isinstance(batch, list) or not batch:
            raise BooruNetworkError(f"Post #{post_id} not found on {self.name}.", url=url)

        post = self._map_post(batch[0])
        if not post:
            raise BooruNetworkError(f"Post #{post_id} has no media URLs on {self.name}.", url=url)
        return post
