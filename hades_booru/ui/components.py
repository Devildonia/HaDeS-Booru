"""
HTML Component Renderers for HaDeS Booru Gradio UI.
Generates escaped, localized HTML snippets for the header bar, inline status indicator,
inspector navigation badge, scrollable taxonomic post inspector, tag dictionary card,
and dataset metrics using semantic CSS classes (zero hardcoded inline theme colors).
"""

from __future__ import annotations

import base64
import html
import re
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from hades_booru import __version__
from hades_booru.i18n import t
from hades_booru.models import ExtractedImageMeta, Language, Post
from hades_booru.normalizer import PromptNormalizer, normalize_tag_key, parse_tag_list
from hades_booru.tag_dictionary.service import TagRecord, get_tag_dictionary

RATING_CLASSES: dict[str, str] = {
    "g": "hades-rating-g",
    "s": "hades-rating-s",
    "q": "hades-rating-q",
    "e": "hades-rating-e",
    "u": "hades-rating-u",
}

CATEGORY_CHIP_CLASSES: dict[str, str] = {
    "copyright": "tag-copyright",
    "character": "tag-character",
    "artist": "tag-artist",
    "general": "tag-general",
    "meta": "tag-meta",
}

STATUS_DOT_COLORS: dict[str, str] = {
    "ready": "#10b981",
    "warn": "#f59e0b",
    "error": "#ef4444",
}

LOGO_PATH = Path(__file__).resolve().parent.parent.parent / "H.webp"


def _load_logo_data_uri() -> str:
    """Loads H.webp from project root and encodes it as a data URI for inline rendering."""
    if LOGO_PATH.exists():
        try:
            encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
            return f"data:image/webp;base64,{encoded}"
        except Exception:
            pass
    return ""


LOGO_DATA_URI = _load_logo_data_uri()


def render_header_html(lang: str = "en") -> str:
    """Renders the top application header bar localized to the active language."""
    title = html.escape(t(lang, "app_title"))
    subtitle = html.escape(t(lang, "app_subtitle"))
    ver_pill = html.escape(f"v{__version__}")
    badge_runtime = html.escape(t(lang, "header_badge_runtime"))
    badge_sources = html.escape(t(lang, "header_badge_sources"))
    meta_1 = html.escape(t(lang, "header_meta_line1"))
    meta_2 = html.escape(t(lang, "header_meta_line2"))

    logo_html = (
        f'<div class="hades-logo-frame">'
        f'<img class="hades-logo-img" src="{LOGO_DATA_URI}" alt="HaDeS Logo" />'
        f"</div>"
        if LOGO_DATA_URI
        else ""
    )

    return f"""
    <div class="hades-header">
      <div class="hades-title-group">
        {logo_html}
        <div>
          <h1 class="hades-brand-title">
            {title}
            <span class="hades-pill">{ver_pill}</span>
            <span class="hades-pill">{badge_runtime}</span>
            <span class="hades-pill hades-pill-accent">{badge_sources}</span>
          </h1>
          <p class="hades-subtitle">{subtitle}</p>
        </div>
      </div>
      <div class="hades-header-meta">
        <div>{meta_1}</div>
        <div class="hades-header-meta-accent">{meta_2}</div>
      </div>
    </div>
    """


def render_status_pill_html(text: str, lang: str = "en", state: str = "ready") -> str:
    """Renders the structured status readout inside the Command Deck."""
    label = html.escape(t(lang, "status_label"))
    safe_text = html.escape(text)
    dot_color = STATUS_DOT_COLORS.get(state, STATUS_DOT_COLORS["ready"])

    return f"""
    <div class="hades-status-box" title="{safe_text}">
      <div class="hades-status-label">
        <span class="hades-status-dot" style="background: {dot_color};"></span>
        {label}
      </div>
      <div class="hades-status-text">{safe_text}</div>
    </div>
    """


def render_inspector_nav_badge_html(
    index: int,
    total: int,
    prompt_text: str,
    lang: str = "en",
    separator: str = ", ",
) -> str:
    """Renders the centered post position and CLIP token counter badge in the Inspector dock.

    R7-11: tag/word counting respects the user's `custom_separator` (default ", ").
    """
    if total <= 0 or not prompt_text.strip():
        text = html.escape(t(lang, "nav_badge_empty"))
        return f'<div class="hades-nav-badge">{text}</div>'

    sep = separator if separator.strip() else ", "
    tags_list = [x.strip() for x in prompt_text.split(sep) if x.strip()]
    tag_count = len(tags_list)
    word_count = len(prompt_text.replace(sep, " ").split())
    est_tokens = max(tag_count, round(word_count * 1.35))
    display_idx = max(1, min(total, index + 1))

    badge_str = html.escape(
        t(
            lang,
            "nav_badge_active",
            idx=display_idx,
            total=total,
            tags=tag_count,
            tokens=est_tokens,
        )
    )
    return f'<div class="hades-nav-badge">{badge_str}</div>'


def render_section_header_html(title: str) -> str:
    """Renders a clean uppercase Bento card header."""
    return f'<div class="hades-section-header">{html.escape(title)}</div>'


def render_blacklist_chips_html(
    default_list: list[str],
    personal_list: list[str],
    whitelist_list: list[str],
    lang: str = "en",
) -> str:
    """Renders the active tag filter as chips: defaults, personal blacklist (accented), whitelist."""
    personal_keys = {normalize_tag_key(x) for x in personal_list}
    seen: set[str] = set()

    chips: list[str] = []
    for tag in [*default_list, *personal_list]:
        key = normalize_tag_key(tag)
        if not key or key in seen:
            continue
        seen.add(key)
        is_personal = key in personal_keys
        css = "tag-chip tag-chip-personal" if is_personal else "tag-chip"
        badge = ' <span class="hades-chip-badge">+</span>' if is_personal else ""
        chips.append(f'<span class="{css}">{html.escape(tag)}{badge}</span>')

    white_chips: list[str] = []
    for tag in whitelist_list:
        key = normalize_tag_key(tag)
        if not key:
            continue
        white_chips.append(f'<span class="tag-chip tag-chip-kept">{html.escape(tag)}</span>')

    if not chips and not white_chips:
        empty = html.escape(t(lang, "filter_chips_empty"))
        return f'<div class="hades-chip-row">{empty}</div>'

    html_parts = [f'<div class="hades-chip-row">{" ".join(chips)}</div>']
    if white_chips:
        kept_label = html.escape(t(lang, "filter_chips_kept_label"))
        html_parts.append(
            f'<div class="hades-chip-row hades-chip-kept-row">'
            f'<span class="hades-chip-kept-label">{kept_label}</span>'
            f' {" ".join(white_chips)}</div>'
        )
    return "".join(html_parts)


def render_extract_result_html(
    meta: ExtractedImageMeta,
    normalizer: PromptNormalizer,
    lang: str = "en",
) -> str:
    """Renders the extracted positive tags (through the active normalizer) as chips."""
    chips: list[str] = []
    for raw in parse_tag_list(meta.prompt or ""):
        clean = normalizer.sanitize_tag(raw)
        if clean is None:
            suffix = html.escape(t(lang, "inspector_filtered_suffix"))
            chips.append(
                f'<span class="tag-chip tag-general tag-chip-filtered">'
                f"{html.escape(raw)} {suffix}</span>"
            )
        else:
            chips.append(f'<span class="tag-chip tag-general">{html.escape(clean)}</span>')
    if not chips:
        return ""
    return f'<div class="hades-chip-row">{" ".join(chips)}</div>'


def render_post_inspector_html(
    post: Post | None,
    normalizer: PromptNormalizer,
    lang: str = "en",
) -> str:
    """Renders the taxonomic breakdown and metadata inside a fixed-height scrollable container."""
    if post is None:
        empty_title = html.escape(t(lang, "inspector_empty_title"))
        empty_msg = html.escape(t(lang, "inspector_empty"))
        return f"""
        <div class="hades-inspector-scroll">
          <div class="hades-empty-state">
            <p class="hades-empty-title">{empty_title}</p>
            <p class="hades-empty-desc">{empty_msg}</p>
          </div>
        </div>
        """

    rating_key = f"rating_{post.rating}" if post.rating in ("g", "s", "q", "e") else "rating_u"
    rating_text = t(lang, rating_key)
    rating_cls = RATING_CLASSES.get(post.rating, RATING_CLASSES["u"])
    dims = f"{post.width} x {post.height} px" if post.width and post.height else "N/A"
    safe_url = html.escape(post.source_url, quote=True)
    # Audit R6-10: only http(s) targets may be clickable — a remote JSON payload
    # could otherwise inject `javascript:`/`data:` URLs that survive html.escape.
    if not re.match(r"^https?://", post.source_url, re.IGNORECASE):
        safe_url = "#"
    safe_source = html.escape(post.source_name)
    safe_id = html.escape(post.id)

    lbl_source_id = html.escape(t(lang, "inspector_source_id"))
    lbl_rating = html.escape(t(lang, "inspector_rating"))
    lbl_res = html.escape(t(lang, "inspector_resolution"))
    lbl_link = html.escape(t(lang, "inspector_original_link"))
    lbl_open = html.escape(t(lang, "inspector_open_link"))
    filtered_suffix = t(lang, "inspector_filtered_suffix")

    sections_html: list[str] = []
    categories: list[tuple[str, str, list[str]]] = [
        (t(lang, "cat_copyright"), "tag-copyright", post.tags.copyright),
        (t(lang, "cat_character"), "tag-character", post.tags.character),
        (t(lang, "cat_artist"), "tag-artist", post.tags.artist),
        (t(lang, "cat_general"), "tag-general", post.tags.general),
        (t(lang, "cat_meta"), "tag-meta", post.tags.meta),
    ]

    for label, css_class, tag_list in categories:
        if not tag_list:
            continue
        chips: list[str] = []
        for raw_t in tag_list:
            clean_t = normalizer.sanitize_tag(raw_t)
            display_t = clean_t if clean_t is not None else f"{raw_t} {filtered_suffix}"
            extra_cls = "" if clean_t is not None else " tag-chip-filtered"
            chips.append(
                f'<span class="tag-chip {css_class}{extra_cls}">{html.escape(display_t)}</span>'
            )
        sections_html.append(
            f'<div class="tag-section-title">{html.escape(label)} ({len(tag_list)})</div>'
            f'<div class="tag-cloud">{"".join(chips)}</div>'
        )

    derived_html = ""
    if post.source_id in ("deviantart", "artstation", "pawoo", "ehentai", "generic"):
        notice_txt = html.escape(t(lang, "inspector_derived_notice"))
        derived_html = f'<div class="hades-derived-notice">{notice_txt}</div>'

    return f"""
    <div class="hades-inspector-scroll">
      <div class="meta-grid">
        <div class="meta-box">
          <strong>{lbl_source_id}</strong>
          {safe_source} &middot; #{safe_id}
        </div>
        <div class="meta-box">
          <strong>{lbl_rating}</strong>
          <span class="{rating_cls}">{html.escape(rating_text)}</span>
        </div>
        <div class="meta-box">
          <strong>{lbl_res}</strong>
          {html.escape(dims)}
        </div>
        <div class="meta-box">
          <strong>{lbl_link}</strong>
          <a href="{safe_url}" target="_blank" rel="noopener noreferrer" class="hades-link">{lbl_open}</a>
        </div>
      </div>
      {derived_html}
      {"".join(sections_html)}
    </div>
    """


def _available_count_html(lang: str) -> str:
    """Renders a high-value line showing how many tags are in the local catalog (empty string if unknown)."""
    try:
        tag_count, _ = get_tag_dictionary().count()
    except Exception:  # noqa: BLE001 - rendering must never break on a dictionary hiccup
        return ""
    if tag_count <= 0:
        return ""
    text = html.escape(t(lang, "dict_available_count", n=tag_count))
    return f'<p class="hades-empty-desc hades-dict-count">{text}</p>'


def render_tag_dictionary_html(
    record: TagRecord | None,
    query: str = "",
    lang: str = "en",
) -> str:
    """Renders the offline Tag Dictionary result card (v1.1.0)."""
    clean_q = (query or "").strip()
    if record is None:
        if not clean_q:
            title = html.escape(t(lang, "dict_empty_title"))
            desc = html.escape(t(lang, "dict_empty_desc"))
        else:
            title = html.escape(t(lang, "dict_not_found_title"))
            desc = html.escape(t(lang, "dict_not_found_desc", query=clean_q))
        return f"""
        <div class="hades-dict-card">
          <div class="hades-empty-state">
            <p class="hades-empty-title">{title}</p>
            <p class="hades-empty-desc">{desc}</p>
            {_available_count_html(lang)}
          </div>
        </div>
        """

    eff_lang: Language = cast(Language, "es" if lang == "es" else "en")
    body_text, is_fallback_en = record.definition_for(eff_lang)
    if not body_text:
        body_text = t(lang, "dict_no_definition")

    cat_label = html.escape(t(lang, f"cat_{record.category}"))
    chip_cls = CATEGORY_CHIP_CLASSES.get(record.category, "tag-general")
    safe_name = html.escape(record.name)
    safe_wiki = html.escape(record.wiki_url, quote=True)
    if not re.match(r"^https?://", record.wiki_url, re.IGNORECASE):
        safe_wiki = "#"

    resolved_html = ""
    if record.resolved_from:
        resolved_txt = html.escape(
            t(lang, "dict_resolved_alias", alias=record.resolved_from, canonical=record.name)
        )
        resolved_html = f'<div class="hades-derived-notice">{resolved_txt}</div>'

    fallback_html = ""
    if is_fallback_en:
        fb_txt = html.escape(t(lang, "dict_fallback_en_notice"))
        fallback_html = f'<div class="hades-derived-notice">{fb_txt}</div>'

    if record.aliases:
        alias_chips = " ".join(
            f'<span class="tag-chip tag-meta">{html.escape(a)}</span>' for a in record.aliases
        )
        aliases_block = f'<div class="tag-cloud">{alias_chips}</div>'
    else:
        aliases_block = (
            f'<div class="hades-subtitle">{html.escape(t(lang, "dict_no_aliases"))}</div>'
        )

    lbl_cat = html.escape(t(lang, "dict_category"))
    lbl_posts = html.escape(t(lang, "dict_post_count"))
    lbl_wiki = html.escape(t(lang, "dict_wiki_link_label"))
    lbl_wiki_open = html.escape(t(lang, "dict_wiki_open"))
    lbl_aliases = html.escape(t(lang, "dict_aliases_label"))

    return f"""
    <div class="hades-dict-card">
      {resolved_html}
      <div class="meta-grid-4">
        <div class="meta-box">
          <strong>TAG</strong>
          <span class="tag-chip {chip_cls}">{safe_name}</span>
        </div>
        <div class="meta-box">
          <strong>{lbl_cat}</strong>
          {cat_label}
        </div>
        <div class="meta-box">
          <strong>{lbl_posts}</strong>
          {record.post_count:,}
        </div>
        <div class="meta-box">
          <strong>{lbl_wiki}</strong>
          <a href="{safe_wiki}" target="_blank" rel="noopener noreferrer" class="hades-link">{lbl_wiki_open}</a>
        </div>
      </div>
      {fallback_html}
      <div class="hades-dict-body">{html.escape(body_text)}</div>
      <div class="tag-section-title">{lbl_aliases} ({len(record.aliases)})</div>
      {aliases_block}
    </div>
    """


def render_export_stats_html(
    posts: Sequence[Post],
    export_text: str,
    mode: str,
    lang: str = "en",
    separator: str = ", ",
) -> str:
    """Renders live dataset metrics in the Batch Export tab.

    R7-11: unique-tag counting respects the user's `custom_separator` (default ", ").
    """
    post_count = len(posts)
    char_count = len(export_text)
    lines = [ln for ln in export_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    line_count = len(lines)
    sep = separator if separator.strip() else ", "
    unique_tags: set[str] = set()
    for ln in lines:
        for tag in ln.split(sep):
            if tag.strip():
                unique_tags.add(tag.strip().lower())

    lbl_posts = html.escape(t(lang, "stats_posts"))
    val_posts = html.escape(t(lang, "stats_posts_unit", count=post_count))
    lbl_mode = html.escape(t(lang, "stats_mode"))
    lbl_lines = html.escape(t(lang, "stats_lines"))
    lbl_unique = html.escape(t(lang, "stats_unique"))
    val_unique = html.escape(t(lang, "stats_unique_val", tags=len(unique_tags), chars=f"{char_count:,}"))

    return f"""
    <div class="meta-grid-4">
      <div class="meta-box"><strong>{lbl_posts}</strong>{val_posts}</div>
      <div class="meta-box"><strong>{lbl_mode}</strong>{html.escape(mode.upper())}</div>
      <div class="meta-box"><strong>{lbl_lines}</strong>{line_count}</div>
      <div class="meta-box"><strong>{lbl_unique}</strong>{val_unique}</div>
    </div>
    """
