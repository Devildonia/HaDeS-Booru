"""
Gradio Blocks Layout & Event Wiring Orchestrator for HaDeS Booru (v1.1.0).
Modularized under R6-25 into:
- `hades_booru/ui/state.py` (search history, URL scrubbing, PersonalListStore for `--share`)
- `hades_booru/ui/desktop.py` (OS folder dialog, file manager integration, gallery cache)
- `hades_booru/ui/handlers.py` (event handlers for all tabs and localization)
- `hades_booru/ui/components.py` (semantic HTML renderers)
- `hades_booru/ui/theme.py` (WCAG AA Light/Dark palettes & locally bundled WOFF2 fonts)
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import gradio as gr

from hades_booru import __version__
from hades_booru.adapters.registry import registry
from hades_booru.config import config_manager
from hades_booru.i18n import (
    get_exclude_category_choices,
    get_export_mode_choices,
    get_quality_choices,
    get_rating_choices,
    get_theme_choices,
    t,
)
from hades_booru.models import Post
from hades_booru.normalizer import PromptNormalizer
from hades_booru.ui.components import (
    render_blacklist_chips_html,
    render_export_stats_html,
    render_header_html,
    render_inspector_nav_badge_html,
    render_post_inspector_html,
    render_section_header_html,
    render_status_pill_html,
    render_tag_dictionary_html,
)
from hades_booru.ui.desktop import (
    _cred_placeholder,
    build_gallery_items,
    open_folder_in_explorer,
    open_native_folder_dialog,
)
from hades_booru.ui.handlers import create_ui_handlers
from hades_booru.ui.state import (
    MAX_SEARCH_HISTORY,
    PersonalListStore,
    _scrub_url_credentials,
    add_top_tag_to_query,
    build_normalizer_from_ui,
    compute_top_tags,
    make_session_lists,
    populate_query_from_recent,
    record_search_history,
)
from hades_booru.ui.theme import THEME_APPLY_JS

__all__ = [
    "MAX_SEARCH_HISTORY",
    "_cred_placeholder",
    "_scrub_url_credentials",
    "add_top_tag_to_query",
    "build_gallery_items",
    "build_normalizer_from_ui",
    "compute_top_tags",
    "create_gradio_app",
    "open_folder_in_explorer",
    "open_native_folder_dialog",
    "populate_query_from_recent",
    "record_search_history",
]


def _make_blocks() -> gr.Blocks:
    """Build the Gradio Blocks root with telemetry disabled.

    v1.1.0 (launch fix, Gradio 6.30):
    1. Privacy: HaDeS Booru is local-first and must not emit telemetry pings
       (Gradio sends them to api.gradio.app).
    2. Gradio 6.30 bug workaround: with analytics enabled, launch() compares
       theme.to_dict() against every built-in theme; Font.__eq__ has no type
       guard and crashes with AttributeError ('str' object has no attribute
       'name') when our str font fallbacks meet a built-in LocalFont entry,
       so the app never starts. Disabling telemetry skips that code path.

    The parameter is guarded by a signature check because the pin is
    gradio>=6.0,<7 and not every 6.x build has it; app.py additionally sets
    GRADIO_ANALYTICS_ENABLED=false for versions that lack the parameter.
    """
    if "analytics_enabled" in inspect.signature(gr.Blocks.__init__).parameters:
        return gr.Blocks(title=f"HaDeS Booru v{__version__}", analytics_enabled=False)
    return gr.Blocks(title=f"HaDeS Booru v{__version__}")


def _dispatch_adapter_search(
    source_id: str,
    trimmed_q: str,
    limit_val: int,
    rating_val: str,
    cur_lang: str,
    progress: Any,
) -> tuple[list[Post], str, str, str, str]:
    """Executes URL auto-detection or standard board search with rating safety net."""
    detected = registry.detect_source_from_url(trimmed_q)
    effective_source = source_id
    effective_tags = trimmed_q
    status_note = ""
    status_state = "ready"

    if detected:
        effective_source = detected.adapter.id
        if detected.is_direct_post:
            # Audit R6-09: the thread-local flag can still be True from an
            # earlier search in this worker thread; a pasted single post must
            # always pass through the client-side rating safety net below.
            detected.adapter.server_rating_applied = False
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

    return results, effective_source, effective_tags, status_note, status_state


def create_gradio_app(share_mode: bool = False) -> gr.Blocks:
    """Creates and wires the complete Gradio Blocks application starting with a clean empty state."""
    cfg = config_manager.config
    lang = cfg.language
    quality = cfg.image_quality
    theme_mode = cfg.theme_mode
    norm_cfg = cfg.normalizer
    exp_cfg = cfg.export

    store = PersonalListStore(share_mode=share_mode)
    handlers = create_ui_handlers(store=store, dispatch_search_fn=_dispatch_adapter_search)

    refresh_views = handlers["refresh_views"]
    persist_settings_only = handlers["persist_settings_only"]
    execute_search_handler = handlers["execute_search_handler"]
    clear_search_history_handler = handlers["clear_search_history_handler"]
    on_quality_change = handlers["on_quality_change"]
    on_theme_change = handlers["on_theme_change"]
    on_copy_prompt_feedback = handlers["on_copy_prompt_feedback"]
    on_language_change = handlers["on_language_change"]
    on_gallery_select = handlers["on_gallery_select"]
    navigate_post_handler = handlers["navigate_post_handler"]
    generate_download_file_handler = handlers["generate_download_file_handler"]
    save_dataset_to_folder_handler = handlers["save_dataset_to_folder_handler"]
    save_credentials_handler = handlers["save_credentials_handler"]
    clear_credentials_handler = handlers["clear_credentials_handler"]
    personal_list_handler = handlers["personal_list_handler"]
    reset_junk_handler = handlers["reset_junk_handler"]
    reset_personal_handler = handlers["reset_personal_handler"]
    blacklist_post_handler = handlers["blacklist_post_handler"]
    extract_handler = handlers["extract_handler"]
    dictionary_lookup_handler = handlers["dictionary_lookup_handler"]
    dictionary_add_to_search_handler = handlers["dictionary_add_to_search_handler"]

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
    initial_dict_html = render_tag_dictionary_html(None, query="", lang=lang)

    with _make_blocks() as app:
        posts_state = gr.State(value=initial_posts)
        selected_idx_state = gr.State(value=0)
        session_lists_state = gr.State(make_session_lists)

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

            with gr.Row(equal_height=True):
                with gr.Row(scale=1, variant="panel", elem_classes=["hades-command-row"]):
                    recent_dropdown = gr.Dropdown(
                        choices=list(config_manager.config.search_history or []),
                        value=None,
                        label=t(lang, "recent_label"),
                        allow_custom_value=False,
                        scale=5,
                    )
                    clear_history_btn = gr.Button(t(lang, "clear_history_btn"), scale=1, size="sm")
                with gr.Row(scale=1, variant="panel", elem_classes=["hades-command-row"]):
                    top_tags_dropdown = gr.Dropdown(
                        choices=compute_top_tags(config_manager.config.search_history),
                        value=None,
                        label=t(lang, "top_tags_label"),
                        allow_custom_value=False,
                        scale=5,
                    )
                    top_tags_add_btn = gr.Button(t(lang, "top_tags_add_btn"), scale=1, size="sm")

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
                theme_dropdown = gr.Dropdown(
                    choices=get_theme_choices(lang),
                    value=theme_mode,
                    label=t(lang, "theme_label"),
                    scale=2,
                )
                lang_dropdown = gr.Dropdown(
                    choices=[("English", "en"), ("Español", "es")],
                    value=lang,
                    label=t(lang, "lang_label"),
                    scale=2,
                )
                status_banner = gr.HTML(value=initial_status)

        # 3. Main Application Tabs
        with gr.Tabs():
            # TAB 1: GALLERY & INSPECTOR
            with gr.TabItem(t(lang, "tab_gallery")) as tab_gallery_item:
                with gr.Row():
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

            # TAB 2: BATCH EXPORT
            with gr.TabItem(t(lang, "tab_export")) as tab_export_item:
                export_stats_box = gr.HTML(value=initial_export_stats)
                with gr.Row():
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

                    with gr.Column(scale=6):
                        with gr.Column(variant="panel"):
                            card_file_exp_hdr = gr.HTML(
                                render_section_header_html(t(lang, "card_file_export_title"))
                            )
                            zip_include_images_chk = gr.Checkbox(
                                value=False,
                                label=t(lang, "zip_include_images_label"),
                            )
                            generate_file_btn = gr.Button(t(lang, "generate_file_btn"), variant="primary")
                            download_file_output = gr.File(
                                label=t(lang, "download_file_label"),
                                interactive=False,
                            )

                        with gr.Column(variant="panel"):
                            card_folder_exp_hdr = gr.HTML(
                                render_section_header_html(t(lang, "card_folder_export_title"))
                            )
                            with gr.Row():
                                # R7-03: in public share mode never pre-reveal the host path.
                                local_folder_input = gr.Textbox(
                                    value="" if share_mode else str(Path(exp_cfg.local_export_dir).resolve()),
                                    label=t(lang, "local_folder_label"),
                                    scale=3,
                                )
                                browse_folder_btn = gr.Button(
                                    t(lang, "browse_folder_btn"),
                                    scale=1,
                                    visible=not share_mode,
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
                                    visible=not share_mode,
                                )
                            local_export_status = gr.Markdown("")

            # TAB 3: IMAGE TO PROMPT
            with gr.TabItem(t(lang, "tab_extract")) as tab_extract_item:
                extract_heading_hdr = gr.HTML(render_section_header_html(t(lang, "extract_heading")))
                extract_sub_md = gr.Markdown(t(lang, "extract_subheading"))
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

            # TAB 4: PERSONAL TAG LIST (BLACKLIST / WHITELIST)
            with gr.TabItem(t(lang, "tab_personal")) as tab_personal_item:
                personal_heading_hdr = gr.HTML(
                    render_section_header_html(t(lang, "personal_list_heading"))
                )
                initial_personal_sub = t(lang, "personal_subheading")
                if share_mode:
                    initial_personal_sub += f"\n\n> {t(lang, 'personal_share_mode_notice')}"
                personal_sub_md = gr.Markdown(initial_personal_sub)
                personal_chips_box = gr.HTML(
                    value=render_blacklist_chips_html(
                        norm_cfg.junk_tags_list,
                        norm_cfg.user_blacklist,
                        norm_cfg.user_whitelist,
                        lang=lang,
                    )
                )
                with gr.Row():
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

            # TAB 5: TAG DICTIONARY (v1.1.0 Flagship Feature)
            with gr.TabItem(t(lang, "tab_dictionary")) as tab_dictionary_item:
                dict_heading_hdr = gr.HTML(render_section_header_html(t(lang, "dict_heading")))
                dict_sub_md = gr.Markdown(t(lang, "dict_subheading"))
                with gr.Row(variant="panel", elem_classes=["hades-command-row"]):
                    dict_query_input = gr.Textbox(
                        value="",
                        label=t(lang, "dict_query_label"),
                        placeholder=t(lang, "dict_query_placeholder"),
                        scale=6,
                    )
                    dict_search_btn = gr.Button(
                        t(lang, "dict_search_btn"),
                        variant="primary",
                        scale=2,
                    )
                    dict_use_tag_btn = gr.Button(
                        t(lang, "dict_use_tag_btn"),
                        variant="secondary",
                        scale=2,
                    )
                dict_result_html = gr.HTML(value=initial_dict_html)

            # TAB 6: NORMALIZATION & API CREDENTIALS
            with gr.TabItem(t(lang, "tab_settings")) as tab_settings_item:
                with gr.Row():
                    with gr.Column(scale=6, variant="panel"):
                        norm_heading_hdr = gr.HTML(render_section_header_html(t(lang, "norm_heading")))
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

                    with gr.Column(scale=6, variant="panel"):
                        creds_heading_hdr = gr.HTML(render_section_header_html(t(lang, "creds_heading")))
                        creds_sub_md = gr.Markdown(t(lang, "creds_subheading"))

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
        # EVENT WIRING
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
        session_input_tail = [session_lists_state] if share_mode else []

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
            recent_dropdown,
            top_tags_dropdown,
        ]
        search_inputs = [
            source_dropdown,
            query_input,
            limit_dropdown,
            rating_filter,
            quality_dropdown,
            lang_dropdown,
            *norm_inputs,
            *export_inputs,
            *session_input_tail,
        ]
        search_btn.click(
            fn=execute_search_handler,
            inputs=search_inputs,
            outputs=search_outputs,
        )
        query_input.submit(
            fn=execute_search_handler,
            inputs=search_inputs,
            outputs=search_outputs,
        )

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

        # v1.1.0: Theme selector (persisted in config.local.json + live client-side CSS application)
        theme_dropdown.change(
            fn=on_theme_change,
            inputs=[theme_dropdown],
            outputs=[theme_dropdown],
            js=THEME_APPLY_JS,
        )
        app.load(
            fn=None,
            inputs=[theme_dropdown],
            outputs=[],
            js=THEME_APPLY_JS,
        )

        copy_prompt_btn.click(
            fn=on_copy_prompt_feedback,
            # R7-11: forward the custom separator so the tag count matches the prompt.
            inputs=[selected_prompt_box, lang_dropdown, separator_input],
            outputs=[status_banner],
            js="(p, l, s) => { if (p) { navigator.clipboard.writeText(p); } return [p, l, s]; }",
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
                theme_dropdown,
                dict_query_input,
                *session_input_tail,
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
                # v1.0.6: indices 80..84
                recent_dropdown,
                clear_history_btn,
                extract_clear_btn,
                top_tags_dropdown,
                top_tags_add_btn,
                # v1.1.0: indices 85..92
                theme_dropdown,
                tab_dictionary_item,
                dict_heading_hdr,
                dict_sub_md,
                dict_query_input,
                dict_search_btn,
                dict_use_tag_btn,
                dict_result_html,
            ],
        )

        # Gallery selection & prev/next navigation
        gallery.select(
            fn=on_gallery_select,
            inputs=[
                posts_state,
                lang_dropdown,
                *norm_inputs,
                trigger_word_input,
                exclude_cats_chk,
                *session_input_tail,
            ],
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
                *session_input_tail,
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
                *session_input_tail,
            ],
            outputs=[selected_idx_state, selected_prompt_box, nav_badge_box, inspector_html, gallery],
        )

        # Discrete controls
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
            ctrl.change(  # type: ignore[attr-defined]  # Gradio stubs: base class lacks .change
                fn=lambda *args: refresh_views(*args, persist=not share_mode),
                # R7-06: include the session state so share-mode previews read the
                # correct per-session lists (parity with the .click handlers).
                inputs=[posts_state, selected_idx_state, lang_dropdown, *norm_inputs, *export_inputs, *session_input_tail],
                outputs=[
                    selected_prompt_box,
                    nav_badge_box,
                    inspector_html,
                    export_preview_box,
                    export_stats_box,
                ],
            )

        # Textbox controls (decoupled live preview vs blur persistence)
        textbox_controls = [
            junk_tags_textbox,
            separator_input,
            trigger_word_input,
            filename_prefix_input,
        ]
        for tb in textbox_controls:
            tb.change(
                fn=lambda *args: refresh_views(*args, persist=False),
                # R7-06: include the session state (parity with the .click handlers).
                inputs=[posts_state, selected_idx_state, lang_dropdown, *norm_inputs, *export_inputs, *session_input_tail],
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
                inputs=[*norm_inputs, *export_inputs, *session_input_tail],
                outputs=[],
            )

        # R7-06: also refresh the personal chips so the display never goes stale.
        reset_junk_btn.click(
            fn=lambda *args: reset_junk_handler(*args),
            inputs=[lang_dropdown, *session_input_tail],
            outputs=[junk_tags_textbox, personal_chips_box],
        ).then(
            fn=persist_settings_only,
            inputs=[*norm_inputs, *export_inputs, *session_input_tail],
            outputs=[],
        )

        # Personal tag list wiring (blacklist / whitelist)
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
            *session_input_tail,
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
            inputs=[
                lang_dropdown,
                posts_state,
                selected_idx_state,
                *norm_inputs,
                *export_inputs,
                *session_input_tail,
            ],
            outputs=personal_view_outputs,
        )

        # v1.1.0: Tag Dictionary wiring
        dict_search_btn.click(
            fn=dictionary_lookup_handler,
            inputs=[dict_query_input, lang_dropdown],
            outputs=[dict_result_html],
        )
        dict_query_input.submit(
            fn=dictionary_lookup_handler,
            inputs=[dict_query_input, lang_dropdown],
            outputs=[dict_result_html],
        )
        dict_use_tag_btn.click(
            fn=dictionary_add_to_search_handler,
            inputs=[dict_query_input, query_input, lang_dropdown],
            outputs=[query_input, status_banner],
        )

        # Image to Prompt wiring
        extract_view_outputs = [
            extract_status_box,
            extract_info_md,
            extract_positive_box,
            extract_negative_box,
            extract_settings_box,
            extract_tags_html,
        ]
        extract_file_input.change(
            fn=lambda f: (
                f
                if isinstance(f, str)
                else (f[-1] if isinstance(f, (list, tuple)) and f else None)
            ),
            inputs=[extract_file_input],
            outputs=[extract_preview],
        ).then(
            fn=extract_handler,
            inputs=[extract_file_input, lang_dropdown, trigger_word_input, *norm_inputs, *session_input_tail],
            outputs=extract_view_outputs,
        )
        extract_btn.click(
            fn=extract_handler,
            inputs=[extract_file_input, lang_dropdown, trigger_word_input, *norm_inputs, *session_input_tail],
            outputs=extract_view_outputs,
        )
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
                *session_input_tail,
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
                *session_input_tail,
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
