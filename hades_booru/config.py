"""
Persistent Configuration Manager for HaDeS Booru.
Provides thread-safe (RLock) atomic writes, automatic backup on corrupt files,
file permission hardening (0600), and optional session-only credential storage.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from hades_booru.models import AppConfig, SourceCredential

logger = logging.getLogger(__name__)

CONFIG_FILE_PATH = Path("config.local.json")


class ConfigManager:
    """Thread-safe local JSON configuration manager with atomic persistence."""

    def __init__(self, config_path: Path = CONFIG_FILE_PATH) -> None:
        self._lock = threading.RLock()
        self._path = config_path
        self._session_credentials: dict[str, SourceCredential] = {}
        self.last_error: str | None = None
        self.config: AppConfig = self._load()

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
        """Atomically persists current configuration to disk using a temp file and os.replace."""
        with self._lock:
            tmp_path = self._path.with_name(f"{self._path.name}.tmp.{os.getpid()}")
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                payload = self.config.model_dump(mode="json")

                if not self.config.persist_credentials:
                    payload["credentials"] = {
                        k: {"user_id": "", "api_key": ""}
                        for k in self.config.credentials
                    }
                else:
                    payload["credentials"] = {
                        k: {"user_id": v.user_id, "api_key": v.api_key}
                        for k, v in self._session_credentials.items()
                    }

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
                if self.config.persist_credentials:
                    self.config.credentials[source_id] = cred
                else:
                    self.config.credentials[source_id] = SourceCredential()

            return self.save()


config_manager = ConfigManager()
