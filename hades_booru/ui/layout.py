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
from hades_booru.models import (
    DEFAULT_JUNK_TAGS,
    DEFAULT_SEMANTIC_ORDER,
    ExportMode,
    ImageQuality,
    NormalizerConfig,
    Post,
    TagCategory,
)
from hades_booru.normalizer import PromptNormalizer
from hades_booru.ui.components import (
    render_export_stats_html,
    render_header_html,
    render_inspector_nav_badge_html,
    render_post_inspector_html,
    render_section_header_html,
    render_status_pill_html,
)


def build_gallery_items(posts: list[Post], quality: ImageQuality) -> list[tuple[str, str]]:
    """Resolves disk-cached gallery image paths for all posts in the batch (C2)."""
    return image_cache.build_gallery_items(posts, quality)


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

    cfg = NormalizerConfig(
        replace_underscores=replace_underscores,
        escape_parentheses=escape_parens,
        filter_junk_tags=filter_junk,
        junk_tags_list=junk_list,
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
            subprocess.Popen(["open", str(target)], check=False)
        else:
            subprocess.Popen(["xdg-open", str(target)], check=False)
        return t(lang, "explorer_opened", path=str(target))
    except Exception as err:
        return t(lang, "explorer_error", error=str(err), path=str(target))


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
            # TAB 3: SYMMETRIC 6:6 NORMALIZATION & 2x2 API CREDENTIALS GRID
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

                        # Saved credentials are intentionally NOT prefilled into the form fields
                        # (they would end up in the page /config and be exposed with --share).
                        # Saved values stay active in the session; placeholders show presence only.
                        danbooru_cred = config_manager.get_credentials("danbooru")
                        e621_cred = config_manager.get_credentials("e621")
                        gelbooru_cred = config_manager.get_credentials("gelbooru")
                        rule34_cred = config_manager.get_credentials("rule34")

                        with gr.Row():
                            with gr.Group():
                                gr.HTML('<div class="hades-cred-title">Danbooru (danbooru.donmai.us)</div>')
                                danbooru_user = gr.Textbox(
                                    placeholder=danbooru_cred.user_id or None,
                                    label="Username",
                                )
                                danbooru_key = gr.Textbox(
                                    placeholder=danbooru_cred.api_key or None,
                                    label="API Key",
                                    type="password",
                                )

                            with gr.Group():
                                gr.HTML('<div class="hades-cred-title">E621 / E926 (e621.net)</div>')
                                e621_user = gr.Textbox(
                                    placeholder=e621_cred.user_id or None,
                                    label="Username",
                                )
                                e621_key = gr.Textbox(
                                    placeholder=e621_cred.api_key or None,
                                    label="API Key",
                                    type="password",
                                )

                        with gr.Row():
                            with gr.Group():
                                gr.HTML('<div class="hades-cred-title">Gelbooru (gelbooru.com)</div>')
                                gelbooru_user = gr.Textbox(
                                    placeholder=gelbooru_cred.user_id or None,
                                    label="User ID",
                                )
                                gelbooru_key = gr.Textbox(
                                    placeholder=gelbooru_cred.api_key or None,
                                    label="API Key",
                                    type="password",
                                )

                            with gr.Group():
                                gr.HTML('<div class="hades-cred-title">Rule34 (rule34.xxx)</div>')
                                rule34_user = gr.Textbox(
                                    placeholder=rule34_cred.user_id or None,
                                    label="User ID",
                                )
                                rule34_key = gr.Textbox(
                                    placeholder=rule34_cred.api_key or None,
                                    label="API Key",
                                    type="password",
                                )

                        persist_creds_chk = gr.Checkbox(
                            value=cfg.persist_credentials,
                            label=t(lang, "persist_creds_label"),
                        )
                        save_creds_btn = gr.Button(t(lang, "save_creds_btn"), variant="primary")
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

                if rating_val and rating_val != "all":
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
                )

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
        ) -> tuple[int, str, str, str]:
            if not posts:
                return (
                    0,
                    "",
                    render_inspector_nav_badge_html(0, 0, "", lang=cur_lang),
                    render_post_inspector_html(None, PromptNormalizer(), lang=cur_lang),
                )
            next_idx = (cur_idx + direction) % len(posts)
            norm = build_normalizer_from_ui(replace_u, escape_p, filter_j, junk_str, sem_order, sep, persist=False)
            post = posts[next_idx]
            prompt = norm.format_post_prompt(post, exclude_categories=excl_cats, trigger_word=trig_word)
            nav_badge = render_inspector_nav_badge_html(next_idx, len(posts), prompt, lang=cur_lang)
            return next_idx, prompt, nav_badge, render_post_inspector_html(post, norm, lang=cur_lang)

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
            try:
                requested.relative_to(cwd)
                out_dir = requested
            except ValueError:
                # Gradio can only serve files inside the server working directory;
                # fall back to a CWD-based folder instead of failing with InvalidPathError.
                out_dir = cwd / "exports"
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
        ) -> str:
            config_manager.set_credentials_many(
                {
                    "danbooru": (d_user, d_key),
                    "e621": (e_user, e_key),
                    "gelbooru": (g_user, g_key),
                    "rule34": (r_user, r_key),
                },
                persist_to_disk=persist_flag,
            )
            if persist_flag:
                return t(cur_lang, "creds_saved_msg")
            return t(cur_lang, "creds_saved_session_msg")

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
            outputs=[selected_idx_state, selected_prompt_box, nav_badge_box, inspector_html],
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
            outputs=[selected_idx_state, selected_prompt_box, nav_badge_box, inspector_html],
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

        save_creds_btn.click(
            fn=save_credentials_handler,
            inputs=[
                lang_dropdown,
                persist_creds_chk,
                danbooru_user,
                danbooru_key,
                e621_user,
                e621_key,
                gelbooru_user,
                gelbooru_key,
                rule34_user,
                rule34_key,
            ],
            outputs=[creds_status_md],
        )

    return app
