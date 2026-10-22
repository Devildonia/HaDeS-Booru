"""
Gelbooru & DAPI Family Adapter.
Supports safebooru.org, gelbooru.com, rule34.xxx, rule34.us, tbib.org, xbooru.com, and realbooru.com
(JSON + XML + HTML fallback).
"""

from __future__ import annotations

import json
import math
import re
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import parse_qs, urlparse

from hades_booru.adapters.base import BooruAdapter, ProgressCallback, host_matches
from hades_booru.config import config_manager
from hades_booru.http_client import BooruNetworkError, http_client
from hades_booru.models import COMMON_META_TAGS, CategorizedTags, Post, Rating


def _normalize_rating(raw: str | None) -> Rating:
    if not raw:
        return "u"
    lower = raw.lower()
    if lower in ("safe", "s", "general", "g"):
        return "g"
    if lower == "sensitive":
        return "s"
    if lower in ("questionable", "q"):
        return "q"
    if lower in ("explicit", "e"):
        return "e"
    return "u"


COPYRIGHT_SUFFIXES = (
    "_(series)",
    "_(game)",
    "_(anime)",
    "_(manga)",
    "_(franchise)",
    "_(movie)",
    "_(ova)",
    "_(visual_novel)",
    "_(light_novel)",
    "_(comic)",
    "_(webtoon)",
    "_(show)",
)

GENERAL_PAREN_SUFFIXES = (
    "_(cosplay)",
    "_(costume)",
    "_(outfit)",
    "_(weapon)",
    "_(object)",
    "_(vehicle)",
    "_(meme)",
)


def _categorize_flat_tags(raw_tags: list[str]) -> CategorizedTags:
    copyright_tags: list[str] = []
    general: list[str] = []
    meta: list[str] = []
    character: list[str] = []

    for tag in raw_tags:
        lower = tag.lower()
        if lower in COMMON_META_TAGS:
            meta.append(tag)
        elif lower.endswith(COPYRIGHT_SUFFIXES):
            copyright_tags.append(tag)
        elif lower.endswith(GENERAL_PAREN_SUFFIXES):
            general.append(tag)
        elif "_(" in tag and tag.endswith(")"):
            character.append(tag)
        else:
            general.append(tag)

    return CategorizedTags(
        copyright=copyright_tags,
        character=character,
        artist=[],
        general=general,
        meta=meta,
    )


class GelbooruAdapter(BooruAdapter):
    """Adapter for Gelbooru, Safebooru, Rule34, TBIB, XBooru, and RealBooru DAPI endpoints."""

    def __init__(
        self,
        adapter_id: str = "safebooru",
        name: str = "Safebooru (DAPI)",
        domain: str = "safebooru.org",
        api_host: str | None = None,
    ) -> None:
        self.id = adapter_id
        self.name = name
        self.default_domain = domain
        self.api_host = api_host or domain

    def can_handle_url(self, url: str) -> bool:
        # Audit R6-01: exact-host matching (no substring).
        return host_matches(url, self.default_domain)

    def _apply_credentials(self, params: dict[str, Any]) -> None:
        creds = config_manager.get_credentials(self.id)
        if not creds.api_key and self.id not in ("gelbooru", "rule34"):
            return
        if creds.api_key:
            params["api_key"] = creds.api_key
        if creds.user_id:
            params["user_id"] = creds.user_id

    def _map_post(self, raw: dict[str, Any]) -> Post | None:
        post_id = raw.get("id")
        if not post_id:
            return None

        tags_str = str(raw.get("tags") or "")
        raw_tags = [t for t in tags_str.strip().split() if t]

        file_url = str(raw.get("file_url") or "")
        preview_url = str(raw.get("preview_url") or "")
        sample_url = str(raw.get("sample_url") or "")

        directory = raw.get("directory")
        image = raw.get("image")

        if not file_url and directory and image:
            file_url = f"https://{self.default_domain}/images/{directory}/{image}"
        if not preview_url and directory and image:
            preview_url = f"https://{self.default_domain}/thumbnails/{directory}/thumbnail_{image}"
        if not sample_url and directory and image and raw.get("sample") in (1, "1", True, "true"):
            base_img = str(image).rsplit(".", 1)[0]
            sample_url = f"https://{self.default_domain}/samples/{directory}/sample_{base_img}.jpg"
        if not sample_url:
            sample_url = file_url or preview_url

        if not preview_url and not file_url:
            return None

        resolved_sample = sample_url or file_url or preview_url
        resolved_preview = preview_url or resolved_sample
        resolved_file = file_url or resolved_sample

        return Post(
            id=str(post_id),
            source_id=self.id,
            source_name=self.name,
            source_url=f"https://{self.default_domain}/index.php?page=post&s=view&id={post_id}",
            preview_url=resolved_preview,
            medium_url=resolved_sample,
            sample_url=resolved_sample,
            file_url=resolved_file,
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            rating=_normalize_rating(str(raw.get("rating") or "")),
            tags=_categorize_flat_tags(raw_tags),
            raw_tags=raw_tags,
            created_at=str(raw.get("created_at") or "") or None,
            author=str(raw.get("owner") or "") or None,
        )

    def _extract_list_from_payload(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            posts = payload.get("post")
            if isinstance(posts, list):
                return [x for x in posts if isinstance(x, dict)]
            if isinstance(posts, dict):
                return [posts]
        return []

    def _fetch_dapi_batch(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"https://{self.api_host}/index.php"
        text = http_client.get_text(url, params=params).strip()
        if not text:
            return []

        try:
            data = json.loads(text)
            return self._extract_list_from_payload(data)
        except json.JSONDecodeError:
            pass

        # Fallback: Gelbooru/Rule34/TBIB/XBooru DAPI mirrors often return XML even when json=1 is passed
        if text.startswith("<") and not text.lower().startswith("<!doctype") and not text.lower().startswith("<html"):
            try:
                root = ET.fromstring(text)
                items: list[dict[str, Any]] = []
                for elem in root.findall(".//post"):
                    entry = dict(elem.attrib)
                    if not entry.get("tags") and elem.findtext("tags"):
                        entry["tags"] = elem.findtext("tags", "")
                    if not entry.get("file_url") and elem.findtext("file_url"):
                        entry["file_url"] = elem.findtext("file_url", "")
                    if not entry.get("preview_url") and elem.findtext("preview_url"):
                        entry["preview_url"] = elem.findtext("preview_url", "")
                    if not entry.get("sample_url") and elem.findtext("sample_url"):
                        entry["sample_url"] = elem.findtext("sample_url", "")
                    items.append(entry)
                return items
            except ET.ParseError as err:
                raise BooruNetworkError(
                    f"{self.name} returned an unreadable XML response: {text[:150]}",
                    url=url,
                ) from err

        # Fallback for rule34.us when DAPI returns HTML listing
        if self.id == "rule34_us":
            return self._scrape_rule34_us_listing(params.get("tags", ""), int(params.get("pid", 0)))

        raise BooruNetworkError(f"Unexpected response from {self.name}: {text[:150]}", url=url)

    def _scrape_rule34_us_listing(self, tags: str, pid: int) -> list[dict[str, Any]]:
        url = f"https://{self.default_domain}/index.php"
        html_text = http_client.get_text(
            url,
            params={"r": "posts/index", "q": tags or "all", "page": pid + 1},
        )
        items: list[dict[str, Any]] = []
        pattern = re.compile(
            r'href=["\'][^"\']*id=(\d+)["\'][^>]*>\s*<img[^>]+src=["\']([^"\']+)["\'][^>]+alt=["\']([^"\']*)["\']',
            re.IGNORECASE,
        )
        for m in pattern.finditer(html_text):
            p_id, thumb_url, alt_tags = m.group(1), m.group(2), m.group(3)
            cleaned_tags = alt_tags.replace(",", " ")
            items.append(
                {
                    "id": p_id,
                    "preview_url": thumb_url,
                    "sample_url": thumb_url.replace("thumbnails", "images").replace("thumbnail_", ""),
                    "file_url": thumb_url.replace("thumbnails", "images").replace("thumbnail_", ""),
                    "tags": cleaned_tags,
                    "rating": "e",
                }
            )
        return items

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

        posts: list[Post] = []
        seen_ids: set[str] = set()
        self.last_warning = None

        for page in range(1, total_pages + 1):
            pid = page - 1  # DAPI uses 0-indexed page offset

            if progress_cb:
                progress_cb(
                    min(0.95, (page - 1) / max(1, total_pages)),
                    f"Querying {self.name} (Page {page}/{total_pages})...",
                )

            params: dict[str, Any] = {
                "page": "dapi",
                "s": "post",
                "q": "index",
                "json": "1",
                "limit": page_size,
                "pid": pid,
            }
            if clean_tags:
                params["tags"] = clean_tags
            # DAPI exposes rating as a tag; "g" and "u" have no DAPI equivalent and
            # fall back to the UI client-side filter.
            dapi_rating_tag = {"s": "rating:s", "q": "rating:q", "e": "rating:e"}.get(rating or "")
            if dapi_rating_tag:
                params["tags"] = f"{params.get('tags', '')} {dapi_rating_tag}".strip()
            self.server_rating_applied = bool(dapi_rating_tag)
            self._apply_credentials(params)

            try:
                batch = self._fetch_dapi_batch(params)
                if not batch:
                    break

                for item in batch:
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
        qs = parse_qs(parsed.query)
        id_list = qs.get("id")
        post_id = id_list[0] if id_list else None

        if not post_id:
            match = re.search(r"/posts?/(\d+)", parsed.path)
            if match:
                post_id = match.group(1)

        if not post_id:
            raise BooruNetworkError(f"Could not extract post ID from {self.name} URL: {url}", url=url)

        params: dict[str, Any] = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": "1",
            "id": post_id,
        }
        self._apply_credentials(params)

        batch = self._fetch_dapi_batch(params)
        if not batch:
            raise BooruNetworkError(f"Post #{post_id} not found on {self.name}.", url=url)

        post = self._map_post(batch[0])
        if not post:
            raise BooruNetworkError(f"Post #{post_id} has no media URLs on {self.name}.", url=url)
        return post
