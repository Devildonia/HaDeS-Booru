"""
Design System Tokens, Matte Dark Slate Theme, and Symmetric Bento CSS for HaDeS Booru.
Follows HIG (Clarity, Deference, Depth) with strict CSS custom properties and zero visual noise.
"""

from __future__ import annotations

import gradio as gr

CUSTOM_CSS = """
:root {
    --hb-bg-canvas: #090d16;
    --hb-bg-surface: #111827;
    --hb-bg-elevated: #1e293b;
    --hb-bg-subtle: #0f172a;
    --hb-border-subtle: #1f2937;
    --hb-border-strong: #334155;
    --hb-accent-primary: #2563eb;
    --hb-accent-brand: #e11d48;
    --hb-text-primary: #f8fafc;
    --hb-text-secondary: #94a3b8;
    --hb-text-muted: #64748b;
    --hb-radius-panel: 10px;
    --hb-radius-control: 6px;
    --hb-font-sans: 'Inter', system-ui, -apple-system, sans-serif;
    --hb-font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Consolas, monospace;
}

/* Remove Gradio's default emoji footer and tighten outer container padding */
footer {
    display: none !important;
}
.gradio-container {
    max-width: 1640px !important;
    margin: 0 auto !important;
    padding-top: 12px !important;
    padding-bottom: 20px !important;
}

/* 1. Top Header Bar */
.hades-header {
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
}
.hades-title-group {
    display: flex;
    align-items: center;
    gap: 14px;
}
.hades-logo-frame {
    width: 42px;
    height: 42px;
    border-radius: 8px;
    background: var(--hb-bg-subtle);
    border: 1px solid var(--hb-border-strong);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}
.hades-logo-img {
    width: 32px;
    height: 32px;
    object-fit: contain;
}
.hades-brand-title {
    font-size: 1.12rem;
    font-weight: 700;
    color: var(--hb-text-primary);
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    letter-spacing: -0.01em;
}
.hades-pill {
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
}
.hades-pill-accent {
    background: rgba(37, 99, 235, 0.14);
    color: #60a5fa;
    border: 1px solid rgba(59, 130, 246, 0.32);
}
.hades-subtitle {
    font-size: 0.76rem;
    color: var(--hb-text-secondary);
    margin: 2px 0 0 0;
}

/* 2. Command Deck Alignment */
.hades-command-row {
    align-items: stretch !important;
    gap: 10px !important;
}
.hades-search-btn {
    min-height: 74px !important;
    height: 100% !important;
    font-weight: 600 !important;
    font-size: 0.92rem !important;
    letter-spacing: 0.01em !important;
    border-radius: var(--hb-radius-control) !important;
}
.hades-status-box {
    background: var(--hb-bg-surface);
    border: 1px solid var(--hb-border-subtle);
    border-radius: var(--hb-radius-control);
    padding: 10px 14px;
    min-height: 74px;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.hades-status-label {
    font-size: 0.66rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--hb-text-muted);
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 6px;
}
.hades-status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
}
.hades-status-text {
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--hb-text-primary);
    line-height: 1.3;
    white-space: normal;
    overflow-wrap: break-word;
}

/* 3. Tab 1: Symmetric Split-Pane Gallery & Inspector (660px coordinated height) */
.hades-nav-bar {
    align-items: center !important;
    gap: 8px !important;
}
.hades-nav-badge {
    background: var(--hb-bg-surface);
    border: 1px solid var(--hb-border-subtle);
    border-radius: var(--hb-radius-control);
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--hb-font-mono);
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--hb-text-secondary);
    letter-spacing: 0.04em;
    padding: 0 10px;
}
.hades-copy-btn {
    font-weight: 600 !important;
    font-size: 0.8rem !important;
}
.hades-inspector-scroll {
    background: var(--hb-bg-surface);
    border: 1px solid var(--hb-border-subtle);
    border-radius: var(--hb-radius-panel);
    padding: 14px;
    height: 412px;
    overflow-y: auto;
    box-sizing: border-box;
}
.hades-empty-state {
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 24px;
    color: var(--hb-text-muted);
    box-sizing: border-box;
}
.hades-empty-title {
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--hb-text-secondary);
    margin: 0 0 6px 0;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.hades-empty-desc {
    font-size: 0.78rem;
    color: var(--hb-text-muted);
    max-width: 340px;
    line-height: 1.45;
    margin: 0;
}

/* 4. Taxonomic Tag Cloud & Metadata Grid */
.meta-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
    margin-bottom: 12px;
}
.meta-box {
    background: var(--hb-bg-elevated);
    border: 1px solid var(--hb-border-strong);
    border-radius: var(--hb-radius-control);
    padding: 7px 11px;
    font-size: 0.76rem;
    color: var(--hb-text-primary);
}
.meta-box strong {
    display: block;
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--hb-text-secondary);
    margin-bottom: 2px;
}
.tag-section-title {
    font-size: 0.69rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--hb-text-secondary);
    margin: 12px 0 6px 0;
    padding-bottom: 3px;
    border-bottom: 1px solid var(--hb-border-subtle);
}
.tag-cloud {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-bottom: 8px;
}
.tag-chip {
    display: inline-block;
    font-size: 0.73rem;
    font-family: var(--hb-font-mono);
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 500;
    transition: border-color 150ms ease;
}
.tag-copyright {
    background: rgba(168, 85, 247, 0.14);
    color: #d8b4fe;
    border: 1px solid rgba(168, 85, 247, 0.3);
}
.tag-character {
    background: rgba(16, 185, 129, 0.14);
    color: #6ee7b7;
    border: 1px solid rgba(16, 185, 129, 0.3);
}
.tag-artist {
    background: rgba(244, 63, 94, 0.14);
    color: #fda4af;
    border: 1px solid rgba(244, 63, 94, 0.3);
}
.tag-general {
    background: rgba(59, 130, 246, 0.12);
    color: #93c5fd;
    border: 1px solid rgba(59, 130, 246, 0.28);
}
.tag-meta {
    background: rgba(100, 116, 139, 0.16);
    color: #cbd5e1;
    border: 1px solid rgba(100, 116, 139, 0.3);
}

/* 5. Symmetric Bento Section Headers */
.hades-section-header {
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--hb-text-primary);
    padding-bottom: 8px;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--hb-border-subtle);
}
.hades-cred-title {
    font-size: 0.74rem;
    font-weight: 600;
    font-family: var(--hb-font-mono);
    color: var(--hb-text-secondary);
    padding: 4px 8px 0 8px;
}
"""


def create_hades_theme() -> gr.Theme:
    """Builds the sober slate/blue workstation theme for Gradio."""
    return gr.themes.Default(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate",
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "Consolas", "monospace"],
    )
