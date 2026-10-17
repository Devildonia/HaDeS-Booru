"""
Philomena Engine Adapter (Derpibooru).
Supports derpibooru.org (/api/v1/json/search/images).
"""

from __future__ import annotations

import math
import re
import time
from typing import Any
from urllib.parse import urlparse

from hades_booru.adapters.base import BooruAdapter, ProgressCallback
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
        return self.default_domain.lower() in url.lower()

    def _map_post(self, raw: dict[str, Any]) -> Post | None:
        post_id = raw.get("id")
        if not post_id:
            return None

        reps = raw.get("representations") if isinstance(raw.get("representations"), dict) else {}
        view_url = str(raw.get("view_url") or "")
        file_url = str(reps.get("full") or view_url)
        sample_url = str(reps.get("large") or reps.get("medium") or file_url)
        medium_url = str(reps.get("medium") or reps.get("small") or sample_url)
        preview_url = str(reps.get("thumb") or reps.get("small") or medium_url)

        if not preview_url and not file_url:
            return None

        raw_tags_list = raw.get("tags") if isinstance(raw.get("tags"), list) else []
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
            score=int(raw.get("score")) if raw.get("score") is not None else None,
        )

    def search(
        self,
        tags: str,
        limit: int = 20,
        progress_cb: ProgressCallback | None = None,
        rating: str | None = None,  # Philomena has no stable rating query param; UI filters client-side.
    ) -> list[Post]:
        target_count = max(1, min(limit, 500))
        page_size = min(50, target_count)
        total_pages = math.ceil(target_count / page_size)

        # Philomena queries use comma-separated tags; convert space-separated tags if no commas are present
        stripped = tags.strip()
        if not stripped:
            query_str = "*"
        elif "," in stripped:
            query_str = stripped
        else:
            query_str = ", ".join(t.replace("_", " ") for t in stripped.split() if t)

        posts: list[Post] = []
        seen_ids: set[str] = set()
        self.last_warning = None

        for page in range(1, total_pages + 1):
            if progress_cb:
                progress_cb(
                    min(0.95, (page - 1) / max(1, total_pages)),
                    f"Querying {self.name} (Page {page}/{total_pages})...",
                )

            url = f"https://{self.default_domain}/api/v1/json/search/images"
            params: dict[str, Any] = {
                "q": query_str,
                "per_page": page_size,
                "page": page,
            }

            try:
                data = http_client.get_json(url, params=params)
                batch = data.get("images") if isinstance(data, dict) else []
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
                    time.sleep(0.25)

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
