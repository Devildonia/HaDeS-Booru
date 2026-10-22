"""
E621 / E926 Adapter.
Supports e621.net and e926.net with mandatory User-Agent compliance and full taxonomic tag categorization.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from hades_booru.adapters.base import BooruAdapter, ProgressCallback, host_matches
from hades_booru.config import config_manager
from hades_booru.http_client import BooruNetworkError, http_client
from hades_booru.models import CategorizedTags, Post, Rating

# E621/E926 filter ratings via `rating:s`, `rating:q`, `rating:e` metatags inside `tags`.
SERVER_RATING_TAGS: dict[str, str] = {
    "g": "rating:s",
    "s": "rating:s",
    "q": "rating:q",
    "e": "rating:e",
}


def _normalize_rating(raw: str | None, adapter_id: str = "e621") -> Rating:
    if not raw:
        return "u"
    lower = raw.lower()
    if lower in ("g", "general"):
        return "g"
    if lower in ("s", "safe", "sensitive"):
        # E926 is strictly SFW ("s" means Safe/General there), whereas on E621 "s" maps to "s".
        return "g" if adapter_id == "e926" else "s"
    if lower in ("q", "questionable"):
        return "q"
    if lower in ("e", "explicit"):
        return "e"
    return "u"


class E621Adapter(BooruAdapter):
    """Adapter for E621/E926 JSON API (/posts.json)."""

    def __init__(
        self,
        adapter_id: str = "e621",
        name: str = "E621",
        domain: str = "e621.net",
    ) -> None:
        self.id = adapter_id
        self.name = name
        self.default_domain = domain

    def can_handle_url(self, url: str) -> bool:
        # Audit R6-01: exact-host matching (no substring).
        return host_matches(url, self.default_domain)

    def _get_auth(self) -> tuple[str, str] | None:
        creds = config_manager.get_credentials("e621")
        if creds.user_id and creds.api_key:
            return (creds.user_id, creds.api_key)
        return None

    def _map_post(self, raw: dict[str, Any]) -> Post | None:
        post_id = raw.get("id")
        if not post_id:
            return None

        file_obj = raw.get("file") or {}
        sample_obj = raw.get("sample") or {}
        preview_obj = raw.get("preview") or {}

        file_url = str(file_obj.get("url") or "")
        sample_url = str(sample_obj.get("url") or file_url)
        preview_url = str(preview_obj.get("url") or sample_url)

        if not preview_url and not file_url:
            return None

        tags_obj = raw.get("tags") or {}
        copyright_tags = list(tags_obj.get("copyright") or [])
        character_tags = list(tags_obj.get("character") or [])
        artist_tags = list(tags_obj.get("artist") or [])
        general_tags = [
            *(tags_obj.get("species") or []),
            *(tags_obj.get("general") or []),
            *(tags_obj.get("lore") or []),
        ]
        meta_tags = list(tags_obj.get("meta") or [])

        all_raw = [*copyright_tags, *character_tags, *artist_tags, *general_tags, *meta_tags]
        score_obj = raw.get("score") or {}

        return Post(
            id=str(post_id),
            source_id=self.id,
            source_name=self.name,
            source_url=f"https://{self.default_domain}/posts/{post_id}",
            preview_url=preview_url,
            medium_url=sample_url,
            sample_url=sample_url,
            file_url=file_url or sample_url,
            width=int(file_obj.get("width") or 0),
            height=int(file_obj.get("height") or 0),
            rating=_normalize_rating(raw.get("rating"), self.id),
            tags=CategorizedTags(
                copyright=copyright_tags,
                character=character_tags,
                artist=artist_tags,
                general=general_tags,
                meta=meta_tags,
            ),
            raw_tags=all_raw,
            created_at=raw.get("created_at"),
            score=score_obj.get("total") if isinstance(score_obj, dict) else None,
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
        auth = self._get_auth()
        url = f"https://{self.default_domain}/posts.json"

        def _fetch_page(page: int, page_size: int) -> Any:
            params: dict[str, Any] = {"limit": page_size, "page": page}
            if clean_tags:
                params["tags"] = clean_tags
            data = http_client.get_json(url, params=params, auth=auth)
            return data.get("posts") if isinstance(data, dict) else []

        return self.paginate(
            limit=limit,
            max_limit=500,
            max_page_size=100,
            page_delay=0.35,
            fetch_page=_fetch_page,
            map_item=self._map_post,
            progress_cb=progress_cb,
        )

    def fetch_single_by_url(self, url: str) -> Post:
        parsed = urlparse(url)
        match = re.search(r"/posts/(\d+)", parsed.path)
        if not match:
            raise BooruNetworkError(f"Could not extract post ID from {self.name} URL: {url}", url=url)

        post_id = match.group(1)
        api_url = f"https://{self.default_domain}/posts/{post_id}.json"
        data = http_client.get_json(api_url, auth=self._get_auth())
        raw_post = data.get("post") if isinstance(data, dict) else None
        if not isinstance(raw_post, dict):
            raise BooruNetworkError(f"Post #{post_id} not found on {self.name}.", url=api_url)

        post = self._map_post(raw_post)
        if not post:
            raise BooruNetworkError(f"Post #{post_id} has no media URL on {self.name}.", url=api_url)
        return post
