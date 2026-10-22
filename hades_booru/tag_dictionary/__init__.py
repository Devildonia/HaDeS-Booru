"""
Public interface for the HaDeS Booru Offline Tag Dictionary (v1.1.0).
"""

from __future__ import annotations

from hades_booru.tag_dictionary.importer import TagDictionaryImporter, strip_dtext
from hades_booru.tag_dictionary.service import (
    DEFAULT_DB_PATH,
    TagDictionaryService,
    TagRecord,
    get_tag_dictionary,
    normalize_dict_query,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "TagDictionaryImporter",
    "TagDictionaryService",
    "TagRecord",
    "get_tag_dictionary",
    "normalize_dict_query",
    "strip_dtext",
]
