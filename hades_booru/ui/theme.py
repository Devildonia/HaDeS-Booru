"""
Design System Tokens, Selectable Light/Dark/System Theme Palettes (WCAG AA >= 4.5:1),
Bundled Local Fonts (Inter & JetBrains Mono WOFF2, R6-17), and Symmetric Bento CSS for HaDeS Booru.
Follows HIG (Clarity, Deference, Depth) with strict CSS custom properties and zero visual noise.
"""

from __future__ import annotations

import base64
from pathlib import Path

import gradio as gr

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

# Structured token dictionaries exposed for automated WCAG AA contrast verification (v1.1.0)
DARK_PALETTE: dict[str, str] = {
    "bg_canvas": "#090d16",
    "bg_surface": "#111827",
    "bg_elevated": "#1e293b",
    "bg_subtle": "#0f172a",
    "border_subtle": "#1f2937",
    "border_strong": "#334155",
    "accent_primary": "#2563eb",
    "accent_brand": "#e11d48",
    "accent_link": "#60a5fa",
    "pill_accent_bg": "#172554",
    "pill_accent_fg": "#93c5fd",
    "pill_accent_border": "#1d4ed8",
    "text_primary": "#f8fafc",
    "text_secondary": "#cbd5e1",
    "text_muted": "#94a3b8",
    "notice_bg": "#451a03",
    "notice_fg": "#fcd34d",
    "notice_border": "#92400e",
    "chip_copyright_bg": "#2e1065",
    "chip_copyright_fg": "#e9d5ff",
    "chip_copyright_border": "#6b21a8",
    "chip_character_bg": "#064e3b",
    "chip_character_fg": "#a7f3d0",
    "chip_character_border": "#047857",
    "chip_artist_bg": "#4c0519",
    "chip_artist_fg": "#fecdd3",
    "chip_artist_border": "#9f1239",
    "chip_general_bg": "#172554",
    "chip_general_fg": "#bfdbfe",
    "chip_general_border": "#1d4ed8",
    "chip_meta_bg": "#1e293b",
    "chip_meta_fg": "#e2e8f0",
    "chip_meta_border": "#475569",
    "chip_personal_bg": "#4c0519",
    "chip_personal_fg": "#fecdd3",
    "chip_personal_border": "#e11d48",
    "chip_kept_bg": "#064e3b",
    "chip_kept_fg": "#a7f3d0",
    "chip_kept_border": "#10b981",
    "rating_g": "#34d399",
    "rating_s": "#fbbf24",
    "rating_q": "#fb923c",
    "rating_e": "#f87171",
    "rating_u": "#cbd5e1",
}

LIGHT_PALETTE: dict[str, str] = {
    "bg_canvas": "#f1f5f9",
    "bg_surface": "#ffffff",
    "bg_elevated": "#f8fafc",
    "bg_subtle": "#e2e8f0",
    "border_subtle": "#cbd5e1",
    "border_strong": "#94a3b8",
    "accent_primary": "#1d4ed8",
    "accent_brand": "#be123c",
    "accent_link": "#1d4ed8",
    "pill_accent_bg": "#dbeafe",
    "pill_accent_fg": "#1e3a8a",
    "pill_accent_border": "#60a5fa",
    "text_primary": "#0f172a",
    "text_secondary": "#334155",
    "text_muted": "#475569",
    "notice_bg": "#fef3c7",
    "notice_fg": "#78350f",
    "notice_border": "#d97706",
    "chip_copyright_bg": "#f3e8ff",
    "chip_copyright_fg": "#581c87",
    "chip_copyright_border": "#c084fc",
    "chip_character_bg": "#d1fae5",
    "chip_character_fg": "#065f46",
    "chip_character_border": "#34d399",
    "chip_artist_bg": "#ffe4e6",
    "chip_artist_fg": "#881337",
    "chip_artist_border": "#fb7185",
    "chip_general_bg": "#dbeafe",
    "chip_general_fg": "#1e3a8a",
    "chip_general_border": "#60a5fa",
    "chip_meta_bg": "#e2e8f0",
    "chip_meta_fg": "#1e293b",
    "chip_meta_border": "#94a3b8",
    "chip_personal_bg": "#ffe4e6",
    "chip_personal_fg": "#881337",
    "chip_personal_border": "#be123c",
    "chip_kept_bg": "#d1fae5",
    "chip_kept_fg": "#065f46",
    "chip_kept_border": "#059669",
    "rating_g": "#047857",
    "rating_s": "#b45309",
    "rating_q": "#c2410c",
    "rating_e": "#b91c1c",
    "rating_u": "#334155",
}


def _encode_font_woff2(filename: str) -> str:
    path = FONTS_DIR / filename
    if path.exists():
        try:
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:font/woff2;base64,{b64}"
        except OSError:
            pass
    return ""


def _build_local_font_face_css() -> str:
    """Generates @font-face declarations for locally bundled Inter and JetBrains Mono (R6-17)."""
    blocks: list[str] = []
    inter_uri = _encode_font_woff2("Inter-Regular.woff2")
    if inter_uri:
        blocks.append(
            "@font-face {\n"
            "    font-family: 'Inter';\n"
            "    font-style: normal;\n"
            "    font-weight: 400 700;\n"
            "    font-display: swap;\n"
            f"    src: url('{inter_uri}') format('woff2');\n"
            "}"
        )
    jb_uri = _encode_font_woff2("JetBrainsMono-Regular.woff2")
    if jb_uri:
        blocks.append(
            "@font-face {\n"
            "    font-family: 'JetBrains Mono';\n"
            "    font-style: normal;\n"
            "    font-weight: 400 700;\n"
            "    font-display: swap;\n"
            f"    src: url('{jb_uri}') format('woff2');\n"
            "}"
        )
    return "\n".join(blocks)


def _palette_to_css_vars(p: dict[str, str]) -> str:
    lines = [f"    --hb-{k.replace('_', '-')}: {v};" for k, v in p.items()]
    return "\n".join(lines)


THEME_APPLY_JS = """
(mode) => {
    const m = (mode === 'light' || mode === 'dark') ? mode : 'system';

    // Gradio 6.30 native component CSS variable overrides per theme.
    // These map our design tokens to Gradio's internal variable names so that
    // dropdowns, buttons, tabs, gallery, and all other native components
    // follow the selected theme.
    const GRADIO_VARS = {
        dark: {
            '--body-background-fill': '#090d16',
            '--body-text-color': '#f8fafc',
            '--body-text-color-subdued': '#94a3b8',
            '--bg': '#090d16',
            '--background-fill-primary': '#111827',
            '--background-fill-secondary': '#1e293b',
            '--block-background-fill': '#111827',
            '--block-border-color': '#1f2937',
            '--block-label-background-fill': '#111827',
            '--block-label-border-color': '#1f2937',
            '--block-label-text-color': '#94a3b8',
            '--block-title-text-color': '#94a3b8',
            '--block-info-text-color': '#94a3b8',
            '--border-color-primary': '#1f2937',
            '--border-color-accent': '#60a5fa',
            '--border-color-accent-subdued': '#1d4ed8',
            '--button-primary-background-fill': '#2563eb',
            '--button-primary-text-color': '#ffffff',
            '--button-secondary-background-fill': '#1e293b',
            '--button-secondary-text-color': '#f8fafc',
            '--slider-color': '#2563eb',
            '--checkbox-background-color': '#1e293b',
            '--table-even-background-fill': '#111827',
            '--table-odd-background-fill': '#0f172a',
            '--table-border-color': '#1f2937',
            '--table-text-color': '#f8fafc',
            '--accordion-text-color': '#f8fafc',
        },
        light: {
            '--body-background-fill': '#f1f5f9',
            '--body-text-color': '#0f172a',
            '--body-text-color-subdued': '#475569',
            '--bg': '#f1f5f9',
            '--background-fill-primary': '#ffffff',
            '--background-fill-secondary': '#f8fafc',
            '--block-background-fill': '#ffffff',
            '--block-border-color': '#cbd5e1',
            '--block-label-background-fill': '#ffffff',
            '--block-label-border-color': '#cbd5e1',
            '--block-label-text-color': '#475569',
            '--block-title-text-color': '#475569',
            '--block-info-text-color': '#475569',
            '--border-color-primary': '#cbd5e1',
            '--border-color-accent': '#60a5fa',
            '--border-color-accent-subdued': '#93c5fd',
            '--button-primary-background-fill': '#1d4ed8',
            '--button-primary-text-color': '#ffffff',
            '--button-secondary-background-fill': '#e2e8f0',
            '--button-secondary-text-color': '#0f172a',
            '--slider-color': '#1d4ed8',
            '--checkbox-background-color': '#ffffff',
            '--table-even-background-fill': '#ffffff',
            '--table-odd-background-fill': '#f8fafc',
            '--table-border-color': '#cbd5e1',
            '--table-text-color': '#0f172a',
            '--accordion-text-color': '#0f172a',
        },
    };

    const applyMode = (mode) => {
        const mm = (mode === 'light' || mode === 'dark') ? mode : 'system';
        const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        const effective = (mm === 'system') ? (prefersDark ? 'dark' : 'light') : mm;
        document.documentElement.setAttribute('data-hb-theme', effective);
        document.documentElement.classList.toggle('dark', effective === 'dark');
        if (document.body) {
            document.body.setAttribute('data-hb-theme', effective);
            document.body.classList.toggle('dark', effective === 'dark');
        }
        // Override Gradio 6.30 native component variables
        const gv = GRADIO_VARS[effective];
        if (gv) {
            for (const [prop, val] of Object.entries(gv)) {
                document.documentElement.style.setProperty(prop, val);
            }
        }
    };

    applyMode(m);
    // R7-14: remember the selected mode and bind a singleton listener so a live
    // OS color-scheme change re-applies the theme while in "system" mode.
    window.__hb_theme_mode = m;
    window.__hb_apply_theme = applyMode;
    if (!window.__hb_theme_mql_bound && window.matchMedia) {
        const mql = window.matchMedia('(prefers-color-scheme: dark)');
        const onSchemeChange = () => {
            if (window.__hb_theme_mode === 'system' && window.__hb_apply_theme) {
                window.__hb_apply_theme('system');
            }
        };
        if (typeof mql.addEventListener === 'function') {
            mql.addEventListener('change', onSchemeChange);
        } else if (typeof mql.addListener === 'function') {
            mql.addListener(onSchemeChange);  // legacy Safari
        }
        window.__hb_theme_mql_bound = true;
    }
    return mode;
}
"""


def build_custom_css() -> str:
    font_css = _build_local_font_face_css()
    dark_vars = _palette_to_css_vars(DARK_PALETTE)
    light_vars = _palette_to_css_vars(LIGHT_PALETTE)

    return f"""
{font_css}

:root,
:root[data-hb-theme="dark"],
.dark {{
{dark_vars}
    --hb-radius-panel: 10px;
    --hb-radius-control: 6px;
    --hb-font-sans: 'Inter', system-ui, -apple-system, sans-serif;
    --hb-font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Consolas, monospace;
}}

:root[data-hb-theme="light"],
body:not(.dark)[data-hb-theme="light"] {{
{light_vars}
}}

@media (prefers-color-scheme: light) {{
    :root:not([data-hb-theme="dark"]):not(.dark) {{
{light_vars}
    }}
}}

/* Remove Gradio's default emoji footer and tighten outer container padding */
footer {{
    display: none !important;
}}
.gradio-container {{
    max-width: 1640px !important;
    margin: 0 auto !important;
    padding-top: 12px !important;
    padding-bottom: 20px !important;
    font-family: var(--hb-font-sans) !important;
}}

/* 1. Top Header Bar */
.hades-header {{
    background: var(--hb-bg-surface);
    border: 1px solid var(--hb-border-subtle);
    border-radius: var(--hb-radius-panel);
    padding: 12px 18px;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 14px;
}}
.hades-title-group {{
    display: flex;
    align-items: center;
    gap: 14px;
}}
.hades-logo-frame {{
    width: 42px;
    height: 42px;
    border-radius: 8px;
    background: var(--hb-bg-subtle);
    border: 1px solid var(--hb-border-strong);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}}
.hades-logo-img {{
    width: 32px;
    height: 32px;
    object-fit: contain;
}}
.hades-brand-title {{
    font-size: 1.12rem;
    font-weight: 700;
    color: var(--hb-text-primary);
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    letter-spacing: -0.01em;
}}
.hades-pill {{
    font-size: 0.65rem;
    font-family: var(--hb-font-mono);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 8px;
    border-radius: 4px;
    background: var(--hb-bg-elevated);
    color: var(--hb-text-secondary);
    border: 1px solid var(--hb-border-strong);
}}
.hades-pill-accent {{
    background: var(--hb-pill-accent-bg);
    color: var(--hb-pill-accent-fg);
    border: 1px solid var(--hb-pill-accent-border);
}}
.hades-subtitle {{
    font-size: 0.76rem;
    color: var(--hb-text-secondary);
    margin: 2px 0 0 0;
}}
.hades-header-meta {{
    font-size: 0.74rem;
    color: var(--hb-text-secondary);
    text-align: right;
}}
.hades-header-meta-accent {{
    color: var(--hb-accent-link);
    font-size: 0.7rem;
    font-weight: 500;
}}

/* 2. Command Deck Alignment */
.hades-command-row {{
    align-items: flex-start !important;
    gap: 10px !important;
}}
/* Gradio 6.30 sets explicit heights on .container and .html-container
   inside dropdown blocks and HTML wrappers, which combined with
   align-items:stretch creates a circular stretch chain.
   Reset them so content sits at its natural height. */
.hades-command-row .form .container {{
    height: auto !important;
}}
.hades-command-row .form .block {{
    height: auto !important;
    min-height: 0 !important;
}}
.hades-command-row > .block .html-container {{
    height: auto !important;
    max-height: 94px !important;
    overflow: hidden !important;
}}
.hades-command-row > .block {{
    height: auto !important;
    max-height: 114px !important;
}}
.hades-search-btn {{
    min-height: 74px !important;
    height: 74px !important;
    font-weight: 600 !important;
    font-size: 0.92rem !important;
    letter-spacing: 0.01em !important;
    border-radius: var(--hb-radius-control) !important;
}}
.hades-status-box {{
    background: var(--hb-bg-surface);
    border: 1px solid var(--hb-border-subtle);
    border-radius: var(--hb-radius-control);
    padding: 10px 14px;
    min-height: 74px;
    /* Audit R7-E: allow the flex item to shrink and wrap long text (URLs, tag
    chains) instead of clipping it at narrow viewports. */
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
}}
.hades-status-label {{
    font-size: 0.66rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--hb-text-muted);
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 6px;
}}
.hades-status-dot {{
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
}}
.hades-status-text {{
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--hb-text-primary);
    line-height: 1.3;
    white-space: normal;
    /* Audit R7-E: `anywhere` breaks inside long unbroken tokens (URLs, tag
    chains) that `break-word` would still clip. */
    overflow-wrap: anywhere;
    word-break: break-word;
}}

/* 3. Tab 1: Symmetric Split-Pane Gallery & Inspector (660px coordinated height) */
.hades-nav-bar {{
    align-items: center !important;
    gap: 8px !important;
}}
.hades-nav-badge {{
    background: var(--hb-bg-surface);
    border: 1px solid var(--hb-border-subtle);
    border-radius: var(--hb-radius-control);
    /* Audit R6-27: min-height so the badge keeps a stable height. */
    min-height: 36px;
    height: auto;
    max-width: 100%;
    /* Audit R7-E: the old nowrap + ellipsis CLIPPED the counter text at narrow
    viewports (screenshot evidence). Wrap instead of truncate. */
    min-width: 0;
    white-space: normal;
    overflow-wrap: anywhere;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--hb-font-mono);
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--hb-text-secondary);
    letter-spacing: 0.04em;
    padding: 4px 10px;
}}
.hades-copy-btn {{
    font-weight: 600 !important;
    font-size: 0.8rem !important;
}}
.hades-inspector-scroll {{
    background: var(--hb-bg-surface);
    border: 1px solid var(--hb-border-subtle);
    border-radius: var(--hb-radius-panel);
    padding: 14px;
    height: 412px;
    overflow-y: auto;
    box-sizing: border-box;
}}
.hades-dict-card {{
    background: var(--hb-bg-surface);
    border: 1px solid var(--hb-border-subtle);
    border-radius: var(--hb-radius-panel);
    padding: 18px;
    min-height: 260px;
    box-sizing: border-box;
}}
.hades-dict-body {{
    font-size: 0.88rem;
    line-height: 1.6;
    color: var(--hb-text-primary);
    background: var(--hb-bg-elevated);
    border: 1px solid var(--hb-border-subtle);
    border-radius: var(--hb-radius-control);
    padding: 12px 14px;
    margin: 10px 0;
}}
.hades-empty-state {{
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 24px;
    color: var(--hb-text-muted);
    box-sizing: border-box;
}}
.hades-empty-title {{
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--hb-text-secondary);
    margin: 0 0 6px 0;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}
.hades-empty-desc {{
    font-size: 0.78rem;
    color: var(--hb-text-muted);
    max-width: 420px;
    line-height: 1.45;
    margin: 0;
}}

/* 4. Taxonomic Tag Cloud, Chips, Notices & Metadata Grid */
.meta-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
    margin-bottom: 12px;
}}
.meta-grid-4 {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 12px;
}}
.meta-box {{
    background: var(--hb-bg-elevated);
    border: 1px solid var(--hb-border-strong);
    border-radius: var(--hb-radius-control);
    padding: 7px 11px;
    font-size: 0.76rem;
    color: var(--hb-text-primary);
}}
.meta-box strong {{
    display: block;
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--hb-text-secondary);
    margin-bottom: 2px;
}}
.hades-link {{
    color: var(--hb-accent-link);
    text-decoration: underline;
    font-weight: 500;
}}
.hades-derived-notice {{
    font-size: 0.74rem;
    color: var(--hb-notice-fg);
    background: var(--hb-notice-bg);
    border: 1px solid var(--hb-notice-border);
    border-radius: 5px;
    padding: 7px 11px;
    margin-bottom: 10px;
}}
.hades-rating-g {{ color: var(--hb-rating-g); font-weight: 600; }}
.hades-rating-s {{ color: var(--hb-rating-s); font-weight: 600; }}
.hades-rating-q {{ color: var(--hb-rating-q); font-weight: 600; }}
.hades-rating-e {{ color: var(--hb-rating-e); font-weight: 600; }}
.hades-rating-u {{ color: var(--hb-rating-u); font-weight: 600; }}

.tag-section-title {{
    font-size: 0.69rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--hb-text-secondary);
    margin: 12px 0 6px 0;
    padding-bottom: 3px;
    border-bottom: 1px solid var(--hb-border-subtle);
}}
.tag-cloud,
.hades-chip-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-bottom: 8px;
    align-items: center;
}}
.hades-chip-kept-row {{
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px dashed var(--hb-border-subtle);
}}
.hades-chip-kept-label {{
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--hb-text-secondary);
    margin-right: 4px;
}}
.tag-chip {{
    display: inline-block;
    font-size: 0.73rem;
    font-family: var(--hb-font-mono);
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 500;
    background: var(--hb-chip-meta-bg);
    color: var(--hb-chip-meta-fg);
    border: 1px solid var(--hb-chip-meta-border);
    transition: border-color 150ms ease;
}}
.tag-chip-filtered {{
    opacity: 0.55;
    text-decoration: line-through;
}}
.tag-copyright {{
    background: var(--hb-chip-copyright-bg);
    color: var(--hb-chip-copyright-fg);
    border: 1px solid var(--hb-chip-copyright-border);
}}
.tag-character {{
    background: var(--hb-chip-character-bg);
    color: var(--hb-chip-character-fg);
    border: 1px solid var(--hb-chip-character-border);
}}
.tag-artist {{
    background: var(--hb-chip-artist-bg);
    color: var(--hb-chip-artist-fg);
    border: 1px solid var(--hb-chip-artist-border);
}}
.tag-general {{
    background: var(--hb-chip-general-bg);
    color: var(--hb-chip-general-fg);
    border: 1px solid var(--hb-chip-general-border);
}}
.tag-meta {{
    background: var(--hb-chip-meta-bg);
    color: var(--hb-chip-meta-fg);
    border: 1px solid var(--hb-chip-meta-border);
}}
.tag-chip-personal {{
    background: var(--hb-chip-personal-bg);
    color: var(--hb-chip-personal-fg);
    border: 1px solid var(--hb-chip-personal-border);
}}
.tag-chip-kept {{
    background: var(--hb-chip-kept-bg);
    color: var(--hb-chip-kept-fg);
    border: 1px solid var(--hb-chip-kept-border);
}}

/* 5. Symmetric Bento Section Headers */
.hades-section-header {{
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--hb-text-primary);
    padding-bottom: 8px;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--hb-border-subtle);
}}
.hades-cred-title {{
    font-size: 0.74rem;
    font-weight: 600;
    font-family: var(--hb-font-mono);
    color: var(--hb-text-secondary);
    padding: 4px 8px 0 8px;
}}
"""


CUSTOM_CSS = build_custom_css()


def create_hades_theme() -> gr.Theme:
    """Builds the sober slate/blue workstation theme for Gradio using locally bundled fonts (R6-17)."""
    return gr.themes.Default(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate",
        font=["Inter", "system-ui", "-apple-system", "sans-serif"],
        font_mono=["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
    )
