"""
Gelbooru & DAPI Family Adapter.
Supports safebooru.org, gelbooru.com, rule34.xxx, rule34.us, tbib.org, xbooru.com, and realbooru.com
(JSON + XML + HTML fallback).
"""

from __future__ import annotations

import json
import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from hades_booru.adapters.base import BooruAdapter, ProgressCallback, host_matches
from hades_booru.config import config_manager
from hades_booru.http_client import BooruNetworkError, http_client
from hades_booru.models import COMMON_META_TAGS, CategorizedTags, Post, Rating, TagCategory
from hades_booru.tag_dictionary import get_tag_dictionary


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
    "_(brand)",
    "_(company)",
    "_(studio)",
    "_(publisher)",
    "_(magazine)",
    "_(vocaloid)",
    "_(utau)",
    "_(synthesizer_v)",
    "_(cevio)",
    "_(hololive)",
    "_(nijisanji)",
    "_(touhou)",
    "_(pokemon)",
)

ARTIST_PAREN_SUFFIXES = (
    "_(artist)",
    "_(circle)",
    "_(voice_actor)",
    "_(seiyuu)",
    "_(illustrator)",
    "_(mangaka)",
)

GENERAL_PAREN_SUFFIXES = (
    "_(cosplay)",
    "_(costume)",
    "_(outfit)",
    "_(weapon)",
    "_(object)",
    "_(vehicle)",
    "_(meme)",
    "_(color)",
    "_(colour)",
    "_(pose)",
    "_(position)",
    "_(expression)",
    "_(clothing)",
    "_(attire)",
    "_(dress)",
    "_(swimsuit)",
    "_(uniform)",
    "_(hair)",
    "_(eyes)",
    "_(focus)",
    "_(framing)",
    "_(angle)",
    "_(lighting)",
    "_(background)",
    "_(style)",
    "_(medium)",
    "_(theme)",
    "_(trope)",
    "_(symbol)",
    "_(gesture)",
    "_(action)",
    "_(state)",
    "_(size)",
    "_(pattern)",
    "_(material)",
    "_(food)",
    "_(drink)",
    "_(animal)",
    "_(creature)",
    "_(plant)",
    "_(flower)",
    "_(instrument)",
    "_(tool)",
    "_(furniture)",
    "_(building)",
    "_(location)",
    "_(place)",
    "_(weather)",
    "_(time)",
    "_(season)",
    "_(holiday)",
    "_(event)",
    "_(sport)",
    "_(activity)",
    "_(occupation)",
    "_(role)",
    "_(body_part)",
    "_(anatomy)",
    "_(marking)",
    "_(accessory)",
    "_(jewelry)",
    "_(headwear)",
    "_(footwear)",
    "_(legwear)",
    "_(neckwear)",
    "_(eyewear)",
    "_(handwear)",
    "_(underwear)",
    "_(lingerie)",
    "_(armor)",
    "_(mecha)",
    "_(robot)",
    "_(monster)",
    "_(number)",
    "_(count)",
    "_(kanji)",
    "_(kana)",
    "_(text)",
    "_(font)",
    "_(sound_effect)",
    "_(archetype)",
    "_(form)",
    "_(mode)",
)

DAPI_TYPE_MAP: dict[str, TagCategory] = {
    "0": "general",
    "tag": "general",
    "general": "general",
    "1": "artist",
    "artist": "artist",
    "3": "copyright",
    "copyright": "copyright",
    "4": "character",
    "character": "character",
    "5": "meta",
    "metadata": "meta",
    "meta": "meta",
}


class DapiTagCategoryCache:
    """Thread-safe cache for per-board DAPI tag category lookups (`s=tag&q=index`)."""

    def __init__(self, cache_path: Path | None = None, max_entries: int = 10000) -> None:
        self._lock = threading.RLock()
        self._path = cache_path or (Path(".cache") / "dapi_tag_categories.json")
        self._max_entries = max_entries
        self._mem: dict[str, TagCategory] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    if v in ("copyright", "character", "artist", "general", "meta"):
                        self._mem[str(k)] = cast(TagCategory, v)
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if len(self._mem) > self._max_entries:
                keys = list(self._mem.keys())[-self._max_entries :]
                self._mem = {k: self._mem[k] for k in keys}
            self._path.write_text(
                json.dumps(self._mem, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def get_many(self, board_id: str, tags: list[str]) -> dict[str, TagCategory]:
        with self._lock:
            self._ensure_loaded()
            out: dict[str, TagCategory] = {}
            for t in tags:
                key = f"{board_id}:{t.lower()}"
                if key in self._mem:
                    out[t.lower()] = self._mem[key]
            return out

    def put_many(self, board_id: str, mapping: dict[str, TagCategory]) -> None:
        if not mapping:
            return
        with self._lock:
            self._ensure_loaded()
            for tag, cat in mapping.items():
                self._mem[f"{board_id}:{tag.lower()}"] = cat
            self._save()


dapi_tag_cache = DapiTagCategoryCache()

# R7-08a: process-level memo for dictionary category lookups. Tag names repeat
# heavily across posts, so one search ends up issuing a single SQLite batch
# lookup per unique tag instead of one connection per post (500 posts -> 500
# connections before this fix).
_dict_lookup_lock = threading.Lock()
_dict_lookup_memo: dict[str, TagCategory] = {}
_DICT_LOOKUP_MEMO_MAX = 20000


def _lookup_tag_categories_batch(raw_tags: list[str]) -> dict[str, TagCategory]:
    """Memoized bulk lookup of tag categories from the local dictionary."""
    if not raw_tags:
        return {}
    out: dict[str, TagCategory] = {}
    missing: list[str] = []
    with _dict_lookup_lock:
        for raw in raw_tags:
            key = str(raw).strip().lower()
            if not key:
                continue
            hit = _dict_lookup_memo.get(key)
            if hit is not None:
                out[key] = hit
            else:
                missing.append(key)
    if missing:
        try:
            fetched = get_tag_dictionary().lookup_categories_batch(missing)
        except Exception:
            fetched = {}
        if fetched:
            with _dict_lookup_lock:
                if len(_dict_lookup_memo) > _DICT_LOOKUP_MEMO_MAX:
                    _dict_lookup_memo.clear()
                for k, v in fetched.items():
                    norm = str(k).strip().lower()
                    if norm:
                        _dict_lookup_memo[norm] = v
            for k, v in fetched.items():
                norm = str(k).strip().lower()
                if norm:
                    out[norm] = v
    return out


def _categorize_flat_tags(
    raw_tags: list[str],
    resolved_overrides: dict[str, TagCategory] | None = None,
    use_dictionary: bool = True,
) -> CategorizedTags:
    """Categorizes flat DAPI tags using a 3-layer hybrid strategy (X9 / R6-13):
    1. Explicit per-board DAPI `s=tag` overrides (when cached/resolved) + `COMMON_META_TAGS`.
    2. Parenthesized suffix rules (`COPYRIGHT_SUFFIXES`, `ARTIST_PAREN_SUFFIXES`,
       and expanded `GENERAL_PAREN_SUFFIXES` exemptions such as `_(color)`, `_(pose)`).
    3. Local `TagDictionaryService` batch lookup for unparenthesized `artist`, `copyright`,
       and `character` tags, falling back to `_(...) -> character` and `general`.
    """
    copyright_tags: list[str] = []
    character: list[str] = []
    artist: list[str] = []
    general: list[str] = []
    meta: list[str] = []

    overrides = {k.lower(): v for k, v in (resolved_overrides or {}).items()}
    dict_cats: dict[str, TagCategory] = {}
    if use_dictionary and raw_tags:
        dict_cats = _lookup_tag_categories_batch(raw_tags)

    buckets: dict[TagCategory, list[str]] = {
        "copyright": copyright_tags,
        "character": character,
        "artist": artist,
        "general": general,
        "meta": meta,
    }

    for tag in raw_tags:
        lower = tag.lower()
        if lower in overrides:
            buckets[overrides[lower]].append(tag)
        elif lower in COMMON_META_TAGS:
            meta.append(tag)
        elif lower.endswith(COPYRIGHT_SUFFIXES):
            copyright_tags.append(tag)
        elif lower.endswith(ARTIST_PAREN_SUFFIXES):
            artist.append(tag)
        elif lower.endswith(GENERAL_PAREN_SUFFIXES):
            general.append(tag)
        elif lower in dict_cats:
            buckets[dict_cats[lower]].append(tag)
        elif "_(" in tag and tag.endswith(")"):
            character.append(tag)
        else:
            general.append(tag)

    return CategorizedTags(
        copyright=copyright_tags,
        character=character,
        artist=artist,
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

    def resolve_tag_categories(
        self,
        tags: list[str],
        cache: DapiTagCategoryCache | None = None,
    ) -> dict[str, TagCategory]:
        """Resolves tag categories via the board's DAPI `s=tag&q=index` endpoint with caching (X9)."""
        active_cache = cache or dapi_tag_cache
        clean_tags = [t.strip() for t in tags if t and t.strip()]
        if not clean_tags:
            return {}

        cached = active_cache.get_many(self.id, clean_tags)
        missing = [t for t in clean_tags if t.lower() not in cached]
        if not missing:
            return cached

        url = f"https://{self.api_host}/index.php"
        params: dict[str, Any] = {
            "page": "dapi",
            "s": "tag",
            "q": "index",
            "json": "1",
            "names": " ".join(missing[:100]),
        }
        self._apply_credentials(params)

        fetched: dict[str, TagCategory] = {}
        try:
            text = http_client.get_text(url, params=params).strip()
            if text:
                items: list[dict[str, Any]] = []
                try:
                    data = json.loads(text)
                    if isinstance(data, list):
                        items = [x for x in data if isinstance(x, dict)]
                    elif isinstance(data, dict):
                        tag_node = data.get("tag")
                        if isinstance(tag_node, list):
                            items = [x for x in tag_node if isinstance(x, dict)]
                        elif isinstance(tag_node, dict):
                            items = [tag_node]
                except json.JSONDecodeError:
                    if text.startswith("<") and not text.lower().startswith("<!doctype"):
                        root = ET.fromstring(text)
                        items = [dict(el.attrib) for el in root.findall(".//tag")]

                for entry in items:
                    name = str(entry.get("name") or "").strip().lower()
                    raw_type = str(entry.get("type") if entry.get("type") is not None else "").strip().lower()
                    cat = DAPI_TYPE_MAP.get(raw_type)
                    if name and cat:
                        fetched[name] = cat
        except Exception:
            # Degrade gracefully to local dictionary + suffix heuristics if `s=tag` fails
            return cached

        if fetched:
            active_cache.put_many(self.id, fetched)
            cached.update(fetched)
        return cached

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
            tags=_categorize_flat_tags(
                raw_tags,
                resolved_overrides=dapi_tag_cache.get_many(self.id, raw_tags),
            ),
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
        clean_tags = " ".join(tags.strip().split())
        # DAPI exposes rating as a tag; "g" and "u" have no DAPI equivalent and
        # fall back to the UI client-side filter.
        dapi_rating_tag = {"s": "rating:s", "q": "rating:q", "e": "rating:e"}.get(rating or "")
        self.server_rating_applied = bool(dapi_rating_tag)

        # R7-08d: resolve the query tags' native board categories via the DAPI
        # `s=tag` endpoint so the cached overrides feed `_map_post` (X9 layer 1).
        # Degrades silently to local dictionary + suffix heuristics on failure.
        if clean_tags:
            try:
                self.resolve_tag_categories(clean_tags.split())
            except Exception:
                pass

        def _fetch_page(page: int, page_size: int) -> list[dict[str, Any]]:
            pid = page - 1  # DAPI uses 0-indexed page offset
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
            if dapi_rating_tag:
                params["tags"] = f"{params.get('tags', '')} {dapi_rating_tag}".strip()
            self._apply_credentials(params)
            return self._fetch_dapi_batch(params)

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
