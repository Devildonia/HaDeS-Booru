"""
Internationalization (i18n) module for HaDeS Booru.
Provides English (default) and Spanish UI translations with zero emojis and sober technical wording.
"""

from __future__ import annotations

from typing import Any, Literal

Language = Literal["en", "es"]

TRANSLATIONS: dict[Language, dict[str, str]] = {
    "en": {
        # Header
        "app_title": "HaDeS Booru",
        "app_subtitle": "Multi-source tag extractor, prompt normalizer, and dataset utility",
        "header_badge_runtime": "PYTHON 3.11",
        "header_badge_sources": "27 SOURCES",
        "header_meta_line1": "Engines: Danbooru, Gelbooru/DAPI, Moebooru, E621, Philomena, Zerochan, ArtStation, DeviantArt, Pawoo",
        "header_meta_line2": "Enter space-separated search tags or paste any direct post/listing URL",
        # Top Command Deck
        "source_label": "Source",
        "query_label": "Search Tags or Direct URL",
        "query_placeholder": "hatsune_miku 1girl solo  |  or https://danbooru.donmai.us/posts/...",
        "limit_label": "Limit",
        "rating_label": "Rating",
        "rating_all": "All",
        "rating_g": "G - General",
        "rating_s": "S - Sensitive",
        "rating_q": "Q - Questionable",
        "rating_e": "E - Explicit",
        "rating_u": "U - Unrated",
        "quality_label": "Display Quality",
        "quality_low": "Low (Thumbnail 180p)",
        "quality_medium": "Medium (Preview 720p)",
        "quality_high": "High (Sample HD)",
        "quality_original": "Original (Full Resolution)",
        "quality_text": "Text Only (No Images)",
        "lang_label": "Language",
        "search_btn": "Search",
        "status_label": "System Status",
        # Status messages
        "status_ready": "Ready. Enter search tags or paste a direct URL.",
        "status_direct_post": "Extracted post #{id} from {source}.",
        "status_url_search": "Detected search URL ({source}): {count} posts for '{tags}'.",
        "status_search_done": "Query completed on {source}: {count} posts returned.",
        "status_partial_result": " (Partial results from {source}: {error})",
        "status_filtered_rating": " (Rating {rating}: {count}).",
        "status_no_results": "No results returned from {source} for '{tags}'.",
        "status_error": "Request error: {error}",
        "status_copied": "Copied prompt to clipboard ({tags} tags).",
        "progress_direct": "Fetching post from {source}...",
        "progress_thumbnails": "Loading gallery images...",
        # Tabs
        "tab_gallery": "Gallery & Inspector",
        "tab_export": "Batch Export",
        "tab_settings": "Normalization & API Keys",
        # Tab 1: Gallery & Inspector
        "gallery_label": "Search Results",
        "prev_post_btn": "Previous",
        "next_post_btn": "Next",
        "nav_badge_empty": "NO POST SELECTED",
        "nav_badge_active": "POST {idx} / {total}  ·  {tags} TAGS  ·  ~{tokens} CLIP TOKENS",
        "selected_prompt_label": "Normalized Prompt",
        "copy_prompt_btn": "Copy Prompt to Clipboard",
        "inspector_empty_title": "No Post Selected",
        "inspector_empty": "Run a search and select any image in the gallery to inspect its taxonomic breakdown and normalized prompt.",
        "inspector_source_id": "Source & ID",
        "inspector_rating": "Rating",
        "inspector_resolution": "Dimensions",
        "inspector_original_link": "Source URL",
        "inspector_open_link": "Open original post",
        "inspector_filtered_suffix": "(filtered)",
        "inspector_derived_notice": "Note: Tags on this platform are derived from post titles/metadata rather than native booru taxonomy.",
        "cat_copyright": "Copyright / Series",
        "cat_character": "Character",
        "cat_artist": "Artist",
        "cat_general": "General",
        "cat_meta": "Meta",
        # Tab 2: Batch Export
        "card_export_config_title": "1. Format & Content Preview",
        "card_file_export_title": "2. Archive & File Download (.TXT / .ZIP)",
        "card_folder_export_title": "3. Direct Local Directory Export (Kohya_ss / OneTrainer)",
        "export_mode_label": "Export Format",
        "export_mode_dataset": "Dataset (.txt) - One prompt per line",
        "export_mode_unified": "Unified (.txt) - Deduplicated tag block",
        "export_mode_zip": "Trainer Archive (.zip) - Individual <id>.txt files",
        "trigger_word_label": "Trigger Prefix (Optional)",
        "trigger_word_placeholder": "e.g. char_name, masterpiece",
        "filename_prefix_label": "Filename Prefix",
        "filename_prefix_placeholder": "e.g. dataset_v1",
        "exclude_cats_label": "Exclude Tag Categories",
        "excl_copyright": "Copyright",
        "excl_character": "Character",
        "excl_artist": "Artist",
        "excl_meta": "Meta",
        "include_header_label": "Include metadata header comment in .txt files",
        "zip_include_images_label": "Bundle source images inside .zip archive (Trainer Archive mode)",
        "stats_posts": "Batch Size",
        "stats_posts_unit": "{count} posts",
        "stats_mode": "Export Mode",
        "stats_lines": "Output Lines",
        "stats_unique": "Unique Tags / Size",
        "stats_unique_val": "{tags} tags ({chars} chars)",
        "export_preview_label": "Normalized Output Preview",
        "generate_file_btn": "Generate Downloadable File",
        "download_file_label": "Generated File",
        "local_folder_label": "Target Directory Path",
        "browse_folder_btn": "Browse...",
        "download_imgs_local_label": "Download source images alongside <id>.txt",
        "high_res_local_label": "Prefer uncompressed original over sample",
        "save_local_folder_btn": "Write Dataset to Directory",
        "open_explorer_btn": "Open Directory",
        "export_empty_warn": "No posts loaded to export.",
        "export_file_saved": "File generated: {path}",
        "export_zip_errors_suffix": " ({count} image(s) failed to pack - see errors.txt inside the ZIP)",
        "export_folder_saved": "Exported to {folder}: {txt} .txt files, {img} images.",
        "export_folder_failed_suffix": " ({failed} failed/offline)",
        "explorer_opened": "Opened directory: {path}",
        "explorer_error": "Could not open file manager: {error} ({path})",
        "folder_dialog_title": "Select Export Directory",
        # Tab 3: Normalization & API Keys
        "norm_heading": "Tag Normalization & Formatting Rules",
        "replace_underscores_label": "Replace underscores (_) with spaces (preserves kaomoji tokens)",
        "escape_parens_label": r"Escape parentheses ( and ) as \( and \)",
        "filter_junk_label": "Filter non-visual meta and junk tags",
        "semantic_order_label": "Category Ordering",
        "separator_label": "Tag Delimiter",
        "junk_tags_label": "Excluded Tags (comma-separated, supports * wildcard)",
        "reset_junk_btn": "Reset Default Excluded Tags",
        "creds_heading": "Optional API Credentials (config.local.json)",
        "creds_subheading": "Configure account keys to elevate rate limits. Keys are stored in plain text with 0600 permissions when disk persistence is enabled.",
        "persist_creds_label": "Persist credentials to disk (config.local.json) - uncheck for session-only memory",
        "save_creds_btn": "Save Credentials",
        "creds_saved_msg": "Credentials saved to config.local.json (0600).",
        "creds_saved_session_msg": "Credentials active in memory for this session only (stripped from disk).",
    },
    "es": {
        # Header
        "app_title": "HaDeS Booru",
        "app_subtitle": "Extractor multi-fuente de etiquetas, normalizador de prompts y generador de datasets",
        "header_badge_runtime": "PYTHON 3.11",
        "header_badge_sources": "27 FUENTES",
        "header_meta_line1": "Motores: Danbooru, Gelbooru/DAPI, Moebooru, E621, Philomena, Zerochan, ArtStation, DeviantArt, Pawoo",
        "header_meta_line2": "Introduce tags separados por espacios o pega cualquier URL directa de post/listado",
        # Top Command Deck
        "source_label": "Servidor / Fuente",
        "query_label": "Tags de Búsqueda o URL Directa",
        "query_placeholder": "hatsune_miku 1girl solo  |  o https://danbooru.donmai.us/posts/...",
        "limit_label": "Límite",
        "rating_label": "Clasificación",
        "rating_all": "Todos",
        "rating_g": "G - General",
        "rating_s": "S - Sensible",
        "rating_q": "Q - Cuestionable",
        "rating_e": "E - Explícito",
        "rating_u": "U - Sin clasificar",
        "quality_label": "Calidad de Imagen",
        "quality_low": "Baja (Miniatura 180p)",
        "quality_medium": "Media (Vista previa 720p)",
        "quality_high": "Alta (Sample HD)",
        "quality_original": "Original (Resolución completa)",
        "quality_text": "Solo Texto (Sin imágenes)",
        "lang_label": "Idioma",
        "search_btn": "Buscar",
        "status_label": "Estado del Sistema",
        # Status messages
        "status_ready": "Listo. Introduce tags de búsqueda o pega una URL directa.",
        "status_direct_post": "Post #{id} extraído desde {source}.",
        "status_url_search": "URL de búsqueda detectada ({source}): {count} posts para '{tags}'.",
        "status_search_done": "Consulta completada en {source}: {count} posts obtenidos.",
        "status_partial_result": " (Resultados parciales de {source}: {error})",
        "status_filtered_rating": " (Clasificación {rating}: {count}).",
        "status_no_results": "Sin resultados en {source} para '{tags}'.",
        "status_error": "Error en la petición: {error}",
        "status_copied": "Prompt copiado al portapapeles ({tags} tags).",
        "progress_direct": "Descargando post desde {source}...",
        "progress_thumbnails": "Cargando imágenes de la galería...",
        # Tabs
        "tab_gallery": "Galería e Inspector",
        "tab_export": "Exportación por Lotes",
        "tab_settings": "Normalización y Credenciales API",
        # Tab 1: Gallery & Inspector
        "gallery_label": "Resultados de Búsqueda",
        "prev_post_btn": "Anterior",
        "next_post_btn": "Siguiente",
        "nav_badge_empty": "NINGÚN POST SELECCIONADO",
        "nav_badge_active": "POST {idx} / {total}  ·  {tags} TAGS  ·  ~{tokens} TOKENS CLIP",
        "selected_prompt_label": "Prompt Normalizado",
        "copy_prompt_btn": "Copiar Prompt al Portapapeles",
        "inspector_empty_title": "Ningún Post Seleccionado",
        "inspector_empty": "Realiza una búsqueda y selecciona cualquier imagen de la galería para inspeccionar sus categorías de tags y su prompt.",
        "inspector_source_id": "Fuente e ID",
        "inspector_rating": "Clasificación",
        "inspector_resolution": "Dimensiones",
        "inspector_original_link": "URL de Origen",
        "inspector_open_link": "Abrir publicación original",
        "inspector_filtered_suffix": "(filtrado)",
        "inspector_derived_notice": "Nota: Las etiquetas de esta plataforma se derivan del título/metadatos y no de una taxonomía booru nativa.",
        "cat_copyright": "Copyright / Obra",
        "cat_character": "Personaje",
        "cat_artist": "Artista",
        "cat_general": "General",
        "cat_meta": "Metadatos",
        # Tab 2: Batch Export
        "card_export_config_title": "1. Formato y Vista Previa",
        "card_file_export_title": "2. Descarga de Archivo (.TXT / .ZIP)",
        "card_folder_export_title": "3. Exportación Directa a Carpeta Local (Kohya_ss / OneTrainer)",
        "export_mode_label": "Formato de Exportación",
        "export_mode_dataset": "Dataset (.txt) - Un prompt por línea",
        "export_mode_unified": "Unificado (.txt) - Bloque único sin duplicados",
        "export_mode_zip": "Archivo Trainer (.zip) - Archivos <id>.txt individuales",
        "trigger_word_label": "Prefijo / Trigger Word (Opcional)",
        "trigger_word_placeholder": "ej. char_name, masterpiece",
        "filename_prefix_label": "Prefijo de Archivo",
        "filename_prefix_placeholder": "ej. dataset_v1",
        "exclude_cats_label": "Excluir Categorías de Tags",
        "excl_copyright": "Copyright",
        "excl_character": "Personaje",
        "excl_artist": "Artista",
        "excl_meta": "Metadatos",
        "include_header_label": "Incluir comentario de cabecera con metadatos en archivos .txt",
        "zip_include_images_label": "Incluir imágenes originales dentro del archivo .zip (Modo Trainer Archive)",
        "stats_posts": "Tamaño del Lote",
        "stats_posts_unit": "{count} posts",
        "stats_mode": "Modo de Exportación",
        "stats_lines": "Líneas de Salida",
        "stats_unique": "Tags Únicos / Tamaño",
        "stats_unique_val": "{tags} tags ({chars} caracteres)",
        "export_preview_label": "Vista Previa del Contenido Normalizado",
        "generate_file_btn": "Generar Archivo Descargable",
        "download_file_label": "Archivo Generado",
        "local_folder_label": "Ruta de Carpeta de Destino",
        "browse_folder_btn": "Examinar...",
        "download_imgs_local_label": "Descargar imágenes junto a cada <id>.txt",
        "high_res_local_label": "Preferir original sin comprimir frente a sample",
        "save_local_folder_btn": "Guardar Dataset en Carpeta",
        "open_explorer_btn": "Abrir Carpeta",
        "export_empty_warn": "No hay posts cargados para exportar.",
        "export_file_saved": "Archivo generado: {path}",
        "export_zip_errors_suffix": " ({count} imágenes fallaron al empaquetar - ver errors.txt dentro del ZIP)",
        "export_folder_saved": "Exportado en {folder}: {txt} archivos .txt, {img} imágenes.",
        "export_folder_failed_suffix": " ({failed} fallidas/offline)",
        "explorer_opened": "Carpeta abierta: {path}",
        "explorer_error": "No se pudo abrir el explorador de archivos: {error} ({path})",
        "folder_dialog_title": "Seleccionar Carpeta de Exportación",
        # Tab 3: Normalization & API Keys
        "norm_heading": "Reglas de Normalización y Formato de Tags",
        "replace_underscores_label": "Reemplazar guiones bajos (_) por espacios (conserva kaomojis)",
        "escape_parens_label": r"Escapar paréntesis ( y ) como \( y \)",
        "filter_junk_label": "Filtrar metadatos no visuales y tags irrelevantes",
        "semantic_order_label": "Orden de Categorías",
        "separator_label": "Delimitador de Tags",
        "junk_tags_label": "Tags Excluidos (separados por coma, soporta comodín *)",
        "reset_junk_btn": "Restaurar Lista por Defecto",
        "creds_heading": "Credenciales de API Opcionales (config.local.json)",
        "creds_subheading": "Configura llaves de cuenta para elevar límites de peticiones. Se guardan en texto plano con permisos 0600 si la persistencia en disco está activa.",
        "persist_creds_label": "Persistir credenciales en disco (config.local.json) - desmarca para guardar solo en memoria de sesión",
        "save_creds_btn": "Guardar Credenciales",
        "creds_saved_msg": "Credenciales guardadas en config.local.json (0600).",
        "creds_saved_session_msg": "Credenciales activas solo en memoria para esta sesión (borradas de disco).",
    },
}


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Returns the translated string for the given language and key."""
    effective_lang: Language = "es" if lang == "es" else "en"
    catalog = TRANSLATIONS[effective_lang]
    template = catalog.get(key) or TRANSLATIONS["en"].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template


def get_rating_choices(lang: str) -> list[tuple[str, str]]:
    """Returns localized choices for the rating filter dropdown."""
    return [
        (t(lang, "rating_all"), "all"),
        (t(lang, "rating_g"), "g"),
        (t(lang, "rating_s"), "s"),
        (t(lang, "rating_q"), "q"),
        (t(lang, "rating_e"), "e"),
    ]


def get_quality_choices(lang: str) -> list[tuple[str, str]]:
    """Returns localized choices for the image display quality dropdown."""
    return [
        (t(lang, "quality_low"), "low"),
        (t(lang, "quality_medium"), "medium"),
        (t(lang, "quality_high"), "high"),
        (t(lang, "quality_original"), "original"),
        (t(lang, "quality_text"), "text"),
    ]


def get_export_mode_choices(lang: str) -> list[tuple[str, str]]:
    """Returns localized choices for the export format radio button."""
    return [
        (t(lang, "export_mode_dataset"), "dataset"),
        (t(lang, "export_mode_unified"), "unified"),
        (t(lang, "export_mode_zip"), "trainer-zip"),
    ]


def get_exclude_category_choices(lang: str) -> list[tuple[str, str]]:
    """Returns localized choices for the excluded tag categories checkbox group."""
    return [
        (t(lang, "excl_copyright"), "copyright"),
        (t(lang, "excl_character"), "character"),
        (t(lang, "excl_artist"), "artist"),
        (t(lang, "excl_meta"), "meta"),
    ]
