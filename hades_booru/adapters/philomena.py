"""
Philomena Engine Adapter (Derpibooru).
Supports derpibooru.org (/api/v1/json/search/images).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from hades_booru.adapters.base import BooruAdapter, ProgressCallback, host_matches
from hades_booru.http_client import BooruNetworkError, http_client
from hades_booru.models import CategorizedTags, Post, Rating


class PhilomenaAdapter(BooruAdapter):
    """Adapter for Philomena-based image boards (Derpibooru)."""

    def __init__(
        self,
        adapter_id: str = "derpibooru",
        name: str = "Derpibooru (Philomena)",
        domain: str = "derpibooru.org",
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

        reps_val = raw.get("representations")
        reps: dict[str, Any] = reps_val if isinstance(reps_val, dict) else {}
        view_url = str(raw.get("view_url") or "")
        file_url = str(reps.get("full") or view_url)
        sample_url = str(reps.get("large") or reps.get("medium") or file_url)
        medium_url = str(reps.get("medium") or reps.get("small") or sample_url)
        preview_url = str(reps.get("thumb") or reps.get("small") or medium_url)

        if not preview_url and not file_url:
            return None

        raw_tags_val = raw.get("tags")
        raw_tags_list: list[Any] = raw_tags_val if isinstance(raw_tags_val, list) else []
        artist: list[str] = []
        character: list[str] = []
        general: list[str] = []
        meta: list[str] = []
        rating: Rating = "g"

        for tag_obj in raw_tags_list:
            tag_str = str(tag_obj).strip()
            if not tag_str:
                continue
            normalized = tag_str.replace(" ", "_")
            lower = tag_str.lower()
            if lower in ("safe",):
                rating = "g"
                meta.append(normalized)
            elif lower in ("suggestive",):
                rating = "s"
                meta.append(normalized)
            elif lower in ("questionable",):
                rating = "q"
                meta.append(normalized)
            elif lower in ("explicit", "grimdark"):
                rating = "e"
                meta.append(normalized)
            elif lower.startswith("artist:"):
                artist.append(normalized.split(":", 1)[1])
            elif lower.startswith("oc:"):
                character.append(normalized)
            else:
                general.append(normalized)

        all_raw = [*character, *artist, *general, *meta]

        return Post(
            id=str(post_id),
            source_id=self.id,
            source_name=self.name,
            source_url=f"https://{self.default_domain}/images/{post_id}",
            preview_url=preview_url,
            medium_url=medium_url,
            sample_url=sample_url,
            file_url=file_url,
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            rating=rating,
            tags=CategorizedTags(
                character=character,
                artist=artist,
                general=general,
                meta=meta,
            ),
            raw_tags=all_raw,
            created_at=str(raw.get("created_at") or "") or None,
            score=self._safe_int(raw.get("score")),
        )

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def search(
        self,
        tags: str,
        limit: int = 20,
        progress_cb: ProgressCallback | None = None,
        rating: str | None = None,  # Philomena has no stable rating query param; UI filters client-side.
    ) -> list[Post]:
        # Philomena queries use comma-separated tags; convert space-separated tags if no commas are present
        stripped = tags.strip()
        if not stripped:
            query_str = "*"
        elif "," in stripped:
            query_str = stripped
        else:
            query_str = ", ".join(t.replace("_", " ") for t in stripped.split() if t)

        url = f"https://{self.default_domain}/api/v1/json/search/images"

        def _fetch_page(page: int, page_size: int) -> Any:
            params: dict[str, Any] = {
                "q": query_str,
                "per_page": page_size,
                "page": page,
            }
            data = http_client.get_json(url, params=params)
            return data.get("images") if isinstance(data, dict) else []

        return self.paginate(
            limit=limit,
            max_limit=500,
            max_page_size=50,
            page_delay=0.25,
            fetch_page=_fetch_page,
            map_item=self._map_post,
            progress_cb=progress_cb,
        )

    def fetch_single_by_url(self, url: str) -> Post:
        parsed = urlparse(url)
        match = re.search(r"/(?:images/)?(\d+)", parsed.path)
        if not match:
            raise BooruNetworkError(f"Could not extract image ID from {self.name} URL: {url}", url=url)

        post_id = match.group(1)
        api_url = f"https://{self.default_domain}/api/v1/json/images/{post_id}"
        data = http_client.get_json(api_url)
        raw_img = data.get("image") if isinstance(data, dict) else None
        if not isinstance(raw_img, dict):
            raise BooruNetworkError(f"Image #{post_id} not found on {self.name}.", url=api_url)

        post = self._map_post(raw_img)
        if not post:
            raise BooruNetworkError(f"Image #{post_id} has no accessible media on {self.name}.", url=api_url)
        return post
