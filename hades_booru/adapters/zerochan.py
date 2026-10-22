"""
Zerochan Adapter.
Supports zerochan.net JSON endpoint (/?json) with listing URL tag extraction and CDN ID resolution.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any
from urllib.parse import quote, unquote, urlparse

from hades_booru.adapters.base import BooruAdapter, ProgressCallback, host_matches
from hades_booru.http_client import BooruNetworkError, http_client
from hades_booru.models import COMMON_META_TAGS, CategorizedTags, Post


def extract_zerochan_tag_from_path(path: str) -> str | None:
    """Extracts a search tag from a Zerochan listing path like '/Hatsune%20Miku' or '/Hatsune+Miku'."""
    segments = [s for s in path.strip("/").split("/") if s]
    if not segments:
        return None
    first = segments[0]
    if first.isdigit():
        return None
    decoded = unquote(first).replace("+", " ").replace("_", " ").strip()
    return decoded or None


def extract_zerochan_post_id(url: str) -> str | None:
    """Extracts the numeric post ID from a Zerochan post URL, CDN image URL, or path."""
    parsed = urlparse(url)
    path = parsed.path

    # Image file URLs or CDN paths (e.g. /240/45/23/4012345.jpg or /Hatsune.Miku.full.4012345.jpg)
    cdn_match = re.search(r"[/.](\d+)\.[a-zA-Z0-9]+$", path)
    if cdn_match:
        return cdn_match.group(1)

    # Main site direct post URL: https://www.zerochan.net/4012345 (single numeric path segment)
    direct_match = re.match(r"^/(\d+)/?$", path)
    if direct_match:
        return direct_match.group(1)

    return None


class ZerochanAdapter(BooruAdapter):
    """Adapter for Zerochan anime illustration board (zerochan.net)."""

    def __init__(
        self,
        adapter_id: str = "zerochan",
        name: str = "Zerochan",
        domain: str = "www.zerochan.net",
    ) -> None:
        self.id = adapter_id
        self.name = name
        self.default_domain = domain

    def can_handle_url(self, url: str) -> bool:
        # Audit R6-01: exact-host matching (no substring).
        return host_matches(url, "zerochan.net")

    def _map_post(self, raw: dict[str, Any]) -> Post | None:
        post_id = raw.get("id")
        if not post_id:
            return None

        thumb = str(raw.get("thumbnail") or raw.get("small") or "")
        medium = str(raw.get("medium") or raw.get("large") or thumb)
        large = str(raw.get("large") or raw.get("full") or medium)
        full = str(raw.get("full") or large)

        if not thumb and not large:
            return None

        raw_tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
        primary_tag = str(raw.get("tag") or "").strip()
        cleaned_tags: list[str] = []
        if primary_tag:
            cleaned_tags.append(primary_tag.lower().replace(" ", "_"))
        for t in raw_tags:
            norm = str(t).strip().lower().replace(" ", "_")
            if norm and norm not in cleaned_tags:
                cleaned_tags.append(norm)

        general: list[str] = []
        meta: list[str] = []
        for t in cleaned_tags:
            if t in COMMON_META_TAGS:
                meta.append(t)
            else:
                general.append(t)

        return Post(
            id=str(post_id),
            source_id=self.id,
            source_name=self.name,
            source_url=f"https://www.zerochan.net/{post_id}",
            preview_url=thumb or medium,
            medium_url=medium or large,
            sample_url=large or full,
            file_url=full or large,
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            rating="g",
            tags=CategorizedTags(general=general, meta=meta),
            raw_tags=cleaned_tags,
            title=primary_tag or None,
        )

    def search(
        self,
        tags: str,
        limit: int = 20,
        progress_cb: ProgressCallback | None = None,
        rating: str | None = None,  # Zerochan has no rating query param; UI filters client-side.
    ) -> list[Post]:
        target_count = max(1, min(limit, 200))
        page_size = min(50, target_count)
        total_pages = math.ceil(target_count / page_size)

        raw_query = tags.strip()
        if raw_query.startswith("http://") or raw_query.startswith("https://"):
            parsed_q = urlparse(raw_query)
            extracted = extract_zerochan_tag_from_path(parsed_q.path)
            clean_tag = extracted or ""
        else:
            clean_tag = raw_query.replace("_", " ")

        encoded_path = f"/{quote(clean_tag)}" if clean_tag else "/"

        posts: list[Post] = []
        seen_ids: set[str] = set()
        self.last_warning = None

        for page in range(1, total_pages + 1):
            if progress_cb:
                progress_cb(
                    min(0.95, (page - 1) / max(1, total_pages)),
                    f"Querying {self.name} (Page {page}/{total_pages})...",
                )

            url = f"https://{self.default_domain}{encoded_path}"
            params: dict[str, Any] = {
                "json": "1",
                "l": page_size,
                "p": page,
            }

            try:
                data = http_client.get_json(
                    url,
                    params=params,
                    headers={"User-Agent": "HaDeS_Booru_Client - Zerochan Reader"},
                )
                batch = data.get("items") if isinstance(data, dict) else []
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
                    time.sleep(0.3)

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
        post_id = extract_zerochan_post_id(url)
        if not post_id:
            raise BooruNetworkError(f"Could not extract post ID from Zerochan URL: {url}", url=url)

        api_url = f"https://www.zerochan.net/{post_id}?json"
        raw = http_client.get_json(
            api_url,
            headers={"User-Agent": "HaDeS_Booru_Client - Zerochan Reader"},
        )
        if not isinstance(raw, dict):
            raise BooruNetworkError(f"Post #{post_id} not found on Zerochan.", url=api_url)

        post = self._map_post(raw)
        if not post:
            raise BooruNetworkError(f"Post #{post_id} has no accessible media on Zerochan.", url=api_url)
        return post
