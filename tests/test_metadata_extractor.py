"""
Unit Tests for the v1.0.3 local Image to Prompt metadata extractor.
Synthetic images are generated in-memory with Pillow (no network, no fixtures).
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from hades_booru.metadata_extractor import (
    MetadataExtractionError,
    extract_image_metadata,
    format_settings_lines,
    split_sd_parameters,
)


def _png_bytes(pnginfo: PngInfo | None) -> bytes:
    img = Image.new("RGB", (32, 32), color=(120, 130, 140))
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=pnginfo)
    return buf.getvalue()


def _write(path, data: bytes) -> None:
    path.write_bytes(data)


def test_extracts_danbooru_style_png_comment(tmp_path) -> None:
    pnginfo = PngInfo()
    pnginfo.add_text("comment", "hatsune miku, 1girl, solo, watermark, commission")
    pnginfo.add_text("rating", "s")
    pnginfo.add_text("source", "https://danbooru.donmai.us/posts/123")

    target = tmp_path / "danbooru.png"
    _write(target, _png_bytes(pnginfo))

    meta = extract_image_metadata(str(target))
    assert meta.found is True
    assert meta.format == "PNG"
    assert meta.width == 32 and meta.height == 32
    assert "hatsune miku" in meta.tags
    assert "1girl" in meta.tags
    assert "watermark" in meta.tags
    assert meta.rating == "s"
    assert meta.source_url == "https://danbooru.donmai.us/posts/123"
    assert "PNG tEXt 'comment'" in meta.sources


def test_extracts_sd_prompt_parameters_png(tmp_path) -> None:
    """The SD parameters blob is split into positive / negative / settings."""
    pnginfo = PngInfo()
    pnginfo.add_text(
        "parameters",
        "masterpiece, best quality, 1girl, blue dress, "
        "Negative Prompt: blurry, watermark, "
        "Steps: 30, Sampler: DPM++ 2M, Seed: 12345, Size: 896x1152",
    )

    target = tmp_path / "sd.png"
    _write(target, _png_bytes(pnginfo))

    meta = extract_image_metadata(str(target))
    assert meta.found is True
    assert meta.prompt == "masterpiece, best quality, 1girl, blue dress"
    assert meta.negative == "blurry, watermark"
    assert "Steps: 30" in meta.settings
    assert "DPM++ 2M" in meta.settings
    assert "1girl" in meta.tags
    assert any("parameters" in s for s in meta.sources)


def test_split_sd_parameters_real_world_blob() -> None:
    """Regression fixture: real A1111/Forge 'parameters' blob (Illustrus model)."""
    blob = (
        "1girl, bikini, blonde hair, breasts, chain, chain necklace, covered nipples, "
        "head out of frame, huge breasts, jewelry, mole, mole under mouth, navel, necklace, "
        "puckered lips, sand, selfie, shadow, shiny skin, solo, sweat, swimsuit, thick lips, "
        "white bikini, realistic, photorealistic, hyperrealistic, raw photo, 8k, best quality, "
        "detailed skin, amateur photo, realistic shadows, depth of field, high-resolution textures, {prompt}], "
        "Negative prompt: cartoon, anime, 3d, render, illustration, painting, drawing, sketch, "
        "low quality, worst quality, deformed, distorted, disfigured, bad anatomy, bad hands, "
        "missing limbs, extra limbs, text, blurry, fat, "
        "Steps: 30, Sampler: DPM++ 2M, Schedule type: Beta, CFG scale: 5, Seed: 3817369013, "
        "Size: 896x1152, Model: Illustrus from HaDeS v2 Series, Model hash: a60555409f, "
        "RNG: CPU, Beta schedule alpha: 0.6, Beta schedule beta: 0.6, Version: neo-2.30"
    )
    positive, negative, settings = split_sd_parameters(blob)
    assert positive.startswith("1girl, bikini")
    # The stray ']' from the user's template is preserved verbatim
    assert positive.endswith("high-resolution textures, {prompt}]")
    assert negative == (
        "cartoon, anime, 3d, render, illustration, painting, drawing, sketch, low quality, "
        "worst quality, deformed, distorted, disfigured, bad anatomy, bad hands, missing limbs, "
        "extra limbs, text, blurry, fat"
    )
    assert settings.startswith("Steps: 30")
    assert "Sampler: DPM++ 2M" in settings
    assert "Model: Illustrus from HaDeS v2 Series" in settings
    assert "Version: neo-2.30" in settings
    # No text lost across the three sections
    joined = f"{positive} | {negative} | {settings}"
    for fragment in ("1girl, bikini", "cartoon, anime", "Steps: 30", "Version: neo-2.30"):
        assert fragment in joined
    lines = format_settings_lines(settings)
    assert lines.split("\n")[0] == "Steps: 30"
    assert any(line.startswith("Model hash:") for line in lines.split("\n"))


def test_split_sd_parameters_without_negative_or_settings() -> None:
    positive, negative, settings = split_sd_parameters("1girl, solo, best quality")
    assert positive == "1girl, solo, best quality"
    assert negative == ""
    assert settings == ""


def test_format_settings_lines_fallback() -> None:
    assert format_settings_lines("") == ""
    assert format_settings_lines("Steps: 30") == "Steps: 30"
    assert format_settings_lines("weird: stuff, more") == "weird: stuff, more"  # lowercase key: raw fallback


def test_extracts_comfyui_json_prompt_graph(tmp_path) -> None:
    """ComfyUI stores the prompt graph as JSON in the 'prompt' tEXt chunk.

    The extractor must decode it into readable texts (positive then negative,
    node order) instead of exposing raw JSON.
    """
    import json as _json

    graph = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 42}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "masterpiece, 1girl, blue dress, solo"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, watermark, bad hands"}},
        "8": {"class_type": "VAEDecode", "inputs": {}},
    }
    pnginfo = PngInfo()
    pnginfo.add_text("prompt", _json.dumps(graph))

    target = tmp_path / "comfyui.png"
    _write(target, _png_bytes(pnginfo))

    meta = extract_image_metadata(str(target))
    assert meta.found is True
    assert meta.prompt == "masterpiece, 1girl, blue dress, solo"
    assert meta.negative == "blurry, watermark, bad hands"
    assert meta.settings is None
    # Raw JSON must not leak anywhere
    assert "class_type" not in (meta.prompt or "")
    assert "1girl" in meta.tags
    assert any("ComfyUI" in s for s in meta.sources)


def test_non_json_prompt_chunk_stays_verbatim(tmp_path) -> None:
    """A 'prompt' tEXt chunk that is plain text (NovelAI style) must pass through untouched."""
    pnginfo = PngInfo()
    pnginfo.add_text("prompt", "1girl, silver hair, school uniform")

    target = tmp_path / "novelai.png"
    _write(target, _png_bytes(pnginfo))

    meta = extract_image_metadata(str(target))
    assert meta.found is True
    assert meta.prompt == "1girl, silver hair, school uniform"
    assert meta.negative is None
    assert meta.settings is None
    assert "silver hair" in meta.tags


def test_extracts_jpeg_exif_user_comment(tmp_path) -> None:
    img = Image.new("RGB", (32, 32), color=(200, 60, 60))
    exif = img.getexif()
    # 0x9286 = EXIF UserComment
    exif[0x9286] = "1boy, 2girls, simple background, watermark"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())

    target = tmp_path / "exif.jpg"
    _write(target, buf.getvalue())

    meta = extract_image_metadata(str(target))
    assert meta.found is True
    assert "1boy" in meta.tags
    assert "EXIF UserComment" in meta.sources


def test_clean_image_reports_not_found(tmp_path) -> None:
    target = tmp_path / "clean.png"
    _write(target, _png_bytes(None))

    meta = extract_image_metadata(str(target))
    assert meta.found is False
    assert meta.tags == []
    assert meta.prompt is None


def test_unsupported_extension_raises(tmp_path) -> None:
    target = tmp_path / "doc.txt"
    target.write_text("hello", encoding="utf-8")
    with pytest.raises(MetadataExtractionError):
        extract_image_metadata(str(target))


def test_invalid_image_raises(tmp_path) -> None:
    target = tmp_path / "fake.png"
    target.write_text("not a real png", encoding="utf-8")
    with pytest.raises(MetadataExtractionError):
        extract_image_metadata(str(target))


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(MetadataExtractionError):
        extract_image_metadata(str(tmp_path / "missing.png"))
