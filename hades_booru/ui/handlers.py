"""
Event Handlers for HaDeS Booru Gradio UI (R6-25 modular split).
Encapsulates search, gallery navigation, batch export, credentials, session-aware
personal lists (X8 / R6-12), local metadata extraction, offline Tag Dictionary lookup,
theme switching, and full EN/ES live localization.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import gradio as gr

from hades_booru.config import config_manager
from hades_booru.exporter import bulk_exporter
from hades_booru.i18n import (
    get_exclude_category_choices,
    get_export_mode_choices,
    get_quality_choices,
    get_rating_choices,
    get_theme_choices,
    t,
)
from hades_booru.metadata_extractor import (
    MetadataExtractionError,
    extract_image_metadata,
    format_settings_lines,
)
from hades_booru.models import DEFAULT_JUNK_TAGS, ExportMode, ImageQuality, Post, TagCategory, ThemeMode
from hades_booru.normalizer import PromptNormalizer, add_tags, normalize_tag_key, parse_tag_list, remove_tags
from hades_booru.tag_dictionary import get_tag_dictionary
from hades_booru.ui.components import (
    render_blacklist_chips_html,
    render_export_stats_html,
    render_extract_result_html,
    render_header_html,
    render_inspector_nav_badge_html,
    render_post_inspector_html,
    render_section_header_html,
    render_status_pill_html,
    render_tag_dictionary_html,
)
from hades_booru.ui.desktop import _cred_placeholder, build_gallery_items
from hades_booru.ui.state import (
    PersonalListStore,
    SessionLists,
    add_top_tag_to_query,
    build_normalizer_from_ui,
    compute_top_tags,
    record_search_history,
)


def create_ui_handlers(
    store: PersonalListStore,
    dispatch_search_fn: Callable[[str, str, int, str, str, Any], tuple[list[Post], str, str, str, str]],
) -> dict[str, Callable[..., Any]]:
    """Builds the dictionary of UI event handlers bound to the active `PersonalListStore`."""

    def _personal_chips(cur_lang: str, session_lists: SessionLists | None = None) -> str:
        junk_list, blacklist, whitelist = store.get_lists(session_lists)
        return render_blacklist_chips_html(junk_list, blacklist, whitelist, lang=cur_lang)

    def reset_junk_handler(
        cur_lang: str,
        session_lists: SessionLists | None = None,
    ) -> tuple[str, str]:
        """R7-06: reset junk tags to defaults and refresh the personal chips in one go.

        Previously the reset button only rewrote the textbox, leaving the chips
        display stale until the next unrelated event.
        """
        _junk, blacklist, whitelist = store.get_lists(session_lists)
        defaults = list(DEFAULT_JUNK_TAGS)
        return ", ".join(defaults), render_blacklist_chips_html(
            defaults, blacklist, whitelist, lang=cur_lang
        )

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
        session_lists: SessionLists | None = None,
    ) -> tuple[str, str, str, str, str]:
        norm = build_normalizer_from_ui(
            replace_u,
            escape_p,
            filter_j,
            junk_str,
            sem_order,
            sep,
            persist=False,
            store=store,
            session_lists=session_lists,
        )
        if not store.share_mode:
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
        nav_badge = render_inspector_nav_badge_html(eff_idx, len(posts), single_prompt, lang=cur_lang, separator=sep)
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
        stats_html = render_export_stats_html(posts, export_text, exp_mode, lang=cur_lang, separator=sep)
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
        session_lists: SessionLists | None = None,
    ) -> None:
        if not store.share_mode:
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
            persist=not store.share_mode,
            store=store,
            session_lists=session_lists,
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
        session_lists: SessionLists | None = None,
        progress: gr.Progress = gr.Progress(),
    ) -> tuple[Any, ...]:
        if not store.share_mode:
            config_manager.config.image_quality = quality_val
            config_manager.config.data_saver_mode = quality_val == "text"

        trimmed_q = query_str.strip()
        effective_source = source_id
        effective_tags = trimmed_q

        try:
            results, effective_source, effective_tags, status_note, status_state = dispatch_search_fn(
                source_id,
                trimmed_q,
                int(limit_val),
                rating_val,
                cur_lang,
                progress,
            )

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
                persist=not store.share_mode,
                session_lists=session_lists,
            )

            new_history = record_search_history(trimmed_q, persist=not store.share_mode)
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
                session_lists=session_lists,
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
                gr.update(
                    choices=list(config_manager.config.search_history or []),
                    value=None,
                ),
                gr.update(
                    choices=compute_top_tags(config_manager.config.search_history),
                    value=None,
                ),
            )

    def clear_search_history_handler() -> list[Any]:
        if not store.share_mode:
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
        if not store.share_mode:
            config_manager.config.image_quality = quality_val
            config_manager.config.data_saver_mode = quality_val == "text"
            config_manager.save()
        return build_gallery_items(posts, quality_val)

    def on_theme_change(theme_val: str) -> str:
        effective: ThemeMode = (
            theme_val if theme_val in ("system", "dark", "light") else "system"  # type: ignore[assignment]
        )
        if not store.share_mode:
            config_manager.config.theme_mode = effective
            config_manager.save()
        return effective

    def on_copy_prompt_feedback(prompt_str: str, cur_lang: str, sep: str = ", ") -> str:
        if not prompt_str.strip():
            return render_status_pill_html(t(cur_lang, "status_ready"), lang=cur_lang, state="ready")
        # R7-11: count tags with the user's custom separator, not a hardcoded comma.
        effective_sep = sep if sep.strip() else ", "
        tag_count = len([x.strip() for x in prompt_str.split(effective_sep) if x.strip()])
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
        cur_theme: str = "system",
        cur_dict_q: str = "",
        session_lists: SessionLists | None = None,
    ) -> tuple[Any, ...]:
        effective_lang = "es" if new_lang == "es" else "en"
        if not store.share_mode:
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
            persist=not store.share_mode,
            session_lists=session_lists,
        )

        dict_record = get_tag_dictionary().lookup(cur_dict_q) if (cur_dict_q or "").strip() else None
        personal_sub_txt = t(effective_lang, "personal_subheading")
        if store.share_mode:
            personal_sub_txt += f"\n\n> {t(effective_lang, 'personal_share_mode_notice')}"

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
            # v1.0.3: new tabs & personal lists (indices 51..79 preserved)
            gr.update(label=t(effective_lang, "tab_extract")),
            gr.update(label=t(effective_lang, "tab_personal")),
            gr.update(value=t(effective_lang, "blacklist_post_btn")),
            render_section_header_html(t(effective_lang, "personal_list_heading")),
            personal_sub_txt,
            _personal_chips(effective_lang, session_lists=session_lists),
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
            # v1.0.6: indices 80..84 preserved
            gr.update(label=t(effective_lang, "recent_label")),
            gr.update(value=t(effective_lang, "clear_history_btn")),
            gr.update(value=t(effective_lang, "extract_clear_btn")),
            gr.update(label=t(effective_lang, "top_tags_label")),
            gr.update(value=t(effective_lang, "top_tags_add_btn")),
            # v1.1.0: theme picker + Tag Dictionary tab & controls appended at indices 85..92
            gr.update(
                label=t(effective_lang, "theme_label"),
                choices=get_theme_choices(effective_lang),
                value=cur_theme,
            ),
            gr.update(label=t(effective_lang, "tab_dictionary")),
            render_section_header_html(t(effective_lang, "dict_heading")),
            t(effective_lang, "dict_subheading"),
            gr.update(
                label=t(effective_lang, "dict_query_label"),
                placeholder=t(effective_lang, "dict_query_placeholder"),
            ),
            gr.update(value=t(effective_lang, "dict_search_btn")),
            gr.update(value=t(effective_lang, "dict_use_tag_btn")),
            render_tag_dictionary_html(dict_record, query=cur_dict_q, lang=effective_lang),
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
        session_lists: SessionLists | None = None,
    ) -> tuple[int, str, str, str]:
        idx = int(evt.index) if evt and evt.index is not None else 0
        norm = build_normalizer_from_ui(
            replace_u,
            escape_p,
            filter_j,
            junk_str,
            sem_order,
            sep,
            persist=False,
            store=store,
            session_lists=session_lists,
        )
        post = posts[idx] if posts and 0 <= idx < len(posts) else None
        prompt = (
            norm.format_post_prompt(post, exclude_categories=excl_cats, trigger_word=trig_word)
            if post
            else ""
        )
        nav_badge = render_inspector_nav_badge_html(idx, len(posts), prompt, lang=cur_lang, separator=sep)
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
        session_lists: SessionLists | None = None,
    ) -> tuple[int, str, str, str, dict[str, Any]]:
        if not posts:
            return (
                0,
                "",
                render_inspector_nav_badge_html(0, 0, "", lang=cur_lang),
                render_post_inspector_html(None, PromptNormalizer(), lang=cur_lang),
                gr.update(selected_index=0),
            )
        next_idx = (cur_idx + direction) % len(posts)
        norm = build_normalizer_from_ui(
            replace_u,
            escape_p,
            filter_j,
            junk_str,
            sem_order,
            sep,
            persist=False,
            store=store,
            session_lists=session_lists,
        )
        post = posts[next_idx]
        prompt = norm.format_post_prompt(post, exclude_categories=excl_cats, trigger_word=trig_word)
        nav_badge = render_inspector_nav_badge_html(next_idx, len(posts), prompt, lang=cur_lang, separator=sep)
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
        session_lists: SessionLists | None = None,
        progress: gr.Progress = gr.Progress(),
    ) -> tuple[str | None, str]:
        if not posts:
            return None, t(cur_lang, "export_empty_warn")
        norm = build_normalizer_from_ui(
            replace_u,
            escape_p,
            filter_j,
            junk_str,
            sem_order,
            sep,
            persist=not store.share_mode,
            store=store,
            session_lists=session_lists,
        )
        requested = Path(local_dir or "./exports").expanduser().resolve()
        cwd = Path.cwd().resolve()
        used_cwd_fallback = False
        try:
            requested.relative_to(cwd)
            out_dir = requested
        except ValueError:
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
            status += t(cur_lang, "export_zip_errors_suffix", count=len(bulk_exporter.last_zip_errors))
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
        session_lists: SessionLists | None = None,
        progress: gr.Progress = gr.Progress(),
    ) -> str:
        if store.share_mode:
            # R7-03: folder export would write to the host filesystem; the ZIP
            # download is the supported export path for public share sessions.
            return t(cur_lang, "export_folder_share_disabled")
        if not posts:
            return t(cur_lang, "export_empty_warn")
        norm = build_normalizer_from_ui(
            replace_u,
            escape_p,
            filter_j,
            junk_str,
            sem_order,
            sep,
            persist=not store.share_mode,
            store=store,
            session_lists=session_lists,
        )
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
        if store.share_mode:
            # R7-03 (CRITICAL): a public share session must never touch the host's
            # credential store or config.local.json; return a localized notice.
            return (t(cur_lang, "creds_share_disabled"), *(gr.update() for _ in range(8)))
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
        if store.share_mode:
            # R7-03 (CRITICAL): never wipe the host's persisted credentials from a
            # public share session.
            return (t(cur_lang, "creds_share_disabled"), *(gr.update() for _ in range(8)))
        config_manager.clear_credentials()
        return (t(cur_lang, "creds_cleared_msg"), *_cred_textbox_updates(cur_lang))

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
        session_lists: SessionLists | None = None,
    ) -> tuple[Any, ...]:
        _junk, blacklist, whitelist = store.get_lists(session_lists)
        new_tags = parse_tag_list(tag_text)
        if not new_tags:
            return (
                _personal_chips(cur_lang, session_lists=session_lists),
                t(cur_lang, "personal_not_found", tags=""),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
            )

        if kind == "blacklist_add":
            blacklist, added = add_tags(blacklist, new_tags)
            msg = (
                t(cur_lang, "personal_not_found", tags=", ".join(new_tags))
                if not added
                else t(cur_lang, "personal_added", tags=", ".join(added))
            )
        elif kind == "whitelist_add":
            whitelist, added = add_tags(whitelist, new_tags)
            msg = (
                t(cur_lang, "personal_not_found", tags=", ".join(new_tags))
                if not added
                else t(cur_lang, "personal_whitelisted", tags=", ".join(added))
            )
        elif kind == "blacklist_remove":
            blacklist, removed = remove_tags(blacklist, new_tags)
            msg = (
                t(cur_lang, "personal_not_found", tags=", ".join(new_tags))
                if not removed
                else t(cur_lang, "personal_removed", tags=", ".join(removed))
            )
        else:  # whitelist_remove
            whitelist, removed = remove_tags(whitelist, new_tags)
            msg = (
                t(cur_lang, "personal_not_found", tags=", ".join(new_tags))
                if not removed
                else t(cur_lang, "personal_removed", tags=", ".join(removed))
            )

        store.set_personal_lists(blacklist, whitelist, session_lists=session_lists)
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
            persist=not store.share_mode,
            session_lists=session_lists,
        )
        return _personal_chips(cur_lang, session_lists=session_lists), msg, *refresh

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
        session_lists: SessionLists | None = None,
    ) -> tuple[Any, ...]:
        store.set_personal_lists([], [], session_lists=session_lists)
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
            persist=not store.share_mode,
            session_lists=session_lists,
        )
        return (
            _personal_chips(cur_lang, session_lists=session_lists),
            t(cur_lang, "personal_reset_done"),
            *refresh,
        )

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
        session_lists: SessionLists | None = None,
    ) -> tuple[Any, ...]:
        norm = build_normalizer_from_ui(
            replace_u,
            escape_p,
            filter_j,
            junk_str,
            sem_order,
            sep,
            persist=False,
            store=store,
            session_lists=session_lists,
        )
        eff_idx = sel_idx if posts and 0 <= sel_idx < len(posts) else 0
        post = posts[eff_idx] if posts else None
        if post is None:
            # R7-07: gr.skip() keeps the current views intact (empty strings would
            # silently clear Inspector/Export/stats).
            return (
                _personal_chips(cur_lang, session_lists=session_lists),
                t(cur_lang, "blacklist_post_none"),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
            )

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
            # R7-07: gr.skip() keeps the current views intact.
            return (
                _personal_chips(cur_lang, session_lists=session_lists),
                t(cur_lang, "blacklist_post_none"),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
            )

        _junk, blacklist, whitelist = store.get_lists(session_lists)
        blacklist, added = add_tags(blacklist, filtered)
        store.set_personal_lists(blacklist, whitelist, session_lists=session_lists)
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
            persist=not store.share_mode,
            session_lists=session_lists,
        )
        msg = t(cur_lang, "blacklist_post_done", count=len(added))
        return _personal_chips(cur_lang, session_lists=session_lists), msg, *refresh

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
        session_lists: SessionLists | None = None,
    ) -> tuple[Any, ...]:
        path: str | None = None
        if isinstance(file_val, (list, tuple)):
            file_val = file_val[-1] if file_val else None
        if file_val is not None:
            path = file_val if isinstance(file_val, str) else getattr(file_val, "name", None)

        if not path:
            return gr.skip()

        norm = build_normalizer_from_ui(
            replace_u,
            escape_p,
            filter_j,
            junk_str,
            sem_order,
            sep,
            persist=False,
            store=store,
            session_lists=session_lists,
        )
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
        except Exception as err:
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

    def dictionary_lookup_handler(query: str, cur_lang: str) -> str:
        svc = get_tag_dictionary()
        record = svc.lookup(query)
        return render_tag_dictionary_html(record, query=query, lang=cur_lang)

    def dictionary_add_to_search_handler(
        dict_query: str,
        current_search_query: str,
        cur_lang: str,
    ) -> tuple[str, str]:
        svc = get_tag_dictionary()
        record = svc.lookup(dict_query)
        canonical = record.name if record is not None else (dict_query or "").strip().replace(" ", "_")
        if not canonical:
            return (
                current_search_query or "",
                render_status_pill_html(t(cur_lang, "status_ready"), lang=cur_lang, state="ready"),
            )
        updated_q, _ = add_top_tag_to_query(current_search_query, canonical)
        status = render_status_pill_html(
            t(cur_lang, "dict_added_to_search", tag=canonical),
            lang=cur_lang,
            state="ready",
        )
        return updated_q, status

    return {
        "refresh_views": refresh_views,
        "persist_settings_only": persist_settings_only,
        "execute_search_handler": execute_search_handler,
        "clear_search_history_handler": clear_search_history_handler,
        "on_quality_change": on_quality_change,
        "on_theme_change": on_theme_change,
        "on_copy_prompt_feedback": on_copy_prompt_feedback,
        "on_language_change": on_language_change,
        "on_gallery_select": on_gallery_select,
        "navigate_post_handler": navigate_post_handler,
        "generate_download_file_handler": generate_download_file_handler,
        "save_dataset_to_folder_handler": save_dataset_to_folder_handler,
        "save_credentials_handler": save_credentials_handler,
        "clear_credentials_handler": clear_credentials_handler,
        "personal_list_handler": personal_list_handler,
        "reset_junk_handler": reset_junk_handler,
        "reset_personal_handler": reset_personal_handler,
        "blacklist_post_handler": blacklist_post_handler,
        "extract_handler": extract_handler,
        "dictionary_lookup_handler": dictionary_lookup_handler,
        "dictionary_add_to_search_handler": dictionary_add_to_search_handler,
    }
