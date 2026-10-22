"""
Abstract Base Class for all Booru and Art Platform Adapters.
"""

from __future__ import annotations

import math
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from hades_booru.models import Post

ProgressCallback = Callable[[float, str], None]


def host_matches(url: str, domain: str) -> bool:
    """True if `url`'s hostname is exactly `domain` or a subdomain of it (audit R6-01).

    Replaces the old substring check so lookalike hosts and query/fragment tricks
    never match: `https://danbooru.donmai.us.evil.example` and
    `https://evil.example/?ref=danbooru.donmai.us` both return False.
    """
    host = (urlparse(url).hostname or "").lower()
    d = domain.lower()
    return bool(host) and (host == d or host.endswith("." + d))

_ADAPTER_TLS = threading.local()


def _tls_get(obj: object, store_name: str, default: Any = None) -> Any:
    """Reads a thread-local value for `obj`.

    Entries store a strong reference to the object itself (audit Y2 hardening):
    while an entry exists the original object stays alive, so its `id()` can never
    be reused by a different object — and the identity check (`is`) rejects any
    stale entry anyway. This closes the id-reuse hazard of plain id-keyed maps.
    """
    store: dict[int, tuple[object, Any]] | None = getattr(_ADAPTER_TLS, store_name, None)
    if store is None:
        return default
    entry = store.get(id(obj))
    if entry is not None and entry[0] is obj:
        return entry[1]
    return default


def _tls_set(obj: object, store_name: str, value: Any) -> None:
    if not hasattr(_ADAPTER_TLS, store_name):
        setattr(_ADAPTER_TLS, store_name, {})
    store: dict[int, tuple[object, Any]] = getattr(_ADAPTER_TLS, store_name)
    store[id(obj)] = (obj, value)


class BooruAdapter(ABC):
    """Contract for searching and extracting posts from a booru or art platform."""

    id: str
    name: str
    default_domain: str

    @property
    def server_rating_applied(self) -> bool:
        """Thread-local flag: True when the current thread's search applied the rating
        filter server-side. The UI skips its client-side re-filter when True, so
        server-normalized ratings (e.g. e621's "s" safe bucket for a "General" selection)
        are not wrongly excluded by client-side equality (audit X7).

        Audit Y2: backed by threading.local (same mechanism as last_warning) so two
        concurrent searches with different ratings on the same singleton adapter
        cannot leak each other's flag and skip the client-side safety filter.
        """
        return _tls_get(self, "rating_flags", False)

    @server_rating_applied.setter
    def server_rating_applied(self, value: bool) -> None:
        _tls_set(self, "rating_flags", bool(value))

    @property
    def last_warning(self) -> str | None:
        """Thread-local warning populated when pagination stops early with partial results (N3)."""
        return _tls_get(self, "warnings", None)

    @last_warning.setter
    def last_warning(self, value: str | None) -> None:
        _tls_set(self, "warnings", value)

    def paginate(
        self,
        *,
        limit: int,
        max_limit: int,
        max_page_size: int,
        page_delay: float,
        fetch_page: Callable[[int, int], Any],
        map_item: Callable[[dict[str, Any]], Post | None],
        progress_cb: ProgressCallback | None = None,
        min_batch_size: int = 1,
    ) -> list[Post]:
        """Shared paginated search loop across all Booru adapters (audit R6-24).

        Handles target count clamping, per-page progress reporting, ID deduplication,
        early termination on partial/empty batches, inter-page rate-limit delay, and
        thread-local `last_warning` population when pagination fails after page 1.

        `min_batch_size` (R7-13, opt-in, default 1 = no behavior change): when the
        server returns a short batch smaller than this floor before the target count
        is reached, a truncation warning is surfaced in `last_warning` instead of
        failing silently. A genuinely final short page above the floor stays quiet.
        """
        target_count = max(1, min(limit, max_limit))
        page_size = min(max_page_size, target_count)
        total_pages = math.ceil(target_count / page_size)

        posts: list[Post] = []
        seen_ids: set[str] = set()
        self.last_warning = None

        for page in range(1, total_pages + 1):
            if progress_cb:
                progress_cb(
                    min(0.95, (page - 1) / max(1, total_pages)),
                    f"Querying {self.name} (Page {page}/{total_pages})...",
                )

            try:
                batch = fetch_page(page, page_size)
                if not isinstance(batch, list) or not batch:
                    break

                for item in batch:
                    if not isinstance(item, dict):
                        continue
                    mapped = map_item(item)
                    if mapped and mapped.id not in seen_ids:
                        seen_ids.add(mapped.id)
                        posts.append(mapped)
                        if len(posts) >= target_count:
                            break

                if len(posts) >= target_count:
                    break
                if len(batch) < page_size:
                    # R7-13: opt-in floor — a very short batch before reaching the
                    # target suggests the server capped the result set; flag it.
                    if min_batch_size > 1 and len(batch) < min_batch_size:
                        self.last_warning = (
                            f"{self.name} returned fewer results than requested; "
                            "the server may have truncated the result set"
                        )
                    break

                if page < total_pages and page_delay > 0:
                    time.sleep(page_delay)

            except Exception as err:
                if posts:
                    # Surface the partial-result condition instead of failing silently.
                    self.last_warning = f"pagination stopped early on page {page}: {err}"
                    break
                raise

        if progress_cb:
            progress_cb(1.0, f"Loaded {len(posts)} posts from {self.name}.")

        return posts[:target_count]

    @abstractmethod
    def can_handle_url(self, url: str) -> bool:
        """Returns True if this adapter can handle the given pasted URL."""

    @abstractmethod
    def search(
        self,
        tags: str,
        limit: int = 20,
        progress_cb: ProgressCallback | None = None,
        rating: str | None = None,
    ) -> list[Post]:
        """Executes a paginated tag search and returns normalized Post instances.

        `rating` ("g"/"s"/"q"/"e"/"u") is applied server-side when the source API
        supports it; adapters without server-side support ignore it and the UI keeps
        its client-side safety filter.
        """

    @abstractmethod
    def fetch_single_by_url(self, url: str) -> Post:
        """Fetches a single post directly from its canonical page or API URL."""
