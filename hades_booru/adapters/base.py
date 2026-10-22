"""
Abstract Base Class for all Booru and Art Platform Adapters.
"""

from __future__ import annotations

import threading
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
