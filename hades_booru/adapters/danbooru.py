"""
Danbooru & Donmai Family Adapter.
Supports danbooru.donmai.us, safebooru.donmai.us, hijiribe.donmai.us, sonohara.donmai.us,
aibooru.online, and booru.allthefallen.moe.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any
from urllib.parse import urlparse

from hades_booru.adapters.base import BooruAdapter, ProgressCallback
from hades_booru.config import config_manager
from hades_booru.http_client import BooruNetworkError, http_client
from hades_booru.models import CategorizedTags, Post, Rating

POST_ID_RE = re.compile(r"/posts/(\d+)", re.IGNORECASE)

# Danbooru v2 exposes rating as a tag (e.g. `rating:safe`). "u" (unrated) has no
# server-side equivalent and falls back to the UI client-side filter.
SERVER_RATING_TAGS: dict[str, str] = {
    "g": "rating:safe",
    "s": "rating:sensitive",
    "q": "rating:questionable",
    "e": "rating:explicit",
}


def _normalize_rating(raw: str | None) -> Rating:
    if not raw:
        return "u"
    lower = raw.lower()
    if lower in ("g", "s", "q", "e"):
        return lower  # type: ignore[return-value]
    return "u"


def _split_tags(tag_str: str | None) -> list[str]:
    if not tag_str or not tag_str.strip():
        return []
    return [t for t in tag_str.strip().split() if t]


def _extract_variant_urls(raw: dict[str, Any]) -> dict[str, str]:
    """Extracts resolution variants from Danbooru v2 media_asset.variants if present."""
    variants_map: dict[str, str] = {}
    media_asset = raw.get("media_asset")
    if isinstance(media_asset, dict):
        variants = media_asset.get("variants")
        if isinstance(variants, list):
            for v in variants:
                if isinstance(v, dict):
                    v_type = str(v.get("type") or "")
                    v_url = str(v.get("url") or "")
                    if v_type and v_url:
                        variants_map[v_type] = v_url
    return variants_map


class DanbooruAdapter(BooruAdapter):
    """Adapter for Danbooru v2 JSON API (/posts.json)."""

    def __init__(
        self,
        adapter_id: str = "danbooru",
        name: str = "Danbooru",
        domain: str = "danbooru.donmai.us",
    ) -> None:
        self.id = adapter_id
        self.name = name
        self.default_domain = domain

    def can_handle_url(self, url: str) -> bool:
        lower = url.lower()
        if self.default_domain.lower() in lower:
            return True
        if self.id == "danbooru" and "testbooru.donmai.us" in lower:
            return True
        return False

    def _get_auth(self) -> tuple[str, str] | None:
        # Credentials are bound to the concrete board ID, so Danbooru-family mirrors
        # (safebooru, hijiribe, aibooru, ...) never inherit the danbooru.donmai.us key.
        creds = config_manager.get_credentials(self.id)
        if creds.user_id and creds.api_key:
            return (creds.user_id, creds.api_key)
        return None

    def _map_post(self, raw: dict[str, Any], domain: str) -> Post | None:
        post_id = raw.get("id")
        if not post_id:
            return None

        variants = _extract_variant_urls(raw)

        file_url = (
            str(raw.get("file_url") or "")
            or variants.get("original", "")
            or str(raw.get("large_file_url") or "")
            or variants.get("sample", "")
        )
        sample_url = (
            str(raw.get("large_file_url") or "")
            or variants.get("sample", "")
            or variants.get("720x720", "")
            or file_url
        )
        medium_url = (
            variants.get("720x720", "")
            or variants.get("360x360", "")
            or sample_url
            or str(raw.get("preview_file_url") or "")
        )
        preview_url = (
            variants.get("360x360", "")
            or str(raw.get("preview_file_url") or "")
            or variants.get("180x180", "")
            or medium_url
            or sample_url
            or file_url
        )

        if not preview_url and not sample_url and not file_url:
            return None

        tags = CategorizedTags(
            copyright=_split_tags(raw.get("tag_string_copyright")),
            character=_split_tags(raw.get("tag_string_character")),
            artist=_split_tags(raw.get("tag_string_artist")),
            general=_split_tags(raw.get("tag_string_general")),
            meta=_split_tags(raw.get("tag_string_meta")),
        )

        return Post(
            id=str(post_id),
            source_id=self.id,
            source_name=self.name,
            source_url=f"https://{domain}/posts/{post_id}",
            preview_url=preview_url,
            medium_url=medium_url,
            sample_url=sample_url or file_url or preview_url,
            file_url=file_url or sample_url or preview_url,
            width=int(raw.get("image_width") or 0),
            height=int(raw.get("image_height") or 0),
            rating=_normalize_rating(raw.get("rating")),
            tags=tags,
            raw_tags=_split_tags(raw.get("tag_string")),
            created_at=raw.get("created_at"),
            score=raw.get("score"),
        )

    def search(
        self,
        tags: str,
        limit: int = 20,
        progress_cb: ProgressCallback | None = None,
        rating: str | None = None,
    ) -> list[Post]:
        target_count = max(1, min(limit, 500))
        page_size = min(200, target_count)
        total_pages = math.ceil(target_count / page_size)

        user_tokens = [t for t in tags.strip().split() if t]
        base_tags = " ".join(user_tokens)
        auth = self._get_auth()
        rating_tag = SERVER_RATING_TAGS.get(rating or "")

        # N6: danbooru.donmai.us enforces a strict 2-tag limit for anonymous queries (HTTP 422).
        # Only append the server-side rating metatag when the query has <= 1 user tag,
        # credentials are provided, or we are querying a mirror board.
        can_inject_rating = bool(
            rating_tag and (self.id != "danbooru" or auth is not None or len(user_tokens) <= 1)
        )
        clean_tags = f"{base_tags} {rating_tag}".strip() if can_inject_rating else base_tags
        self.server_rating_applied = can_inject_rating

        posts: list[Post] = []
        seen_ids: set[str] = set()
        self.last_warning = None

        for page in range(1, total_pages + 1):
            if progress_cb:
                progress_cb(
                    min(0.95, (page - 1) / max(1, total_pages)),
                    f"Querying {self.name} (Page {page}/{total_pages})...",
                )

            url = f"https://{self.default_domain}/posts.json"
            params: dict[str, Any] = {
                "limit": page_size,
                "page": page,
            }
            if clean_tags:
                params["tags"] = clean_tags

            try:
                try:
                    batch = http_client.get_json(url, params=params, auth=auth)
                except BooruNetworkError as net_err:
                    # Fallback if a member account or mirror rejects the extra rating tag with HTTP 422
                    if net_err.status_code == 422 and can_inject_rating and base_tags:
                        can_inject_rating = False
                        clean_tags = base_tags
                        params["tags"] = clean_tags
                        batch = http_client.get_json(url, params=params, auth=auth)
                    else:
                        raise
                if not isinstance(batch, list) or not batch:
                    break

                for item in batch:
                    if not isinstance(item, dict):
                        continue
                    mapped = self._map_post(item, self.default_domain)
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
        host = parsed.hostname or self.default_domain
        match = POST_ID_RE.search(parsed.path)
        if not match:
            raise BooruNetworkError(f"Could not extract post ID from Danbooru URL: {url}", url=url)

        post_id = match.group(1)
        api_url = f"https://{host}/posts/{post_id}.json"
        raw = http_client.get_json(api_url, auth=self._get_auth())
        if not isinstance(raw, dict):
            raise BooruNetworkError(f"Unexpected payload from {api_url}", url=api_url)

        post = self._map_post(raw, host)
        if not post:
            raise BooruNetworkError(f"Post #{post_id} has no accessible media files.", url=api_url)
        return post
