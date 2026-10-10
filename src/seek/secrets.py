"""Keychain credentials with durable, private routing to a fallback file.

Each replacement uses a new keychain account. An atomic journal write commits which
account (or file value) is current; a failed backend or an old copy can never undo it.
Successful keychain storage keeps only account identifiers in the journal.
"""

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal, TypedDict, cast

import keyring

from seek.ports import SecretStoreStatus, SecretsUnavailable


class _Entry(TypedDict):
    store: Literal["keychain", "file", "deleted"]
    account: str | None
    value: str | None
    reason: str | None


class KeyringSecrets:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "secrets.json"
        self._status = SecretStoreStatus("keychain")
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def status(self) -> SecretStoreStatus:
        return self._status

    def _fallback(self, operation: str) -> str:
        reason = f"The operating system keychain could not {operation} credentials. Using the private fallback file."
        self._status = SecretStoreStatus("file", reason)
        return reason

    def _read(self) -> dict[str, _Entry]:
        try:
            content = self._path.read_text()
        except FileNotFoundError:
            return {}
        except OSError:
            raise SecretsUnavailable("The private credential file could not be read.") from None
        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError
            for name, entry in data.items():
                if not isinstance(name, str) or not isinstance(entry, dict):
                    raise ValueError
                if set(entry) != {"store", "account", "value", "reason"}:
                    raise ValueError
                if entry["store"] not in ("keychain", "file", "deleted"):
                    raise ValueError
                if any(entry[key] is not None and not isinstance(entry[key], str) for key in ("account", "value", "reason")):
                    raise ValueError
                if entry["store"] == "keychain" and (not entry["account"] or entry["value"] is not None):
                    raise ValueError
                if entry["store"] == "file" and entry["value"] is None:
                    raise ValueError
                if entry["store"] == "deleted" and entry["value"] is not None:
                    raise ValueError
            return cast(dict[str, _Entry], data)
        except (ValueError, TypeError):
            raise SecretsUnavailable("The private credential file is damaged and could not be read.") from None

    def _write(self, entries: dict[str, _Entry]) -> None:
        temporary: str | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".secrets-", dir=self._path.parent)
            with os.fdopen(descriptor, "w") as stream:
                # mkstemp already creates mode 0600, including while the file is being written.
                json.dump(entries, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except OSError:
            raise SecretsUnavailable("The private credential file could not be saved.") from None
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    # Preserve the safe error above. A leftover temporary file is still owner-only.
                    pass

    def get(self, name: str) -> str | None:
        with self._lock:
            entries = self._read()
            entry = entries.get(name)
            if entry is None:
                return None
            if entry["store"] in ("file", "deleted"):
                if entry["store"] == "file" or entry["reason"] is not None:
                    # Do not expose arbitrary journal text through diagnostics.
                    self._fallback("access")
                return entry["value"]
            account = entry["account"]
            assert account is not None
            try:
                value = keyring.get_password("seek", account)
            except Exception:
                value = self._cache.get(account)
                if value is None:
                    reason = (
                        "The keychain credential is unavailable and no fallback copy exists. Unlock the keychain or replace the key."
                    )
                    self._status = SecretStoreStatus("keychain", reason)
                    raise SecretsUnavailable(reason) from None
                reason = self._fallback("read")
                entries[name] = _Entry(store="file", account=account, value=value, reason=reason)
                self._write(entries)
                return value
            self._status = SecretStoreStatus("keychain")
            if value is not None:
                self._cache[account] = value
            else:
                self._cache.pop(account, None)
            return value

    def set(self, name: str, value: str) -> None:
        with self._lock:
            entries = self._read()
            old = entries.get(name)
            account = f"{name}:{uuid.uuid4().hex}"
            try:
                keyring.set_password("seek", account, value)
            except Exception:
                entry = _Entry(store="file", account=None, value=value, reason=self._fallback("write"))
            else:
                entry = _Entry(store="keychain", account=account, value=None, reason=None)
            entries[name] = entry
            self._write(entries)
            self._cache.clear()
            if entry["store"] == "keychain":
                self._cache[account] = value
                self._status = SecretStoreStatus("keychain")
            if old is not None and old["account"] is not None:
                try:
                    keyring.delete_password("seek", old["account"])
                except Exception:
                    # The new credential is already committed. Keep it current if cleanup is refused.
                    entry["reason"] = self._fallback("delete")
                    entry["store"] = "file"
                    entry["value"] = value
                    self._write(entries)

    def delete(self, name: str) -> None:
        with self._lock:
            entries = self._read()
            old = entries.get(name)
            # Commit the tombstone before touching the backend: even a refused deletion stays deleted.
            reason = old["reason"] if old is not None else None
            entries[name] = _Entry(store="deleted", account=None, value=None, reason=reason)
            self._write(entries)
            self._cache.clear()
            if reason is not None:
                self._fallback("access")
            if old is not None and old["account"] is not None:
                try:
                    keyring.delete_password("seek", old["account"])
                except Exception:
                    entries[name]["reason"] = self._fallback("delete")
                    self._write(entries)
