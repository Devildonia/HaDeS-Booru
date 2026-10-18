"""
Art Platforms & Generic Scraper Adapter.
Supports DeviantArt (RSS), ArtStation (API v2), Pawoo (Mastodon API v1), E-Hentai, Booru.io, and Generic OpenGraph fallback.
"""

from __future__ import annotations

import re
import time
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

from hades_booru.adapters.base import BooruAdapter, ProgressCallback
from hades_booru.http_client import BooruNetworkError, http_client
from hades_booru.models import CategorizedTags, Post


class ArtPlatformsAdapter(BooruAdapter):
    """Multi-platform adapter for DeviantArt, ArtStation, Pawoo, E-Hentai, and generic OpenGraph URLs."""

    def __init__(
        self,
        adapter_id: str = "deviantart",
        name: str = "DeviantArt (RSS)",
        domain: str = "deviantart.com",
    ) -> None:
        self.id = adapter_id
        self.name = name
        self.default_domain = domain

    def can_handle_url(self, url: str) -> bool:
        lower = url.lower()
        if self.id == "deviantart":
            return "deviantart.com" in lower
        if self.id == "artstation":
            return "artstation.com" in lower
        if self.id == "pawoo":
            return "pawoo.net" in lower
        if self.id == "ehentai":
            return "e-hentai.org" in lower or "exhentai.org" in lower
        if self.id == "generic":
            return "booru.io" in lower
        return False

    def search(
        self,
        tags: str,
        limit: int = 20,
        progress_cb: ProgressCallback | None = None,
        rating: str | None = None,  # Art platforms have no rating query param; UI filters client-side.
    ) -> list[Post]:
        self.last_warning = None
        if self.id in ("generic", "ehentai"):
            raise BooruNetworkError(
                f"Tag search is not supported on {self.name}. Paste a direct gallery/post URL in the search bar instead."
            )
        if self.id == "artstation":
            return self._search_artstation(tags, limit, progress_cb)
        if self.id == "pawoo":
            return self._search_pawoo(tags, limit, progress_cb)
        return self._search_deviantart(tags, limit, progress_cb)

    def _search_deviantart(
        self,
        tags: str,
        limit: int,
        progress_cb: ProgressCallback | None = None,
    ) -> list[Post]:
        query = tags.strip() or "anime"
        url = "https://backend.deviantart.com/rss.xml"
        if progress_cb:
            progress_cb(0.3, "Fetching DeviantArt RSS feed...")

        xml_text = http_client.get_text(url, params={"q": query, "type": "deviation"})
        if progress_cb:
            progress_cb(0.7, "Parsing DeviantArt media items...")

        posts: list[Post] = []
        item_re = re.compile(r"<item>([\s\S]*?)</item>", re.IGNORECASE)

        for idx, match in enumerate(item_re.finditer(xml_text)):
            if len(posts) >= limit:
                break
            block = match.group(1)

            title_m = re.search(r"<title>([^<]+)</title>", block, re.IGNORECASE)
            link_m = re.search(r"<link>([^<]+)</link>", block, re.IGNORECASE)
            thumbs = re.findall(r'<media:thumbnail[^>]+url="([^"]+)"', block, re.IGNORECASE)
            content_m = re.search(r'<media:content[^>]+url="([^"]+)"', block, re.IGNORECASE)
            author_m = re.search(r'<media:credit[^>]*role="author"[^>]*>([^<]+)</media:credit>', block, re.IGNORECASE)
            cat_m = re.search(r"<media:category[^>]*>([^<]+)</media:category>", block, re.IGNORECASE)

            title = title_m.group(1).strip() if title_m else "DeviantArt Post"
            source_url = link_m.group(1).strip() if link_m else "https://www.deviantart.com"
            file_url = content_m.group(1) if content_m else (thumbs[-1] if thumbs else "")
            preview_url = thumbs[0] if thumbs else file_url
            medium_url = thumbs[-1] if len(thumbs) > 1 else file_url
            author = author_m.group(1).strip() if author_m else None

            if not preview_url:
                continue

            derived_tags: list[str] = []
            for word in re.split(r"[\s,._\-]+", title.lower()):
                if len(word) > 2:
                    derived_tags.append(word)
            if cat_m:
                derived_tags.extend(cat_m.group(1).lower().split("/"))
            derived_tags.extend(query.lower().split())

            unique_tags = list(dict.fromkeys(t for t in derived_tags if t))
            artist_tags = [author.lower().replace(" ", "_")] if author else []

            posts.append(
                Post(
                    id=f"da_{int(time.time())}_{idx}",
                    source_id="deviantart",
                    source_name="DeviantArt",
                    source_url=source_url,
                    preview_url=preview_url,
                    medium_url=medium_url,
                    sample_url=file_url,
                    file_url=file_url,
                    rating="g",
                    tags=CategorizedTags(
                        artist=artist_tags,
                        general=unique_tags,
                        meta=["deviantart", "rss_feed"],
                    ),
                    raw_tags=unique_tags,
                    title=title,
                    author=author,
                )
            )

        if progress_cb:
            progress_cb(1.0, f"Loaded {len(posts)} deviations from DeviantArt.")
        return posts

    def _search_artstation(
        self,
        tags: str,
        limit: int,
        progress_cb: ProgressCallback | None = None,
    ) -> list[Post]:
        query = tags.strip() or "character"
        per_page = max(3, min(50, limit))
        url = "https://www.artstation.com/api/v2/search/projects.json"

        if progress_cb:
            progress_cb(0.4, "Searching ArtStation projects...")

        data = http_client.get_json(url, params={"query": query, "page": 1, "per_page": per_page})
        items = data.get("data") if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []

        posts: list[Post] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if not item_id:
                continue

            title = str(item.get("title") or "")
            title_words = [
                w for w in re.sub(r"[^a-z0-9\s]", "", title.lower()).split() if len(w) > 2
            ]
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            artist_name = str(user.get("username") or user.get("full_name") or "")
            small_cover = str(item.get("smaller_square_cover_url") or "")
            if not small_cover:
                continue

            # Upgrade ArtStation square thumbnail URL to larger variant when available
            large_cover = re.sub(r"/\d+_square/", "/large/", small_cover).replace("/smaller_square/", "/large/")

            is_adult = bool(item.get("is_adult_content"))
            artist_list = [artist_name.lower().replace(" ", "_")] if artist_name else []

            posts.append(
                Post(
                    id=f"as_{item_id}",
                    source_id="artstation",
                    source_name="ArtStation",
                    source_url=str(item.get("url") or f"https://www.artstation.com/artwork/{item_id}"),
                    preview_url=small_cover,
                    medium_url=large_cover,
                    sample_url=large_cover,
                    file_url=large_cover,
                    rating="q" if is_adult else "g",
                    tags=CategorizedTags(
                        artist=artist_list,
                        general=title_words,
                        meta=["artstation"],
                    ),
                    raw_tags=[*artist_list, *title_words],
                    title=title or None,
                    author=artist_name or None,
                )
            )
            if len(posts) >= limit:
                break

        if progress_cb:
            progress_cb(1.0, f"Loaded {len(posts)} projects from ArtStation.")
        return posts

    def _search_pawoo(
        self,
        tags: str,
        limit: int,
        progress_cb: ProgressCallback | None = None,
    ) -> list[Post]:
        tokens = [t.lstrip("#") for t in (tags.strip() or "anime").split() if t.lstrip("#")]
        clean_tag = tokens[0] if tokens else "anime"
        if len(tokens) > 1:
            self.last_warning = (
                f"Pawoo timeline API only supports a single hashtag; searched '#{clean_tag}' "
                f"(ignored: {', '.join(tokens[1:])})"
            )
        fetch_limit = min(40, limit)
        url = f"https://pawoo.net/api/v1/timelines/tag/{clean_tag}"

        if progress_cb:
            progress_cb(0.4, "Searching Pawoo federated timeline...")

        raw = http_client.get_json(url, params={"limit": fetch_limit})
        if not isinstance(raw, list):
            err_msg = raw.get("error") if isinstance(raw, dict) else "Unexpected response"
            raise BooruNetworkError(f"Pawoo API error: {err_msg}", url=url)

        posts: list[Post] = []
        for status in raw:
            if not isinstance(status, dict):
                continue
            media_list = status.get("media_attachments")
            if not isinstance(media_list, list) or not media_list:
                continue
            media = media_list[0]
            if not isinstance(media, dict):
                continue

            preview_url = str(media.get("preview_url") or media.get("url") or "")
            file_url = str(media.get("url") or preview_url)
            if not preview_url:
                continue

            tag_objs = status.get("tags") if isinstance(status.get("tags"), list) else []
            post_tags = [
                str(t.get("name", "")).lower()
                for t in tag_objs
                if isinstance(t, dict) and t.get("name")
            ]
            account = status.get("account") if isinstance(status.get("account"), dict) else {}
            author = str(account.get("username") or account.get("display_name") or "") or None
            meta_orig: dict[str, Any] = (
                (media.get("meta") or {}).get("original") or {}
                if isinstance(media.get("meta"), dict)
                else {}
            )

            status_id = status.get("id")
            posts.append(
                Post(
                    id=f"pawoo_{status_id}",
                    source_id="pawoo",
                    source_name="Pawoo (Mastodon)",
                    source_url=str(status.get("url") or f"https://pawoo.net/web/statuses/{status_id}"),
                    preview_url=preview_url,
                    medium_url=file_url,
                    sample_url=file_url,
                    file_url=file_url,
                    width=int(meta_orig.get("width") or 0),
                    height=int(meta_orig.get("height") or 0),
                    rating="s" if status.get("sensitive") else "g",
                    tags=CategorizedTags(
                        artist=[author.lower().replace(" ", "_")] if author else [],
                        general=post_tags,
                        meta=["pawoo", "fediverse"],
                    ),
                    raw_tags=post_tags,
                    author=author,
                )
            )
            if len(posts) >= limit:
                break

        if progress_cb:
            progress_cb(1.0, f"Loaded {len(posts)} media statuses from Pawoo.")
        return posts

    def fetch_single_by_url(self, url: str) -> Post:
        html = http_client.get_text(url)

        og_img = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        ) or re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            html,
            re.IGNORECASE,
        )
        og_title = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        ) or re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
        og_desc = re.search(
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        kw_match = re.search(
            r'<meta[^>]+name=["\']keywords["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )

        # HTML-unescape entity-encoded meta values and resolve relative og:image paths.
        image_url = urljoin(url, unescape(og_img.group(1))) if og_img else ""
        title = unescape(og_title.group(1)).strip() if og_title else "Scraped Post"
        keywords = [k.strip() for k in unescape(kw_match.group(1)).split(",") if k.strip()] if kw_match else []
        desc_words = unescape(og_desc.group(1)).lower().split()[:10] if og_desc else []

        all_tags = list(dict.fromkeys(t for t in [*keywords, *desc_words] if len(t) > 2))
        hostname = urlparse(url).hostname or "scraped"

        return Post(
            id=f"scraped_{int(time.time())}",
            source_id=self.id,
            source_name=self.name,
            source_url=url,
            preview_url=image_url,
            medium_url=image_url,
            sample_url=image_url,
            file_url=image_url,
            rating="e" if re.search(r"nsfw|18\+|hentai|adult", html, re.IGNORECASE) else "g",
            tags=CategorizedTags(
                general=all_tags,
                meta=["scraped", hostname],
            ),
            raw_tags=all_tags,
            title=title,
        )
