"""Secrets survive keychain failures without resurrecting replaced credentials."""

import json
import os
import stat
from pathlib import Path

import pytest

from mentor.ports import SecretsUnavailable
from mentor.secrets import KeyringSecrets


class Keychain:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.failure: str | None = None

    def get_password(self, service: str, name: str) -> str | None:
        self._check("get")
        return self.values.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self._check("set")
        self.values[service, name] = value

    def delete_password(self, service: str, name: str) -> None:
        self._check("delete")
        self.values.pop((service, name), None)

    def _check(self, operation: str) -> None:
        if self.failure == operation:
            raise RuntimeError("locked, refused or missing backend; raw-secret-must-not-escape")


@pytest.fixture
def keychain(monkeypatch: pytest.MonkeyPatch) -> Keychain:
    import mentor.secrets

    backend = Keychain()
    monkeypatch.setattr(mentor.secrets, "keyring", backend)
    return backend


def test_keychain_success_and_restart_have_no_plaintext_file(tmp_path: Path, keychain: Keychain) -> None:
    secrets = KeyringSecrets(tmp_path)
    secrets.set("anthropic", "raw-secret")
    assert secrets.get("anthropic") == "raw-secret"
    assert KeyringSecrets(tmp_path).get("anthropic") == "raw-secret"
    assert "raw-secret" not in (tmp_path / "secrets.json").read_text()
    assert secrets.status.store == "keychain"
    assert secrets.status.fallback_reason is None


def test_write_failure_persists_private_file_and_safe_reason(tmp_path: Path, keychain: Keychain) -> None:
    keychain.failure = "set"
    secrets = KeyringSecrets(tmp_path)
    secrets.set("anthropic", "raw-secret")
    assert secrets.get("anthropic") == "raw-secret"
    path = tmp_path / "secrets.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())
    restarted = KeyringSecrets(tmp_path)
    assert restarted.get("anthropic") == "raw-secret"
    assert restarted.status.store == "file"
    assert restarted.status.fallback_reason
    assert "raw-secret" not in repr(restarted.status)
    assert "raw-secret" not in repr(secrets)


def test_replacement_never_revives_old_fallback_when_keychain_fails_again(tmp_path: Path, keychain: Keychain) -> None:
    secrets = KeyringSecrets(tmp_path)
    keychain.failure = "set"
    secrets.set("anthropic", "old")
    keychain.failure = None
    secrets.set("anthropic", "new")
    keychain.failure = "get"
    assert secrets.get("anthropic") == "new"
    assert KeyringSecrets(tmp_path).get("anthropic") == "new"


def test_fallback_replacement_wins_after_keychain_recovers(tmp_path: Path, keychain: Keychain) -> None:
    secrets = KeyringSecrets(tmp_path)
    secrets.set("anthropic", "old")
    keychain.failure = "set"
    secrets.set("anthropic", "new")
    keychain.failure = None
    assert KeyringSecrets(tmp_path).get("anthropic") == "new"


@pytest.mark.parametrize("failure", [None, "delete"])
def test_deletion_survives_restart_and_backend_recovery(tmp_path: Path, keychain: Keychain, failure: str | None) -> None:
    secrets = KeyringSecrets(tmp_path)
    secrets.set("anthropic", "old")
    keychain.failure = failure
    secrets.delete("anthropic")
    assert secrets.get("anthropic") is None
    keychain.failure = None
    assert KeyringSecrets(tmp_path).get("anthropic") is None
    if failure:
        assert secrets.status.store == "file"
        assert secrets.status.fallback_reason


def test_read_failure_caches_only_the_current_credential(tmp_path: Path, keychain: Keychain) -> None:
    secrets = KeyringSecrets(tmp_path)
    secrets.set("anthropic", "value")
    secrets = KeyringSecrets(tmp_path)
    assert secrets.get("anthropic") == "value"
    keychain.failure = "get"
    assert secrets.get("anthropic") == "value"
    assert secrets.status.store == "file"
    assert KeyringSecrets(tmp_path).get("anthropic") == "value"


def test_read_failure_without_copy_reports_unavailable_and_can_recover(tmp_path: Path, keychain: Keychain) -> None:
    KeyringSecrets(tmp_path).set("anthropic", "value")
    secrets = KeyringSecrets(tmp_path)
    keychain.failure = "get"
    with pytest.raises(SecretsUnavailable, match="keychain") as error:
        secrets.get("anthropic")
    assert "raw-secret" not in str(error.value)
    assert secrets.status.store == "file"
    keychain.failure = None
    assert secrets.get("anthropic") == "value"


def test_bad_journal_fails_closed_without_exposing_contents(tmp_path: Path, keychain: Keychain) -> None:
    (tmp_path / "secrets.json").write_text("raw-secret-not-json")
    with pytest.raises(SecretsUnavailable) as error:
        KeyringSecrets(tmp_path).get("anthropic")
    assert "raw-secret" not in str(error.value)


def test_separate_names_and_missing_deletion(tmp_path: Path, keychain: Keychain) -> None:
    secrets = KeyringSecrets(tmp_path)
    secrets.set("one", "first")
    secrets.set("two", "second")
    secrets.delete("missing")
    secrets.delete("one")
    assert secrets.get("one") is None
    assert secrets.get("two") == "second"


def test_deletion_of_fallback_does_not_restore_old_keychain_copy(tmp_path: Path, keychain: Keychain) -> None:
    secrets = KeyringSecrets(tmp_path)
    secrets.set("anthropic", "old")
    keychain.failure = "delete"
    secrets.set("anthropic", "new")
    assert secrets.status.store == "file"
    secrets.delete("anthropic")
    keychain.failure = None
    restarted = KeyringSecrets(tmp_path)
    assert restarted.get("anthropic") is None
    assert restarted.status.store == "file"
    assert restarted.status.fallback_reason


def test_failed_atomic_commit_keeps_previous_credential_and_safe_error(
    tmp_path: Path, keychain: Keychain, monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = KeyringSecrets(tmp_path)
    secrets.set("anthropic", "old")

    def fail_replace(source: str, destination: Path) -> None:
        raise PermissionError("raw-secret in filesystem error")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(SecretsUnavailable) as error:
        secrets.set("anthropic", "new")
    assert "raw-secret" not in str(error.value)
    assert KeyringSecrets(tmp_path).get("anthropic") == "old"
    assert not list(tmp_path.glob(".secrets-*"))


def test_temporary_cleanup_error_cannot_replace_safe_failure(
    tmp_path: Path, keychain: Keychain, monkeypatch: pytest.MonkeyPatch,
) -> None:
    keychain.failure = "set"

    def fail_replace(source: str, destination: Path) -> None:
        raise PermissionError("raw-secret in replacement error")

    def fail_unlink(path: Path, missing_ok: bool = False) -> None:
        raise PermissionError("raw-secret in cleanup error")

    monkeypatch.setattr(os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(SecretsUnavailable) as error:
        KeyringSecrets(tmp_path).set("anthropic", "raw-secret")
    assert "raw-secret" not in str(error.value)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in tmp_path.glob(".secrets-*"))


def test_private_file_failure_cannot_fall_through_to_keychain(
    tmp_path: Path, keychain: Keychain, monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = KeyringSecrets(tmp_path)
    secrets.set("anthropic", "key")

    def fail_read(path: Path) -> str:
        raise PermissionError("raw-secret in filesystem error")

    monkeypatch.setattr(Path, "read_text", fail_read)
    with pytest.raises(SecretsUnavailable) as error:
        secrets.get("anthropic")
    assert "raw-secret" not in str(error.value)


def test_fake_representation_redacts_credentials() -> None:
    from mentor.fakes import FakeSecrets

    secrets = FakeSecrets()
    secrets.set("anthropic", "raw-secret")
    assert secrets.get("anthropic") == "raw-secret"
    assert "raw-secret" not in repr(secrets)
    secrets.delete("anthropic")
    assert secrets.get("anthropic") is None
