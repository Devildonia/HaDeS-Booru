"""
Offline SQLite Tag Dictionary Service for HaDeS Booru (v1.1.0).
Provides millisecond exact-match lookup, canonical alias resolution, prefix suggestions,
and batch category lookup for flat-tag adapters (DAPI/Moebooru/Zerochan).
Strictly enforces the bilingual contract: Spanish definitions are returned only when a
genuine translation is stored; otherwise the original English definition is returned with
an explicit fallback flag (never machine-translated).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from hades_booru.models import Language, TagCategory
from hades_booru.tag_dictionary.seed_data import SEED_TAG_CATALOG, SeedTagEntry

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "tags.sqlite3"

VALID_TAG_CATEGORIES: frozenset[str] = frozenset(
    {"copyright", "character", "artist", "general", "meta"}
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tags (
    name TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    post_count INTEGER NOT NULL DEFAULT 0,
    body_en TEXT NOT NULL DEFAULT '',
    body_es TEXT DEFAULT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tag_aliases (
    antecedent_name TEXT PRIMARY KEY,
    consequent_name TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_aliases_consequent ON tag_aliases(consequent_name);
CREATE INDEX IF NOT EXISTS idx_tags_post_count ON tags(post_count DESC);
"""


def normalize_dict_query(raw: str) -> str:
    """Normalizes a user tag query into canonical Danbooru underscore format."""
    cleaned = "_".join((raw or "").strip().lower().split())
    return cleaned.strip("_") if cleaned != "_" else cleaned


class TagRecord(BaseModel):
    """Canonical tag definition and taxonomic metadata from the local dictionary."""

    model_config = ConfigDict(extra="ignore")

    name: str
    category: TagCategory = "general"
    post_count: int = 0
    body_en: str = ""
    body_es: str | None = None
    aliases: list[str] = Field(default_factory=list)
    resolved_from: str | None = None

    @property
    def wiki_url(self) -> str:
        """Returns the official Danbooru wiki URL for this canonical tag."""
        return f"https://danbooru.donmai.us/wiki_pages/{quote(self.name, safe='')}"

    def definition_for(self, lang: Language = "en") -> tuple[str, bool]:
        """Returns `(definition_text, is_fallback_to_english)`.

        When `lang == "es"`, returns `(body_es, False)` only if a genuine Spanish
        translation is stored; otherwise returns `(body_en, True)` so the UI can
        clearly indicate that the original English definition is shown.
        """
        if lang == "es":
            if self.body_es and self.body_es.strip():
                return self.body_es.strip(), False
            return self.body_en.strip(), True
        return self.body_en.strip(), False


class TagDictionaryService:
    """Thread-safe local SQLite dictionary service with automatic seed bootstrap."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH, auto_seed: bool = True) -> None:
        self._db_path = db_path
        self._auto_seed = auto_seed
        self._lock = threading.RLock()
        self._initialized = False
        self._memory_conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), timeout=10.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as err:
            logger.warning("Falling back to in-memory SQLite for TagDictionaryService: %s", err)
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn

    def ensure_initialized(self) -> None:
        """Ensures schema exists and seeds foundational catalog if the database is empty."""
        with self._lock:
            if self._initialized and (self._memory_conn is not None or self._db_path.exists()):
                return
            conn = self._connect()
            try:
                with conn:
                    conn.executescript(SCHEMA_SQL)
                    if self._auto_seed:
                        row = conn.execute("SELECT COUNT(*) AS cnt FROM tags").fetchone()
                        count = int(row["cnt"]) if row else 0
                        if count == 0:
                            self._insert_entries(conn, SEED_TAG_CATALOG)
                self._initialized = True
            finally:
                if conn is not self._memory_conn:
                    conn.close()

    def _insert_entries(
        self,
        conn: sqlite3.Connection,
        entries: Sequence[SeedTagEntry],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        for entry in entries:
            name = normalize_dict_query(entry["name"])
            if not name:
                continue
            raw_cat = entry.get("category", "general")
            cat: TagCategory = (
                cast(TagCategory, raw_cat) if raw_cat in VALID_TAG_CATEGORIES else "general"
            )
            conn.execute(
                """
                INSERT INTO tags (name, category, post_count, body_en, body_es, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    category = excluded.category,
                    post_count = MAX(tags.post_count, excluded.post_count),
                    body_en = CASE WHEN excluded.body_en != '' THEN excluded.body_en ELSE tags.body_en END,
                    body_es = COALESCE(excluded.body_es, tags.body_es),
                    updated_at = excluded.updated_at
                """,
                (
                    name,
                    cat,
                    int(entry.get("post_count", 0)),
                    str(entry.get("body_en") or ""),
                    entry.get("body_es"),
                    now,
                ),
            )
            for alias in entry.get("aliases") or []:
                norm_alias = normalize_dict_query(alias)
                if norm_alias and norm_alias != name:
                    conn.execute(
                        """
                        INSERT INTO tag_aliases (antecedent_name, consequent_name)
                        VALUES (?, ?)
                        ON CONFLICT(antecedent_name) DO UPDATE SET
                            consequent_name = excluded.consequent_name
                        """,
                        (norm_alias, name),
                    )

    def upsert_entries(self, entries: Sequence[SeedTagEntry]) -> int:
        """Inserts or updates a batch of tag definitions and aliases atomically."""
        self.ensure_initialized()
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    self._insert_entries(conn, entries)
                return len(entries)
            finally:
                if conn is not self._memory_conn:
                    conn.close()

    def lookup(self, query: str) -> TagRecord | None:
        """Performs exact tag lookup with automatic alias resolution."""
        norm = normalize_dict_query(query)
        if not norm:
            return None

        self.ensure_initialized()
        with self._lock:
            conn = self._connect()
            try:
                resolved_from: str | None = None
                canonical = norm

                row = conn.execute(
                    "SELECT name, category, post_count, body_en, body_es FROM tags WHERE name = ?",
                    (canonical,),
                ).fetchone()

                if row is None:
                    alias_row = conn.execute(
                        "SELECT consequent_name FROM tag_aliases WHERE antecedent_name = ?",
                        (norm,),
                    ).fetchone()
                    if alias_row is None:
                        return None
                    canonical = str(alias_row["consequent_name"])
                    resolved_from = norm
                    row = conn.execute(
                        "SELECT name, category, post_count, body_en, body_es FROM tags WHERE name = ?",
                        (canonical,),
                    ).fetchone()
                    if row is None:
                        return None

                alias_rows = conn.execute(
                    "SELECT antecedent_name FROM tag_aliases WHERE consequent_name = ? ORDER BY antecedent_name ASC",
                    (canonical,),
                ).fetchall()
                aliases = [str(r["antecedent_name"]) for r in alias_rows]
                raw_cat = str(row["category"])
                cat: TagCategory = (
                    cast(TagCategory, raw_cat) if raw_cat in VALID_TAG_CATEGORIES else "general"
                )

                return TagRecord(
                    name=str(row["name"]),
                    category=cat,
                    post_count=int(row["post_count"] or 0),
                    body_en=str(row["body_en"] or ""),
                    body_es=str(row["body_es"]) if row["body_es"] is not None else None,
                    aliases=aliases,
                    resolved_from=resolved_from,
                )
            finally:
                if conn is not self._memory_conn:
                    conn.close()

    def suggest(self, prefix: str, limit: int = 12) -> list[str]:
        """Returns canonical tag names matching a prefix (or alias prefix), ordered by post_count."""
        norm = normalize_dict_query(prefix)
        if not norm:
            self.ensure_initialized()
            with self._lock:
                conn = self._connect()
                try:
                    rows = conn.execute(
                        "SELECT name FROM tags ORDER BY post_count DESC, name ASC LIMIT ?",
                        (max(1, min(limit, 50)),),
                    ).fetchall()
                    return [str(r["name"]) for r in rows]
                finally:
                    if conn is not self._memory_conn:
                        conn.close()

        escaped = norm.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"{escaped}%"
        self.ensure_initialized()
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT DISTINCT t.name, t.post_count
                    FROM tags t
                    LEFT JOIN tag_aliases a ON a.consequent_name = t.name
                    WHERE t.name LIKE ? ESCAPE '\\' OR a.antecedent_name LIKE ? ESCAPE '\\'
                    ORDER BY t.post_count DESC, t.name ASC
                    LIMIT ?
                    """,
                    (pattern, pattern, max(1, min(limit, 50))),
                ).fetchall()
                return [str(r["name"]) for r in rows]
            finally:
                if conn is not self._memory_conn:
                    conn.close()

    def lookup_categories_batch(self, tags: Sequence[str]) -> dict[str, TagCategory]:
        """Resolves known tag categories in bulk for flat-tag adapters (DAPI/Moebooru)."""
        cleaned_map: dict[str, str] = {}
        for raw in tags:
            norm = normalize_dict_query(raw)
            if norm:
                cleaned_map[norm] = raw
        if not cleaned_map:
            return {}

        self.ensure_initialized()
        unique_norms = list(cleaned_map.keys())
        placeholders = ",".join("?" for _ in unique_norms)
        result: dict[str, TagCategory] = {}

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"SELECT name, category FROM tags WHERE name IN ({placeholders})",
                    unique_norms,
                ).fetchall()
                for r in rows:
                    name = str(r["name"])
                    raw_cat = str(r["category"])
                    if raw_cat in VALID_TAG_CATEGORIES:
                        result[name] = cast(TagCategory, raw_cat)

                remaining = [n for n in unique_norms if n not in result]
                if remaining:
                    rem_ph = ",".join("?" for _ in remaining)
                    alias_rows = conn.execute(
                        f"""
                        SELECT a.antecedent_name, t.category
                        FROM tag_aliases a
                        JOIN tags t ON t.name = a.consequent_name
                        WHERE a.antecedent_name IN ({rem_ph})
                        """,
                        remaining,
                    ).fetchall()
                    for r in alias_rows:
                        ant = str(r["antecedent_name"])
                        raw_cat = str(r["category"])
                        if raw_cat in VALID_TAG_CATEGORIES:
                            result[ant] = cast(TagCategory, raw_cat)
            finally:
                if conn is not self._memory_conn:
                    conn.close()

        return result

    def count(self) -> tuple[int, int]:
        """Returns `(tag_count, alias_count)` stored in the local catalog."""
        self.ensure_initialized()
        with self._lock:
            conn = self._connect()
            try:
                t_row = conn.execute("SELECT COUNT(*) AS c FROM tags").fetchone()
                a_row = conn.execute("SELECT COUNT(*) AS c FROM tag_aliases").fetchone()
                return (
                    int(t_row["c"]) if t_row else 0,
                    int(a_row["c"]) if a_row else 0,
                )
            finally:
                if conn is not self._memory_conn:
                    conn.close()


_default_service: TagDictionaryService | None = None
_service_lock = threading.Lock()


def get_tag_dictionary() -> TagDictionaryService:
    """Returns the process-wide singleton TagDictionaryService."""
    global _default_service
    with _service_lock:
        if _default_service is None:
            _default_service = TagDictionaryService()
        return _default_service
