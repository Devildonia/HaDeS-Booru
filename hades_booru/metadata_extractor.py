"""
Local Image Metadata Extractor (v1.0.3 "Image to Prompt").

Reads embedded prompt/tags from an image file WITHOUT uploading anything:
- PNG tEXt chunks:  'comment' (Danbooru/Bilibili/Gelbooru), 'description',
                    'parameters' / 'prompt' (Civitai / Stable Diffusion),
                    'rating', 'source'
- XMP blob:         <dc:subject>/<dc:term> and prompt-like elements
                    (JPEG/WebP 'XMP' key, PNG 'XML:com.adobe.xmp' key)
- JPEG/WebP EXIF:   UserComment (0x9286), including 'UNICODE' (UTF-16) prefixed
                    comments as written by A1111 in JPEG/WebP output

Everything runs in-process with Pillow; no network access is performed.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from PIL import Image
from PIL.Image import DecompressionBombError, UnidentifiedImageError

from hades_booru.models import ExtractedImageMeta
from hades_booru.normalizer import parse_tag_list

# Audit R6-03: explicit, generous decompression-bomb ceiling so the guard raises a
# clean error instead of Pillow's default (which is lower) or unbounded memory use.
Image.MAX_IMAGE_PIXELS = 64_000_000  # 64 MP

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})
SUPPORTED_FORMATS: frozenset[str] = frozenset({"PNG", "JPEG", "WEBP"})

# dc:subject appears as xmp-array '<dc:term>' or plain RDF '<rdf:Bag><rdf:li>' depending on the writer.
DC_SUBJECT_RE = re.compile(r"<(?:dc:term|rdf:li)[^>]*>([^<]+)</(?:dc:term|rdf:li)>", re.IGNORECASE)
PROMPT_XMP_RE = re.compile(r"<[^>]*(?:prompt|parameters)[^>]*>([^<]+)<", re.IGNORECASE)
EXIF_USER_COMMENT_TAG = 0x9286
# EXIF UserComment prefixes: 'ASCII\0' + 3 padding NULs, 'UNICODE\0' (UTF-16 body), 'JIS\0'.
EXIF_PREFIX_RE = re.compile(rb"^(?:UNICODE|Unicode|ASCII|JIS)\x00", re.IGNORECASE)

# A1111-style 'parameters' blob: split into positive / negative / settings.
NEGATIVE_MARKER_RE = re.compile(r"\bNegative\s+prompt\s*:", re.IGNORECASE)
SETTING_CANDIDATE_RE = re.compile(r",\s*([A-Z][A-Za-z0-9][A-Za-z0-9 _/\-]*?)\s*:\s*\S")
# A1111/Forge place the settings block on its own line starting with 'Steps:'
# (there is NO comma before it), so the comma-anchored candidate regex alone
# would miss it and leak 'Steps: N' into the negative section (audit X1).
STEPS_LINE_RE = re.compile(r"(?m)^\s*Steps\s*:\s")
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
        # errors="replace" never raises; no latin-1 fallback needed (R7 type fix).
        value = value.decode("utf-8", errors="replace")
    text = str(value)
    text = html.unescape(text)
    return text.strip()


def _extract_comfyui_prompt(blob: str) -> tuple[str, str] | None:
    """Decodes a ComfyUI prompt graph (JSON) into (positive, negative) texts.

    ComfyUI stores the API prompt graph in the 'prompt' tEXt chunk. The correct
    positive/negative pairing is given by the sampler node's `positive` /
    `negative` inputs (each `[node_id, slot]`), so we follow those links first.
    Only when no sampler link exists do we fall back to text-node order (first
    node = positive, second = negative). Returns None if the blob is not a graph
    with at least one text node.
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

    texts: dict[str, str] = {}
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict):
            text = inputs.get("text")
            if isinstance(text, str) and text.strip():
                texts[str(node_id).strip()] = text.strip()
    if not texts:
        return None

    def _link_target(value: object) -> str | None:
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        if isinstance(value, (str, int)) and str(value).strip() in texts:
            return str(value).strip()
        return None

    pos_id: str | None = None
    neg_id: str | None = None
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        pos_id = pos_id or _link_target(inputs.get("positive"))
        neg_id = neg_id or _link_target(inputs.get("negative"))

    if pos_id is not None or neg_id is not None:
        positive = texts.get(pos_id, "") if pos_id is not None else ""
        negative = texts.get(neg_id, "") if neg_id is not None else ""
        # Audit Y3: text nodes NOT linked by the sampler are dead nodes (orphaned
        # style presets, discarded drafts). Mixing them into the negative prompt would
        # inject positive-side words ("1girl, smile") into what users train against,
        # so they are discarded rather than smuggled into the negative bucket.
        return positive, negative

    # Fallback: no sampler links found; use text-node order.
    ordered = list(texts.values())
    positive = ordered[0]
    negative = ", ".join(ordered[1:]) if len(ordered) > 1 else ""
    return positive, negative


def _find_settings_start(text: str) -> int | None:
    """Locates the start of the settings block inside a blob.

    Prefers a line starting with 'Steps:' (A1111/Forge layout: settings on their
    own line, no leading comma); otherwise the first ', Key: value' candidate.
    """
    steps_line = STEPS_LINE_RE.search(text)
    if steps_line is not None:
        return steps_line.start()
    candidates = list(SETTING_CANDIDATE_RE.finditer(text))
    if not candidates:
        return None
    known = [m for m in candidates if m.group(1).strip().lower() in KNOWN_SETTING_KEYS]
    pick = known[0] if known else candidates[0]
    return pick.start()


def split_sd_parameters(blob: str) -> tuple[str, str, str]:
    """Splits an A1111/Forge/SD.Next 'parameters' blob into (positive, negative, settings).

    The split is heuristic: the 'Negative prompt:' marker separates positive from
    the rest, and the settings block starts at the 'Steps:' line (or the first
    recognized ', Key: value' pair). Without a negative marker, a trailing
    settings block is still separated from the positive prompt. Anything that
    cannot be separated is kept in the closest preceding section, so no text is
    ever lost.
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
    else:
        start = _find_settings_start(blob)
        if start is not None:
            positive = blob[:start]
            settings = blob[start:]
    positive = positive.strip().strip(",").strip()
    negative = negative.strip().strip(",").strip()
    settings = settings.strip().strip(",").strip()
    return positive, negative, settings


def format_settings_lines(settings: str) -> str:
    """Renders a settings blob as one 'Key: value' per line (falls back to raw text)."""
    text = (settings or "").strip().strip(",").strip()
    if not text:
        return ""
    # Normalize line breaks to comma separators so one setting per line always holds.
    text = re.sub(r"\s*\n\s*", ", ", text)
    boundaries = [0] + [m.start() for m in SETTING_CANDIDATE_RE.finditer(text)]
    lines: list[str] = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        segment = text[start:end].strip().lstrip(",").strip()
        if segment:
            lines.append(segment)
    return "\n".join(lines) if lines else text


def _extract_exif_user_comment(img: Image.Image) -> str:
    """Best-effort EXIF UserComment extraction (JPEG/WebP).

    Handles the EXIF prefixes correctly (audit X2): 'UNICODE' bodies are
    UTF-16 (A1111 writes JPEG/WebP comments this way), 'ASCII' bodies carry up
    to 3 padding NULs after the prefix that must not leak into the text.
    """
    try:
        exif = img.getexif()
        if not exif:
            return ""
        raw = exif.get(EXIF_USER_COMMENT_TAG)
        if raw is None:
            return ""
        if isinstance(raw, (bytes, bytearray)):
            body = bytes(raw)
            m = EXIF_PREFIX_RE.match(body)
            if m:
                is_unicode = m.group(0)[:1].upper() == b"U"
                body = body[m.end():]
                if not is_unicode:
                    body = body.lstrip(b"\x00")
            if body.startswith(b"\xff\xfe"):
                return body[2:].decode("utf-16-le", errors="replace").strip()
            if body.startswith(b"\xfe\xff"):
                return body[2:].decode("utf-16-be", errors="replace").strip()
            if body and body[0] == 0 and len(body) % 2 == 0:
                # Leading NUL with even length: UTF-16BE without BOM (UNICODE prefix).
                return body.decode("utf-16-be", errors="replace").strip()
            return body.decode("utf-8", errors="replace").strip()
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
        # Audit R6-03: only instantiate the plugins we actually support, so a file
        # with a lying extension (e.g. a GIF named .png) never engages unrelated
        # decoders (TIFF/EPS/...) before our format check runs.
        with Image.open(path, formats=["PNG", "JPEG", "WEBP"]) as img:
            if img.format is None or img.format.upper() not in SUPPORTED_FORMATS:
                raise MetadataExtractionError(f"Unsupported image format: {img.format}")
            width, height = img.size
            fmt = img.format.upper()
            info = dict(img.info)
            exif_comment = _extract_exif_user_comment(img)
            # Pillow stores XMP under 'XMP' for JPEG/WebP but under
            # 'XML:com.adobe.xmp' for PNG (audit X3).
            xmp_blob = info.get("XMP") or info.get("XML:com.adobe.xmp")
    except DecompressionBombError as err:
        # Audit R6-14: surface a clean, user-friendly error instead of raw Pillow text.
        raise MetadataExtractionError(
            "Image is too large to process safely (decompression-bomb guard)."
        ) from err
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
        comfy = _extract_comfyui_prompt(parameters)
        if comfy:
            # ComfyUI graph: positive/negative resolved via sampler links.
            positive, negative = comfy
            meta.prompt = positive
            if negative:
                meta.negative = negative
            # Only positive tags feed the tag list: negative words and settings
            # are shown in their own boxes (audit X6).
            added = _merge_tags(meta.tags, positive)
            if added or negative:
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
            if added or negative:
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
        positive, negative, settings = split_sd_parameters(exif_comment)
        meta.prompt = positive or exif_comment
        if negative:
            meta.negative = negative
        if settings:
            meta.settings = settings
        added = _merge_tags(meta.tags, meta.prompt or "")
        if added or negative:
            meta.sources.append("EXIF UserComment")
            found_anything = True

    meta.found = found_anything or bool(meta.tags or meta.prompt)
    return meta
