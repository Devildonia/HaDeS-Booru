"""
HaDeS Booru — Main Entry Point.
Launches the Gradio Web UI on http://127.0.0.1:7863 by default.

Port behaviour (v1.0.6):
- The default port is 7863, chosen to avoid clashing with Stable Diffusion
  WebUI / Forge (7860 / 7861) and ComfyUI (8188).
- If the requested port is already in use, the app automatically probes the
  next sequential ports (up to 50 tries) and binds the first free one, so the
  UI always comes up. The actually-chosen URL is printed to the console.
"""

from __future__ import annotations

import argparse
import socket
from pathlib import Path

from hades_booru.ui.layout import create_gradio_app
from hades_booru.ui.theme import CUSTOM_CSS, create_hades_theme

DEFAULT_PORT = 7863
MAX_PORT_TRIES = 50


def find_free_port(host: str, start: int, max_tries: int = MAX_PORT_TRIES) -> int:
    """Return the first free TCP port starting at `start`.

    Binds a throwaway socket to each candidate to detect a real conflict, then
    releases it. Raises if no free port is found within `max_tries`.
    """
    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No free port found in the range {start}..{start + max_tries - 1} for host {host!r}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HaDeS Booru — Multi-source tag extractor, prompt normalizer, and dataset utility"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind (default: {DEFAULT_PORT}). If busy, the next free port is used.",
    )
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

    # v1.0.6: resolve a port that is actually free so the app always launches.
    try:
        chosen_port = find_free_port(args.host, args.port)
    except RuntimeError as err:
        print(f"[HaDeS] ERROR: {err}")
        raise SystemExit(1) from err
    if chosen_port != args.port:
        print(f"[HaDeS] Port {args.port} is busy — automatically using {chosen_port} instead.")

    app = create_gradio_app()
    try:
        app.launch(
            server_name=args.host,
            server_port=chosen_port,
            inbrowser=not args.no_browser,
            share=args.share,
            theme=create_hades_theme(),
            css=CUSTOM_CSS,
            favicon_path=favicon,
        )
    except OSError as err:
        # The port was free during the probe but got taken in the meantime (TOCTOU race)
        # or the host binding failed (e.g. another listener on that interface).
        # Turn the low-level error into a clear, actionable message.
        print(f"[HaDeS] ERROR: could not bind http://{args.host}:{chosen_port} - {err}")
        print("[HaDeS] Another program likely grabbed the port in the last moment.")
        print("[HaDeS] Simply run the launcher again, or force a specific port with --port <N>.")
        raise SystemExit(1) from err
    print(f"\n[HaDeS] Interface ready at http://{args.host}:{chosen_port}")


if __name__ == "__main__":
    main()
