"""
Disk-Backed Image Cache for HaDeS Booru Gallery (C2 Remediation).
Streams downloaded gallery images directly to a bounded local disk directory (.cache/gallery)
and returns file paths to Gradio instead of holding hundreds of uncompressed PIL.Image bitmaps in RAM.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import re
import threading
from pathlib import Path

from hades_booru.demo_data import generate_placeholder_image
from hades_booru.exporter import guess_media_extension
from hades_booru.http_client import http_client
from hades_booru.models import ImageQuality, Post

DEFAULT_CACHE_DIR = Path(".cache/gallery")
BROWSER_SAFE_EXTS: frozenset[str] = frozenset({".jpg", ".png", ".webp", ".gif", ".avif"})

logger = logging.getLogger(__name__)


class DiskImageCache:
    """Bounded local disk cache for gallery image files."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR, max_files: int = 600) -> None:
        self._dir = cache_dir
        self._max_files = max_files
        self._lock = threading.Lock()
        self._dir.mkdir(parents=True, exist_ok=True)

    def _safe_key(self, post: Post, quality: ImageQuality, url: str) -> str:
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{post.source_id}_{post.id}")[:48]
        return f"{clean_id}_{quality}_{url_hash}"

    def _find_existing(self, key_prefix: str) -> Path | None:
        with self._lock:
            for ext in BROWSER_SAFE_EXTS:
                candidate = self._dir / f"{key_prefix}{ext}"
                if candidate.exists() and candidate.stat().st_size > 0:
                    return candidate
        return None

    def _write_placeholder(self, post: Post, key_prefix: str, color_hex: str = "#3b82f6") -> Path:
        target = self._dir / f"{key_prefix}_card.png"
        with self._lock:
            if target.exists() and target.stat().st_size > 0:
                return target
            title = post.title or f"{post.source_name} #{post.id}"
            sub = ", ".join(post.raw_tags[:6])
            img = generate_placeholder_image(title, sub, color_hex=color_hex)
            img.save(target, format="PNG")
            return target

    def resolve_post_image(self, post: Post, quality: ImageQuality) -> tuple[str, str]:
        """Returns (file_path_str, caption) for a single post at the requested quality tier."""
        caption = f"#{post.id} [{post.rating.upper()}] - {post.source_name}"
        url = post.url_for_quality(quality)

        if quality == "text" or not url:
            key = self._safe_key(post, "text", post.source_url)
            card_path = self._write_placeholder(post, key, color_hex="#3b82f6")
            return str(card_path.resolve()), caption

        key = self._safe_key(post, quality, url)
        existing = self._find_existing(key)
        if existing is not None:
            return str(existing.resolve()), caption

        urls_to_try = [url]
        if post.preview_url and post.preview_url != url:
            urls_to_try.append(post.preview_url)

        for candidate_url in urls_to_try:
            try:
                raw_bytes, ct = http_client.download_bytes(candidate_url)
                ext = guess_media_extension(candidate_url, ct, raw_bytes)
                if ext not in BROWSER_SAFE_EXTS:
                    # Non-browser-safe media (HEIC/JXL/MP4/WebM/.bin): try next fallback URL or return placeholder card
                    continue
                target = self._dir / f"{key}{ext}"
                with self._lock:
                    target.write_bytes(raw_bytes)
                return str(target.resolve()), caption
            except Exception as err:
                # Never crash the gallery over one bad image: log for diagnostics and
                # fall through to the next fallback URL / placeholder card.
                logger.debug(
                    "Failed to download gallery image for post %s (%s) from %s",
                    post.id,
                    post.source_name,
                    candidate_url,
                    exc_info=err,
                )
                continue

        err_card = self._write_placeholder(post, f"{key}_err", color_hex="#ef4444")
        return str(err_card.resolve()), caption

    def prune_if_needed(self) -> None:
        """Prunes oldest cached files if directory exceeds max_files."""
        with self._lock:
            try:
                files = [p for p in self._dir.iterdir() if p.is_file()]
                if len(files) <= self._max_files:
                    return
                files.sort(key=lambda p: p.stat().st_mtime)
                to_remove = files[: len(files) - self._max_files]
                for old_file in to_remove:
                    try:
                        old_file.unlink()
                    except OSError:
                        pass
            except OSError:
                pass

    def build_gallery_items(self, posts: list[Post], quality: ImageQuality) -> list[tuple[str, str]]:
        """Concurrently resolves disk-cached image paths for all posts in the batch."""
        if not posts:
            return []
        self.prune_if_needed()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self.resolve_post_image, p, quality) for p in posts]
            return [f.result() for f in futures]


image_cache = DiskImageCache()
