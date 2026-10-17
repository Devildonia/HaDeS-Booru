"""
Unit Tests for BulkExporter: Dataset TXT, Unified TXT, Trainer ZIP, and Local Folder Export.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from hades_booru.demo_data import DEMO_POSTS
from hades_booru.exporter import bulk_exporter
from hades_booru.normalizer import PromptNormalizer


def test_dataset_and_unified_export() -> None:
    norm = PromptNormalizer()
    posts = DEMO_POSTS[:2]

    dataset_txt = bulk_exporter.generate_export_content(posts, "dataset", norm)
    lines = dataset_txt.strip().splitlines()
    assert len(lines) == 2
    assert "hatsune miku" in lines[0]
    assert "frieren" in lines[1]

    unified_txt = bulk_exporter.generate_export_content(posts, "unified", norm)
    assert "\n" not in unified_txt.strip()
    assert "hatsune miku" in unified_txt
    assert "frieren" in unified_txt
    # twintails appears in both posts but must be deduplicated in unified mode
    assert unified_txt.split(", ").count("twintails") == 1


def test_trainer_zip_and_local_folder_export(tmp_path: Path) -> None:
    norm = PromptNormalizer()
    posts = DEMO_POSTS[:2]

    zip_path = bulk_exporter.create_export_file(
        posts=posts,
        mode="trainer-zip",
        normalizer=norm,
        output_dir=tmp_path,
        source_name="Danbooru",
        query_tags="1girl solo",
        custom_prefix="lora_v1",
        trigger_word="trigger_tok",
        include_images_in_zip=False,
    )
    assert zip_path.exists()
    assert zip_path.suffix == ".zip"
    assert zip_path.name.startswith("lora_v1_danbooru_")

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert "danbooru_8492011.txt" in names
        caption = zf.read("danbooru_8492011.txt").decode("utf-8")
        assert caption.startswith("trigger_tok, ")

    # Local folder export
    dataset_dir = tmp_path / "kohya_dataset"
    summary = bulk_exporter.export_dataset_to_local_folder(
        posts=posts,
        target_folder=dataset_dir,
        normalizer=norm,
        trigger_word="kohya_trigger",
        download_images=False,
    )
    assert summary["saved_txt"] == 2
    assert (dataset_dir / "danbooru_8492011.txt").exists()
    assert (dataset_dir / "danbooru_8492055.txt").exists()


def test_guess_media_extension() -> None:
    from hades_booru.exporter import guess_media_extension

    assert guess_media_extension("https://cdn.example.com/img.avif", "image/avif") == ".avif"
    assert guess_media_extension("https://cdn.example.com/img.heic", "image/heic") == ".heic"
    assert guess_media_extension("https://cdn.example.com/file", "image/avif") == ".avif"
    assert guess_media_extension("https://cdn.example.com/file", "image/webp") == ".webp"

    # Magic bytes detection when URL and Content-Type are generic
    avif_magic = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00"
    assert guess_media_extension("https://cdn.example.com/blob", "application/octet-stream", avif_magic) == ".avif"

    png_magic = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    assert guess_media_extension("https://cdn.example.com/blob", "", png_magic) == ".png"

    # Unknown format falls back to .bin instead of lying as .jpg
    assert guess_media_extension("https://cdn.example.com/unknown", "application/octet-stream", b"123456") == ".bin"
