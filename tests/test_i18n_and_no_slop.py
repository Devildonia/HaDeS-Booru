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


def test_logo_h_webp_and_version_1_0_1_in_header() -> None:
    from hades_booru import __version__

    assert __version__ == "1.0.1"
    assert LOGO_DATA_URI.startswith("data:image/webp;base64,")
    header = render_header_html("en")
    assert 'class="hades-logo-img"' in header
    assert "data:image/webp;base64," in header
    assert "v1.0.1" in header


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
