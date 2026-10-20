"""
Core Domain Models for HaDeS Booru.
Strictly typed with Pydantic v2 for validation, serialization, and immutability.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TagCategory = Literal["copyright", "character", "artist", "general", "meta"]
Rating = Literal["g", "s", "q", "e", "u"]
ExportMode = Literal["dataset", "unified", "trainer-zip", "local-folder"]
ImageQuality = Literal["low", "medium", "high", "original", "text"]
Language = Literal["en", "es"]

# Canonical set of meta/technical tags used by flat-tag adapters (Gelbooru, Moebooru, etc.)
COMMON_META_TAGS: frozenset[str] = frozenset(
    {
        "highres",
        "absurdres",
        "incredibly_absurdres",
        "huge_filesize",
        "translation_request",
        "translated",
        "partially_translated",
        "hard_translated",
        "poorly_translated",
        "annotated",
        "commentary",
        "commentary_request",
        "english_commentary",
        "check_commentary",
        "sample",
        "watermark",
        "check_source",
        "source_request",
        "bad_id",
        "bad_link",
        "bad_pixiv_id",
        "bad_twitter_id",
        "duplicate",
        "pixel-perfect_duplicate",
        "md5_mismatch",
        "wallpaper",
        "wide_image",
        "tagme",
        "scan",
        "jpeg_artifacts",
        "animated",
        "presumed",
        "resized",
        "third-party_edit",
    }
)

DEFAULT_JUNK_TAGS: list[str] = [
    "bad_id",
    "bad_link",
    "bad_pixiv_id",
    "bad_twitter_id",
    "bad_tumblr_id",
    "bad_deviantart_id",
    "bad_nicoseiga_id",
    "commentary_request",
    "commentary",
    "partial_commentary",
    "english_commentary",
    "chinese_commentary",
    "korean_commentary",
    "symbol_only_commentary",
    "translated",
    "translation_request",
    "partially_translated",
    "hard_translated",
    "poorly_translated",
    "annotated",
    "non-web_source",
    "check_commentary",
    "md5_mismatch",
    "duplicate",
    "pixel-perfect_duplicate",
    "sample",
    "watermark",
    "watermark*",
    "source_request",
    "check_source",
    "resized",
    "third-party_edit",
    "highres",
    "absurdres",
    "incredibly_absurdres",
    "huge_filesize",
]

DEFAULT_SEMANTIC_ORDER: list[TagCategory] = [
    "copyright",
    "character",
    "artist",
    "general",
    "meta",
]


class CategorizedTags(BaseModel):
    """Taxonomic breakdown of tags for a single booru/art post."""

    model_config = ConfigDict(extra="ignore")

    copyright: list[str] = Field(default_factory=list)
    character: list[str] = Field(default_factory=list)
    artist: list[str] = Field(default_factory=list)
    general: list[str] = Field(default_factory=list)
    meta: list[str] = Field(default_factory=list)


class Post(BaseModel):
    """Normalized representation of a post from any supported booru or art platform."""

    model_config = ConfigDict(extra="ignore")

    id: str
    source_id: str
    source_name: str
    source_url: str
    preview_url: str = ""
    medium_url: str = ""
    sample_url: str = ""
    file_url: str = ""
    width: int = 0
    height: int = 0
    rating: Rating = "u"
    tags: CategorizedTags = Field(default_factory=CategorizedTags)
    raw_tags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    score: int | None = None
    title: str | None = None
    author: str | None = None

    @property
    def best_display_url(self) -> str:
        """Returns the best image URL for gallery/preview display (consistent with high quality tier)."""
        return self.sample_url or self.medium_url or self.file_url or self.preview_url

    @property
    def best_download_url(self) -> str:
        """Returns the highest resolution image URL available for dataset export."""
        return self.file_url or self.sample_url or self.medium_url or self.preview_url

    def url_for_quality(self, quality: ImageQuality) -> str:
        """Resolves the optimal image URL for the requested display quality tier."""
        if quality == "text":
            return ""
        if quality == "low":
            return self.preview_url or self.medium_url or self.sample_url or self.file_url
        if quality == "medium":
            return self.medium_url or self.sample_url or self.preview_url or self.file_url
        if quality == "original":
            return self.file_url or self.sample_url or self.medium_url or self.preview_url
        # Default: "high" (Sample HD — matches best_display_url priority)
        return self.sample_url or self.medium_url or self.file_url or self.preview_url


class NormalizerConfig(BaseModel):
    """Configuration for tag cleaning and semantic prompt generation."""

    model_config = ConfigDict(extra="ignore")

    replace_underscores: bool = True
    escape_parentheses: bool = True
    filter_junk_tags: bool = True
    junk_tags_list: list[str] = Field(default_factory=lambda: list(DEFAULT_JUNK_TAGS))
    # Personal user lists (v1.0.3): blacklist EXTENDS the default junk list,
    # whitelist OVERRIDES it (whitelisted tags are always preserved).
    user_blacklist: list[str] = Field(default_factory=list)
    user_whitelist: list[str] = Field(default_factory=list)
    semantic_order: list[TagCategory] = Field(default_factory=lambda: list(DEFAULT_SEMANTIC_ORDER))
    custom_separator: str = ", "


class ExportConfig(BaseModel):
    """Configuration for bulk prompt and LoRA dataset export."""

    model_config = ConfigDict(extra="ignore")

    default_mode: ExportMode = "dataset"
    filename_prefix: str = ""
    include_metadata_header: bool = False
    trigger_word: str = ""
    exclude_categories: list[TagCategory] = Field(default_factory=list)
    local_export_dir: str = "./exports"
    download_high_res: bool = True


class ExtractedImageMeta(BaseModel):
    """Result of local metadata extraction from an image file (v1.0.3 Image to Prompt)."""

    model_config = ConfigDict(extra="ignore")

    format: str = ""
    width: int = 0
    height: int = 0
    found: bool = False
    sources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    prompt: str | None = None  # positive prompt text (verbatim)
    negative: str | None = None  # negative prompt text (SD / ComfyUI)
    settings: str | None = None  # generation settings (Steps, Sampler, Seed, ...)
    rating: str | None = None
    source_url: str | None = None


class SourceCredential(BaseModel):
    """Optional user/API key credentials for rate-limit elevation and restricted tags."""

    model_config = ConfigDict(extra="ignore")

    user_id: str = ""
    api_key: str = ""


class AppConfig(BaseModel):
    """Root persistent configuration model."""

    model_config = ConfigDict(extra="ignore")

    normalizer: NormalizerConfig = Field(default_factory=NormalizerConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    credentials: dict[str, SourceCredential] = Field(
        default_factory=lambda: {
            "danbooru": SourceCredential(),
            "gelbooru": SourceCredential(),
            "rule34": SourceCredential(),
            "e621": SourceCredential(),
        }
    )
    persist_credentials: bool = True
    image_quality: ImageQuality = "high"
    language: Language = "en"
    data_saver_mode: bool = False
    # v1.0.6: most-recent-first search history (dedup, capped in the UI layer).
    search_history: list[str] = Field(default_factory=list)


class BooruSourceSpec(BaseModel):
    """Specification metadata for a registered booru or art platform."""

    id: str
    name: str
    domain: str
    default_endpoint: str
    description: str
    categorized_tags: bool = False
    supports_pagination: bool = True
