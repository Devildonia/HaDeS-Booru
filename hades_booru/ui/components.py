"""
HTML Component Renderers for HaDeS Booru Gradio UI.
Generates escaped, localized HTML snippets for the header bar, inline status indicator,
inspector navigation badge, scrollable taxonomic post inspector, and dataset metrics.
"""

from __future__ import annotations

import base64
import html
import re
from collections.abc import Sequence
from pathlib import Path

from hades_booru import __version__
from hades_booru.i18n import t
from hades_booru.models import ExtractedImageMeta, Post
from hades_booru.normalizer import PromptNormalizer, normalize_tag_key, parse_tag_list

RATING_COLORS: dict[str, str] = {
    "g": "#10b981",
    "s": "#f59e0b",
    "q": "#f97316",
    "e": "#ef4444",
    "u": "#64748b",
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
      <div style="font-size: 0.74rem; color: #94a3b8; text-align: right;">
        <div>{meta_1}</div>
        <div style="color: #60a5fa; font-size: 0.7rem;">{meta_2}</div>
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
) -> str:
    """Renders the centered post position and CLIP token counter badge in the Inspector dock."""
    if total <= 0 or not prompt_text.strip():
        text = html.escape(t(lang, "nav_badge_empty"))
        return f'<div class="hades-nav-badge">{text}</div>'

    tags_list = [x.strip() for x in prompt_text.split(",") if x.strip()]
    tag_count = len(tags_list)
    word_count = len(prompt_text.replace(",", " ").split())
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
    """Renders the extracted positive tags (through the active normalizer) as chips.

    Negative-prompt tags live in their own box; chips represent the positive
    prompt that would be used for training.
    """
    chips: list[str] = []
    for raw in parse_tag_list(meta.prompt or ""):
        clean = normalizer.sanitize_tag(raw)
        if clean is None:
            suffix = html.escape(t(lang, "inspector_filtered_suffix"))
            chips.append(
                f'<span class="tag-chip tag-general" style="opacity: 0.45; text-decoration: line-through;">'
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
    rating_color = RATING_COLORS.get(post.rating, RATING_COLORS["u"])
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
            opacity = "1.0" if clean_t is not None else "0.45; text-decoration: line-through"
            chips.append(
                f'<span class="tag-chip {css_class}" style="opacity: {opacity};">{html.escape(display_t)}</span>'
            )
        sections_html.append(
            f'<div class="tag-section-title">{html.escape(label)} ({len(tag_list)})</div>'
            f'<div class="tag-cloud">{"".join(chips)}</div>'
        )

    derived_html = ""
    if post.source_id in ("deviantart", "artstation", "pawoo", "ehentai", "generic"):
        notice_txt = html.escape(t(lang, "inspector_derived_notice"))
        derived_html = (
            f'<div style="font-size: 0.72rem; color: #f59e0b; background: rgba(245, 158, 11, 0.1); '
            f'border: 1px solid rgba(245, 158, 11, 0.28); border-radius: 5px; padding: 6px 10px; margin-bottom: 10px;">'
            f"{notice_txt}</div>"
        )

    return f"""
    <div class="hades-inspector-scroll">
      <div class="meta-grid">
        <div class="meta-box">
          <strong>{lbl_source_id}</strong>
          {safe_source} &middot; #{safe_id}
        </div>
        <div class="meta-box">
          <strong>{lbl_rating}</strong>
          <span style="color: {rating_color}; font-weight: 600;">{html.escape(rating_text)}</span>
        </div>
        <div class="meta-box">
          <strong>{lbl_res}</strong>
          {html.escape(dims)}
        </div>
        <div class="meta-box">
          <strong>{lbl_link}</strong>
          <a href="{safe_url}" target="_blank" rel="noopener noreferrer" style="color: #60a5fa; text-decoration: underline;">{lbl_open}</a>
        </div>
      </div>
      {derived_html}
      {"".join(sections_html)}
    </div>
    """


def render_export_stats_html(
    posts: Sequence[Post],
    export_text: str,
    mode: str,
    lang: str = "en",
) -> str:
    """Renders live dataset metrics in the Batch Export tab."""
    post_count = len(posts)
    char_count = len(export_text)
    lines = [ln for ln in export_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    line_count = len(lines)
    unique_tags: set[str] = set()
    for ln in lines:
        for tag in ln.split(","):
            if tag.strip():
                unique_tags.add(tag.strip().lower())

    lbl_posts = html.escape(t(lang, "stats_posts"))
    val_posts = html.escape(t(lang, "stats_posts_unit", count=post_count))
    lbl_mode = html.escape(t(lang, "stats_mode"))
    lbl_lines = html.escape(t(lang, "stats_lines"))
    lbl_unique = html.escape(t(lang, "stats_unique"))
    val_unique = html.escape(t(lang, "stats_unique_val", tags=len(unique_tags), chars=f"{char_count:,}"))

    return f"""
    <div class="meta-grid" style="grid-template-columns: repeat(4, 1fr); margin-bottom: 12px;">
      <div class="meta-box"><strong>{lbl_posts}</strong>{val_posts}</div>
      <div class="meta-box"><strong>{lbl_mode}</strong>{html.escape(mode.upper())}</div>
      <div class="meta-box"><strong>{lbl_lines}</strong>{line_count}</div>
      <div class="meta-box"><strong>{lbl_unique}</strong>{val_unique}</div>
    </div>
    """
