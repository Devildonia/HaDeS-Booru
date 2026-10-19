"""
Abstract Base Class for all Booru and Art Platform Adapters.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable

from hades_booru.models import Post

ProgressCallback = Callable[[float, str], None]

_ADAPTER_TLS = threading.local()


class BooruAdapter(ABC):
    """Contract for searching and extracting posts from a booru or art platform."""

    id: str
    name: str
    default_domain: str

    # Set by each adapter inside search() when the rating filter was applied
    # server-side. The UI skips its client-side re-filter when this is True, so
    # server-normalized ratings (e.g. e621's "s" safe bucket for a "General"
    # selection) are not wrongly excluded by client-side equality (audit X7).
    server_rating_applied: bool = False

    @property
    def last_warning(self) -> str | None:
        """Thread-local warning populated when pagination stops early with partial results (N3)."""
        warnings_map: dict[int, str | None] = getattr(_ADAPTER_TLS, "warnings", {})
        return warnings_map.get(id(self))

    @last_warning.setter
    def last_warning(self, value: str | None) -> None:
        if not hasattr(_ADAPTER_TLS, "warnings"):
            _ADAPTER_TLS.warnings = {}
        _ADAPTER_TLS.warnings[id(self)] = value

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
