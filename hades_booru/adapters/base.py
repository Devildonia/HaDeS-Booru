"""
Abstract Base Class for all Booru and Art Platform Adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from hades_booru.models import Post

ProgressCallback = Callable[[float, str], None]


class BooruAdapter(ABC):
    """Contract for searching and extracting posts from a booru or art platform."""

    id: str
    name: str
    default_domain: str

    # Populated by search() implementations when pagination stops early with partial results.
    last_warning: str | None = None

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
