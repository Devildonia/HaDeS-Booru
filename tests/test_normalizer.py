"""
Unit Tests for PromptNormalizer: underscores, parentheses, kaomojis, junk wildcards, semantic order, and trigger words.
"""

from __future__ import annotations

from hades_booru.models import CategorizedTags, NormalizerConfig, Post
from hades_booru.normalizer import PromptNormalizer, add_tags, parse_tag_list, remove_tags


def make_test_normalizer() -> PromptNormalizer:
    return PromptNormalizer(
        NormalizerConfig(
            replace_underscores=True,
            escape_parentheses=True,
            filter_junk_tags=True,
            junk_tags_list=["bad_id", "translated", "watermark*", "highres"],
            semantic_order=["copyright", "character", "artist", "general", "meta"],
            custom_separator=", ",
        )
    )


def test_underscores_and_parentheses_escaping() -> None:
    norm = make_test_normalizer()
    assert norm.sanitize_tag("hatsune_miku") == "hatsune miku"
    assert norm.sanitize_tag("(solo)") == r"\(solo\)"
    assert norm.sanitize_tag("fate_(series)") == r"fate \(series\)"
    # Should not double-escape already escaped parens
    assert norm.sanitize_tag(r"fate_\(series\)") == r"fate \(series\)"


def test_junk_and_wildcard_filtering() -> None:
    norm = make_test_normalizer()
    assert norm.sanitize_tag("bad_id") is None
    assert norm.sanitize_tag("translated") is None
    assert norm.sanitize_tag("watermark_sample") is None
    assert norm.sanitize_tag("highres") is None
    assert norm.sanitize_tag("1girl") == "1girl"


def test_kaomoji_preservation() -> None:
    norm = make_test_normalizer()
    assert norm.sanitize_tag("^_^") == "^_^"
    assert norm.sanitize_tag("(o_o)") == "(o_o)"
    assert norm.sanitize_tag("(>_<)") == "(>_<)"
    assert norm.sanitize_tag("(`_´)") == "(`_´)"
    assert norm.sanitize_tag("-_-") == "-_-"
    assert norm.sanitize_tag("x_x") == "x_x"


def test_semantic_order_and_trigger_word() -> None:
    norm = make_test_normalizer()
    post = Post(
        id="101",
        source_id="danbooru",
        source_name="Danbooru",
        source_url="https://danbooru.donmai.us/posts/101",
        tags=CategorizedTags(
            general=["blue_eyes", "twintails", "bad_id", "(o_o)"],
            character=["hatsune_miku"],
            copyright=["vocaloid"],
            artist=["keix"],
            meta=["highres", "absurdres"],
        ),
    )

    prompt = norm.format_post_prompt(post)
    assert prompt == "vocaloid, hatsune miku, keix, blue eyes, twintails, (o_o), absurdres"

    prompt_no_artist_meta = norm.format_post_prompt(
        post,
        exclude_categories=["artist", "meta"],
        trigger_word="miku_lora, masterpiece",
    )
    assert (
        prompt_no_artist_meta
        == "miku_lora, masterpiece, vocaloid, hatsune miku, blue eyes, twintails, (o_o)"
    )


def test_exclude_categories_on_raw_only_posts() -> None:
    """L4: posts with empty categorized tags (only raw_tags) must still respect exclude_categories."""
    norm = PromptNormalizer(
        NormalizerConfig(
            replace_underscores=True,
            escape_parentheses=True,
            filter_junk_tags=False,
            semantic_order=["copyright", "character", "artist", "general", "meta"],
            custom_separator=", ",
        )
    )
    raw_only_post = Post(
        id="202",
        source_id="generic",
        source_name="Generic",
        source_url="https://example.com/202",
        tags=CategorizedTags(),
        raw_tags=["1girl", "solo", "highres", "absurdres"],
    )

    assert norm.format_post_prompt(raw_only_post, exclude_categories=["meta"]) == "1girl, solo"
    assert norm.format_post_prompt(raw_only_post, exclude_categories=["general"]) == "highres, absurdres"
    assert norm.format_unified_prompt([raw_only_post], exclude_categories=["meta"]) == "1girl, solo"


# ---------------------------------------------------------------------------
# v1.0.3: Personal blacklist / whitelist + list management helpers
# ---------------------------------------------------------------------------

def test_personal_blacklist_extends_defaults() -> None:
    norm = PromptNormalizer(
        NormalizerConfig(
            filter_junk_tags=True,
            junk_tags_list=["watermark*"],
            user_blacklist=["commission", "skeleton"],
            custom_separator=", ",
        )
    )
    # Default junk still filtered
    assert norm.sanitize_tag("watermark_sample") is None
    # Personal blacklist entries filtered (exact match)
    assert norm.sanitize_tag("commission") is None
    assert norm.sanitize_tag("skeleton") is None
    # Unrelated tag survives
    assert norm.sanitize_tag("1girl") == "1girl"


def test_personal_blacklist_wildcard() -> None:
    norm = PromptNormalizer(
        NormalizerConfig(
            filter_junk_tags=True,
            junk_tags_list=[],
            user_blacklist=["stuffed_*"],
            custom_separator=", ",
        )
    )
    assert norm.sanitize_tag("stuffed_animal") is None
    assert norm.sanitize_tag("stuffed_rabbit") is None
    # The wildcard prefix is 'stuffed_' — the bare word 'stuffed' is NOT a prefix match
    assert norm.sanitize_tag("stuffy") == "stuffy"


def test_personal_whitelist_overrides_blacklist() -> None:
    norm = PromptNormalizer(
        NormalizerConfig(
            filter_junk_tags=True,
            junk_tags_list=["commission"],
            user_blacklist=["skeleton"],
            user_whitelist=["commission", "skeleton*"],
            custom_separator=", ",
        )
    )
    # Whitelisted tag is preserved even though it is in the junk list
    assert norm.sanitize_tag("commission") == "commission"
    # Whitelist wildcard preserves members of a blacklisted prefix
    assert norm.sanitize_tag("skeleton_pose") == "skeleton pose"
    assert norm.sanitize_tag("1girl") == "1girl"


def test_whitelist_exact_match_without_wildcard() -> None:
    """X5: a whitelist entry without '*' must match exactly, not by prefix.

    Pre-fix `startswith(keep_norm.rstrip('*'))` ran unconditionally, so a
    whitelist of 'solo' silently preserved 'solo_focus' and 'soloist'.
    """
    norm = PromptNormalizer(
        NormalizerConfig(
            filter_junk_tags=True,
            junk_tags_list=[],
            user_blacklist=["solo_focus", "soloist"],
            user_whitelist=["solo"],
            custom_separator=", ",
        )
    )
    assert norm.sanitize_tag("solo") == "solo"
    # Blacklisted look-alikes are NOT preserved by the exact 'solo' whitelist.
    assert norm.sanitize_tag("solo_focus") is None
    assert norm.sanitize_tag("soloist") is None


def test_personal_lists_respect_filter_junk_toggle() -> None:
    norm = PromptNormalizer(
        NormalizerConfig(
            filter_junk_tags=False,
            junk_tags_list=["commission"],
            user_blacklist=["skeleton"],
            custom_separator=", ",
        )
    )
    # With filtering disabled, nothing is dropped
    assert norm.sanitize_tag("commission") == "commission"
    assert norm.sanitize_tag("skeleton") == "skeleton"


def test_parse_tag_list_dedup_and_split() -> None:
    assert parse_tag_list("a, b ,  c , a") == ["a", "b", "c"]
    assert parse_tag_list("x\ny\nz") == ["x", "y", "z"]
    assert parse_tag_list("  ") == []
    assert parse_tag_list("Watermark*, watermark*") == ["Watermark*"]


def test_add_and_remove_tags_roundtrip() -> None:
    base: list[str] = ["a", "b"]
    new_list, added = add_tags(list(base), ["b", "c", "A"])
    assert added == ["c"]
    assert new_list == ["a", "b", "c"]

    reduced, removed = remove_tags(new_list, ["B", "zzz"])
    assert removed == ["b"]
    assert reduced == ["a", "c"]
