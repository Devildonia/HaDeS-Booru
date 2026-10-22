"""
One-off Danbooru Tag & Wiki Catalog Importer for HaDeS Booru (v1.1.0).

Downloads the most popular Danbooru tags (ranked by post count), their active
aliases, and their wiki definitions from the Danbooru v2 JSON API into the local
SQLite database (`data/tags.sqlite3`).

Design constraints
------------------
* Never runs automatically at application startup; it is invoked only on explicit
  CLI execution (`python -m hades_booru.tag_dictionary.importer`) or explicit user action.
* Respects Danbooru's request-rate limits proactively (throttled pacing) instead of
  relying solely on 429 backoff, so a full import does not hammer the API.
* Reliable and resumable: every per-tag network fetch is isolated, failures are logged
  and skipped, and a final summary reports exactly what was imported.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from typing import Any

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

logger = logging.getLogger(__name__)

# Danbooru's public rate limit is ~2 requests/second unauthenticated and ~4 requests/
# second with valid API credentials. These pacing floors keep a large import polite.
_UNAUTH_PACING_SECONDS = 0.5
_AUTH_PACING_SECONDS = 0.25

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
_DTEXT_MACRO_RE = re.compile(r"\{\{[^{}]*\}\}")


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
    # Remove DText template macros (e.g. {{mpixels:>=1.9}}, {{taglist:...}}) that would
    # otherwise leak raw wiki markup into the definition; strip innermost-first so nested
    # macros collapse cleanly instead of leaving dangling braces.
    while "{{" in text and "}}" in text:
        stripped = _DTEXT_MACRO_RE.sub("", text)
        if stripped == text:
            break
        text = stripped
    paragraphs: list[str] = []
    for line in text.splitlines():
        cleaned_line = line.strip()
        if not cleaned_line or cleaned_line.startswith("* "):
            continue
        paragraphs.append(cleaned_line)
        if len(" ".join(paragraphs)) >= 520:
            break
    summary = " ".join(paragraphs).strip()
    summary = re.sub(r"\s{2,}", " ", summary)
    # Remove stray whitespace left before closing punctuation when a macro was stripped
    # inline (e.g. "equivalent to ." -> "equivalent to.").
    summary = re.sub(r"\s+([.,;:!?)\]])", r"\1", summary)
    return summary


class TagDictionaryImporter:
    """Fetches tags, aliases, and wiki definitions from Danbooru and updates local SQLite."""

    def __init__(
        self,
        service: TagDictionaryService | None = None,
        base_url: str = "https://danbooru.donmai.us",
    ) -> None:
        self.service = service or get_tag_dictionary()
        self.base_url = base_url.rstrip("/")
        self._throttle = 0.0

    def _get_auth(self) -> tuple[str, str] | None:
        creds = config_manager.get_credentials("danbooru")
        if creds.user_id and creds.api_key:
            return (creds.user_id, creds.api_key)
        return None

    def _pause(self) -> None:
        """Paces network calls to stay within Danbooru's request-rate limit."""
        if self._throttle > 0:
            time.sleep(self._throttle)

    def _fetch_json(self, url: str, params: dict[str, Any] | None, auth: tuple[str, str] | None) -> Any:
        return http_client.get_json(url, params=params, auth=auth)

    def import_from_danbooru(
        self,
        top: int | None = None,
        max_pages: int = 2,
        page_size: int = 100,
        skip_wiki: bool = False,
        resume: bool = True,
        throttle: float | None = None,
    ) -> int:
        """Downloads top tags, their wiki pages, and active aliases into the local catalog.

        Parameters
        ----------
        top:
            Target number of most-popular tags to import (e.g. 1000). When ``None``,
            falls back to ``max_pages * page_size`` for backward compatibility.
        max_pages / page_size:
            Legacy pagination controls; ``page_size`` is the tags-per-page cap (max 200).
        skip_wiki:
            When ``True``, only fetch tag metadata + aliases (no wiki bodies) for a faster first pass.
        resume:
            When ``True`` (default), tags already stored in the local database are not
            re-fetched (their wiki/alias are kept as-is); a new tag is still recorded.
        throttle:
            Seconds to pause between network calls. ``None`` selects a safe default
            (0.5s unauthenticated / 0.25s with API credentials); ``0`` disables pacing (tests).

        Returns the number of canonical tags written to the local catalog.
        """
        auth = self._get_auth()
        self._throttle = (
            max(0.0, float(throttle))
            if throttle is not None
            else (_AUTH_PACING_SECONDS if auth else _UNAUTH_PACING_SECONDS)
        )

        limit = max(1, min(page_size, 200))
        target = int(top) if (top and int(top) > 0) else max(1, min(max_pages, 50)) * limit

        # ------------------------------------------------------------------ 1) Tag list
        tag_records: dict[str, SeedTagEntry] = {}
        page = 1
        while len(tag_records) < target:
            raw_tags = self._fetch_json(
                f"{self.base_url}/tags.json",
                {
                    "limit": limit,
                    "page": page,
                    "search[order]": "count",
                    "search[hide_empty]": "yes",
                },
                auth,
            )
            if not isinstance(raw_tags, list) or not raw_tags:
                break

            new_in_page = 0
            for item in raw_tags:
                if not isinstance(item, dict):
                    continue
                name = normalize_dict_query(str(item.get("name") or ""))
                if not name or name in tag_records:
                    continue
                cat_id = int(item.get("category") or 0)
                tag_records[name] = {
                    "name": name,
                    "category": DANBOORU_CATEGORY_MAP.get(cat_id, "general"),
                    "post_count": int(item.get("post_count") or 0),
                    "body_en": "",
                    "body_es": None,
                    "aliases": [],
                }
                new_in_page += 1
                if len(tag_records) >= target:
                    break

            if new_in_page == 0:  # No progress (e.g. exhausted list or mocked duplicate page) — stop.
                break
            page += 1
            self._pause()

        if not tag_records:
            logger.info("Danbooru importer: no tags collected; nothing to write.")
            return 0

        # ------------------------------------------------------ 2) Resume: skip stored tags
        existing: set[str] = self.service.all_tag_names() if resume else set()
        to_enrich = [name for name in tag_records if not (resume and name in existing)]
        resumed_count = len(tag_records) - len(to_enrich)

        # ------------------------------------------------------- 3) Enrich wiki + aliases
        wiki_fetched = 0
        wiki_missed = 0
        alias_fetched = 0
        for idx, name in enumerate(to_enrich, start=1):
            rec = tag_records[name]
            if not skip_wiki:
                body = self._fetch_wiki_body(name, auth)
                if body:
                    rec["body_en"] = body
                    wiki_fetched += 1
                else:
                    wiki_missed += 1
                self._pause()
            aliases = self._fetch_aliases(name, auth)
            if aliases:
                rec["aliases"] = aliases
                alias_fetched += 1
            self._pause()

            if idx % 50 == 0:
                logger.info(
                    "Danbooru importer progress: %d/%d tags enriched (resumed %d, wiki ok %d, aliases %d).",
                    idx,
                    len(to_enrich),
                    resumed_count,
                    wiki_fetched,
                    alias_fetched,
                )

        # ------------------------------------------------------------- 4) Persist results
        written = self.service.upsert_entries(list(tag_records.values()))

        logger.info(
            "Danbooru importer finished: %d tags written (%d enriched, %d resumed, %d wiki bodies, "
            "%d tags with aliases, %d wiki misses%s).",
            written,
            len(to_enrich),
            resumed_count,
            wiki_fetched,
            alias_fetched,
            wiki_missed,
            ", wiki skipped" if skip_wiki else "",
        )
        return written

    def _fetch_wiki_body(self, name: str, auth: tuple[str, str] | None) -> str:
        """Fetches and cleans the wiki body for a single tag; returns '' on any failure/absence."""
        try:
            raw_wikis = self._fetch_json(
                f"{self.base_url}/wiki_pages.json",
                {"limit": 1, "search[title]": name},
                auth,
            )
        except Exception as err:  # noqa: BLE001 - a single tag failure must not abort the import
            logger.warning("Wiki fetch failed for '%s': %s", name, err)
            return ""
        if not isinstance(raw_wikis, list) or not raw_wikis:
            return ""
        wiki = raw_wikis[0]
        if not isinstance(wiki, dict):
            return ""
        return strip_dtext(str(wiki.get("body") or ""))

    def _fetch_aliases(self, name: str, auth: tuple[str, str] | None) -> list[str]:
        """Fetches active aliases that resolve to a tag; returns [] on any failure/absence."""
        try:
            raw_aliases = self._fetch_json(
                f"{self.base_url}/tag_aliases.json",
                {
                    "limit": 50,
                    "search[status]": "active",
                    "search[consequent_name]": name,
                },
                auth,
            )
        except Exception as err:  # noqa: BLE001 - a single tag failure must not abort the import
            logger.warning("Alias fetch failed for '%s': %s", name, err)
            return []
        if not isinstance(raw_aliases, list):
            return []
        result: list[str] = []
        for al in raw_aliases:
            if not isinstance(al, dict):
                continue
            ant = normalize_dict_query(str(al.get("antecedent_name") or ""))
            cons = normalize_dict_query(str(al.get("consequent_name") or ""))
            # Defensive: only accept aliases that genuinely resolve to THIS tag.
            if ant and ant != name and cons == name and ant not in result:
                result.append(ant)
        return result


def _estimate_minutes(requests: int, has_auth: bool) -> float:
    rps = 4.0 if has_auth else 2.0
    return round(requests / (rps * 60.0), 1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[importer] %(message)s")
    parser = argparse.ArgumentParser(
        description="HaDeS Booru - One-off Danbooru Tag Dictionary Importer"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=1000,
        help="Import the N most popular Danbooru tags (default: 1000).",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help="(legacy) Number of 100-tag pages to import; used only when --top is 0.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Tags per page (max 200). Default: 100.",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Initialize the local SQLite database with the built-in curated seed catalog only (no network).",
    )
    parser.add_argument(
        "--skip-wiki",
        action="store_true",
        help="Import tags + aliases only; skip wiki body downloads for a faster first pass.",
    )
    parser.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        default=True,
        help="Skip tags already stored in the local DB (default).",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Re-fetch wiki/aliases even for tags already stored in the local DB.",
    )
    args = parser.parse_args()

    svc = TagDictionaryService(db_path=DEFAULT_DB_PATH, auto_seed=True)
    svc.ensure_initialized()
    if args.seed_only:
        tags_cnt, aliases_cnt = svc.count()
        print(f"[HaDeS Dictionary] Seeded locally at {svc.db_path} ({tags_cnt} tags, {aliases_cnt} aliases).")
        return

    top = args.top if (args.top and args.top > 0) else None
    if top is None:
        top = max(1, (args.pages or 2)) * min(200, max(1, args.page_size))

    importer = TagDictionaryImporter(service=svc)
    has_auth = importer._get_auth() is not None
    est_requests = (top + max(1, args.page_size) - 1) // max(1, args.page_size) + top * (0 if args.skip_wiki else 2)
    est_min = _estimate_minutes(est_requests, has_auth)

    print(f"[HaDeS Dictionary] Importing up to {top} most popular Danbooru tags.")
    print(
        f"[HaDeS Dictionary] Est. {est_requests} API calls, ~{est_min} min "
        f"({'with' if has_auth else 'without'} API credentials)."
    )
    if not has_auth:
        print(
            "[HaDeS Dictionary] Tip: add a Danbooru API key in Settings to roughly double the safe import speed."
        )

    imported = importer.import_from_danbooru(
        top=top,
        page_size=max(1, args.page_size),
        skip_wiki=args.skip_wiki,
        resume=args.resume,
    )
    tags_cnt, aliases_cnt = svc.count()
    print(f"[HaDeS Dictionary] Imported/updated {imported} canonical tags from Danbooru.")
    print(f"[HaDeS Dictionary] Ready at {svc.db_path} ({tags_cnt} tags, {aliases_cnt} aliases).")


if __name__ == "__main__":
    main()
