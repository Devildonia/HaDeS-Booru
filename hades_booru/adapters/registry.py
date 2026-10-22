"""
Adapter Registry & Intelligent URL Auto-Detection.
Catalogues all 27 supported boorus and art platforms across 7 API families, detects direct post links
vs listing/search URLs, and extracts query tags automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from hades_booru.adapters.artplatforms import ArtPlatformsAdapter
from hades_booru.adapters.base import BooruAdapter
from hades_booru.adapters.danbooru import DanbooruAdapter
from hades_booru.adapters.e621 import E621Adapter
from hades_booru.adapters.gelbooru import GelbooruAdapter
from hades_booru.adapters.moebooru import MoebooruAdapter
from hades_booru.adapters.philomena import PhilomenaAdapter
from hades_booru.adapters.zerochan import (
    ZerochanAdapter,
    extract_zerochan_post_id,
    extract_zerochan_tag_from_path,
)
from hades_booru.models import BooruSourceSpec


@dataclass(frozen=True)
class DetectedUrlSource:
    """Result of inspecting a pasted URL in the search bar."""

    adapter: BooruAdapter
    is_direct_post: bool
    extracted_tags: str | None = None


class AdapterRegistry:
    """Central registry of all BooruAdapter instances and specs."""

    def __init__(self) -> None:
        self._adapters: dict[str, BooruAdapter] = {}
        self._specs: list[BooruSourceSpec] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        # =====================================================================
        # FAMILY 1: Danbooru v2 Engine (Categorized Taxonomy)
        # =====================================================================
        danbooru_sources = [
            ("danbooru", "Danbooru", "danbooru.donmai.us", "Primary Danbooru server with full tag taxonomy."),
            ("safebooru_donmai", "Safebooru (Donmai)", "safebooru.donmai.us", "General-rating mirror of Danbooru."),
            ("hijiribe", "Hijiribe (Donmai)", "hijiribe.donmai.us", "Official Donmai mirror server."),
            ("sonohara", "Sonohara (Donmai)", "sonohara.donmai.us", "Official Donmai mirror server."),
            ("aibooru", "AIBooru", "aibooru.online", "AI-generated art booru running Danbooru v2."),
            ("atfbooru", "AllTheFallen Booru", "booru.allthefallen.moe", "Community Danbooru v2 instance."),
        ]
        for s_id, s_name, s_domain, s_desc in danbooru_sources:
            adapter = DanbooruAdapter(s_id, s_name, s_domain)
            self.register(
                adapter,
                BooruSourceSpec(
                    id=s_id,
                    name=s_name,
                    domain=s_domain,
                    default_endpoint="/posts.json",
                    description=s_desc,
                    categorized_tags=True,
                    supports_pagination=True,
                ),
            )

        # =====================================================================
        # FAMILY 2: Gelbooru / DAPI Engine (JSON + XML Fallback)
        # =====================================================================
        dapi_sources: list[tuple[str, str, str, str | None, str]] = [
            ("safebooru", "Safebooru (DAPI)", "safebooru.org", None, "SFW Gelbooru-compatible DAPI board."),
            ("gelbooru", "Gelbooru", "gelbooru.com", None, "Classic anime image board with DAPI."),
            ("rule34", "Rule34.xxx", "rule34.xxx", "api.rule34.xxx", "Adult booru via api.rule34.xxx DAPI."),
            ("rule34_us", "Rule34.us", "rule34.us", None, "Alternative Rule34 board."),
            ("tbib", "The Big ImageBoard (TBIB)", "tbib.org", None, "Aggregated multi-booru DAPI archive."),
            ("xbooru", "XBooru", "xbooru.com", None, "Classic DAPI-compatible image board."),
            ("realbooru", "RealBooru", "realbooru.com", None, "DAPI-compatible board."),
        ]
        for s_id, s_name, s_domain, s_api_host, s_desc in dapi_sources:
            dapi_adapter = GelbooruAdapter(s_id, s_name, s_domain, s_api_host)
            self.register(
                dapi_adapter,
                BooruSourceSpec(
                    id=s_id,
                    name=s_name,
                    domain=s_domain,
                    default_endpoint="/index.php?page=dapi&s=post&q=index&json=1",
                    description=s_desc,
                    categorized_tags=False,
                    supports_pagination=True,
                ),
            )

        # =====================================================================
        # FAMILY 3: Moebooru Engine (/post.json)
        # =====================================================================
        moebooru_sources = [
            ("konachan", "Konachan (All)", "konachan.com", "High-resolution anime wallpaper Moebooru."),
            ("konachan_net", "Konachan.net (SFW)", "konachan.net", "Safe-for-work mirror of Konachan."),
            ("yandere", "Yande.re", "yande.re", "High-resolution illustration and scan repository."),
            ("sakugabooru", "Sakugabooru", "sakugabooru.com", "Key animation, genga, and sakuga archive."),
            ("lolibooru", "Lolibooru", "lolibooru.moe", "Moebooru-compatible illustration board."),
        ]
        for s_id, s_name, s_domain, s_desc in moebooru_sources:
            moe_adapter = MoebooruAdapter(s_id, s_name, s_domain)
            self.register(
                moe_adapter,
                BooruSourceSpec(
                    id=s_id,
                    name=s_name,
                    domain=s_domain,
                    default_endpoint="/post.json",
                    description=s_desc,
                    categorized_tags=False,
                    supports_pagination=True,
                ),
            )

        # =====================================================================
        # FAMILY 4: E621 / E926 Engine (Categorized Taxonomy)
        # =====================================================================
        e621_sources = [
            ("e621", "E621", "e621.net", "Anthro illustration archive with full tag taxonomy."),
            ("e926", "E926 (SFW)", "e926.net", "Safe-for-work mirror of E621."),
        ]
        for s_id, s_name, s_domain, s_desc in e621_sources:
            e_adapter = E621Adapter(s_id, s_name, s_domain)
            self.register(
                e_adapter,
                BooruSourceSpec(
                    id=s_id,
                    name=s_name,
                    domain=s_domain,
                    default_endpoint="/posts.json",
                    description=s_desc,
                    categorized_tags=True,
                    supports_pagination=True,
                ),
            )

        # =====================================================================
        # FAMILY 5: Philomena Engine (Derpibooru)
        # =====================================================================
        derpi = PhilomenaAdapter("derpibooru", "Derpibooru", "derpibooru.org")
        self.register(
            derpi,
            BooruSourceSpec(
                id=derpi.id,
                name=derpi.name,
                domain=derpi.default_domain,
                default_endpoint="/api/v1/json/search/images",
                description="Philomena JSON API image board.",
                categorized_tags=True,
                supports_pagination=True,
            ),
        )

        # =====================================================================
        # FAMILY 6: Zerochan Engine
        # =====================================================================
        zerochan = ZerochanAdapter("zerochan", "Zerochan", "www.zerochan.net")
        self.register(
            zerochan,
            BooruSourceSpec(
                id=zerochan.id,
                name=zerochan.name,
                domain=zerochan.default_domain,
                default_endpoint="/?json=1",
                description="Curated anime illustration index.",
                categorized_tags=False,
                supports_pagination=True,
            ),
        )

        # =====================================================================
        # FAMILY 7: Art Platforms & OpenGraph Scrapers
        # =====================================================================
        art_sources = [
            ("deviantart", "DeviantArt (RSS)", "deviantart.com", "/rss.xml", "Public deviations via RSS media stream."),
            ("artstation", "ArtStation", "artstation.com", "/api/v2/search/projects.json", "2D/3D portfolio platform."),
            ("pawoo", "Pawoo (Mastodon)", "pawoo.net", "/api/v1/timelines/tag", "Mastodon-based illustration timeline."),
            ("ehentai", "E-Hentai (Direct URL)", "e-hentai.org", "/", "Direct gallery metadata extractor."),
            ("generic", "Booru.io / OpenGraph URL", "booru.io", "/", "Extracts OpenGraph metadata from direct URLs."),
        ]
        for s_id, s_name, s_domain, s_ep, s_desc in art_sources:
            art_adapter = ArtPlatformsAdapter(s_id, s_name, s_domain)
            self.register(
                art_adapter,
                BooruSourceSpec(
                    id=s_id,
                    name=s_name,
                    domain=s_domain,
                    default_endpoint=s_ep,
                    description=s_desc,
                    categorized_tags=False,
                    supports_pagination=False,
                ),
            )

    def register(self, adapter: BooruAdapter, spec: BooruSourceSpec) -> None:
        self._adapters[adapter.id] = adapter
        self._specs.append(spec)

    def get_adapter(self, source_id: str) -> BooruAdapter:
        if source_id not in self._adapters:
            raise KeyError(f"No adapter registered for source ID: {source_id}")
        return self._adapters[source_id]

    def get_all_specs(self) -> list[BooruSourceSpec]:
        return list(self._specs)

    def get_dropdown_choices(self) -> list[tuple[str, str]]:
        """Returns (label, source_id) tuples for Gradio Dropdown."""
        return [(f"{s.name} ({s.domain})", s.id) for s in self._specs]

    def detect_source_from_url(self, text: str) -> DetectedUrlSource | None:
        """Inspects input text; if it is an HTTP(S) URL, detects the adapter,
        determines if it is a single post or a listing search URL, and extracts query tags.
        """
        trimmed = text.strip()
        if not (trimmed.startswith("http://") or trimmed.startswith("https://")):
            return None

        try:
            parsed = urlparse(trimmed)
        except Exception:
            return None

        if not parsed.hostname:
            return None

        qs = parse_qs(parsed.query)

        def _first_param(key: str) -> str | None:
            values = qs.get(key)
            return values[0] if values else None

        raw_param = _first_param("tags") or _first_param("q") or _first_param("query")
        extracted_tags: str | None = None
        if raw_param:
            extracted_tags = unquote(raw_param).replace("+", " ").strip()
        else:
            path_tag_m = re.search(r"/(?:timelines/)?tag(?:s)?/([^/?#]+)", parsed.path, re.IGNORECASE)
            if path_tag_m:
                extracted_tags = unquote(path_tag_m.group(1)).replace("+", " ").strip()

        for adapter in self._adapters.values():
            if adapter.can_handle_url(trimmed):
                if adapter.id == "zerochan":
                    zc_post_id = extract_zerochan_post_id(trimmed)
                    if zc_post_id:
                        return DetectedUrlSource(
                            adapter=adapter,
                            is_direct_post=True,
                            extracted_tags=None,
                        )
                    zc_tags = extracted_tags or extract_zerochan_tag_from_path(parsed.path)
                    return DetectedUrlSource(
                        adapter=adapter,
                        is_direct_post=False,
                        extracted_tags=zc_tags,
                    )

                is_direct = bool(
                    re.search(r"/posts?/\d+", trimmed, re.IGNORECASE)
                    or re.search(r"/images/\d+", trimmed, re.IGNORECASE)
                    or (
                        re.search(r"[?&]id=\d+", trimmed, re.IGNORECASE)
                        and not re.search(r"[?&]s=list", trimmed, re.IGNORECASE)
                    )
                    or re.search(r"/post/show/\d+", trimmed, re.IGNORECASE)
                    or re.search(r"/artwork/[a-zA-Z0-9_-]+", trimmed, re.IGNORECASE)
                    or re.search(r"/statuses/\d+", trimmed, re.IGNORECASE)
                    or re.search(r"/g/\d+/[a-z0-9]+", trimmed, re.IGNORECASE)
                )
                return DetectedUrlSource(
                    adapter=adapter,
                    is_direct_post=is_direct,
                    extracted_tags=extracted_tags,
                )

        generic = self._adapters.get("generic")
        if generic:
            return DetectedUrlSource(adapter=generic, is_direct_post=True)

        return None


registry = AdapterRegistry()
