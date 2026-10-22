"""
One-off Danbooru Tag & Wiki Catalog Importer for HaDeS Booru (v1.1.0).
Downloads tags, active aliases, and wiki definitions from the Danbooru v2 JSON API
into the local SQLite database (`data/tags.sqlite3`).
Design constraint: never runs automatically at application startup; invoked only on
explicit CLI execution (`python -m hades_booru.tag_dictionary.importer`) or explicit user action.
"""

from __future__ import annotations

import argparse
import re

from hades_booru.config import config_manager
from hades_booru.http_client import http_client
from hades_booru.models import TagCategory
from hades_booru.tag_dictionary.seed_data import SeedTagEntry
from hades_booru.tag_dictionary.service import (
    DEFAULT_DB_PATH,
    TagDictionaryService,
    get_tag_dictionary,
    normalize_dict_query,
)

DANBOORU_CATEGORY_MAP: dict[int, TagCategory] = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}

_DTEXT_LINK_PIPE_RE = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")
_DTEXT_LINK_SIMPLE_RE = re.compile(r"\[\[([^\]]+)\]\]")
_DTEXT_EXT_LINK_RE = re.compile(r'"([^"]+)":\[https?://[^\]]+\]')
_DTEXT_HEADER_RE = re.compile(r"(?m)^h[1-6]\.\s*.*$")
_DTEXT_BBCODE_RE = re.compile(r"\[/?(?:b|i|u|s|tn|spoilers?|expand(?:=[^\]]*)?|quote|code|table|tr|td|th)\]", re.IGNORECASE)


def strip_dtext(raw: str) -> str:
    """Strips Danbooru DText wiki markup into clean, readable plain text."""
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n")
    text = _DTEXT_LINK_PIPE_RE.sub(r"\2", text)
    text = _DTEXT_LINK_SIMPLE_RE.sub(r"\1", text)
    text = _DTEXT_EXT_LINK_RE.sub(r"\1", text)
    text = _DTEXT_HEADER_RE.sub("", text)
    text = _DTEXT_BBCODE_RE.sub("", text)
    paragraphs: list[str] = []
    for line in text.splitlines():
        cleaned_line = line.strip()
        if not cleaned_line or cleaned_line.startswith("* "):
            continue
        paragraphs.append(cleaned_line)
        if len(" ".join(paragraphs)) >= 520:
            break
    summary = " ".join(paragraphs).strip()
    return re.sub(r"\s{2,}", " ", summary)


class TagDictionaryImporter:
    """Fetches tags, aliases, and wiki definitions from Danbooru and updates local SQLite."""

    def __init__(
        self,
        service: TagDictionaryService | None = None,
        base_url: str = "https://danbooru.donmai.us",
    ) -> None:
        self.service = service or get_tag_dictionary()
        self.base_url = base_url.rstrip("/")

    def _get_auth(self) -> tuple[str, str] | None:
        creds = config_manager.get_credentials("danbooru")
        if creds.user_id and creds.api_key:
            return (creds.user_id, creds.api_key)
        return None

    def import_from_danbooru(
        self,
        max_pages: int = 2,
        page_size: int = 100,
    ) -> int:
        """Downloads top tags, their wiki pages, and active aliases into the local catalog."""
        auth = self._get_auth()
        limit = max(1, min(page_size, 200))
        pages = max(1, min(max_pages, 50))

        tag_records: dict[str, SeedTagEntry] = {}

        for page in range(1, pages + 1):
            raw_tags = http_client.get_json(
                f"{self.base_url}/tags.json",
                params={
                    "limit": limit,
                    "page": page,
                    "search[order]": "count",
                    "search[hide_empty]": "yes",
                },
                auth=auth,
            )
            if not isinstance(raw_tags, list) or not raw_tags:
                break

            names_in_batch: list[str] = []
            for item in raw_tags:
                if not isinstance(item, dict):
                    continue
                name = normalize_dict_query(str(item.get("name") or ""))
                if not name:
                    continue
                cat_id = int(item.get("category") or 0)
                category: TagCategory = DANBOORU_CATEGORY_MAP.get(cat_id, "general")
                post_count = int(item.get("post_count") or 0)
                tag_records[name] = {
                    "name": name,
                    "category": category,
                    "post_count": post_count,
                    "body_en": "",
                    "body_es": None,
                    "aliases": [],
                }
                names_in_batch.append(name)

            if names_in_batch:
                self._enrich_wiki_bodies(names_in_batch, tag_records, auth=auth)
                self._enrich_aliases(names_in_batch, tag_records, auth=auth)

        if not tag_records:
            return 0
        return self.service.upsert_entries(list(tag_records.values()))

    def _enrich_wiki_bodies(
        self,
        tag_names: list[str],
        tag_records: dict[str, SeedTagEntry],
        auth: tuple[str, str] | None = None,
    ) -> None:
        # R7-05: Danbooru v2 has no multi-title search parameter. The previous
        # `search[title_or_other_names_matches]` was invented and silently ignored
        # by the API (so no wiki body was ever imported), and the space-joined
        # `[:50]` blob would be invalid even for a real parameter. Fetch one wiki
        # page per tag with the validated `search[title]` parameter instead.
        for name in tag_names:
            if name not in tag_records:
                continue
            if tag_records[name].get("body_en"):
                continue
            try:
                raw_wikis = http_client.get_json(
                    f"{self.base_url}/wiki_pages.json",
                    params={
                        "limit": 1,
                        "search[title]": name,
                    },
                    auth=auth,
                )
            except Exception:
                continue
            if not isinstance(raw_wikis, list) or not raw_wikis:
                continue
            wiki = raw_wikis[0]
            if not isinstance(wiki, dict):
                continue
            body = strip_dtext(str(wiki.get("body") or ""))
            if body:
                tag_records[name]["body_en"] = body

    def _enrich_aliases(
        self,
        tag_names: list[str],
        tag_records: dict[str, SeedTagEntry],
        auth: tuple[str, str] | None = None,
    ) -> None:
        # R7-05: `search[consequent_name_space]` is valid but accepts a single name
        # space; the previous space-joined blob matched nothing. One request per tag.
        for name in tag_names:
            if name not in tag_records:
                continue
            if tag_records[name].get("aliases"):
                continue
            try:
                raw_aliases = http_client.get_json(
                    f"{self.base_url}/tag_aliases.json",
                    params={
                        "limit": 20,
                        "search[status]": "active",
                        "search[consequent_name_space]": name,
                    },
                    auth=auth,
                )
            except Exception:
                continue
            if not isinstance(raw_aliases, list):
                continue
            for al in raw_aliases:
                if not isinstance(al, dict):
                    continue
                ant = normalize_dict_query(str(al.get("antecedent_name") or ""))
                cons = normalize_dict_query(str(al.get("consequent_name") or ""))
                if ant and cons == name and ant not in tag_records[name]["aliases"]:
                    tag_records[name]["aliases"].append(ant)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HaDeS Booru — One-off Danbooru Tag Dictionary Importer"
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=2,
        help="Number of high-frequency tag pages (100 tags/page) to import from Danbooru (default: 2)",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Initialize the local SQLite database with the built-in curated seed catalog only (no network)",
    )
    args = parser.parse_args()

    svc = TagDictionaryService(db_path=DEFAULT_DB_PATH, auto_seed=True)
    svc.ensure_initialized()
    if not args.seed_only:
        importer = TagDictionaryImporter(service=svc)
        imported = importer.import_from_danbooru(max_pages=args.pages)
        print(f"[HaDeS Dictionary] Imported/updated {imported} canonical tags from Danbooru.")
    tags_cnt, aliases_cnt = svc.count()
    print(f"[HaDeS Dictionary] Ready at {svc.db_path} ({tags_cnt} tags, {aliases_cnt} aliases).")


if __name__ == "__main__":
    main()
