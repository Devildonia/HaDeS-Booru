"""
Moebooru Family Adapter.
Supports konachan.com, konachan.net, yande.re, sakugabooru.com, and lolibooru.moe (/post.json).
"""

from __future__ import annotations

import math
import re
import time
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
            score=int(raw.get("score")) if raw.get("score") is not None else None,
        )

    def search(
        self,
        tags: str,
        limit: int = 20,
        progress_cb: ProgressCallback | None = None,
        rating: str | None = None,
    ) -> list[Post]:
        target_count = max(1, min(limit, 500))
        page_size = min(100, target_count)
        total_pages = math.ceil(target_count / page_size)
        clean_tags = " ".join(tags.strip().split())
        rating_tag = SERVER_RATING_TAGS.get(rating or "")
        if rating_tag:
            clean_tags = f"{clean_tags} {rating_tag}".strip()
        self.server_rating_applied = bool(rating_tag)

        posts: list[Post] = []
        seen_ids: set[str] = set()
        self.last_warning = None

        for page in range(1, total_pages + 1):
            if progress_cb:
                progress_cb(
                    min(0.95, (page - 1) / max(1, total_pages)),
                    f"Querying {self.name} (Page {page}/{total_pages})...",
                )

            url = f"https://{self.default_domain}/post.json"
            params: dict[str, Any] = {
                "limit": page_size,
                "page": page,
            }
            if clean_tags:
                params["tags"] = clean_tags

            try:
                batch = http_client.get_json(url, params=params)
                if not isinstance(batch, list) or not batch:
                    break

                for item in batch:
                    if not isinstance(item, dict):
                        continue
                    mapped = self._map_post(item)
                    if mapped and mapped.id not in seen_ids:
                        seen_ids.add(mapped.id)
                        posts.append(mapped)
                        if len(posts) >= target_count:
                            break

                if len(batch) < page_size or len(posts) >= target_count:
                    break

                if page < total_pages:
                    time.sleep(0.18)

            except Exception as err:
                if posts:
                    # Surface the partial-result condition instead of failing silently.
                    self.last_warning = f"pagination stopped early on page {page}: {err}"
                    break
                raise

        if progress_cb:
            progress_cb(1.0, f"Loaded {len(posts)} posts from {self.name}.")

        return posts[:target_count]

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
