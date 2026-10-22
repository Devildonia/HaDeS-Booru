"""
Persistent Configuration Manager for HaDeS Booru.
Provides thread-safe (RLock) atomic writes, automatic backup on corrupt files,
file permission hardening (0600), and optional session-only credential storage.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

import filelock

from hades_booru.models import AppConfig, SourceCredential

logger = logging.getLogger(__name__)

CONFIG_FILE_PATH = Path("config.local.json")

# v1.1.0 (audit R7): shared cap for the persisted search history so a union of two
# instances' histories in _merge_with_disk() cannot double it. state.py imports it.
MAX_SEARCH_HISTORY = 12


class ConfigManager:
    """Thread-safe local JSON configuration manager with atomic persistence."""

    def __init__(self, config_path: Path = CONFIG_FILE_PATH) -> None:
        self._lock = threading.RLock()
        self._path = config_path
        self._session_credentials: dict[str, SourceCredential] = {}
        # R7-01: sources this process explicitly set (non-empty) at least once. Lets
        # save() distinguish "this process cleared it" (wipe, N5) from "this process
        # never had it; another instance persisted it" (keep the disk value).
        self._creds_touched: set[str] = set()
        self.last_error: str | None = None
        self.config: AppConfig = self._load()
        # Audit R6-07: snapshot of the state at load time; save() uses it to tell
        # which fields this process actually changed before merging with the disk.
        self._loaded_snapshot: dict = self.config.model_dump(mode="json")
        # Credential snapshot at load time: lets save() tell "this process explicitly
        # cleared these" (snapshot had a value) from "another instance persisted them
        # and this one never touched them" (snapshot empty -> keep the disk value).
        self._loaded_creds_snapshot: dict[str, SourceCredential] = {
            k: SourceCredential(user_id=v.user_id, api_key=v.api_key)
            for k, v in self._session_credentials.items()
        }

    def _merge_with_disk(self, disk: dict | None, mine: dict) -> dict:
        """Audit R6-07 + R7-B: 3-way field-level merge (base=snapshot at load, mine, disk).

        Per field:
        - untouched by this process (mine == snapshot): the disk value wins —
          another instance may have updated it (a normal case since the port
          auto-fallback made multi-instance runs common);
        - changed by this process (mine != snapshot): mine wins — including
          clearing a list to ``[]`` or removing individual items. The old
          unconditional union logic resurrected cleared/removed entries (audit
          R7-B cases 2b and 3); the old snapshot comparison also made scalars
          unable to revert back to their loaded value (cases 1b/1c). The snapshot
          is now refreshed after every successful save(), re-basing the merge;
        - lists this process only APPENDED to (snapshot ⊆ mine) keep the union so
          entries another instance added in the meantime survive (R6-07
          cross-instance safety).
        """
        if not isinstance(disk, dict):
            return mine
        snapshot = self._loaded_snapshot or {}
        merged: dict = {}
        for key in set(disk) | set(mine):
            if key not in mine:
                merged[key] = disk[key]
                continue
            if key not in disk:
                merged[key] = mine[key]
                continue
            my_val = mine[key]
            disk_val = disk[key]
            base_val = snapshot.get(key, my_val)
            if my_val == base_val:
                merged[key] = disk_val
                continue
            if isinstance(my_val, list) and isinstance(disk_val, list):
                base_set = {str(x) for x in base_val} if isinstance(base_val, list) else set()
                mine_set = {str(x) for x in my_val}
                if base_set.issubset(mine_set):
                    # This process only appended: union so another instance's new
                    # entries survive; most-recent-first order of this process wins.
                    seen: list = []
                    for item in list(my_val) + list(disk_val):
                        s = str(item)
                        if s not in seen:
                            seen.append(s)
                    if key == "search_history":
                        # Cap the union; this process's most-recent entries come
                        # first, so its recency wins.
                        seen = seen[:MAX_SEARCH_HISTORY]
                    merged[key] = seen
                    continue
            merged[key] = my_val
        return merged

    def _load(self) -> AppConfig:
        with self._lock:
            if not self._path.exists():
                cfg = AppConfig()
                self._session_credentials = {
                    k: SourceCredential(user_id=v.user_id, api_key=v.api_key)
                    for k, v in cfg.credentials.items()
                }
                return cfg
            try:
                raw = self._path.read_text(encoding="utf-8")
                data = json.loads(raw)
                cfg = AppConfig.model_validate(data)
                self._session_credentials = {
                    k: SourceCredential(user_id=v.user_id, api_key=v.api_key)
                    for k, v in cfg.credentials.items()
                }
                return cfg
            except Exception as err:
                ts = int(time.time())
                backup_path = self._path.with_name(f"{self._path.name}.bak-{ts}")
                try:
                    shutil.copy2(self._path, backup_path)
                    logger.warning(
                        "Corrupt configuration file %s backed up to %s (%s)",
                        self._path,
                        backup_path,
                        err,
                    )
                except OSError as copy_err:
                    logger.error(
                        "Failed to back up corrupt configuration %s: %s",
                        self._path,
                        copy_err,
                    )
                self.last_error = f"Invalid configuration backed up to {backup_path.name}: {err}"
                cfg = AppConfig()
                self._session_credentials = {
                    k: SourceCredential(user_id=v.user_id, api_key=v.api_key)
                    for k, v in cfg.credentials.items()
                }
                return cfg

    def save(self) -> bool:
        """Atomically persists current configuration to disk using a temp file and os.replace.

        Audit R6-07: the write is serialized with a cross-process file lock and the
        on-disk state is merged in, so a second running instance (common now that the
        launcher auto-picks a free port) cannot silently clobber the first one's
        history/blacklist/language changes.
        """
        with self._lock:
            tmp_path = self._path.with_name(f"{self._path.name}.tmp.{os.getpid()}")
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with filelock.FileLock(f"{self._path}.lock"):
                    disk_payload = None
                    try:
                        disk_payload = json.loads(self._path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        disk_payload = None

                    payload = self._merge_with_disk(disk_payload, self.config.model_dump(mode="json"))

                    # Merge credentials (audit R6-07 + R7-01 + R7-B):
                    # persist=True: - entry this process set (has a value) -> wins;
                    #              - entry this process set and then cleared -> wiped (N5);
                    #              - entry this process had at load and now empty -> wiped (N5);
                    #              - entry this process never had and never touched -> keep
                    #                the value another instance persisted (no cross-instance wipe);
                    #              - entry unknown to this process (added by another instance
                    #                after load) -> keep the disk value.
                    # persist=False (R7-01/R7-03): only entries THIS process explicitly
                    # set or cleared (touched) are wiped; credentials merely loaded from
                    # disk by this process, or persisted by another instance, are kept.
                    if self.config.persist_credentials:
                        raw_disk_creds = payload.get("credentials")
                    else:
                        raw_disk_creds = (disk_payload or {}).get("credentials")
                    disk_creds = raw_disk_creds if isinstance(raw_disk_creds, dict) else {}
                    merged_creds: dict[str, dict[str, str]] = {}
                    for k in set(self._session_credentials) | set(disk_creds):
                        sc = self._session_credentials.get(k)
                        disk_entry = self._normalize_creds_entry(disk_creds.get(k))
                        snap = self._loaded_creds_snapshot.get(k)
                        snap_had_value = bool(snap and (snap.user_id or snap.api_key))
                        if not self.config.persist_credentials:
                            # Session-only mode: wipe what this process touched, keep the rest.
                            merged_creds[k] = (
                                {"user_id": "", "api_key": ""}
                                if k in self._creds_touched
                                else dict(disk_entry)
                            )
                        elif sc is not None and (sc.user_id or sc.api_key):
                            merged_creds[k] = {"user_id": sc.user_id, "api_key": sc.api_key}
                        elif sc is None:
                            merged_creds[k] = dict(disk_entry)
                        elif k in self._creds_touched or snap_had_value:
                            # Explicitly cleared by this process (N5 contract).
                            merged_creds[k] = {"user_id": "", "api_key": ""}
                        else:
                            # Loaded empty and never touched: another instance persisted it
                            # -> keep the disk value (R7-01).
                            merged_creds[k] = dict(disk_entry)
                    payload["credentials"] = merged_creds

                    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
                    tmp_path.write_text(serialized, encoding="utf-8")
                    try:
                        os.chmod(tmp_path, 0o600)
                    except OSError:
                        pass
                    os.replace(tmp_path, self._path)
                    try:
                        os.chmod(self._path, 0o600)
                    except OSError:
                        pass
                    # Audit R7-B: re-base the 3-way merge on what is now actually on
                    # disk. Without this, a value changed and then reverted to its
                    # loaded value would be indistinguishable from "untouched" and
                    # the stale disk value would resurrect (cases 1b/1c/2b).
                    # deepcopy: the snapshot must not alias live config lists.
                    self._loaded_snapshot = copy.deepcopy(payload)
                self.last_error = None
                return True
            except OSError as err:
                self.last_error = str(err)
                logger.error("Failed to save configuration to %s: %s", self._path, err)
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
                return False

    @staticmethod
    def _normalize_creds_entry(raw: object) -> dict[str, str]:
        if isinstance(raw, dict):
            return {
                "user_id": str(raw.get("user_id") or ""),
                "api_key": str(raw.get("api_key") or ""),
            }
        return {"user_id": "", "api_key": ""}

    def get_credentials(self, source_id: str) -> SourceCredential:
        """Retrieves active credentials for a given source ID (from session memory)."""
        with self._lock:
            return self._session_credentials.get(
                source_id,
                self.config.credentials.get(source_id, SourceCredential()),
            )

    def set_credentials(
        self,
        source_id: str,
        user_id: str,
        api_key: str,
        persist_to_disk: bool | None = None,
    ) -> bool:
        """Updates credentials for a single source and persists once."""
        return self.set_credentials_many(
            {source_id: (user_id, api_key)},
            persist_to_disk=persist_to_disk,
        )

    def set_credentials_many(
        self,
        credentials_map: dict[str, tuple[str, str]],
        persist_to_disk: bool | None = None,
    ) -> bool:
        """Updates multiple source credentials in session memory and executes a single atomic save()."""
        with self._lock:
            if persist_to_disk is not None:
                self.config.persist_credentials = persist_to_disk

            for source_id, (user_id, api_key) in credentials_map.items():
                clean_user = user_id.strip()
                clean_key = api_key.strip()
                # The UI intentionally does NOT prefill saved credentials into the form.
                # An empty pair therefore means "unchanged" and must never wipe the
                # previously saved credentials for that source.
                if not clean_user and not clean_key:
                    continue
                cred = SourceCredential(
                    user_id=clean_user,
                    api_key=clean_key,
                )
                self._session_credentials[source_id] = cred
                self._creds_touched.add(source_id)
                if self.config.persist_credentials:
                    self.config.credentials[source_id] = cred
                else:
                    self.config.credentials[source_id] = SourceCredential()

            return self.save()

    def clear_credentials(self) -> bool:
        """Clears all saved API credentials from both session memory and disk (N5).

        Only sources this process knows about are wiped (N5). Sources another
        instance added to disk after this process loaded are left untouched — the
        safe direction for multi-instance setups (audit R7-01/R7-03).
        """
        with self._lock:
            self._creds_touched.update(self.config.credentials.keys())
            self._session_credentials = {
                k: SourceCredential() for k in self.config.credentials
            }
            self.config.credentials = {
                k: SourceCredential() for k in self.config.credentials
            }
            return self.save()


config_manager = ConfigManager()
