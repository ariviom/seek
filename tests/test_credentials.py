import json
from pathlib import Path

import httpx2
import pytest
from harness import running

from mentor.app import create_app
from mentor.config import Config
from mentor.credentials import Credentials, CredentialStatus
from mentor.events import Events
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeSecrets, FakeTranscriptSource

# Where a status says the key is kept, when the keychain took it.
IN_KEYCHAIN = {"store": "keychain", "fallback_reason": None}


async def test_key_is_validated_once_without_environment_credentials_and_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx2.Request] = []

    async def send(client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: object) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"data": [], "has_more": False, "first_id": None, "last_id": None}, request=request)

    monkeypatch.setattr(httpx2.AsyncClient, "send", send)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "environment-must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "environment-token-must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://wrong.example")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "x-api-key: environment-key\nAuthorization: Bearer environment-token")
    secrets = FakeSecrets()
    config = Config(data_dir=tmp_path)
    for first in (True, False):
        app = create_app(config, FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=secrets)
        async with running(app) as client:
            if first:
                assert (await client.get("/api/credentials/anthropic")).json()["present"] is False
                response = await client.put("/api/credentials/anthropic", json={"key": "stored-secret"})
                assert response.status_code == 200
                assert response.json()["validity"] == "valid"
                assert "stored-secret" not in response.text
            status = (await client.get("/api/credentials/anthropic")).json()
            assert status["present"] is True
            assert status["validity"] == "valid"
            await client.get("/api/health")
            assert "stored-secret" not in json.dumps(status)
    assert len(requests) == 1
    assert requests[0].headers["x-api-key"] == "stored-secret"
    assert "authorization" not in requests[0].headers
    assert str(requests[0].url) == "https://api.anthropic.com/v1/models?limit=1"


@pytest.mark.parametrize("code,validity", [(401, "invalid"), (403, "unverified"), (429, "unverified"), (500, "unverified")])
async def test_provider_failure_does_not_echo_key_or_mislabel_transient_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, code: int, validity: str,
) -> None:
    caplog.set_level("DEBUG")
    key = "sk-ant-private-provider-echo"
    calls = 0

    async def send(client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: object) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(code, json={"type": "error", "error": {"type": "authentication_error", "message": key}}, request=request)

    monkeypatch.setattr(httpx2.AsyncClient, "send", send)
    app = create_app(Config(data_dir=tmp_path), FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=FakeSecrets())
    async with running(app) as client:
        response = await client.put("/api/credentials/anthropic", json={"key": key})
        assert response.status_code == 200
        assert response.json() == {"present": True, "validity": validity, **IN_KEYCHAIN}
        assert key not in response.text
        assert (await client.get("/api/credentials/anthropic")).json() == response.json()
    assert calls == 1
    assert key not in caplog.text


@pytest.mark.parametrize("body", [b'{"key":"private-secret",', b'{"key":["private-secret"]}', b'{"key":"private-secret","extra":"private-secret"}', b'{"private-secret":42}', b'{"key":""}'])
async def test_key_validation_errors_never_echo_submitted_input(tmp_path: Path, body: bytes) -> None:
    app = create_app(Config(data_dir=tmp_path), FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=FakeSecrets())
    async with running(app) as client:
        response = await client.put("/api/credentials/anthropic", content=body)
        assert response.status_code == 422
        assert "private-secret" not in response.text
        assert (await client.get("/api/credentials/anthropic")).json()["present"] is False


async def test_network_failure_is_unverified_and_never_logs_provider_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")

    async def send(client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: object) -> httpx2.Response:
        raise httpx2.ConnectError("provider echoed private-secret", request=request)

    monkeypatch.setattr(httpx2.AsyncClient, "send", send)
    app = create_app(Config(data_dir=tmp_path), FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=FakeSecrets())
    async with running(app) as client:
        response = await client.put("/api/credentials/anthropic", json={"key": "private-secret"})
        assert response.json() == {"present": True, "validity": "unverified", **IN_KEYCHAIN}
    assert "private-secret" not in caplog.text


@pytest.mark.parametrize("replacement", [True, False])
async def test_late_validation_and_turn_rejections_cannot_overwrite_replacement_or_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: bool,
) -> None:
    import asyncio
    from mentor.credentials import Credentials
    from harness import event_stream

    entered, release = asyncio.Event(), asyncio.Event()

    async def send(client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: object) -> httpx2.Response:
        if request.headers["x-api-key"] == "old-secret":
            entered.set()
            await release.wait()
            return httpx2.Response(401, json={"error": {"message": "rejected"}}, request=request)
        return httpx2.Response(200, json={"data": [], "has_more": False}, request=request)

    monkeypatch.setattr(httpx2.AsyncClient, "send", send)
    store = FakeSecrets()
    app = create_app(Config(data_dir=tmp_path), FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=store)
    credentials: Credentials = app.state.credentials
    async with running(app) as client, event_stream(app) as stream:
        old_request = asyncio.create_task(client.put("/api/credentials/anthropic", json={"key": "old-secret"}))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            old = await credentials.current()
            assert old is not None
            assert "old-secret" not in repr(old)
            if replacement:
                response = await client.put("/api/credentials/anthropic", json={"key": "new-secret"})
                expected = {"present": True, "validity": "valid", **IN_KEYCHAIN}
            else:
                response = await client.delete("/api/credentials/anthropic")
                expected = {"present": False, "validity": "unverified", **IN_KEYCHAIN}
            assert response.json() == expected
            release.set()
            assert (await old_request).json() == expected
            await credentials.invalidate(old.generation)
            assert (await client.get("/api/credentials/anthropic")).json() == expected
            emitted = await stream.until(lambda e: e["type"] == "credentials")
            assert "secret" not in json.dumps(emitted)
            if replacement:
                current = await credentials.current()
                assert current is not None
                await credentials.invalidate(current.generation)
                assert (await client.get("/api/credentials/anthropic")).json()["validity"] == "invalid"
        finally:
            release.set()
            await old_request
    async with running(create_app(Config(data_dir=tmp_path), FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=store)) as client:
        state = (await client.get("/api/credentials/anthropic")).json()
        assert state == ({"present": True, "validity": "invalid", **IN_KEYCHAIN} if replacement else expected)


async def test_canceled_key_write_cannot_complete_after_a_later_deletion(tmp_path: Path) -> None:
    import asyncio
    from harness import Gate, event_stream

    gate = Gate()

    class SlowSecrets(FakeSecrets):
        def set(self, name: str, value: str) -> None:
            gate()
            super().set(name, value)

    app = create_app(Config(data_dir=tmp_path), FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=SlowSecrets())
    async with running(app) as client, event_stream(app) as stream:
        write = asyncio.create_task(client.put("/api/credentials/anthropic", json={"key": "private-secret"}))
        try:
            await gate.wait_entered()
            write.cancel()
            with pytest.raises(asyncio.CancelledError):
                await write
            deletion = asyncio.create_task(client.delete("/api/credentials/anthropic"))
        finally:
            gate.released.set()
        assert (await deletion).json() == {"present": False, "validity": "unverified", **IN_KEYCHAIN}
        assert (await client.get("/api/credentials/anthropic")).json()["present"] is False
        assert (await stream.until(lambda e: e["type"] == "credentials"))[-1] == {"type": "credentials"}


async def test_locked_keychain_after_restart_allows_safe_replacement_and_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import keyring
    from keyring.errors import KeyringLocked
    from mentor.secrets import KeyringSecrets

    values: dict[str, str] = {}
    locked = False

    def get(service: str, account: str) -> str | None:
        if locked:
            raise KeyringLocked("private-secret")
        return values.get(account)

    def set_key(service: str, account: str, value: str) -> None:
        if locked:
            raise KeyringLocked("private-secret")
        values[account] = value

    def delete(service: str, account: str) -> None:
        if locked:
            raise KeyringLocked("private-secret")
        values.pop(account, None)

    async def send(client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: object) -> httpx2.Response:
        return httpx2.Response(200, json={"data": [], "has_more": False}, request=request)

    monkeypatch.setattr(keyring, "get_password", get)
    monkeypatch.setattr(keyring, "set_password", set_key)
    monkeypatch.setattr(keyring, "delete_password", delete)
    monkeypatch.setattr(httpx2.AsyncClient, "send", send)

    config = Config(data_dir=tmp_path)
    first = create_app(config, FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=KeyringSecrets(tmp_path))
    async with running(first) as client:
        assert (await client.put("/api/credentials/anthropic", json={"key": "private-secret"})).json()["validity"] == "valid"
    assert "private-secret" not in (tmp_path / "secrets.json").read_text()
    locked = True
    second = create_app(config, FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=KeyringSecrets(tmp_path))
    async with running(second) as client:
        failed = await client.get("/api/credentials/anthropic")
        assert failed.status_code == 503
        assert "private-secret" not in failed.text
        assert (await client.get("/api/health")).status_code == 200
        replacement = await client.put("/api/credentials/anthropic", json={"key": "replacement-secret"})
        # The key went to the private file because the keychain refused it, and the status says so rather
        # than reading as if the keychain had it.
        assert replacement.json() == {
            "present": True,
            "validity": "valid",
            "store": "file",
            "fallback_reason": "The operating system keychain could not write credentials. "
            "Using the private fallback file.",
        }
        assert "replacement-secret" not in replacement.text
    third = create_app(config, FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=KeyringSecrets(tmp_path))
    async with running(third) as client:
        assert (await client.get("/api/credentials/anthropic")).json()["validity"] == "valid"
        assert (await client.delete("/api/credentials/anthropic")).json()["present"] is False
    locked = False
    final = create_app(config, FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), secrets=KeyringSecrets(tmp_path))
    async with running(final) as client:
        assert (await client.get("/api/credentials/anthropic")).json()["present"] is False


async def test_a_turns_late_rejection_cannot_undo_a_replacement_or_a_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn holds the credential it started with. By the time the provider rejects it, the user may have
    replaced or deleted it, and that newer decision wins."""

    async def accept(client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: object) -> httpx2.Response:
        return httpx2.Response(
            200, json={"data": [], "has_more": False, "first_id": None, "last_id": None}, request=request
        )

    monkeypatch.setattr(httpx2.AsyncClient, "send", accept)
    secrets = FakeSecrets()
    credentials = Credentials(secrets, Events())

    await credentials.replace("key-a")
    turn = await credentials.current()
    assert turn is not None
    await credentials.replace("key-b")
    after_replacement = await credentials.invalidate(turn.generation)
    await credentials.delete()
    after_deletion = await credentials.invalidate(turn.generation)

    # Key B was validated on its own terms and keeps that, and the deletion stays deleted.
    assert after_replacement == CredentialStatus(present=True, validity="valid")
    assert after_deletion == CredentialStatus(present=False, validity="unverified")
    assert secrets.values == {}
