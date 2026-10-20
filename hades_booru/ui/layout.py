"""
Gradio Blocks Layout & Event Wiring for HaDeS Booru.
Implements:
- Symmetric 2-tier Command Deck
- Equal-height 660px Split-Pane Gallery & Inspector backed by DiskImageCache (C2)
- Decoupled live preview (persist=False on Textbox keystroke) vs blur/submit persistence (C6)
- Session-only vs 0600 disk credential persistence (C7)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import gradio as gr

from hades_booru import __version__
from hades_booru.adapters.registry import registry
from hades_booru.config import config_manager
from hades_booru.exporter import bulk_exporter
from hades_booru.i18n import (
    get_exclude_category_choices,
    get_export_mode_choices,
    get_quality_choices,
    get_rating_choices,
    t,
)
from hades_booru.image_cache import image_cache
from hades_booru.metadata_extractor import (
    MetadataExtractionError,
    extract_image_metadata,
    format_settings_lines,
)
from hades_booru.models import (
    DEFAULT_JUNK_TAGS,
    DEFAULT_SEMANTIC_ORDER,
    ExportMode,
    ImageQuality,
    NormalizerConfig,
    Post,
    TagCategory,
)
from hades_booru.normalizer import PromptNormalizer, add_tags, normalize_tag_key, parse_tag_list, remove_tags
from hades_booru.ui.components import (
    render_blacklist_chips_html,
    render_export_stats_html,
    render_extract_result_html,
    render_header_html,
    render_inspector_nav_badge_html,
    render_post_inspector_html,
    render_section_header_html,
    render_status_pill_html,
)


def build_gallery_items(posts: list[Post], quality: ImageQuality) -> list[tuple[str, str]]:
    """Resolves disk-cached gallery image paths for all posts in the batch (C2)."""
    return image_cache.build_gallery_items(posts, quality)


MAX_SEARCH_HISTORY = 12


def record_search_history(query: str, limit: int = MAX_SEARCH_HISTORY) -> list[str]:
    """v1.0.6: prepend a search to the persisted history (dedup, most-recent-first).

    Empty/whitespace queries are ignored. Case-insensitive dedup keeps the newest
    position. The list is capped so the dropdown never grows unbounded.
    """
    q = (query or "").strip()
    current = [str(x).strip() for x in (config_manager.config.search_history or []) if str(x).strip()]
    if not q:
        return current[:limit]
    deduped = [h for h in current if h.lower() != q.lower()]
    deduped.insert(0, q)
    new_history = deduped[:limit]
    config_manager.config.search_history = new_history
    config_manager.save()
    return new_history


def populate_query_from_recent(value):
    """v1.0.6 (revised): fill the Search-tags bar from a recent-search selection.

    A real selection returns the query text to drop into the search bar. An empty / None
    value (e.g. the Clear button resetting the dropdown to None) returns gr.skip(), so the
    search bar is left untouched and — crucially — no search is executed on Clear.
    """
    return value if value else gr.skip()


def compute_top_tags(history, limit: int = 8) -> list[str]:
    """v1.0.6 (top tags): derive the most-reused individual tags from search history.

    Splits each stored query into tags, counts frequency (case-insensitive), and ranks by
    count desc then most-recent occurrence. Returns the top `limit` tags in their original
    (most-recent) casing. Pure derivation from existing history — no new persisted state.
    """
    import re

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


def add_top_tag_to_query(current_query, selected_tag) -> tuple[str, Any]:
    """v1.0.6 (top tags): append a chosen tag to the search bar (dedup, no auto-run).

    Returns the updated query plus a reset update for the picker so it is ready for the
    next tag. An empty selection leaves the query unchanged.
    """
    q = (current_query or "").strip()
    tag = (selected_tag or "").strip()
    if tag:
        tags = [x.strip() for x in q.replace("\n", ",").split(",") if x.strip()]
        if not any(x.lower() == tag.lower() for x in tags):
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
) -> PromptNormalizer:
    """Constructs a PromptNormalizer from live UI controls.
    Only writes to disk when persist=True (avoiding disk writes on every keystroke, C6).
    """
    junk_list = [x.strip() for x in junk_text.replace("\n", ",").split(",") if x.strip()]
    valid_cats: set[str] = {"copyright", "character", "artist", "general", "meta"}
    order_raw = [x.strip().lower() for x in semantic_order_str.split(">") if x.strip()]
    order: list[TagCategory] = [x for x in order_raw if x in valid_cats]  # type: ignore[misc]
    for c in DEFAULT_SEMANTIC_ORDER:
        if c not in order:
            order.append(c)

    # v1.0.3: carry the personal blacklist/whitelist across config rebuilds so
    # UI-driven refreshes never silently wipe the user's personal lists.
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


def open_native_folder_dialog(current_dir: str, lang: str = "en") -> str:
    """Opens the native OS folder selection dialog via an isolated Python subprocess."""
    dialog_title = t(lang, "folder_dialog_title")
    script = (
        "import tkinter as tk; from tkinter import filedialog; "
        "root = tk.Tk(); root.attributes('-topmost', True); root.withdraw(); "
        f"path = filedialog.askdirectory(initialdir={repr(current_dir)}, title={repr(dialog_title)}); "
        "print(path or '')"
    )
    try:
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        chosen = res.stdout.strip()
        if chosen:
            config_manager.config.export.local_export_dir = chosen
            config_manager.save()
            return chosen
    except Exception:
        pass
    return current_dir


def open_folder_in_explorer(folder_path: str, lang: str = "en") -> str:
    """Opens the target folder in the OS file manager."""
    target = Path(folder_path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return t(lang, "explorer_opened", path=str(target))
    except Exception as err:
        return t(lang, "explorer_error", error=str(err), path=str(target))


def _cred_placeholder(has_value: bool, lang: str, is_secret: bool = False) -> str | None:
    """Returns a generic masked placeholder when a credential is saved, never exposing the value itself."""
    if not has_value:
        return None
    return t(lang, "cred_key_saved_placeholder" if is_secret else "cred_user_saved_placeholder")


def create_gradio_app() -> gr.Blocks:
    """Creates and wires the complete Gradio Blocks application starting with a clean empty state."""
    cfg = config_manager.config
    lang = cfg.language
    quality = cfg.image_quality
    norm_cfg = cfg.normalizer
    exp_cfg = cfg.export

    initial_normalizer = PromptNormalizer(norm_cfg)
    initial_posts: list[Post] = []
    initial_gallery: list[tuple[str, str]] = []
    initial_prompt = ""
    initial_nav_badge = render_inspector_nav_badge_html(0, 0, "", lang=lang)
    initial_inspector = render_post_inspector_html(None, initial_normalizer, lang=lang)
    initial_export_preview = ""
    initial_export_stats = render_export_stats_html(
        initial_posts, initial_export_preview, exp_cfg.default_mode, lang=lang
    )
    initial_status = render_status_pill_html(t(lang, "status_ready"), lang=lang, state="ready")

    with gr.Blocks(title=f"HaDeS Booru v{__version__}") as app:
        posts_state = gr.State(value=initial_posts)
        selected_idx_state = gr.State(value=0)

        # 1. Header Bar
        header_html_box = gr.HTML(render_header_html(lang=lang))

        # 2. Symmetric 2-Tier Command Deck
        with gr.Group():
            with gr.Row(variant="panel", elem_classes=["hades-command-row"]):
                source_dropdown = gr.Dropdown(
                    choices=registry.get_dropdown_choices(),
                    value="danbooru",
                    label=t(lang, "source_label"),
                    scale=3,
                )
                query_input = gr.Textbox(
                    value="",
                    label=t(lang, "query_label"),
                    placeholder=t(lang, "query_placeholder"),
                    scale=7,
                )
                search_btn = gr.Button(
                    t(lang, "search_btn"),
                    variant="primary",
                    scale=2,
                    elem_classes=["hades-search-btn"],
                )

            # v1.0.6: recent searches (left half) + top tags (right half), side by side.
            # - Recent searches: persisted, most-recent-first; selecting one fills the
            #   Search-tags bar (no auto-run); "Clear" wipes the stored history.
            # - Top tags: the most-reused individual tags derived from that history;
            #   "Add" appends the picked tag to the Search-tags bar (dedup, no auto-run).
            with gr.Row(equal_height=True):
                with gr.Row(scale=1, variant="panel", elem_classes=["hades-command-row"]):
                    recent_dropdown = gr.Dropdown(
                        choices=list(config_manager.config.search_history or []),
                        value=None,
                        label=t(lang, "recent_label"),
                        # Selection-only: free text belongs in the Search-tags bar above;
                        # the dropdown is a strict picker over recorded history (audit v1.0.6).
                        allow_custom_value=False,
                        scale=5,
                    )
                    clear_history_btn = gr.Button(
                        t(lang, "clear_history_btn"), scale=1, size="sm"
                    )
                with gr.Row(scale=1, variant="panel", elem_classes=["hades-command-row"]):
                    top_tags_dropdown = gr.Dropdown(
                        choices=compute_top_tags(config_manager.config.search_history),
                        value=None,
                        label=t(lang, "top_tags_label"),
                        allow_custom_value=False,
                        scale=5,
                    )
                    top_tags_add_btn = gr.Button(
                        t(lang, "top_tags_add_btn"), scale=1, size="sm"
                    )

            with gr.Row(variant="panel", elem_classes=["hades-command-row"]):
                limit_dropdown = gr.Dropdown(
                    choices=[20, 50, 100, 200, 500],
                    value=20,
                    label=t(lang, "limit_label"),
                    scale=2,
                )
                rating_filter = gr.Dropdown(
                    choices=get_rating_choices(lang),
                    value="all",
                    label=t(lang, "rating_label"),
                    scale=2,
                )
                quality_dropdown = gr.Dropdown(
                    choices=get_quality_choices(lang),
                    value=quality,
                    label=t(lang, "quality_label"),
                    scale=3,
                )
                lang_dropdown = gr.Dropdown(
                    choices=[("English", "en"), ("Español", "es")],
                    value=lang,
                    label=t(lang, "lang_label"),
                    scale=2,
                )
                status_banner = gr.HTML(
                    value=initial_status,
                )

        # 3. Main Application Tabs
        with gr.Tabs():
            # =========================================================================
            # TAB 1: SYMMETRIC SPLIT-PANE GALLERY & INSPECTOR (660px Coordinated Height)
            # =========================================================================
            with gr.TabItem(t(lang, "tab_gallery")) as tab_gallery_item:
                with gr.Row():
                    # Left Pane: Visual Grid (660px, served from DiskImageCache paths)
                    with gr.Column(scale=7):
                        gallery = gr.Gallery(
                            value=initial_gallery,
                            label=t(lang, "gallery_label"),
                            columns=5,
                            rows=3,
                            height=660,
                            object_fit="cover",
                            allow_preview=True,
                            show_label=True,
                        )

                    # Right Pane: Inspector Dock (660px matched)
                    with gr.Column(scale=5):
                        with gr.Row(elem_classes=["hades-nav-bar"]):
                            prev_post_btn = gr.Button(t(lang, "prev_post_btn"), size="sm", scale=1)
                            nav_badge_box = gr.HTML(value=initial_nav_badge)
                            next_post_btn = gr.Button(t(lang, "next_post_btn"), size="sm", scale=1)

                        selected_prompt_box = gr.Textbox(
                            value=initial_prompt,
                            label=t(lang, "selected_prompt_label"),
                            lines=4,
                            max_lines=4,
                            buttons=["copy"],
                            interactive=False,
                        )

                        copy_prompt_btn = gr.Button(
                            t(lang, "copy_prompt_btn"),
                            size="sm",
                            variant="secondary",
                            elem_classes=["hades-copy-btn"],
                        )

                        blacklist_post_btn = gr.Button(
                            t(lang, "blacklist_post_btn"),
                            size="sm",
                            variant="secondary",
                            elem_classes=["hades-copy-btn"],
                        )

                        inspector_html = gr.HTML(value=initial_inspector)

            # =========================================================================
            # TAB 2: SYMMETRIC 6:6 BENTO BATCH EXPORT
            # =========================================================================
            with gr.TabItem(t(lang, "tab_export")) as tab_export_item:
                export_stats_box = gr.HTML(value=initial_export_stats)

                with gr.Row():
                    # Left Column (scale=6): Format & Live Output Preview
                    with gr.Column(scale=6, variant="panel"):
                        card_export_cfg_hdr = gr.HTML(
                            render_section_header_html(t(lang, "card_export_config_title"))
                        )
                        export_mode_radio = gr.Radio(
                            choices=get_export_mode_choices(lang),
                            value=exp_cfg.default_mode if exp_cfg.default_mode != "local-folder" else "dataset",
                            label=t(lang, "export_mode_label"),
                        )

                        with gr.Row():
                            trigger_word_input = gr.Textbox(
                                value=exp_cfg.trigger_word,
                                label=t(lang, "trigger_word_label"),
                                placeholder=t(lang, "trigger_word_placeholder"),
                                scale=1,
                            )
                            filename_prefix_input = gr.Textbox(
                                value=exp_cfg.filename_prefix,
                                label=t(lang, "filename_prefix_label"),
                                placeholder=t(lang, "filename_prefix_placeholder"),
                                scale=1,
                            )

                        exclude_cats_chk = gr.CheckboxGroup(
                            choices=get_exclude_category_choices(lang),
                            value=exp_cfg.exclude_categories,
                            label=t(lang, "exclude_cats_label"),
                        )
                        include_header_chk = gr.Checkbox(
                            value=exp_cfg.include_metadata_header,
                            label=t(lang, "include_header_label"),
                        )

                        export_preview_box = gr.Textbox(
                            value=initial_export_preview,
                            label=t(lang, "export_preview_label"),
                            lines=11,
                            max_lines=11,
                            buttons=["copy"],
                            interactive=False,
                        )

                    # Right Column (scale=6): Two Structured Delivery Cards
                    with gr.Column(scale=6):
                        with gr.Column(variant="panel"):
                            card_file_exp_hdr = gr.HTML(
                                render_section_header_html(t(lang, "card_file_export_title"))
                            )
                            zip_include_images_chk = gr.Checkbox(
                                value=False,
                                label=t(lang, "zip_include_images_label"),
                            )
                            generate_file_btn = gr.Button(
                                t(lang, "generate_file_btn"),
                                variant="primary",
                            )
                            download_file_output = gr.File(
                                label=t(lang, "download_file_label"),
                                interactive=False,
                            )

                        with gr.Column(variant="panel"):
                            card_folder_exp_hdr = gr.HTML(
                                render_section_header_html(t(lang, "card_folder_export_title"))
                            )
                            with gr.Row():
                                local_folder_input = gr.Textbox(
                                    value=str(Path(exp_cfg.local_export_dir).resolve()),
                                    label=t(lang, "local_folder_label"),
                                    scale=3,
                                )
                                browse_folder_btn = gr.Button(
                                    t(lang, "browse_folder_btn"),
                                    scale=1,
                                )

                            with gr.Row():
                                download_imgs_local_chk = gr.Checkbox(
                                    value=True,
                                    label=t(lang, "download_imgs_local_label"),
                                    scale=1,
                                )
                                high_res_local_chk = gr.Checkbox(
                                    value=exp_cfg.download_high_res,
                                    label=t(lang, "high_res_local_label"),
                                    scale=1,
                                )

                            with gr.Row():
                                save_local_folder_btn = gr.Button(
                                    t(lang, "save_local_folder_btn"),
                                    variant="primary",
                                    scale=1,
                                )
                                open_explorer_btn = gr.Button(
                                    t(lang, "open_explorer_btn"),
                                    variant="secondary",
                                    scale=1,
                                )

                            local_export_status = gr.Markdown("")

            # =========================================================================
            # TAB 3: IMAGE TO PROMPT (v1.0.3) — local metadata extraction
            # =========================================================================
            with gr.TabItem(t(lang, "tab_extract")) as tab_extract_item:
                extract_heading_hdr = gr.HTML(
                    render_section_header_html(t(lang, "extract_heading"))
                )
                extract_sub_md = gr.Markdown(t(lang, "extract_subheading"))
                # v1.0.6: file_count="multiple" keeps the drop zone visible after a file
                # is loaded (Gradio hides it in "single" mode once populated), so a new
                # image can be dragged in to replace the current one. The handlers below
                # always analyze the LATEST file (last in the list).
                extract_file_input = gr.File(
                    label=t(lang, "extract_file_label"),
                    file_count="multiple",
                    file_types=[".png", ".jpg", ".jpeg", ".webp"],
                )
                extract_preview = gr.Image(
                    label=t(lang, "extract_preview_label"),
                    type="filepath",
                    interactive=False,
                    height=320,
                )
                extract_btn = gr.Button(t(lang, "extract_btn"), variant="primary")
                extract_clear_btn = gr.Button(t(lang, "extract_clear_btn"), size="sm")
                extract_status_box = gr.HTML(value="")
                extract_info_md = gr.Markdown("")
                extract_positive_box = gr.Textbox(
                    label=t(lang, "extract_positive_label"),
                    lines=5,
                    max_lines=10,
                    buttons=["copy"],
                    interactive=False,
                )
                extract_negative_box = gr.Textbox(
                    label=t(lang, "extract_negative_label"),
                    lines=3,
                    max_lines=8,
                    buttons=["copy"],
                    interactive=False,
                )
                extract_settings_box = gr.Textbox(
                    label=t(lang, "extract_settings_label"),
                    lines=4,
                    max_lines=10,
                    buttons=["copy"],
                    interactive=False,
                )
                extract_tags_html = gr.HTML(value="")

            # =========================================================================
            # TAB 4: PERSONAL TAG LIST (v1.0.3) — dedicated panel
            # =========================================================================
            with gr.TabItem(t(lang, "tab_personal")) as tab_personal_item:
                personal_heading_hdr = gr.HTML(
                    render_section_header_html(t(lang, "personal_list_heading"))
                )
                personal_sub_md = gr.Markdown(t(lang, "personal_subheading"))
                personal_chips_box = gr.HTML(
                    value=render_blacklist_chips_html(
                        norm_cfg.junk_tags_list,
                        norm_cfg.user_blacklist,
                        norm_cfg.user_whitelist,
                        lang=lang,
                    )
                )
                with gr.Row():
                    # Left Card: Blacklist (always excluded)
                    with gr.Column(scale=1, variant="panel"):
                        personal_bl_hdr = gr.HTML(render_section_header_html(t(lang, "blacklist_heading")))
                        with gr.Row():
                            blacklist_add_input = gr.Textbox(
                                placeholder=t(lang, "blacklist_add_placeholder"),
                                scale=3,
                            )
                            blacklist_add_btn = gr.Button(
                                t(lang, "blacklist_add_btn"),
                                variant="secondary",
                                size="sm",
                                scale=1,
                            )
                        with gr.Row():
                            blacklist_remove_input = gr.Textbox(
                                placeholder=t(lang, "blacklist_remove_placeholder"),
                                scale=3,
                            )
                            blacklist_remove_btn = gr.Button(
                                t(lang, "blacklist_remove_btn"),
                                variant="secondary",
                                size="sm",
                                scale=1,
                            )
                    # Right Card: Whitelist (always kept)
                    with gr.Column(scale=1, variant="panel"):
                        personal_wl_hdr = gr.HTML(render_section_header_html(t(lang, "whitelist_heading")))
                        with gr.Row():
                            whitelist_add_input = gr.Textbox(
                                placeholder=t(lang, "whitelist_add_placeholder"),
                                scale=3,
                            )
                            whitelist_add_btn = gr.Button(
                                t(lang, "whitelist_add_btn"),
                                variant="secondary",
                                size="sm",
                                scale=1,
                            )
                        with gr.Row():
                            whitelist_remove_input = gr.Textbox(
                                placeholder=t(lang, "whitelist_remove_placeholder"),
                                scale=3,
                            )
                            whitelist_remove_btn = gr.Button(
                                t(lang, "whitelist_remove_btn"),
                                variant="secondary",
                                size="sm",
                                scale=1,
                            )
                with gr.Row():
                    reset_personal_btn = gr.Button(
                        t(lang, "reset_personal_btn"),
                        variant="secondary",
                        size="sm",
                        scale=1,
                    )
                personal_status_md = gr.Markdown("")

            # =========================================================================
            # TAB 5: SYMMETRIC 6:6 NORMALIZATION & 2x2 API CREDENTIALS GRID
            # =========================================================================
            with gr.TabItem(t(lang, "tab_settings")) as tab_settings_item:
                with gr.Row():
                    # Left Card (scale=6): Tag Normalization Rules
                    with gr.Column(scale=6, variant="panel"):
                        norm_heading_hdr = gr.HTML(
                            render_section_header_html(t(lang, "norm_heading"))
                        )
                        replace_underscores_chk = gr.Checkbox(
                            value=norm_cfg.replace_underscores,
                            label=t(lang, "replace_underscores_label"),
                        )
                        escape_parens_chk = gr.Checkbox(
                            value=norm_cfg.escape_parentheses,
                            label=t(lang, "escape_parens_label"),
                        )
                        filter_junk_chk = gr.Checkbox(
                            value=norm_cfg.filter_junk_tags,
                            label=t(lang, "filter_junk_label"),
                        )

                        with gr.Row():
                            semantic_order_dropdown = gr.Dropdown(
                                choices=[
                                    "copyright > character > artist > general > meta",
                                    "artist > character > copyright > general > meta",
                                    "character > copyright > artist > general > meta",
                                    "general > character > copyright > artist > meta",
                                ],
                                value=" > ".join(norm_cfg.semantic_order),
                                label=t(lang, "semantic_order_label"),
                                scale=3,
                            )
                            separator_input = gr.Textbox(
                                value=norm_cfg.custom_separator,
                                label=t(lang, "separator_label"),
                                scale=1,
                            )

                        junk_tags_textbox = gr.Textbox(
                            value=", ".join(norm_cfg.junk_tags_list),
                            label=t(lang, "junk_tags_label"),
                            lines=5,
                            max_lines=5,
                        )
                        reset_junk_btn = gr.Button(
                            t(lang, "reset_junk_btn"),
                            variant="secondary",
                            size="sm",
                        )

                    # Right Card (scale=6): 2x2 API Credentials Grid
                    with gr.Column(scale=6, variant="panel"):
                        creds_heading_hdr = gr.HTML(
                            render_section_header_html(t(lang, "creds_heading"))
                        )
                        creds_sub_md = gr.Markdown(t(lang, "creds_subheading"))

                        # Saved credentials are NEVER passed to value= or placeholder=
                        # (both are serialized into Gradio's /config JSON). Only generic masked
                        # indicators are shown when a credential is present.
                        danbooru_cred = config_manager.get_credentials("danbooru")
                        e621_cred = config_manager.get_credentials("e621")
                        gelbooru_cred = config_manager.get_credentials("gelbooru")
                        rule34_cred = config_manager.get_credentials("rule34")

                        with gr.Row():
                            with gr.Group():
                                gr.HTML('<div class="hades-cred-title">Danbooru (danbooru.donmai.us)</div>')
                                danbooru_user = gr.Textbox(
                                    placeholder=_cred_placeholder(bool(danbooru_cred.user_id), lang),
                                    label="Username",
                                )
                                danbooru_key = gr.Textbox(
                                    placeholder=_cred_placeholder(
                                        bool(danbooru_cred.api_key), lang, is_secret=True
                                    ),
                                    label="API Key",
                                    type="password",
                                )

                            with gr.Group():
                                gr.HTML('<div class="hades-cred-title">E621 / E926 (e621.net)</div>')
                                e621_user = gr.Textbox(
                                    placeholder=_cred_placeholder(bool(e621_cred.user_id), lang),
                                    label="Username",
                                )
                                e621_key = gr.Textbox(
                                    placeholder=_cred_placeholder(
                                        bool(e621_cred.api_key), lang, is_secret=True
                                    ),
                                    label="API Key",
                                    type="password",
                                )

                        with gr.Row():
                            with gr.Group():
                                gr.HTML('<div class="hades-cred-title">Gelbooru (gelbooru.com)</div>')
                                gelbooru_user = gr.Textbox(
                                    placeholder=_cred_placeholder(bool(gelbooru_cred.user_id), lang),
                                    label="User ID",
                                )
                                gelbooru_key = gr.Textbox(
                                    placeholder=_cred_placeholder(
                                        bool(gelbooru_cred.api_key), lang, is_secret=True
                                    ),
                                    label="API Key",
                                    type="password",
                                )

                            with gr.Group():
                                gr.HTML('<div class="hades-cred-title">Rule34 (rule34.xxx)</div>')
                                rule34_user = gr.Textbox(
                                    placeholder=_cred_placeholder(bool(rule34_cred.user_id), lang),
                                    label="User ID",
                                )
                                rule34_key = gr.Textbox(
                                    placeholder=_cred_placeholder(
                                        bool(rule34_cred.api_key), lang, is_secret=True
                                    ),
                                    label="API Key",
                                    type="password",
                                )

                        persist_creds_chk = gr.Checkbox(
                            value=cfg.persist_credentials,
                            label=t(lang, "persist_creds_label"),
                        )
                        with gr.Row():
                            save_creds_btn = gr.Button(t(lang, "save_creds_btn"), variant="primary")
                            clear_creds_btn = gr.Button(t(lang, "clear_creds_btn"), variant="secondary")
                        creds_status_md = gr.Markdown("")

        # =========================================================================
        # EVENT HANDLERS
        # =========================================================================
        norm_inputs = [
            replace_underscores_chk,
            escape_parens_chk,
            filter_junk_chk,
            junk_tags_textbox,
            semantic_order_dropdown,
            separator_input,
        ]
        export_inputs = [
            export_mode_radio,
            trigger_word_input,
            filename_prefix_input,
            exclude_cats_chk,
            include_header_chk,
        ]

        def refresh_views(
            posts: list[Post],
            sel_idx: int,
            cur_lang: str,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            exp_mode: ExportMode,
            trig_word: str,
            prefix_str: str,
            excl_cats: list[TagCategory],
            inc_header: bool,
            persist: bool = False,
        ) -> tuple[str, str, str, str, str]:
            norm = build_normalizer_from_ui(
                replace_u,
                escape_p,
                filter_j,
                junk_str,
                sem_order,
                sep,
                persist=False,
            )
            config_manager.config.export.default_mode = exp_mode
            config_manager.config.export.trigger_word = trig_word
            config_manager.config.export.filename_prefix = prefix_str
            config_manager.config.export.exclude_categories = excl_cats
            config_manager.config.export.include_metadata_header = inc_header
            if persist:
                config_manager.save()

            eff_idx = sel_idx if posts and 0 <= sel_idx < len(posts) else 0
            post = posts[eff_idx] if posts else None
            single_prompt = (
                norm.format_post_prompt(post, exclude_categories=excl_cats, trigger_word=trig_word)
                if post
                else ""
            )
            nav_badge = render_inspector_nav_badge_html(
                eff_idx, len(posts), single_prompt, lang=cur_lang
            )
            inspector = render_post_inspector_html(post, norm, lang=cur_lang)
            source_label = post.source_name if post else "Booru"
            export_text = bulk_exporter.generate_export_content(
                posts=posts,
                mode=exp_mode,
                normalizer=norm,
                include_header=inc_header,
                source_name=source_label,
                trigger_word=trig_word,
                exclude_categories=excl_cats,
            )
            stats_html = render_export_stats_html(posts, export_text, exp_mode, lang=cur_lang)
            return single_prompt, nav_badge, inspector, export_text, stats_html

        def persist_settings_only(
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            exp_mode: ExportMode,
            trig_word: str,
            prefix_str: str,
            excl_cats: list[TagCategory],
            inc_header: bool,
        ) -> None:
            config_manager.config.export.default_mode = exp_mode
            config_manager.config.export.trigger_word = trig_word
            config_manager.config.export.filename_prefix = prefix_str
            config_manager.config.export.exclude_categories = excl_cats
            config_manager.config.export.include_metadata_header = inc_header
            build_normalizer_from_ui(
                replace_u,
                escape_p,
                filter_j,
                junk_str,
                sem_order,
                sep,
                persist=True,
            )

        def execute_search_handler(
            source_id: str,
            query_str: str,
            limit_val: int,
            rating_val: str,
            quality_val: ImageQuality,
            cur_lang: str,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            exp_mode: ExportMode,
            trig_word: str,
            prefix_str: str,
            excl_cats: list[TagCategory],
            inc_header: bool,
            progress: gr.Progress = gr.Progress(),
        ) -> tuple[Any, ...]:
            config_manager.config.image_quality = quality_val
            config_manager.config.data_saver_mode = quality_val == "text"

            trimmed_q = query_str.strip()
            detected = registry.detect_source_from_url(trimmed_q)

            effective_source = source_id
            effective_tags = trimmed_q
            status_note = ""
            status_state = "ready"

            try:
                if detected:
                    effective_source = detected.adapter.id
                    if detected.is_direct_post:
                        progress(0.2, desc=t(cur_lang, "progress_direct", source=detected.adapter.name))
                        single_post = detected.adapter.fetch_single_by_url(trimmed_q)
                        results = [single_post]
                        status_note = t(
                            cur_lang,
                            "status_direct_post",
                            id=single_post.id,
                            source=detected.adapter.name,
                        )
                    else:
                        if detected.extracted_tags is not None:
                            effective_tags = detected.extracted_tags
                        adapter = detected.adapter
                        results = adapter.search(
                            tags=effective_tags,
                            limit=int(limit_val),
                            progress_cb=lambda p, msg: progress(p, desc=msg),
                            rating=rating_val if rating_val and rating_val != "all" else None,
                        )
                        status_note = t(
                            cur_lang,
                            "status_url_search",
                            source=adapter.name,
                            count=len(results),
                            tags=effective_tags,
                        )
                        if adapter.last_warning:
                            status_note += t(
                                cur_lang, "status_partial_result", source=adapter.name, error=adapter.last_warning
                            )
                            status_state = "warn"
                else:
                    adapter = registry.get_adapter(effective_source)
                    results = adapter.search(
                        tags=effective_tags,
                        limit=int(limit_val),
                        progress_cb=lambda p, msg: progress(p, desc=msg),
                        rating=rating_val if rating_val and rating_val != "all" else None,
                    )
                    status_note = t(
                        cur_lang,
                        "status_search_done",
                        source=adapter.name,
                        count=len(results),
                    )
                    if adapter.last_warning:
                        status_note += t(
                            cur_lang, "status_partial_result", source=adapter.name, error=adapter.last_warning
                        )
                        status_state = "warn"

                # Safety net: ratings the adapter could not apply server-side
                # (unmapped values like "u", or injection skipped for danbooru's
                # anonymous 2-tag limit) are still filtered client-side. When the
                # server already applied the filter we must NOT re-filter by
                # equality: on e621 a "General" selection legitimately returns
                # posts rated "s" (its safe bucket), which equality would wipe
                # out to zero results (audit X7).
                active_adapter = detected.adapter if detected else adapter
                if (
                    rating_val
                    and rating_val != "all"
                    and not getattr(active_adapter, "server_rating_applied", False)
                ):
                    results = [p for p in results if p.rating == rating_val]
                    status_note += t(
                        cur_lang,
                        "status_filtered_rating",
                        rating=rating_val.upper(),
                        count=len(results),
                    )

                if not results:
                    status_note = t(
                        cur_lang,
                        "status_no_results",
                        source=effective_source,
                        tags=effective_tags,
                    )
                    status_state = "warn"

                progress(0.92, desc=t(cur_lang, "progress_thumbnails"))
                gallery_items = build_gallery_items(results, quality_val)

                single_prompt, nav_badge, inspector, export_text, stats_html = refresh_views(
                    results,
                    0,
                    cur_lang,
                    replace_u,
                    escape_p,
                    filter_j,
                    junk_str,
                    sem_order,
                    sep,
                    exp_mode,
                    trig_word,
                    prefix_str,
                    excl_cats,
                    inc_header,
                    persist=True,
                )

                # v1.0.6: record the executed query in history (success path only — failed
                # searches are not pinned to the dropdown). Returns the updated choices
                # plus a refreshed top-tags list (derived from the same history).
                new_history = record_search_history(trimmed_q)
                return (
                    results,
                    0,
                    effective_source,
                    effective_tags,
                    gallery_items,
                    single_prompt,
                    nav_badge,
                    inspector,
                    export_text,
                    stats_html,
                    render_status_pill_html(status_note, lang=cur_lang, state=status_state),
                    gr.update(choices=new_history, value=trimmed_q or None),
                    # Reset the picker: never leave a stale selection after a refresh.
                    gr.update(choices=compute_top_tags(new_history), value=None),
                )

            except Exception as err:
                err_msg = t(cur_lang, "status_error", error=str(err))
                single_prompt, nav_badge, inspector, export_text, stats_html = refresh_views(
                    [],
                    0,
                    cur_lang,
                    replace_u,
                    escape_p,
                    filter_j,
                    junk_str,
                    sem_order,
                    sep,
                    exp_mode,
                    trig_word,
                    prefix_str,
                    excl_cats,
                    inc_header,
                    persist=False,
                )
                # v1.0.6: failed searches do NOT change history; keep the current choices
                # and the current top-tags list (both derived from unchanged history).
                return (
                    [],
                    0,
                    effective_source,
                    effective_tags,
                    [],
                    single_prompt,
                    nav_badge,
                    inspector,
                    export_text,
                    stats_html,
                    render_status_pill_html(err_msg, lang=cur_lang, state="error"),
                    gr.update(
                        choices=list(config_manager.config.search_history or []),
                        value=None,
                    ),
                    gr.update(
                        choices=compute_top_tags(config_manager.config.search_history),
                        value=None,
                    ),
                )

        def clear_search_history_handler() -> list:
            """v1.0.6: wipe the persisted search history and reset both the recent-searches
            dropdown and the derived top-tags list (both come from the same history)."""
            config_manager.config.search_history = []
            config_manager.save()
            return [
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
            ]

        def on_quality_change(
            quality_val: ImageQuality,
            posts: list[Post],
        ) -> list[tuple[str, str]]:
            config_manager.config.image_quality = quality_val
            config_manager.config.data_saver_mode = quality_val == "text"
            config_manager.save()
            return build_gallery_items(posts, quality_val)

        def on_copy_prompt_feedback(prompt_str: str, cur_lang: str) -> str:
            if not prompt_str.strip():
                return render_status_pill_html(t(cur_lang, "status_ready"), lang=cur_lang, state="ready")
            tag_count = len([x.strip() for x in prompt_str.split(",") if x.strip()])
            msg = t(cur_lang, "status_copied", tags=tag_count)
            return render_status_pill_html(msg, lang=cur_lang, state="ready")

        def on_language_change(
            new_lang: str,
            posts: list[Post],
            sel_idx: int,
            cur_rating: str,
            cur_quality: ImageQuality,
            cur_exp_mode: ExportMode,
            cur_excl_cats: list[TagCategory],
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            trig_word: str,
            prefix_str: str,
            inc_header: bool,
        ) -> tuple[Any, ...]:
            effective_lang = "es" if new_lang == "es" else "en"
            config_manager.config.language = effective_lang  # type: ignore[assignment]

            single_prompt, nav_badge, inspector, export_text, stats_html = refresh_views(
                posts,
                sel_idx,
                effective_lang,
                replace_u,
                escape_p,
                filter_j,
                junk_str,
                sem_order,
                sep,
                cur_exp_mode,
                trig_word,
                prefix_str,
                cur_excl_cats,
                inc_header,
                persist=True,
            )

            return (
                render_header_html(lang=effective_lang),
                gr.update(label=t(effective_lang, "source_label")),
                gr.update(
                    label=t(effective_lang, "query_label"),
                    placeholder=t(effective_lang, "query_placeholder"),
                ),
                gr.update(value=t(effective_lang, "search_btn")),
                gr.update(label=t(effective_lang, "limit_label")),
                gr.update(
                    label=t(effective_lang, "rating_label"),
                    choices=get_rating_choices(effective_lang),
                    value=cur_rating,
                ),
                gr.update(
                    label=t(effective_lang, "quality_label"),
                    choices=get_quality_choices(effective_lang),
                    value=cur_quality,
                ),
                gr.update(label=t(effective_lang, "lang_label")),
                render_status_pill_html(t(effective_lang, "status_ready"), lang=effective_lang, state="ready"),
                gr.update(label=t(effective_lang, "tab_gallery")),
                gr.update(label=t(effective_lang, "tab_export")),
                gr.update(label=t(effective_lang, "tab_settings")),
                gr.update(label=t(effective_lang, "gallery_label")),
                gr.update(value=t(effective_lang, "prev_post_btn")),
                nav_badge,
                gr.update(value=t(effective_lang, "next_post_btn")),
                gr.update(label=t(effective_lang, "selected_prompt_label"), value=single_prompt),
                gr.update(value=t(effective_lang, "copy_prompt_btn")),
                inspector,
                stats_html,
                render_section_header_html(t(effective_lang, "card_export_config_title")),
                gr.update(
                    label=t(effective_lang, "export_mode_label"),
                    choices=get_export_mode_choices(effective_lang),
                    value=cur_exp_mode,
                ),
                gr.update(
                    label=t(effective_lang, "trigger_word_label"),
                    placeholder=t(effective_lang, "trigger_word_placeholder"),
                ),
                gr.update(
                    label=t(effective_lang, "filename_prefix_label"),
                    placeholder=t(effective_lang, "filename_prefix_placeholder"),
                ),
                gr.update(
                    label=t(effective_lang, "exclude_cats_label"),
                    choices=get_exclude_category_choices(effective_lang),
                    value=cur_excl_cats,
                ),
                gr.update(label=t(effective_lang, "include_header_label")),
                gr.update(label=t(effective_lang, "export_preview_label"), value=export_text),
                render_section_header_html(t(effective_lang, "card_file_export_title")),
                gr.update(label=t(effective_lang, "zip_include_images_label")),
                gr.update(value=t(effective_lang, "generate_file_btn")),
                gr.update(label=t(effective_lang, "download_file_label")),
                render_section_header_html(t(effective_lang, "card_folder_export_title")),
                gr.update(label=t(effective_lang, "local_folder_label")),
                gr.update(value=t(effective_lang, "browse_folder_btn")),
                gr.update(label=t(effective_lang, "download_imgs_local_label")),
                gr.update(label=t(effective_lang, "high_res_local_label")),
                gr.update(value=t(effective_lang, "save_local_folder_btn")),
                gr.update(value=t(effective_lang, "open_explorer_btn")),
                render_section_header_html(t(effective_lang, "norm_heading")),
                gr.update(label=t(effective_lang, "replace_underscores_label")),
                gr.update(label=t(effective_lang, "escape_parens_label")),
                gr.update(label=t(effective_lang, "filter_junk_label")),
                gr.update(label=t(effective_lang, "semantic_order_label")),
                gr.update(label=t(effective_lang, "separator_label")),
                gr.update(label=t(effective_lang, "junk_tags_label")),
                gr.update(value=t(effective_lang, "reset_junk_btn")),
                render_section_header_html(t(effective_lang, "creds_heading")),
                t(effective_lang, "creds_subheading"),
                gr.update(label=t(effective_lang, "persist_creds_label")),
                gr.update(value=t(effective_lang, "save_creds_btn")),
                gr.update(value=t(effective_lang, "clear_creds_btn")),
                # v1.0.3: new tabs & personal lists
                gr.update(label=t(effective_lang, "tab_extract")),
                gr.update(label=t(effective_lang, "tab_personal")),
                gr.update(value=t(effective_lang, "blacklist_post_btn")),
                render_section_header_html(t(effective_lang, "personal_list_heading")),
                t(effective_lang, "personal_subheading"),
                render_blacklist_chips_html(
                    config_manager.config.normalizer.junk_tags_list,
                    config_manager.config.normalizer.user_blacklist,
                    config_manager.config.normalizer.user_whitelist,
                    lang=effective_lang,
                ),
                render_section_header_html(t(effective_lang, "blacklist_heading")),
                render_section_header_html(t(effective_lang, "whitelist_heading")),
                gr.update(placeholder=t(effective_lang, "blacklist_add_placeholder")),
                gr.update(value=t(effective_lang, "blacklist_add_btn")),
                gr.update(placeholder=t(effective_lang, "blacklist_remove_placeholder")),
                gr.update(value=t(effective_lang, "blacklist_remove_btn")),
                gr.update(placeholder=t(effective_lang, "whitelist_add_placeholder")),
                gr.update(value=t(effective_lang, "whitelist_add_btn")),
                gr.update(placeholder=t(effective_lang, "whitelist_remove_placeholder")),
                gr.update(value=t(effective_lang, "whitelist_remove_btn")),
                gr.update(value=t(effective_lang, "reset_personal_btn")),
                "",
                render_section_header_html(t(effective_lang, "extract_heading")),
                t(effective_lang, "extract_subheading"),
                gr.update(label=t(effective_lang, "extract_file_label")),
                gr.update(label=t(effective_lang, "extract_preview_label")),
                gr.update(value=t(effective_lang, "extract_btn")),
                render_status_pill_html(t(effective_lang, "status_ready"), lang=effective_lang, state="ready"),
                "",
                gr.update(label=t(effective_lang, "extract_positive_label")),
                gr.update(label=t(effective_lang, "extract_negative_label")),
                gr.update(label=t(effective_lang, "extract_settings_label")),
                "",
                # v1.0.6: recent-searches row + Image to Prompt clear button + top tags
                # (appended last so the existing 0..N output indices stay stable for the
                # wiring tests).
                gr.update(label=t(effective_lang, "recent_label")),
                gr.update(value=t(effective_lang, "clear_history_btn")),
                gr.update(value=t(effective_lang, "extract_clear_btn")),
                gr.update(label=t(effective_lang, "top_tags_label")),
                gr.update(value=t(effective_lang, "top_tags_add_btn")),
            )

        def on_gallery_select(
            evt: gr.SelectData,
            posts: list[Post],
            cur_lang: str,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            trig_word: str,
            excl_cats: list[TagCategory],
        ) -> tuple[int, str, str, str]:
            idx = int(evt.index) if evt and evt.index is not None else 0
            norm = build_normalizer_from_ui(replace_u, escape_p, filter_j, junk_str, sem_order, sep, persist=False)
            post = posts[idx] if posts and 0 <= idx < len(posts) else None
            prompt = (
                norm.format_post_prompt(post, exclude_categories=excl_cats, trigger_word=trig_word)
                if post
                else ""
            )
            nav_badge = render_inspector_nav_badge_html(idx, len(posts), prompt, lang=cur_lang)
            return idx, prompt, nav_badge, render_post_inspector_html(post, norm, lang=cur_lang)

        def navigate_post_handler(
            direction: int,
            posts: list[Post],
            cur_idx: int,
            cur_lang: str,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            trig_word: str,
            excl_cats: list[TagCategory],
        ) -> tuple[int, str, str, str, dict]:
            # 5th return value: move the gallery selection to the newly selected post.
            # Gradio 6.30 Gallery exposes a `selected_index` prop (Svelte setter applies it
            # reactively), and gr.update(selected_index=N) survives the server-side
            # hasattr filter + delete_none (0 is not None). Click-to-select already works
            # because the browser sets it locally; this makes programmatic navigation work.
            if not posts:
                return (
                    0,
                    "",
                    render_inspector_nav_badge_html(0, 0, "", lang=cur_lang),
                    render_post_inspector_html(None, PromptNormalizer(), lang=cur_lang),
                    gr.update(selected_index=0),
                )
            next_idx = (cur_idx + direction) % len(posts)
            norm = build_normalizer_from_ui(replace_u, escape_p, filter_j, junk_str, sem_order, sep, persist=False)
            post = posts[next_idx]
            prompt = norm.format_post_prompt(post, exclude_categories=excl_cats, trigger_word=trig_word)
            nav_badge = render_inspector_nav_badge_html(next_idx, len(posts), prompt, lang=cur_lang)
            return (
                next_idx,
                prompt,
                nav_badge,
                render_post_inspector_html(post, norm, lang=cur_lang),
                gr.update(selected_index=next_idx),
            )

        def generate_download_file_handler(
            posts: list[Post],
            source_id: str,
            query_str: str,
            cur_lang: str,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            exp_mode: ExportMode,
            trig_word: str,
            prefix_str: str,
            excl_cats: list[TagCategory],
            inc_header: bool,
            zip_imgs: bool,
            local_dir: str,
            progress: gr.Progress = gr.Progress(),
        ) -> tuple[str | None, str]:
            if not posts:
                return None, t(cur_lang, "export_empty_warn")
            norm = build_normalizer_from_ui(replace_u, escape_p, filter_j, junk_str, sem_order, sep, persist=True)
            requested = Path(local_dir or "./exports").expanduser().resolve()
            cwd = Path.cwd().resolve()
            used_cwd_fallback = False
            try:
                requested.relative_to(cwd)
                out_dir = requested
            except ValueError:
                # Gradio can only serve files inside the server working directory;
                # fall back to a CWD-based folder instead of failing with InvalidPathError.
                out_dir = cwd / "exports"
                used_cwd_fallback = True
            file_path = bulk_exporter.create_export_file(
                posts=posts,
                mode=exp_mode,
                normalizer=norm,
                output_dir=out_dir,
                source_name=source_id,
                query_tags=query_str or "dataset",
                custom_prefix=prefix_str,
                include_header=inc_header,
                trigger_word=trig_word,
                exclude_categories=excl_cats,
                include_images_in_zip=zip_imgs,
                progress_cb=lambda p, msg: progress(p, desc=msg),
            )
            status = t(cur_lang, "export_file_saved", path=str(file_path))
            if used_cwd_fallback:
                status += t(cur_lang, "export_file_cwd_fallback_suffix", requested=str(requested))
            if bulk_exporter.last_zip_errors:
                status += t(
                    cur_lang, "export_zip_errors_suffix", count=len(bulk_exporter.last_zip_errors)
                )
            return str(file_path), status

        def save_dataset_to_folder_handler(
            posts: list[Post],
            local_dir: str,
            dl_imgs: bool,
            hi_res: bool,
            cur_lang: str,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            trig_word: str,
            excl_cats: list[TagCategory],
            progress: gr.Progress = gr.Progress(),
        ) -> str:
            if not posts:
                return t(cur_lang, "export_empty_warn")
            norm = build_normalizer_from_ui(replace_u, escape_p, filter_j, junk_str, sem_order, sep, persist=True)
            summary = bulk_exporter.export_dataset_to_local_folder(
                posts=posts,
                target_folder=local_dir,
                normalizer=norm,
                trigger_word=trig_word,
                exclude_categories=excl_cats,
                download_images=dl_imgs,
                high_res=hi_res,
                progress_cb=lambda p, msg: progress(p, desc=msg),
            )
            msg = t(
                cur_lang,
                "export_folder_saved",
                folder=summary["folder"],
                txt=summary["saved_txt"],
                img=summary["saved_img"],
            )
            if summary["failed_img"]:
                msg += t(cur_lang, "export_folder_failed_suffix", failed=summary["failed_img"])
            return msg

        def _cred_textbox_updates(cur_lang: str) -> tuple[Any, ...]:
            d_c = config_manager.get_credentials("danbooru")
            e_c = config_manager.get_credentials("e621")
            g_c = config_manager.get_credentials("gelbooru")
            r_c = config_manager.get_credentials("rule34")
            return (
                gr.update(value="", placeholder=_cred_placeholder(bool(d_c.user_id), cur_lang)),
                gr.update(value="", placeholder=_cred_placeholder(bool(d_c.api_key), cur_lang, is_secret=True)),
                gr.update(value="", placeholder=_cred_placeholder(bool(e_c.user_id), cur_lang)),
                gr.update(value="", placeholder=_cred_placeholder(bool(e_c.api_key), cur_lang, is_secret=True)),
                gr.update(value="", placeholder=_cred_placeholder(bool(g_c.user_id), cur_lang)),
                gr.update(value="", placeholder=_cred_placeholder(bool(g_c.api_key), cur_lang, is_secret=True)),
                gr.update(value="", placeholder=_cred_placeholder(bool(r_c.user_id), cur_lang)),
                gr.update(value="", placeholder=_cred_placeholder(bool(r_c.api_key), cur_lang, is_secret=True)),
            )

        def save_credentials_handler(
            cur_lang: str,
            persist_flag: bool,
            d_user: str,
            d_key: str,
            e_user: str,
            e_key: str,
            g_user: str,
            g_key: str,
            r_user: str,
            r_key: str,
        ) -> tuple[Any, ...]:
            config_manager.set_credentials_many(
                {
                    "danbooru": (d_user, d_key),
                    "e621": (e_user, e_key),
                    "gelbooru": (g_user, g_key),
                    "rule34": (r_user, r_key),
                },
                persist_to_disk=persist_flag,
            )
            msg = t(cur_lang, "creds_saved_msg") if persist_flag else t(cur_lang, "creds_saved_session_msg")
            return (msg, *_cred_textbox_updates(cur_lang))

        def clear_credentials_handler(cur_lang: str) -> tuple[Any, ...]:
            config_manager.clear_credentials()
            return (t(cur_lang, "creds_cleared_msg"), *_cred_textbox_updates(cur_lang))

        # =========================================================================
        # v1.0.3: PERSONAL TAG LIST (BLACKLIST / WHITELIST) HANDLERS
        # =========================================================================
        def _personal_chips(cur_lang: str) -> str:
            n = config_manager.config.normalizer
            return render_blacklist_chips_html(
                n.junk_tags_list, n.user_blacklist, n.user_whitelist, lang=cur_lang
            )

        def personal_list_handler(
            kind: str,
            tag_text: str,
            cur_lang: str,
            posts: list[Post],
            sel_idx: int,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            exp_mode: ExportMode,
            trig_word: str,
            prefix_str: str,
            excl_cats: list[TagCategory],
            inc_header: bool,
        ) -> tuple[Any, ...]:
            norm_live = config_manager.config.normalizer
            new_tags = parse_tag_list(tag_text)
            if not new_tags:
                # 7 values to match personal_view_outputs: chips + status + 5 no-op views
                # (gr.skip() leaves the current gallery/inspector/export views untouched).
                return (
                    _personal_chips(cur_lang),
                    t(cur_lang, "personal_not_found", tags=""),
                    gr.skip(),
                    gr.skip(),
                    gr.skip(),
                    gr.skip(),
                    gr.skip(),
                )

            if kind == "blacklist_add":
                norm_live.user_blacklist, added = add_tags(list(norm_live.user_blacklist), new_tags)
                if not added:
                    msg = t(cur_lang, "personal_not_found", tags=", ".join(new_tags))
                else:
                    msg = t(cur_lang, "personal_added", tags=", ".join(added))
            elif kind == "whitelist_add":
                norm_live.user_whitelist, added = add_tags(list(norm_live.user_whitelist), new_tags)
                if not added:
                    msg = t(cur_lang, "personal_not_found", tags=", ".join(new_tags))
                else:
                    msg = t(cur_lang, "personal_whitelisted", tags=", ".join(added))
            elif kind == "blacklist_remove":
                norm_live.user_blacklist, removed = remove_tags(list(norm_live.user_blacklist), new_tags)
                if not removed:
                    msg = t(cur_lang, "personal_not_found", tags=", ".join(new_tags))
                else:
                    msg = t(cur_lang, "personal_removed", tags=", ".join(removed))
            else:  # whitelist_remove
                norm_live.user_whitelist, removed = remove_tags(list(norm_live.user_whitelist), new_tags)
                if not removed:
                    msg = t(cur_lang, "personal_not_found", tags=", ".join(new_tags))
                else:
                    msg = t(cur_lang, "personal_removed", tags=", ".join(removed))

            config_manager.save()
            refresh = refresh_views(
                posts,
                sel_idx,
                cur_lang,
                replace_u,
                escape_p,
                filter_j,
                junk_str,
                sem_order,
                sep,
                exp_mode,
                trig_word,
                prefix_str,
                excl_cats,
                inc_header,
                persist=True,
            )
            return _personal_chips(cur_lang), msg, *refresh

        def reset_personal_handler(
            cur_lang: str,
            posts: list[Post],
            sel_idx: int,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            exp_mode: ExportMode,
            trig_word: str,
            prefix_str: str,
            excl_cats: list[TagCategory],
            inc_header: bool,
        ) -> tuple[Any, ...]:
            norm_live = config_manager.config.normalizer
            norm_live.user_blacklist = []
            norm_live.user_whitelist = []
            config_manager.save()
            refresh = refresh_views(
                posts,
                sel_idx,
                cur_lang,
                replace_u,
                escape_p,
                filter_j,
                junk_str,
                sem_order,
                sep,
                exp_mode,
                trig_word,
                prefix_str,
                excl_cats,
                inc_header,
                persist=True,
            )
            return _personal_chips(cur_lang), t(cur_lang, "personal_reset_done"), *refresh

        def blacklist_post_handler(
            cur_lang: str,
            posts: list[Post],
            sel_idx: int,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
            exp_mode: ExportMode,
            trig_word: str,
            prefix_str: str,
            excl_cats: list[TagCategory],
            inc_header: bool,
        ) -> tuple[Any, ...]:
            norm = build_normalizer_from_ui(replace_u, escape_p, filter_j, junk_str, sem_order, sep, persist=False)
            eff_idx = sel_idx if posts and 0 <= sel_idx < len(posts) else 0
            post = posts[eff_idx] if posts else None
            if post is None:
                return _personal_chips(cur_lang), t(cur_lang, "blacklist_post_none"), "", "", "", "", ""

            all_raw: list[str] = []
            for cat in ("copyright", "character", "artist", "general", "meta"):
                all_raw.extend(getattr(post.tags, cat) or [])
            all_raw.extend(post.raw_tags or [])

            filtered: list[str] = []
            seen: set[str] = set()
            for raw in all_raw:
                if not raw or norm.sanitize_tag(raw) is not None:
                    continue
                key = normalize_tag_key(raw)
                if key and key not in seen:
                    seen.add(key)
                    filtered.append(raw)

            if not filtered:
                return _personal_chips(cur_lang), t(cur_lang, "blacklist_post_none"), "", "", "", "", ""

            norm_live = config_manager.config.normalizer
            norm_live.user_blacklist, added = add_tags(list(norm_live.user_blacklist), filtered)
            config_manager.save()
            refresh = refresh_views(
                posts,
                eff_idx,
                cur_lang,
                replace_u,
                escape_p,
                filter_j,
                junk_str,
                sem_order,
                sep,
                exp_mode,
                trig_word,
                prefix_str,
                excl_cats,
                inc_header,
                persist=True,
            )
            msg = t(cur_lang, "blacklist_post_done", count=len(added))
            return _personal_chips(cur_lang), msg, *refresh

        # =========================================================================
        # v1.0.3: IMAGE TO PROMPT HANDLER (local metadata extraction)
        # =========================================================================
        def extract_handler(
            file_val: Any,
            cur_lang: str,
            trig_word: str,
            replace_u: bool,
            escape_p: bool,
            filter_j: bool,
            junk_str: str,
            sem_order: str,
            sep: str,
        ) -> tuple[Any, ...]:
            path: str | None = None
            if isinstance(file_val, (list, tuple)):
                # v1.0.6: the LATEST dropped file wins (drop-to-replace). New files are
                # appended to the end, so [-1] is the most recent image the user loaded.
                file_val = file_val[-1] if file_val else None
            if file_val is not None:
                path = file_val if isinstance(file_val, str) else getattr(file_val, "name", None)

            if not path:
                # No file selected (e.g. user cleared the input): leave the UI as-is.
                return gr.skip()

            norm = build_normalizer_from_ui(replace_u, escape_p, filter_j, junk_str, sem_order, sep, persist=False)
            try:
                meta = extract_image_metadata(path)
            except MetadataExtractionError as err:
                return (
                    render_status_pill_html(t(cur_lang, "extract_error", error=str(err)), lang=cur_lang, state="error"),
                    "",
                    "",
                    "",
                    "",
                    "",
                )
            except Exception as err:  # Defensive: unexpected Pillow failure must not crash the UI
                return (
                    render_status_pill_html(t(cur_lang, "extract_error", error=str(err)), lang=cur_lang, state="error"),
                    "",
                    "",
                    "",
                    "",
                    "",
                )

            info_bits = [t(cur_lang, "extract_info_format", fmt=meta.format, w=meta.width, h=meta.height)]
            if meta.rating:
                info_bits.append(t(cur_lang, "extract_rating", rating=meta.rating))
            if meta.source_url:
                info_bits.append(t(cur_lang, "extract_source", url=meta.source_url))
            info_md = "  ·  ".join(info_bits)

            pos_body = norm.format_tags(parse_tag_list(meta.prompt or ""))
            neg_body = norm.format_tags(parse_tag_list(meta.negative or ""))
            prefix = (trig_word or "").strip().rstrip(",")
            if prefix and pos_body:
                positive_text = f"{prefix}{norm.config.custom_separator}{pos_body}"
            else:
                positive_text = prefix or pos_body
            negative_text = neg_body
            settings_text = format_settings_lines(meta.settings or "")

            tags_html = render_extract_result_html(meta, norm, lang=cur_lang)
            if meta.found:
                status_html = render_status_pill_html(
                    t(cur_lang, "extract_success", tags=len(meta.tags), sources=", ".join(meta.sources)),
                    lang=cur_lang,
                    state="ready",
                )
            else:
                status_html = render_status_pill_html(t(cur_lang, "extract_no_meta"), lang=cur_lang, state="warn")
            return status_html, info_md, positive_text, negative_text, settings_text, tags_html

        # Wire search events
        search_outputs = [
            posts_state,
            selected_idx_state,
            source_dropdown,
            query_input,
            gallery,
            selected_prompt_box,
            nav_badge_box,
            inspector_html,
            export_preview_box,
            export_stats_box,
            status_banner,
            recent_dropdown,  # v1.0.6: refresh history choices after each search
            top_tags_dropdown,  # v1.0.6: refresh top tags after each search
        ]
        search_btn.click(
            fn=execute_search_handler,
            inputs=[
                source_dropdown,
                query_input,
                limit_dropdown,
                rating_filter,
                quality_dropdown,
                lang_dropdown,
                *norm_inputs,
                *export_inputs,
            ],
            outputs=search_outputs,
        )
        query_input.submit(
            fn=execute_search_handler,
            inputs=[
                source_dropdown,
                query_input,
                limit_dropdown,
                rating_filter,
                quality_dropdown,
                lang_dropdown,
                *norm_inputs,
                *export_inputs,
            ],
            outputs=search_outputs,
        )

        # v1.0.6 (revised): selecting a recent search just fills the Search-tags bar — no
        # auto-run; the user presses Search / Enter when ready. Clear resets the dropdown
        # to None, which maps to gr.skip() (via populate_query_from_recent), so it can no
        # longer trigger a spurious search or wipe the search bar.
        recent_dropdown.change(
            fn=populate_query_from_recent,
            inputs=[recent_dropdown],
            outputs=[query_input],
        )
        clear_history_btn.click(
            fn=clear_search_history_handler,
            outputs=[recent_dropdown, top_tags_dropdown],
        )
        top_tags_add_btn.click(
            fn=add_top_tag_to_query,
            inputs=[query_input, top_tags_dropdown],
            outputs=[query_input, top_tags_dropdown],
        )

        quality_dropdown.change(
            fn=on_quality_change,
            inputs=[quality_dropdown, posts_state],
            outputs=[gallery],
        )

        copy_prompt_btn.click(
            fn=on_copy_prompt_feedback,
            inputs=[selected_prompt_box, lang_dropdown],
            outputs=[status_banner],
            js="(p, l) => { if (p) { navigator.clipboard.writeText(p); } return [p, l]; }",
        )

        lang_dropdown.change(
            fn=on_language_change,
            inputs=[
                lang_dropdown,
                posts_state,
                selected_idx_state,
                rating_filter,
                quality_dropdown,
                export_mode_radio,
                exclude_cats_chk,
                *norm_inputs,
                trigger_word_input,
                filename_prefix_input,
                include_header_chk,
            ],
            outputs=[
                header_html_box,
                source_dropdown,
                query_input,
                search_btn,
                limit_dropdown,
                rating_filter,
                quality_dropdown,
                lang_dropdown,
                status_banner,
                tab_gallery_item,
                tab_export_item,
                tab_settings_item,
                gallery,
                prev_post_btn,
                nav_badge_box,
                next_post_btn,
                selected_prompt_box,
                copy_prompt_btn,
                inspector_html,
                export_stats_box,
                card_export_cfg_hdr,
                export_mode_radio,
                trigger_word_input,
                filename_prefix_input,
                exclude_cats_chk,
                include_header_chk,
                export_preview_box,
                card_file_exp_hdr,
                zip_include_images_chk,
                generate_file_btn,
                download_file_output,
                card_folder_exp_hdr,
                local_folder_input,
                browse_folder_btn,
                download_imgs_local_chk,
                high_res_local_chk,
                save_local_folder_btn,
                open_explorer_btn,
                norm_heading_hdr,
                replace_underscores_chk,
                escape_parens_chk,
                filter_junk_chk,
                semantic_order_dropdown,
                separator_input,
                junk_tags_textbox,
                reset_junk_btn,
                creds_heading_hdr,
                creds_sub_md,
                persist_creds_chk,
                save_creds_btn,
                clear_creds_btn,
                tab_extract_item,
                tab_personal_item,
                blacklist_post_btn,
                personal_heading_hdr,
                personal_sub_md,
                personal_chips_box,
                personal_bl_hdr,
                personal_wl_hdr,
                blacklist_add_input,
                blacklist_add_btn,
                blacklist_remove_input,
                blacklist_remove_btn,
                whitelist_add_input,
                whitelist_add_btn,
                whitelist_remove_input,
                whitelist_remove_btn,
                reset_personal_btn,
                personal_status_md,
                extract_heading_hdr,
                extract_sub_md,
                extract_file_input,
                extract_preview,
                extract_btn,
                extract_status_box,
                extract_info_md,
                extract_positive_box,
                extract_negative_box,
                extract_settings_box,
                extract_tags_html,
                # v1.0.6: appended last to keep 0..N indices stable for the wiring tests
                recent_dropdown,
                clear_history_btn,
                extract_clear_btn,
                top_tags_dropdown,
                top_tags_add_btn,
            ],
        )

        # Gallery selection & prev/next navigation
        gallery.select(
            fn=on_gallery_select,
            inputs=[posts_state, lang_dropdown, *norm_inputs, trigger_word_input, exclude_cats_chk],
            outputs=[selected_idx_state, selected_prompt_box, nav_badge_box, inspector_html],
        )
        prev_post_btn.click(
            fn=lambda posts, idx, lng, *args: navigate_post_handler(-1, posts, idx, lng, *args),
            inputs=[
                posts_state,
                selected_idx_state,
                lang_dropdown,
                *norm_inputs,
                trigger_word_input,
                exclude_cats_chk,
            ],
            outputs=[selected_idx_state, selected_prompt_box, nav_badge_box, inspector_html, gallery],
        )
        next_post_btn.click(
            fn=lambda posts, idx, lng, *args: navigate_post_handler(1, posts, idx, lng, *args),
            inputs=[
                posts_state,
                selected_idx_state,
                lang_dropdown,
                *norm_inputs,
                trigger_word_input,
                exclude_cats_chk,
            ],
            outputs=[selected_idx_state, selected_prompt_box, nav_badge_box, inspector_html, gallery],
        )

        # Discrete controls (Checkboxes, Dropdowns, Radio): update preview AND persist to disk
        discrete_controls = [
            replace_underscores_chk,
            escape_parens_chk,
            filter_junk_chk,
            semantic_order_dropdown,
            export_mode_radio,
            exclude_cats_chk,
            include_header_chk,
        ]
        for ctrl in discrete_controls:
            ctrl.change(
                fn=lambda *args: refresh_views(*args, persist=True),
                inputs=[posts_state, selected_idx_state, lang_dropdown, *norm_inputs, *export_inputs],
                outputs=[
                    selected_prompt_box,
                    nav_badge_box,
                    inspector_html,
                    export_preview_box,
                    export_stats_box,
                ],
            )

        # Textbox controls: update live preview on keystroke WITHOUT writing to disk (C6),
        # and persist to disk only on blur or submit
        textbox_controls = [
            junk_tags_textbox,
            separator_input,
            trigger_word_input,
            filename_prefix_input,
        ]
        for tb in textbox_controls:
            tb.change(
                fn=lambda *args: refresh_views(*args, persist=False),
                inputs=[posts_state, selected_idx_state, lang_dropdown, *norm_inputs, *export_inputs],
                outputs=[
                    selected_prompt_box,
                    nav_badge_box,
                    inspector_html,
                    export_preview_box,
                    export_stats_box,
                ],
            )
            tb.blur(
                fn=persist_settings_only,
                inputs=[*norm_inputs, *export_inputs],
                outputs=[],
            )

        reset_junk_btn.click(
            fn=lambda: ", ".join(DEFAULT_JUNK_TAGS),
            inputs=[],
            outputs=[junk_tags_textbox],
        ).then(
            fn=persist_settings_only,
            inputs=[*norm_inputs, *export_inputs],
            outputs=[],
        )

        # v1.0.3: Personal tag list wiring (blacklist / whitelist)
        personal_view_outputs = [
            personal_chips_box,
            personal_status_md,
            selected_prompt_box,
            nav_badge_box,
            inspector_html,
            export_preview_box,
            export_stats_box,
        ]
        personal_common_inputs = [
            lang_dropdown,
            posts_state,
            selected_idx_state,
            *norm_inputs,
            *export_inputs,
        ]
        blacklist_add_btn.click(
            fn=lambda text, *args: personal_list_handler("blacklist_add", text, *args),
            inputs=[blacklist_add_input, *personal_common_inputs],
            outputs=personal_view_outputs,
        ).then(fn=lambda: "", inputs=[], outputs=[blacklist_add_input])
        blacklist_remove_btn.click(
            fn=lambda text, *args: personal_list_handler("blacklist_remove", text, *args),
            inputs=[blacklist_remove_input, *personal_common_inputs],
            outputs=personal_view_outputs,
        ).then(fn=lambda: "", inputs=[], outputs=[blacklist_remove_input])
        whitelist_add_btn.click(
            fn=lambda text, *args: personal_list_handler("whitelist_add", text, *args),
            inputs=[whitelist_add_input, *personal_common_inputs],
            outputs=personal_view_outputs,
        ).then(fn=lambda: "", inputs=[], outputs=[whitelist_add_input])
        whitelist_remove_btn.click(
            fn=lambda text, *args: personal_list_handler("whitelist_remove", text, *args),
            inputs=[whitelist_remove_input, *personal_common_inputs],
            outputs=personal_view_outputs,
        ).then(fn=lambda: "", inputs=[], outputs=[whitelist_remove_input])

        reset_personal_btn.click(
            fn=reset_personal_handler,
            inputs=personal_common_inputs,
            outputs=personal_view_outputs,
        )

        blacklist_post_btn.click(
            fn=blacklist_post_handler,
            inputs=[lang_dropdown, posts_state, selected_idx_state, *norm_inputs, *export_inputs],
            outputs=personal_view_outputs,
        )

        # v1.0.3: Image to Prompt wiring (local metadata extraction)
        extract_view_outputs = [
            extract_status_box,
            extract_info_md,
            extract_positive_box,
            extract_negative_box,
            extract_settings_box,
            extract_tags_html,
        ]
        extract_file_input.change(
            # v1.0.6: preview the LATEST file (drop-to-replace keeps the newest at [-1]).
            fn=lambda f: (
                f
                if isinstance(f, str)
                else (f[-1] if isinstance(f, (list, tuple)) and f else None)
            ),
            inputs=[extract_file_input],
            outputs=[extract_preview],
        ).then(
            # v1.0.3 UX: extraction runs automatically when the file lands,
            # no need to hunt for the button.
            fn=extract_handler,
            inputs=[extract_file_input, lang_dropdown, trigger_word_input, *norm_inputs],
            outputs=extract_view_outputs,
        )
        extract_btn.click(
            fn=extract_handler,
            inputs=[extract_file_input, lang_dropdown, trigger_word_input, *norm_inputs],
            outputs=extract_view_outputs,
        )

        # v1.0.6: clear the loaded image, the preview, and all extracted results at once,
        # so the user can immediately drag in a different image.
        extract_clear_btn.click(
            fn=lambda: (None, None, "", "", "", "", "", ""),
            outputs=[
                extract_file_input,
                extract_preview,
                extract_status_box,
                extract_info_md,
                extract_positive_box,
                extract_negative_box,
                extract_settings_box,
                extract_tags_html,
            ],
        )

        # Export & Local Folder actions
        generate_file_btn.click(
            fn=generate_download_file_handler,
            inputs=[
                posts_state,
                source_dropdown,
                query_input,
                lang_dropdown,
                *norm_inputs,
                *export_inputs,
                zip_include_images_chk,
                local_folder_input,
            ],
            outputs=[download_file_output, local_export_status],
        )

        browse_folder_btn.click(
            fn=open_native_folder_dialog,
            inputs=[local_folder_input, lang_dropdown],
            outputs=[local_folder_input],
        )

        save_local_folder_btn.click(
            fn=save_dataset_to_folder_handler,
            inputs=[
                posts_state,
                local_folder_input,
                download_imgs_local_chk,
                high_res_local_chk,
                lang_dropdown,
                *norm_inputs,
                trigger_word_input,
                exclude_cats_chk,
            ],
            outputs=[local_export_status],
        )

        open_explorer_btn.click(
            fn=open_folder_in_explorer,
            inputs=[local_folder_input, lang_dropdown],
            outputs=[local_export_status],
        )

        cred_textbox_list = [
            danbooru_user,
            danbooru_key,
            e621_user,
            e621_key,
            gelbooru_user,
            gelbooru_key,
            rule34_user,
            rule34_key,
        ]

        save_creds_btn.click(
            fn=save_credentials_handler,
            inputs=[
                lang_dropdown,
                persist_creds_chk,
                *cred_textbox_list,
            ],
            outputs=[creds_status_md, *cred_textbox_list],
        )

        clear_creds_btn.click(
            fn=clear_credentials_handler,
            inputs=[lang_dropdown],
            outputs=[creds_status_md, *cred_textbox_list],
        )

    return app
