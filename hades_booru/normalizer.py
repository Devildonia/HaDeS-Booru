"""
Tag Normalization & Semantic Prompt Formatting Engine.
Handles kaomoji preservation, underscore conversion, parenthesis escaping,
wildcard junk tag filtering, semantic ordering, and trigger words.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from hades_booru.models import COMMON_META_TAGS, NormalizerConfig, Post, TagCategory

KAOMOJI_SET: set[str] = {
    "^_^",
    "(^_^)",
    "o_o",
    "(o_o)",
    "o_0",
    "0_o",
    "0_0",
    "(0_0)",
    "x_x",
    "(x_x)",
    "x_o",
    "o_x",
    ">_<",
    "(>_<)",
    "-_-",
    "(-_-)",
    "=_=",
    "(=_=)",
    "._.",
    "(._.)",
    ";_;",
    "(;_;)",
    "@_@",
    "(@_@)",
    "+_+",
    "(+_+)",
    "*_*",
    "(*_*)",
    "t_t",
    "(t_t)",
    "<o>_<o>",
    "(^o^)",
    "\\(^o^)/",
    "(/_\\)",
    "(`_´)",
    "(`Д´)",
    "(´_ゝ`)",
    "u_u",
    "(u_u)",
    "v_v",
    "(v_v)",
    "^o^",
    "\\o/",
}

KAOMOJI_PATTERN = re.compile(
    r"^(?:\\?\(?[o0xuv\^><@\+\-=\.;\*~'´`Д\|]+_[o0xuv\^><@\+\-=\.;\*~'´`Д\|]+\)?\\?|\(?\^[o_\-]\^\)?)$",
    re.IGNORECASE,
)

UNESCAPED_OPEN_PAREN = re.compile(r"(?<!\\)\(")
UNESCAPED_CLOSE_PAREN = re.compile(r"(?<!\\)\)")
UNDERSCORE_RUN = re.compile(r"_+")


def is_kaomoji_tag(tag: str) -> bool:
    """Checks whether a tag is a facial emoticon/kaomoji that should be preserved verbatim."""
    lower = tag.strip().lower()
    return lower in KAOMOJI_SET or bool(KAOMOJI_PATTERN.match(lower))


def normalize_tag_key(tag: str) -> str:
    """Canonical comparison key for a tag (lowercase, underscores instead of spaces)."""
    return tag.strip().lower().replace(" ", "_")


def parse_tag_list(text: str) -> list[str]:
    """Parses a user-entered tag list (comma or newline separated) into clean, deduplicated entries."""
    result: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[\n,]", text or ""):
        tag = chunk.strip()
        if not tag:
            continue
        key = normalize_tag_key(tag)
        if key not in seen:
            seen.add(key)
            result.append(tag)
    return result


def add_tags(existing: list[str], new_tags: list[str]) -> tuple[list[str], list[str]]:
    """Appends new tags to an existing list (deduplicated). Returns (new_list, actually_added)."""
    seen = {normalize_tag_key(x) for x in existing}
    added: list[str] = []
    for tag in new_tags:
        key = normalize_tag_key(tag)
        if key not in seen:
            seen.add(key)
            existing.append(tag)
            added.append(tag)
    return existing, added


def remove_tags(existing: list[str], to_remove: list[str]) -> tuple[list[str], list[str]]:
    """Removes tags from a list (deduplicated match). Returns (new_list, actually_removed)."""
    remove_keys = {normalize_tag_key(x) for x in to_remove}
    kept: list[str] = []
    removed: list[str] = []
    for tag in existing:
        if normalize_tag_key(tag) in remove_keys:
            removed.append(tag)
        else:
            kept.append(tag)
    return kept, removed


class PromptNormalizer:
    """Deterministic prompt normalizer and semantic tag sorter."""

    def __init__(self, config: NormalizerConfig | None = None) -> None:
        self.config = config or NormalizerConfig()

    def update_config(self, new_config: NormalizerConfig) -> None:
        self.config = new_config

    def sanitize_tag(self, raw_tag: str) -> str | None:
        """Sanitizes a single tag according to active rules. Returns None if filtered as junk.

        v1.0.3: personal whitelist entries always bypass junk filtering;
        personal blacklist entries extend the default junk list.
        """
        if not raw_tag:
            return None
        tag = raw_tag.strip()
        if not tag:
            return None

        # 0. Personal whitelist: always preserved, skips junk filtering entirely
        lower_norm = tag.lower().replace(" ", "_")
        for keep in self.config.user_whitelist:
            keep_norm = keep.strip().lower().replace(" ", "_")
            if keep_norm and (lower_norm == keep_norm or lower_norm.startswith(keep_norm.rstrip("*"))):
                break
        else:
            # 1. Junk / meta tag filtering (defaults + personal blacklist, trailing wildcard '*' supported)
            if self.config.filter_junk_tags:
                effective_junk: Sequence[str] = list(self.config.junk_tags_list)
                if self.config.user_blacklist:
                    effective_junk = [*effective_junk, *self.config.user_blacklist]
                for junk in effective_junk:
                    junk_norm = junk.strip().lower().replace(" ", "_")
                    if not junk_norm:
                        continue
                    if junk_norm.endswith("*"):
                        if lower_norm.startswith(junk_norm[:-1]):
                            return None
                    elif lower_norm == junk_norm:
                        return None

        # 2. Preserve kaomojis intact without replacing underscores or escaping facial parens
        if is_kaomoji_tag(tag):
            return tag

        # 3. Replace underscores with spaces if enabled
        if self.config.replace_underscores:
            tag = UNDERSCORE_RUN.sub(" ", tag)

        # 4. Escape parentheses if enabled (without double-escaping)
        if self.config.escape_parentheses:
            tag = UNESCAPED_OPEN_PAREN.sub(r"\(", tag)
            tag = UNESCAPED_CLOSE_PAREN.sub(r"\)", tag)

        return tag.strip()

    def format_tags(self, tags: Sequence[str]) -> str:
        """Formats a sequence of tags into a deduplicated, separator-joined prompt string."""
        sanitized: list[str] = []
        seen: set[str] = set()

        for raw in tags:
            clean = self.sanitize_tag(raw)
            if clean:
                key = clean.lower()
                if key not in seen:
                    seen.add(key)
                    sanitized.append(clean)

        return self.config.custom_separator.join(sanitized)

    def extract_ordered_tags(
        self,
        post: Post,
        exclude_categories: Sequence[TagCategory] | None = None,
    ) -> list[str]:
        """Extracts sanitized, deduplicated tags from a post following semantic category order."""
        excluded = set(exclude_categories or [])
        ordered_raw: list[str] = []

        has_categorized = any(
            len(getattr(post.tags, cat)) > 0
            for cat in ("copyright", "character", "artist", "general", "meta")
        )

        if has_categorized:
            for category in self.config.semantic_order:
                if category in excluded:
                    continue
                category_tags: list[str] = getattr(post.tags, category, [])
                ordered_raw.extend(category_tags)
        else:
            # L4: partition uncategorized raw_tags into general vs meta so exclude_categories is respected.
            fallback_buckets: dict[TagCategory, list[str]] = {
                "copyright": [],
                "character": [],
                "artist": [],
                "general": [],
                "meta": [],
            }
            for raw in post.raw_tags:
                if raw.strip().lower() in COMMON_META_TAGS:
                    fallback_buckets["meta"].append(raw)
                else:
                    fallback_buckets["general"].append(raw)
            for category in self.config.semantic_order:
                if category in excluded:
                    continue
                ordered_raw.extend(fallback_buckets[category])

        result: list[str] = []
        seen: set[str] = set()

        for raw in ordered_raw:
            clean = self.sanitize_tag(raw)
            if clean:
                key = clean.lower()
                if key not in seen:
                    seen.add(key)
                    result.append(clean)

        return result

    def format_post_prompt(
        self,
        post: Post,
        exclude_categories: Sequence[TagCategory] | None = None,
        trigger_word: str = "",
    ) -> str:
        """Generates the complete normalized prompt string for a single post."""
        tags = self.extract_ordered_tags(post, exclude_categories=exclude_categories)
        body = self.config.custom_separator.join(tags)
        prefix = trigger_word.strip().rstrip(",")
        if prefix and body:
            return f"{prefix}{self.config.custom_separator}{body}"
        if prefix:
            return prefix
        return body

    def format_unified_prompt(
        self,
        posts: Sequence[Post],
        exclude_categories: Sequence[TagCategory] | None = None,
        trigger_word: str = "",
    ) -> str:
        """Combines and deduplicates tags across multiple posts while preserving semantic order."""
        excluded = set(exclude_categories or [])
        bucket: dict[TagCategory, list[str]] = {
            "copyright": [],
            "character": [],
            "artist": [],
            "general": [],
            "meta": [],
        }

        for post in posts:
            has_categorized = any(
                len(getattr(post.tags, cat)) > 0
                for cat in ("copyright", "character", "artist", "general", "meta")
            )
            if has_categorized:
                for cat in ("copyright", "character", "artist", "general", "meta"):
                    bucket[cat].extend(getattr(post.tags, cat, []))
            else:
                for raw in post.raw_tags:
                    if raw.strip().lower() in COMMON_META_TAGS:
                        bucket["meta"].append(raw)
                    else:
                        bucket["general"].append(raw)

        combined_raw: list[str] = []
        for category in self.config.semantic_order:
            if category in excluded:
                continue
            combined_raw.extend(bucket[category])

        body = self.format_tags(combined_raw)
        prefix = trigger_word.strip().rstrip(",")
        if prefix and body:
            return f"{prefix}{self.config.custom_separator}{body}"
        if prefix:
            return prefix
        return body
