"""
Desktop OS Integration and Gallery Cache Helpers for HaDeS Booru UI (R6-25).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from hades_booru.config import config_manager
from hades_booru.i18n import t
from hades_booru.image_cache import image_cache
from hades_booru.models import ImageQuality, Post

logger = logging.getLogger(__name__)


def build_gallery_items(posts: list[Post], quality: ImageQuality) -> list[tuple[str, str]]:
    """Resolves disk-cached gallery image paths for all posts in the batch (C2)."""
    return image_cache.build_gallery_items(posts, quality)


def open_native_folder_dialog(current_dir: str, lang: str = "en") -> str:
    """Opens the native OS folder selection dialog via an isolated Python subprocess."""
    dialog_title = t(lang, "folder_dialog_title")
    script = (
        "import tkinter as tk; from tkinter import filedialog; "
        "root = tk.Tk(); root.attributes('-topmost', True); root.withdraw(); "
        f"path = filedialog.askdirectory(initialdir={repr(current_dir)}, title={repr(dialog_title)}); "
        "print(path or '')"
    )
    try:
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        chosen = res.stdout.strip()
        if chosen:
            config_manager.config.export.local_export_dir = chosen
            config_manager.save()
            return chosen
    except Exception as err:  # Audit R6-15: log instead of failing silently
        logger.warning("Native folder dialog failed: %s", err)
    return current_dir


def open_folder_in_explorer(folder_path: str, lang: str = "en") -> str:
    """Opens the target folder in the OS file manager."""
    target = Path(folder_path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return t(lang, "explorer_opened", path=str(target))
    except Exception as err:
        return t(lang, "explorer_error", error=str(err), path=str(target))


def _cred_placeholder(has_value: bool, lang: str, is_secret: bool = False) -> str | None:
    """Returns a generic masked placeholder when a credential is saved, never exposing the value itself."""
    if not has_value:
        return None
    return t(lang, "cred_key_saved_placeholder" if is_secret else "cred_user_saved_placeholder")
