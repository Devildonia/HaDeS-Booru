"""
Verification tests for the v1.1.0 UI Overhaul (Audit R6-17):
- Mathematical WCAG 2.1 AA contrast verification (>= 4.5:1) for both Dark and Light palettes
- Offline bundled fonts (`Inter` and `JetBrains Mono` WOFF2 + `OFL.txt`, zero Google Fonts)
- Zero hardcoded inline theme colors in `components.py`
- Theme mode persistence (`system`, `dark`, `light`) and Tag Dictionary UI tab wiring
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hades_booru import config as config_module
from hades_booru.ui import components as components_module
from hades_booru.ui.layout import create_gradio_app
from hades_booru.ui.theme import (
    CUSTOM_CSS,
    DARK_PALETTE,
    FONTS_DIR,
    LIGHT_PALETTE,
    create_hades_theme,
)


def _hex_to_srgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    assert len(h) == 6, f"Expected 6-digit hex color, got {hex_color!r}"
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return r, g, b


def _relative_luminance(hex_color: str) -> float:
    def _channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_srgb(hex_color)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """Computes the WCAG 2.1 contrast ratio between two hex colors (1.0 to 21.0)."""
    l1 = _relative_luminance(fg_hex)
    l2 = _relative_luminance(bg_hex)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("palette_name,palette", [("dark", DARK_PALETTE), ("light", LIGHT_PALETTE)])
def test_wcag_aa_contrast_ratios_for_all_text_and_chips(
    palette_name: str, palette: dict[str, str]
) -> None:
    """Every text token and category chip must meet WCAG AA (>= 4.5:1) in both themes."""
    pairs = [
        ("text_primary", "bg_canvas"),
        ("text_primary", "bg_surface"),
        ("text_primary", "bg_elevated"),
        ("text_secondary", "bg_canvas"),
        ("text_secondary", "bg_surface"),
        ("text_secondary", "bg_elevated"),
        ("text_muted", "bg_canvas"),
        ("text_muted", "bg_surface"),
        ("text_muted", "bg_elevated"),
        ("accent_link", "bg_surface"),
        ("accent_link", "bg_elevated"),
        ("pill_accent_fg", "pill_accent_bg"),
        ("notice_fg", "notice_bg"),
        ("chip_copyright_fg", "chip_copyright_bg"),
        ("chip_character_fg", "chip_character_bg"),
        ("chip_artist_fg", "chip_artist_bg"),
        ("chip_general_fg", "chip_general_bg"),
        ("chip_meta_fg", "chip_meta_bg"),
        ("chip_personal_fg", "chip_personal_bg"),
        ("chip_kept_fg", "chip_kept_bg"),
        ("rating_g", "bg_elevated"),
        ("rating_s", "bg_elevated"),
        ("rating_q", "bg_elevated"),
        ("rating_e", "bg_elevated"),
        ("rating_u", "bg_elevated"),
    ]
    for fg_key, bg_key in pairs:
        ratio = contrast_ratio(palette[fg_key], palette[bg_key])
        assert ratio >= 4.5, (
            f"[{palette_name}] Contrast {fg_key} ({palette[fg_key]}) on {bg_key} "
            f"({palette[bg_key]}) is {ratio:.2f}:1 (< 4.5:1 WCAG AA)"
        )


def test_r617_fonts_bundled_locally_with_license_and_no_google_fonts() -> None:
    """R6-17: Inter and JetBrains Mono are bundled locally as WOFF2 with OFL license;
    no external Google Fonts requests are emitted."""
    assert (FONTS_DIR / "Inter-Regular.woff2").exists()
    assert (FONTS_DIR / "JetBrainsMono-Regular.woff2").exists()
    assert (FONTS_DIR / "OFL.txt").exists()

    assert "@font-face" in CUSTOM_CSS
    assert "font-family: 'Inter'" in CUSTOM_CSS
    assert "font-family: 'JetBrains Mono'" in CUSTOM_CSS
    assert "data:font/woff2;base64," in CUSTOM_CSS
    assert "fonts.googleapis.com" not in CUSTOM_CSS
    assert "fonts.gstatic.com" not in CUSTOM_CSS

    theme_src = Path(components_module.__file__).resolve().parent / "theme.py"
    assert "GoogleFont" not in theme_src.read_text(encoding="utf-8")
    theme_obj = create_hades_theme()
    assert theme_obj is not None


def test_components_have_no_hardcoded_inline_theme_colors() -> None:
    src = Path(components_module.__file__).read_text(encoding="utf-8")
    # Inline hex colors in HTML templates broke light-mode contrast; all must use CSS classes
    assert "color: #" not in src
    assert "background: rgba(" not in src


def test_theme_and_tag_dictionary_handlers_wired_in_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_module.ConfigManager, "save", lambda self: True)
    app = create_gradio_app()

    by_name = {getattr(e.fn, "__name__", ""): e for e in app.fns.values()}
    assert "on_theme_change" in by_name
    assert "dictionary_lookup_handler" in by_name
    assert "dictionary_add_to_search_handler" in by_name

    # Test theme change handler
    theme_entry = by_name["on_theme_change"]
    assert theme_entry.fn("light") == "light"
    assert config_module.config_manager.config.theme_mode == "light"
    assert theme_entry.fn("dark") == "dark"
    assert config_module.config_manager.config.theme_mode == "dark"

    # Test dictionary lookup handler (alias resolution + bilingual rendering)
    dict_entry = by_name["dictionary_lookup_handler"]
    html_en = dict_entry.fn("miku", "en")
    assert "hatsune_miku" in html_en
    assert "Resolved from alias: miku -&gt; hatsune_miku" in html_en
    assert "https://danbooru.donmai.us/wiki_pages/hatsune_miku" in html_en

    html_es_fallback = dict_entry.fn("cowboy_shot", "es")
    assert "Mostrando definición original en inglés" in html_es_fallback

    # Test adding canonical tag from dictionary to search bar
    use_entry = by_name["dictionary_add_to_search_handler"]
    new_query, status_html = use_entry.fn("miku", "1girl", "en")
    assert new_query == "1girl, hatsune_miku"
    assert "hatsune_miku" in status_html


def test_gradio_telemetry_disabled_launch_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard (v1.1.0 launch crash, Gradio 6.30).

    With analytics enabled (the Gradio 6.30 default), launch() compares our
    theme's to_dict() against every built-in theme. Font.__eq__ in
    gradio/themes/utils/fonts.py has no isinstance guard, so comparing our str
    font fallbacks against a built-in LocalFont entry raises
    AttributeError: 'str' object has no attribute 'name' and the app never
    starts. The app must therefore ship with telemetry disabled (privacy +
    skipping the buggy launch path). app.py enforces the same via
    GRADIO_ANALYTICS_ENABLED=false for Gradio builds without the parameter.
    """
    monkeypatch.setattr(config_module.ConfigManager, "save", lambda self: True)
    app = create_gradio_app()
    assert app.analytics_enabled is False
