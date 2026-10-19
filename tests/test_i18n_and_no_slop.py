"""
Unit Tests for Internationalization (EN/ES parity), Logo Embedding, Inspector Badges,
and Zero-Emoji / Zero-Slop enforcement.
"""

from __future__ import annotations

import re
from pathlib import Path

from hades_booru.i18n import TRANSLATIONS, t
from hades_booru.models import AppConfig
from hades_booru.ui.components import (
    LOGO_DATA_URI,
    render_header_html,
    render_inspector_nav_badge_html,
    render_status_pill_html,
)

# Unicode emoji ranges (Pictographs, Emoticons, Transport/Map, Dingbats, Supplemental Symbols)
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002600-\U000027BF"
    "\U0001FA00-\U0001FAFF"
    "]"
)


def test_default_config_is_english_and_high_quality() -> None:
    cfg = AppConfig()
    assert cfg.language == "en"
    assert cfg.image_quality == "high"


def test_i18n_en_es_key_parity() -> None:
    en_keys = set(TRANSLATIONS["en"].keys())
    es_keys = set(TRANSLATIONS["es"].keys())
    assert en_keys == es_keys
    assert t("en", "search_btn") == "Search"
    assert t("es", "search_btn") == "Buscar"


def test_i18n_v103_new_feature_keys_present() -> None:
    """v1.0.3 feature strings (personal lists + Image to Prompt) exist in both languages."""
    required_v103_keys = [
        "tab_extract",
        "tab_personal",
        "extract_preview_label",
        "personal_list_heading",
        "blacklist_add_btn",
        "whitelist_add_btn",
        "reset_personal_btn",
        "blacklist_post_btn",
        "extract_heading",
        "extract_btn",
        "extract_no_meta",
    ]
    for key in required_v103_keys:
        assert key in TRANSLATIONS["en"], f"Missing EN key: {key}"
        assert key in TRANSLATIONS["es"], f"Missing ES key: {key}"


def test_windows_launcher_is_ascii_safe() -> None:
    """cmd.exe parses .bat with the OEM code page (cp850 on Spanish Windows).

    UTF-8 multi-byte chars render as mojibake (e.g. 'ÔÇç') and an unescaped
    '&' in a line splits it into extra commands (the 'LORA' error of v1.0.2).
    Keep start.bat pure ASCII, CRLF, and free of ampersands.
    """
    bat = Path(__file__).resolve().parent.parent / "start.bat"
    data = bat.read_bytes()
    data.decode("ascii")  # raises UnicodeDecodeError on any non-ASCII byte
    assert b"\r\n" in data, "start.bat must use CRLF line endings"
    assert b" & " not in data, "unescaped '&' would be parsed as a command separator"


def test_logo_h_webp_and_current_version_in_header() -> None:
    from hades_booru import __version__

    # The header must advertise the exact version shipped by the package.
    assert LOGO_DATA_URI.startswith("data:image/webp;base64,")
    header = render_header_html("en")
    assert 'class="hades-logo-img"' in header
    assert "data:image/webp;base64," in header
    assert f"v{__version__}" in header


def test_inspector_nav_badge_and_status_pill() -> None:
    empty_badge = render_inspector_nav_badge_html(0, 0, "", lang="en")
    assert "NO POST SELECTED" in empty_badge

    active_badge = render_inspector_nav_badge_html(
        0, 20, "vocaloid, hatsune miku, 1girl, solo", lang="en"
    )
    assert "POST 1 / 20" in active_badge
    assert "4 TAGS" in active_badge
    assert "CLIP TOKENS" in active_badge

    status_html = render_status_pill_html("Ready.", lang="en", state="ready")
    assert "System Status" in status_html
    assert "Ready." in status_html


def test_zero_emojis_across_codebase() -> None:
    root = Path(__file__).resolve().parent.parent
    checked_files = [
        *root.glob("hades_booru/**/*.py"),
        root / "app.py",
        root / "README.md",
    ]
    assert len(checked_files) >= 15

    for file_path in checked_files:
        content = file_path.read_text(encoding="utf-8")
        match = EMOJI_RE.search(content)
        assert match is None, f"Found forbidden emoji {repr(match.group(0))} in {file_path}"
