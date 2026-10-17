"""
Unit Tests for PromptNormalizer: underscores, parentheses, kaomojis, junk wildcards, semantic order, and trigger words.
"""

from __future__ import annotations

from hades_booru.models import CategorizedTags, NormalizerConfig, Post
from hades_booru.normalizer import PromptNormalizer


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
