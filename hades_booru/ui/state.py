"""
UI State Management, Search History, and Session-Scoped Personal List Store (v1.1.0).
Implements R6-25 modularization and X8 / R6-12 per-session isolation under `--share`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import gradio as gr

from hades_booru.config import MAX_SEARCH_HISTORY, config_manager  # noqa: F401 (re-exported for layout/tests)
from hades_booru.models import (
    DEFAULT_JUNK_TAGS,
    DEFAULT_SEMANTIC_ORDER,
    NormalizerConfig,
    TagCategory,
)
from hades_booru.normalizer import PromptNormalizer

# Audit R6-05: query params that commonly carry secrets in booru API URLs.
_SENSITIVE_QUERY_PARAMS = frozenset(
    {
        "api_key",
        "apikey",
        "key",
        "token",
        "password",
        "pass",
        "login",
        "user_id",
        "auth",
        "access_token",
        "secret",
    }
)


@dataclass
class SessionLists:
    """In-memory per-session personal tag lists used when running with `--share` (X8 / R6-12)."""

    junk_tags_list: list[str] = field(default_factory=lambda: list(DEFAULT_JUNK_TAGS))
    user_blacklist: list[str] = field(default_factory=list)
    user_whitelist: list[str] = field(default_factory=list)


def make_session_lists() -> SessionLists:
    """Factory passed to `gr.State(make_session_lists)` so each browser session gets a fresh copy."""
    norm = config_manager.config.normalizer
    return SessionLists(
        junk_tags_list=list(norm.junk_tags_list),
        user_blacklist=list(norm.user_blacklist),
        user_whitelist=list(norm.user_whitelist),
    )


class PersonalListStore:
    """Routes personal list reads and writes to disk (local mode) or session memory (`--share`)."""

    def __init__(self, share_mode: bool = False) -> None:
        self.share_mode = share_mode
        self._fallback_session = make_session_lists()

    def resolve_target(self, session_lists: SessionLists | None = None) -> SessionLists | NormalizerConfig:
        if not self.share_mode:
            return config_manager.config.normalizer
        return session_lists if isinstance(session_lists, SessionLists) else self._fallback_session

    def get_lists(
        self, session_lists: SessionLists | None = None
    ) -> tuple[list[str], list[str], list[str]]:
        target = self.resolve_target(session_lists)
        return (
            list(target.junk_tags_list),
            list(target.user_blacklist),
            list(target.user_whitelist),
        )

    def set_personal_lists(
        self,
        blacklist: list[str],
        whitelist: list[str],
        session_lists: SessionLists | None = None,
    ) -> None:
        target = self.resolve_target(session_lists)
        target.user_blacklist = list(blacklist)
        target.user_whitelist = list(whitelist)
        if not self.share_mode:
            config_manager.save()


def _scrub_url_credentials(q: str) -> str:
    """Audit Y5 + R6-05: never persist a pasted URL with embedded credentials.

    Strips `user:pass@` AND sensitive query params (`api_key=`, `token=`, `login=`,
    ...) that Gelbooru/Danbooru API URLs carry. Non-URL queries are returned
    untouched; safe query params are preserved.
    """
    if "://" not in q:
        return q
    parts = urlsplit(q.strip())
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _SENSITIVE_QUERY_PARAMS
    ]
    return urlunsplit((parts.scheme, host, parts.path, urlencode(kept), ""))


def record_search_history(
    query: str,
    limit: int = MAX_SEARCH_HISTORY,
    persist: bool = True,
) -> list[str]:
    """v1.0.6: prepend a search to the persisted history (dedup, most-recent-first).

    Empty/whitespace queries are ignored. Case-insensitive dedup keeps the newest
    position. The list is capped so the dropdown never grows unbounded.
    Audit Y5: pasted URLs are stored with any embedded user:pass credentials stripped.
    """
    q = _scrub_url_credentials((query or "").strip())
    current = [str(x).strip() for x in (config_manager.config.search_history or []) if str(x).strip()]
    if not q:
        return current[:limit]
    deduped = [h for h in current if h.lower() != q.lower()]
    deduped.insert(0, q)
    new_history = deduped[:limit]
    if persist:
        config_manager.config.search_history = new_history
        config_manager.save()
    return new_history


def populate_query_from_recent(value: Any) -> Any:
    """v1.0.6 (revised): fill the Search-tags bar from a recent-search selection."""
    return value if value else gr.skip()


def compute_top_tags(history: list[str] | None, limit: int = 8) -> list[str]:
    """v1.0.6 (top tags): derive the most-reused individual tags from search history."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    first_seen: dict[str, int] = {}
    for idx, query in enumerate(history or []):
        for tag in re.split(r"[,\s]+", str(query or "")):
            tag = tag.strip()
            if not tag or "://" in tag or len(tag) > 40:
                continue
            key = tag.lower()
            counts[key] = counts.get(key, 0) + 1
            if key not in display:
                display[key] = tag
                first_seen[key] = idx
    ranked = sorted(counts, key=lambda k: (-counts[k], first_seen[k]))
    return [display[k] for k in ranked[:limit]]


def _append_tag_to_url(url: str, tag: str, lowered: str) -> str:
    """R7-02: appends `tag` to the `tags` query parameter of a booru search URL (dedup).

    Falls back to adding a new `tags` parameter when the URL carries none, so a
    pasted search URL is never corrupted by comma-joining a tag into the string.
    """
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    for i, (k, v) in enumerate(pairs):
        if k.lower() == "tags":
            existing = [x for x in v.replace(",", " ").split() if x]
            if not any(x.lower() == lowered for x in existing):
                existing.append(tag)
            pairs[i] = ("tags", " ".join(existing))
            break
    else:
        pairs.append(("tags", tag))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def add_top_tag_to_query(current_query: str | None, selected_tag: str | None) -> tuple[str, Any]:
    """v1.0.6 (top tags) / R7-02: append a chosen tag to the search bar (dedup, no auto-run).

    URL-aware: when the current query is an http(s) URL, the tag is merged into the
    URL's `tags` query parameter instead of being comma-joined into the URL string,
    which would break URL-based searches.
    """
    q = (current_query or "").strip()
    tag = (selected_tag or "").strip()
    if tag:
        lowered = tag.lower()
        if re.match(r"^https?://", q, re.IGNORECASE):
            q = _append_tag_to_url(q, tag, lowered)
        else:
            tags = [x.strip() for x in q.replace("\n", ",").split(",") if x.strip()]
            if not any(x.lower() == lowered for x in tags):
                tags.append(tag)
            q = ", ".join(tags)
    return q, gr.update(value=None)


def build_normalizer_from_ui(
    replace_underscores: bool,
    escape_parens: bool,
    filter_junk: bool,
    junk_text: str,
    semantic_order_str: str,
    separator: str,
    persist: bool = False,
    store: PersonalListStore | None = None,
    session_lists: SessionLists | None = None,
) -> PromptNormalizer:
    """Constructs a PromptNormalizer from live UI controls.
    Only writes to disk when persist=True and not in `--share` mode (C6, X8).
    """
    junk_list = [x.strip() for x in junk_text.replace("\n", ",").split(",") if x.strip()]
    valid_cats: set[str] = {"copyright", "character", "artist", "general", "meta"}
    order_raw = [x.strip().lower() for x in semantic_order_str.split(">") if x.strip()]
    order: list[TagCategory] = [x for x in order_raw if x in valid_cats]  # type: ignore[misc]
    for c in DEFAULT_SEMANTIC_ORDER:
        if c not in order:
            order.append(c)

    if store is not None and store.share_mode:
        target = store.resolve_target(session_lists)
        target.junk_tags_list = list(junk_list)
        cfg = NormalizerConfig(
            replace_underscores=replace_underscores,
            escape_parentheses=escape_parens,
            filter_junk_tags=filter_junk,
            junk_tags_list=junk_list,
            user_blacklist=list(target.user_blacklist),
            user_whitelist=list(target.user_whitelist),
            semantic_order=order,
            custom_separator=separator or ", ",
        )
        return PromptNormalizer(cfg)

    prev_norm = config_manager.config.normalizer
    cfg = NormalizerConfig(
        replace_underscores=replace_underscores,
        escape_parentheses=escape_parens,
        filter_junk_tags=filter_junk,
        junk_tags_list=junk_list,
        user_blacklist=list(prev_norm.user_blacklist),
        user_whitelist=list(prev_norm.user_whitelist),
        semantic_order=order,
        custom_separator=separator or ", ",
    )
    config_manager.config.normalizer = cfg
    if persist:
        config_manager.save()
    return PromptNormalizer(cfg)
