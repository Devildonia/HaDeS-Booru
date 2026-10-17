"""
HaDeS Booru — Main Entry Point.
Launches the Gradio Web UI on http://127.0.0.1:7860.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hades_booru.ui.layout import create_gradio_app
from hades_booru.ui.theme import CUSTOM_CSS, create_hades_theme


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HaDeS Booru — Multi-source tag extractor, prompt normalizer, and dataset utility"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7860, help="Port to bind (default: 7860)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the browser tab on launch",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="Create a public Gradio share link",
    )
    args = parser.parse_args()

    logo_path = Path(__file__).resolve().parent / "H.webp"
    favicon = str(logo_path) if logo_path.exists() else None

    app = create_gradio_app()
    app.launch(
        server_name=args.host,
        server_port=args.port,
        inbrowser=not args.no_browser,
        share=args.share,
        theme=create_hades_theme(),
        css=CUSTOM_CSS,
        favicon_path=favicon,
    )


if __name__ == "__main__":
    main()
