"""
Multi-Format Exporter & LoRA Dataset Builder for HaDeS Booru.
Supports:
1. Dataset format (.txt): 1 prompt per line
2. Unified format (.txt): Single deduplicated tag block
3. Trainer Captions (.zip): ZIP archive with individual <id>.txt files (and optional images)
4. Direct Local Folder Export: Saves <source>_<id>.<ext> + <source>_<id>.txt directly to a local directory
"""

from __future__ import annotations

import datetime as dt
import re
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlparse

from hades_booru.http_client import http_client
from hades_booru.models import ExportMode, Post, TagCategory
from hades_booru.normalizer import PromptNormalizer

KNOWN_EXTENSIONS: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".avif",
    ".heic",
    ".heif",
    ".jxl",
    ".bmp",
    ".svg",
    ".mp4",
    ".webm",
)

CONTENT_TYPE_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/jxl": ".jxl",
    "image/bmp": ".bmp",
    "image/x-ms-bmp": ".bmp",
    "image/svg+xml": ".svg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


def _sanitize_filename_segment(text: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip().lower()).strip("_")
    return clean[:36] or "all"


def _magic_ext(data: bytes) -> str | None:
    """Sniffs the concrete format from binary magic bytes (None when unknown or too short)."""
    if len(data) < 12:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    if data.startswith((b"\xff\x0a", b"\x00\x00\x00\x0cJXL ")):
        return ".jxl"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return ".avif"
        if brand in (b"heic", b"heix", b"hevc", b"mif1"):
            return ".heic"
        if brand in (b"isom", b"mp41", b"mp42", b"M4V "):
            return ".mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    return None


def looks_like_image(data: bytes) -> bool:
    """Audit R6-06: magic-byte sniff for the image formats the gallery can render.

    A `200 text/html` error page served from a `.jpg` URL must not be cached as an
    image — this check is the gate before anything is written to the gallery cache.
    """
    return _magic_ext(data) in (".png", ".jpg", ".gif", ".webp")


def guess_media_extension(url: str, content_type: str = "", data: bytes = b"") -> str:
    """Determines the accurate file extension from binary magic bytes, URL path, or HTTP Content-Type.

    Audit R6-23: magic bytes are ground truth and are preferred over the URL — a CDN
    serving WebP from a `.jpg` URL now yields `.webp` instead of a mislabeled file.
    Falls back to '.bin' if the format cannot be identified rather than mislabeling as '.jpg'.
    """
    magic = _magic_ext(data)
    if magic is not None:
        return magic

    path = urlparse(url).path.lower()
    for ext in KNOWN_EXTENSIONS:
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext

    ct_base = content_type.split(";")[0].strip().lower()
    if ct_base in CONTENT_TYPE_TO_EXT:
        return CONTENT_TYPE_TO_EXT[ct_base]

    return ".bin"


# Alias preserved for backwards compatibility
_guess_image_extension = guess_media_extension


class BulkExporter:
    """Handles text formatting, ZIP packaging, and direct local dataset generation."""

    # Populated by create_export_file() with per-post packaging failures (ZIP image downloads).
    last_zip_errors: list[str] = []

    def generate_filename(
        self,
        source_name: str,
        query_tags: str,
        mode: ExportMode,
        custom_prefix: str = "",
    ) -> str:
        safe_source = _sanitize_filename_segment(source_name)
        safe_tags = _sanitize_filename_segment(query_tags)
        safe_prefix = _sanitize_filename_segment(custom_prefix) if custom_prefix.strip() else ""
        # Audit R6-22: include the time so two exports of the same query on the same
        # day no longer collide (the caller also suffixes _2/_3 if the file exists).
        date_stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
        ext = "zip" if mode == "trainer-zip" else "txt"
        prefix_part = f"{safe_prefix}_" if safe_prefix else ""
        return f"{prefix_part}{safe_source}_{safe_tags}_{mode}_{date_stamp}.{ext}"

    def generate_export_content(
        self,
        posts: Sequence[Post],
        mode: ExportMode,
        normalizer: PromptNormalizer,
        include_header: bool = False,
        source_name: str = "Booru",
        trigger_word: str = "",
        exclude_categories: Sequence[TagCategory] | None = None,
    ) -> str:
        """Generates the text content for 'dataset' or 'unified' modes (or preview for ZIP/folder)."""
        if not posts:
            return ""

        header = ""
        if include_header and mode in ("dataset", "unified"):
            now_iso = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
            header = (
                f"# HaDeS Booru Prompt Dataset\n"
                f"# Source: {source_name} | Mode: {mode} | Posts: {len(posts)} | Date: {now_iso}\n"
                f"# ------------------------------------------------------------------------\n"
            )

        if mode == "unified":
            body = normalizer.format_unified_prompt(
                posts,
                exclude_categories=exclude_categories,
                trigger_word=trigger_word,
            )
            return f"{header}{body}"

        lines: list[str] = []
        for post in posts:
            prompt = normalizer.format_post_prompt(
                post,
                exclude_categories=exclude_categories,
                trigger_word=trigger_word,
            ).strip()
            if prompt:
                lines.append(prompt)

        return f"{header}" + "\n".join(lines)

    def create_export_file(
        self,
        posts: Sequence[Post],
        mode: ExportMode,
        normalizer: PromptNormalizer,
        output_dir: Path,
        source_name: str = "Booru",
        query_tags: str = "tags",
        custom_prefix: str = "",
        include_header: bool = False,
        trigger_word: str = "",
        exclude_categories: Sequence[TagCategory] | None = None,
        include_images_in_zip: bool = False,
        progress_cb: Callable[[float, str], None] | None = None,
    ) -> Path:
        """Writes a downloadable .txt or .zip file to output_dir and returns its Path."""
        # Audit R6-11: reset stale per-instance state first so two overlapping exports
        # never mix each other's error reports in the UI.
        self.last_zip_errors = []
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = self.generate_filename(source_name, query_tags, mode, custom_prefix)
        target_path = output_dir / filename
        if target_path.exists():
            # Audit R6-22: never silently overwrite a previous export.
            stem, suffix = Path(filename).stem, Path(filename).suffix
            counter = 2
            while (output_dir / f"{stem}_{counter}{suffix}").exists():
                counter += 1
            target_path = output_dir / f"{stem}_{counter}{suffix}"

        if mode == "trainer-zip":
            zip_errors: list[str] = []
            with zipfile.ZipFile(target_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                total = max(1, len(posts))
                for idx, post in enumerate(posts):
                    if progress_cb:
                        progress_cb(
                            idx / total,
                            f"Packaging post #{post.id} ({idx + 1}/{total})...",
                        )
                    base_name = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{post.source_id}_{post.id}")
                    prompt = normalizer.format_post_prompt(
                        post,
                        exclude_categories=exclude_categories,
                        trigger_word=trigger_word,
                    ).strip()
                    zf.writestr(f"{base_name}.txt", prompt.encode("utf-8"))

                    if include_images_in_zip and post.best_download_url:
                        try:
                            img_bytes, ct = http_client.download_bytes(post.best_download_url)
                            ext = guess_media_extension(post.best_download_url, ct, img_bytes)
                            zf.writestr(f"{base_name}{ext}", img_bytes)
                        except Exception as err:
                            zip_errors.append(f"{base_name}: {err}")

                # Never swallow packaging failures silently: ship an errors.txt manifest.
                if zip_errors:
                    zf.writestr("errors.txt", "\n".join(zip_errors).encode("utf-8"))

            self.last_zip_errors = zip_errors
            if progress_cb:
                progress_cb(1.0, f"Created ZIP archive: {target_path.name}")
            return target_path

        self.last_zip_errors = []

        content = self.generate_export_content(
            posts=posts,
            mode=mode,
            normalizer=normalizer,
            include_header=include_header,
            source_name=source_name,
            trigger_word=trigger_word,
            exclude_categories=exclude_categories,
        )
        target_path.write_text(content, encoding="utf-8")
        return target_path

    def export_dataset_to_local_folder(
        self,
        posts: Sequence[Post],
        target_folder: str | Path,
        normalizer: PromptNormalizer,
        trigger_word: str = "",
        exclude_categories: Sequence[TagCategory] | None = None,
        download_images: bool = True,
        high_res: bool = True,
        progress_cb: Callable[[float, str], None] | None = None,
    ) -> dict[str, int | str]:
        """Saves individual <source>_<id>.txt captions and (optionally) downloads their paired
        images directly into target_folder on disk — ready for Kohya_ss / OneTrainer.
        """
        folder = Path(target_folder).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)

        saved_txt = 0
        saved_img = 0
        failed_img = 0
        total = max(1, len(posts))

        for idx, post in enumerate(posts):
            base_name = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{post.source_id}_{post.id}")
            if progress_cb:
                progress_cb(
                    idx / total,
                    f"Saving {base_name} ({idx + 1}/{total})...",
                )

            prompt = normalizer.format_post_prompt(
                post,
                exclude_categories=exclude_categories,
                trigger_word=trigger_word,
            ).strip()
            txt_path = folder / f"{base_name}.txt"
            txt_path.write_text(prompt, encoding="utf-8")
            saved_txt += 1

            if download_images:
                img_url = post.best_download_url if high_res else post.best_display_url
                if img_url:
                    try:
                        img_bytes, ct = http_client.download_bytes(img_url)
                        ext = guess_media_extension(img_url, ct, img_bytes)
                        img_path = folder / f"{base_name}{ext}"
                        img_path.write_bytes(img_bytes)
                        saved_img += 1
                    except Exception:
                        failed_img += 1

        if progress_cb:
            progress_cb(1.0, f"Dataset saved to {folder}")

        return {
            "folder": str(folder),
            "saved_txt": saved_txt,
            "saved_img": saved_img,
            "failed_img": failed_img,
        }


bulk_exporter = BulkExporter()
