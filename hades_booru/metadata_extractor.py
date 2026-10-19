"""
Local Image Metadata Extractor (v1.0.3 "Image to Prompt").

Reads embedded prompt/tags from an image file WITHOUT uploading anything:
- PNG tEXt chunks:  'comment' (Danbooru/Bilibili/Gelbooru), 'description',
                    'parameters' / 'prompt' (Civitai / Stable Diffusion),
                    'rating', 'source'
- PNG XMP blob:     <dc:subject>/<dc:term> and prompt-like elements
- JPEG/WebP EXIF:   UserComment (0x9286)

Everything runs in-process with Pillow; no network access is performed.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from hades_booru.models import ExtractedImageMeta
from hades_booru.normalizer import parse_tag_list

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})
SUPPORTED_FORMATS: frozenset[str] = frozenset({"PNG", "JPEG", "WEBP"})

DC_SUBJECT_RE = re.compile(r"<dc:term[^>]*>([^<]+)</dc:term>", re.IGNORECASE)
PROMPT_XMP_RE = re.compile(r"<[^>]*(?:prompt|parameters)[^>]*>([^<]+)<", re.IGNORECASE)
EXIF_USER_COMMENT_TAG = 0x9286
EXIF_COMMENT_PREFIX_RE = re.compile(rb"^(?:ASCII|UNICODE|JIS|Unicode|ASCII )\x00", re.IGNORECASE)

# A1111-style 'parameters' blob: split into positive / negative / settings.
NEGATIVE_MARKER_RE = re.compile(r"\bNegative\s+prompt\s*:", re.IGNORECASE)
SETTING_CANDIDATE_RE = re.compile(r",\s*([A-Z][A-Za-z0-9][A-Za-z0-9 _/\-]*?)\s*:\s*\S")
# Common generation-setting keys across A1111, Forge, SD.Next and friends.
KNOWN_SETTING_KEYS: frozenset[str] = frozenset({
    "steps",
    "sampler",
    "sampler_name",
    "sampling_method",
    "schedule_type",
    "cfg_scale",
    "seed",
    "size",
    "model",
    "model_hash",
    "checkpoint",
    "checkpoint_title",
    "rng",
    "version",
    "face_restoration",
    "clip_skip",
    "denoise",
    "batch_size",
    "batch_count",
    "eta",
    "tiling",
    "upscaler",
    "hires_steps",
    "hires_upscaler",
    "hires_resize_x",
    "hires_resize_y",
    "beta_schedule_alpha",
    "beta_schedule_beta",
    "style",
    "vae",
    "lora_strength",
    "controlnet",
    "ipadapter",
})


class MetadataExtractionError(Exception):
    """Raised when the file is not a readable supported image."""


def _clean_text(value: object) -> str:
    """Decodes and HTML-unescapes a metadata text payload."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            value = value.decode("latin-1", errors="replace")
    text = str(value)
    text = html.unescape(text)
    return text.strip()


def _extract_comfyui_prompt(blob: str) -> str | None:
    """Decodes a ComfyUI prompt graph (JSON) into its readable prompt texts.

    ComfyUI stores the API prompt graph in the 'prompt' tEXt chunk: a dict of
    nodes whose 'inputs' may contain a 'text' field (CLIPTextEncode nodes).
    Returns the texts joined in node order, or None if the blob is not a graph.
    """
    stripped = blob.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        graph = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(graph, dict):
        return None

    def _node_key(item: tuple[str, object]) -> tuple[int, str]:
        key = item[0]
        try:
            return (0, str(int(key)))
        except (TypeError, ValueError):
            return (1, str(key))

    texts: list[str] = []
    for _node_id, node in sorted(graph.items(), key=_node_key):
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict):
            text = inputs.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return "\n".join(texts) if texts else None


def _find_settings_start(text: str) -> int | None:
    """Locates the first generation-setting key (', Key: value') inside a blob."""
    candidates = list(SETTING_CANDIDATE_RE.finditer(text))
    if not candidates:
        return None
    known = [m for m in candidates if m.group(1).strip().lower() in KNOWN_SETTING_KEYS]
    pick = known[0] if known else candidates[0]
    return pick.start()


def split_sd_parameters(blob: str) -> tuple[str, str, str]:
    """Splits an A1111/Forge/SD.Next 'parameters' blob into (positive, negative, settings).

    The split is heuristic: the 'Negative prompt:' marker separates positive from
    the rest, and the first recognized setting key (or first 'Capitalized: value'
    pair) separates negative from settings. Anything that cannot be separated is
    kept in the closest preceding section, so no text is ever lost.
    """
    positive = blob
    negative = ""
    settings = ""
    marker = NEGATIVE_MARKER_RE.search(blob)
    if marker:
        positive = blob[: marker.start()]
        rest = blob[marker.end():]
        start = _find_settings_start(rest)
        if start is not None:
            negative = rest[:start]
            settings = rest[start:]
        else:
            negative = rest
    positive = positive.strip().strip(",").strip()
    negative = negative.strip().strip(",").strip()
    settings = settings.strip().strip(",").strip()
    return positive, negative, settings


def format_settings_lines(settings: str) -> str:
    """Renders a settings blob as one 'Key: value' per line (falls back to raw text)."""
    text = (settings or "").strip().strip(",").strip()
    if not text:
        return ""
    boundaries = [0] + [m.start() for m in SETTING_CANDIDATE_RE.finditer(text)]
    lines: list[str] = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        segment = text[start:end].strip().lstrip(",").strip()
        if segment:
            lines.append(segment)
    return "\n".join(lines) if lines else text


def _extract_exif_user_comment(img: Image.Image) -> str:
    """Best-effort EXIF UserComment extraction (JPEG/WebP)."""
    try:
        exif = img.getexif()
        if not exif:
            return ""
        raw = exif.get(EXIF_USER_COMMENT_TAG)
        if raw is None:
            return ""
        if isinstance(raw, bytes):
            raw = EXIF_COMMENT_PREFIX_RE.sub(b"", raw, count=1)
            return raw.decode("utf-8", errors="replace").strip()
        return _clean_text(raw)
    except Exception:
        return ""


def _merge_tags(target: list[str], candidates: str) -> bool:
    """Appends parsed tag candidates to target (deduplicated). Returns True if anything was added."""
    seen = {x.strip().lower() for x in target}
    added = False
    for tag in parse_tag_list(candidates):
        key = tag.strip().lower()
        if key and key not in seen:
            seen.add(key)
            target.append(tag)
            added = True
    return added


def extract_image_metadata(file_path: str) -> ExtractedImageMeta:
    """Extracts embedded prompt/tags metadata from a local image file.

    Raises:
        MetadataExtractionError: if the file is missing, unsupported, or not a valid image.
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise MetadataExtractionError(f"File not found: {path.name}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise MetadataExtractionError(
            f"Unsupported file type '{suffix}'. Supported: PNG, JPEG, WebP."
        )

    try:
        with Image.open(path) as img:
            if img.format is None or img.format.upper() not in SUPPORTED_FORMATS:
                raise MetadataExtractionError(f"Unsupported image format: {img.format}")
            width, height = img.size
            fmt = img.format.upper()
            info = dict(img.info)
            exif_comment = _extract_exif_user_comment(img)
            xmp_blob = info.get("XMP")
    except UnidentifiedImageError as err:
        raise MetadataExtractionError(f"Not a valid image: {err}") from err

    meta = ExtractedImageMeta(format=fmt, width=width, height=height)
    found_anything = False

    # --- 1. PNG tEXt chunks -------------------------------------------------
    comment = _clean_text(info.get("comment"))
    if comment:
        if _merge_tags(meta.tags, comment):
            meta.sources.append("PNG tEXt 'comment'")
            found_anything = True

    description = _clean_text(info.get("description"))
    if description and not comment:
        if _merge_tags(meta.tags, description):
            meta.sources.append("PNG tEXt 'description'")
            found_anything = True

    # The full parameters blob is kept verbatim (positive prompt, negative prompt
    # and generation settings included): users may want any of those sections.
    parameters = _clean_text(info.get("parameters")) or _clean_text(info.get("prompt"))
    if parameters:
        comfy_prompt = _extract_comfyui_prompt(parameters)
        if comfy_prompt:
            # ComfyUI graph: first text node = positive, remaining = negative.
            texts = [line.strip() for line in comfy_prompt.split("\n") if line.strip()]
            meta.prompt = texts[0]
            if len(texts) > 1:
                meta.negative = ", ".join(texts[1:])
            added = _merge_tags(meta.tags, meta.prompt)
            added = _merge_tags(meta.tags, meta.negative or "") or added
            if added:
                meta.sources.append("PNG tEXt 'prompt' (ComfyUI graph)")
                found_anything = True
        else:
            # A1111/Forge/SD.Next style: split into positive / negative / settings
            # so the UI can show each section separately. No text is lost.
            positive, negative, settings = split_sd_parameters(parameters)
            meta.prompt = positive
            meta.negative = negative or None
            meta.settings = settings or None
            added = _merge_tags(meta.tags, positive)
            added = _merge_tags(meta.tags, negative) or added
            if added:
                meta.sources.append("PNG tEXt 'parameters'/'prompt'")
                found_anything = True

    rating = _clean_text(info.get("rating"))
    if rating:
        meta.rating = rating

    source_url = _clean_text(info.get("source"))
    if source_url:
        meta.source_url = source_url

    # --- 2. XMP blob (Civitai and friends) ----------------------------------
    if xmp_blob:
        xmp_text = xmp_blob.decode("utf-8", errors="replace") if isinstance(xmp_blob, bytes) else str(xmp_blob)
        subject_terms = [html.unescape(m.strip()) for m in DC_SUBJECT_RE.findall(xmp_text)]
        if subject_terms:
            if _merge_tags(meta.tags, ", ".join(subject_terms)):
                meta.sources.append("XMP dc:subject")
                found_anything = True
        prompt_match = PROMPT_XMP_RE.search(xmp_text)
        if prompt_match:
            prompt_text = html.unescape(prompt_match.group(1)).strip()
            if prompt_text:
                if not meta.prompt:
                    meta.prompt = prompt_text
                if _merge_tags(meta.tags, prompt_text):
                    meta.sources.append("XMP prompt")
                    found_anything = True

    # --- 3. EXIF UserComment (JPEG/WebP) ------------------------------------
    if exif_comment:
        if "negative prompt" in exif_comment.lower():
            meta.prompt = exif_comment
        if _merge_tags(meta.tags, exif_comment):
            meta.sources.append("EXIF UserComment")
            found_anything = True

    meta.found = found_anything or bool(meta.tags or meta.prompt)
    return meta
