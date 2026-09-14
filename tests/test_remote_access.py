import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from harness import event_stream, running
from jwt.algorithms import RSAAlgorithm

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource

# What a reverse proxy publishing mentor at https://mentor.example.com/mentor/ adds, with the prefix stripped.
PROXIED = {
    "X-Forwarded-For": "203.0.113.7",
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": "mentor.example.com",
    "X-Forwarded-Prefix": "/mentor",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}


@pytest.fixture
def published(config: Config) -> Config:
    return replace(config, allowed_hosts=("mentor.example.com",))


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    static = tmp_path / "bundle"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(
        '<!doctype html>\n<html>\n  <head>\n    <script src="./assets/app.js"></script>\n  </head>\n</html>\n'
    )
    (static / "assets" / "app.js").write_text("console.log('mentor')\n")
    return static


def app_for(config: Config, static_dir: Path, events_keepalive_seconds: float = 15.0) -> FastAPI:
    return create_app(
        config,
        FakeTranscriptSource(),
        FakeEmbedder(),
        FakeReranker(),
        FakeChatEngine(),
        static_dir=static_dir,
        events_keepalive_seconds=events_keepalive_seconds,
    )


async def test_the_api_and_redirects_follow_the_public_url_whether_or_not_the_proxy_strips_the_prefix(
    published: Config, tmp_path: Path
) -> None:
    async with running(app_for(published, tmp_path / "no-bundle")) as client:
        stripped = await client.get("/api/syncs", headers=PROXIED)
        unstripped = await client.get("/mentor/api/syncs", headers=PROXIED)
        redirect = await client.get("/api/syncs/", headers=PROXIED)
        unstripped_redirect = await client.get("/mentor/api/syncs/", headers=PROXIED)
        local_redirect = await client.get("/api/syncs/")

    assert (stripped.status_code, stripped.json()) == (200, [])
    assert (unstripped.status_code, unstripped.json()) == (200, [])
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://mentor.example.com/mentor/api/syncs"
    assert unstripped_redirect.headers["location"] == "https://mentor.example.com/mentor/api/syncs"
    assert local_redirect.headers["location"] == "http://127.0.0.1:7337/api/syncs"


async def test_the_web_ui_resolves_its_assets_and_api_under_the_prefix_even_without_a_trailing_slash(
    published: Config, bundle: Path
) -> None:
    async with running(app_for(published, bundle)) as client:
        proxied = await client.get("/", headers=PROXIED)
        local = await client.get("/")
        asset = await client.get("/assets/app.js", headers=PROXIED)
        unstripped_asset = await client.get("/mentor/assets/app.js", headers=PROXIED)
        unstripped_root = await client.get("/mentor", headers=PROXIED)

    assert proxied.status_code == 200
    assert '<head>\n    <base href="/mentor/">' in proxied.text
    assert '<script src="./assets/app.js"></script>' in proxied.text
    assert '<base href="/">' in local.text
    assert asset.text == unstripped_asset.text == "console.log('mentor')\n"
    assert unstripped_root.headers["location"] == "https://mentor.example.com/mentor/"


async def test_the_mcp_endpoint_answers_under_the_prefix(published: Config, tmp_path: Path) -> None:
    async with running(app_for(published, tmp_path / "no-bundle")) as client:
        stripped = await client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS | PROXIED)
        unstripped = await client.post("/mentor/mcp", json=INITIALIZE, headers=MCP_HEADERS | PROXIED)

    assert stripped.status_code == 200, stripped.text
    assert unstripped.status_code == 200, unstripped.text


async def test_the_event_stream_keeps_sending_keepalives_through_the_proxy(published: Config, tmp_path: Path) -> None:
    app = app_for(published, tmp_path / "no-bundle", events_keepalive_seconds=0.05)

    async with running(app), event_stream(app, "/mentor/api/events", PROXIED) as stream:
        await stream.wait_for_comments(2)

    assert stream.status == 200
    assert stream.headers["x-accel-buffering"] == "no"
    assert stream.headers["cache-control"] == "no-cache, no-transform"


async def test_requests_through_hosts_or_from_origins_not_allowed_are_refused(
    published: Config, tmp_path: Path
) -> None:
    async with running(app_for(published, tmp_path / "no-bundle")) as client:

        async def status(**headers: str) -> int:
            return (await client.post("/api/syncs", headers=headers)).status_code

        allowed = [
            await status(),
            await status(Host="localhost:5173", Origin="http://localhost:5173"),
            await status(**PROXIED, Origin="https://mentor.example.com"),
            await status(Host="mentor.example.com"),
        ]
        # DNS rebinding: a page on another site whose name resolves to this machine.
        refused = [
            await status(Host="attacker.example:7337"),
            await status(**(PROXIED | {"X-Forwarded-Host": "attacker.example"})),
            await status(Host="attacker.example:7337", **{"X-Forwarded-Host": "mentor.example.com"}),
            await status(Origin="https://attacker.example"),
            await status(Origin="null"),
        ]
        bad_prefixes = [
            (await client.get("/api/syncs", headers=PROXIED | {"X-Forwarded-Prefix": prefix})).status_code
            for prefix in ('/x"><script>', "/..", "/mentor/../api")
        ]

    assert allowed == [202, 202, 202, 202]
    assert refused == [421, 421, 421, 403, 403]
    assert bad_prefixes == [400, 400, 400]


# Cloudflare Access


TEAM_DOMAIN = "woodshop.cloudflareaccess.com"
AUDIENCE = "4714c1358e65fe4b408ad6d432a5f878"


class Certs:
    """The team's certs endpoint: signing keys by kid, and every fetch made."""

    def __init__(self) -> None:
        self.keys: dict[str, rsa.RSAPrivateKey] = {"key-1": new_key()}
        self.fetched: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.fetched.append(url)
        jwks = [
            json.loads(RSAAlgorithm.to_jwk(key.public_key())) | {"kid": kid, "alg": "RS256", "use": "sig"}
            for kid, key in self.keys.items()
        ]
        return json.dumps({"keys": jwks}).encode()

    def token(self, kid: str = "key-1", key: rsa.RSAPrivateKey | None = None, **claims: object) -> str:
        now = int(time.time())
        payload = {"aud": [AUDIENCE], "iss": f"https://{TEAM_DOMAIN}", "iat": now, "exp": now + 600} | claims
        return jwt.encode(payload, key or self.keys[kid], algorithm="RS256", headers={"kid": kid})


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def guarded_app(config: Config, certs: Certs, static_dir: Path, refetch_seconds: float = 60.0) -> FastAPI:
    return create_app(
        replace(config, cf_access_team_domain=TEAM_DOMAIN, cf_access_aud=AUDIENCE),
        FakeTranscriptSource(),
        FakeEmbedder(),
        FakeReranker(),
        FakeChatEngine(),
        static_dir=static_dir,
        events_keepalive_seconds=0.05,
        fetch_access_keys=certs,
        access_keys_refetch_seconds=refetch_seconds,
    )


def with_token(token: str) -> dict[str, str]:
    return PROXIED | {"Cf-Access-Jwt-Assertion": token, "Cf-Ray": "8a1b2c3d4e5f6071-SJC"}


async def test_with_access_configured_every_proxied_request_needs_a_valid_token(
    published: Config, bundle: Path
) -> None:
    certs = Certs()
    app = guarded_app(published, certs, bundle)
    valid = with_token(certs.token())

    async with running(app) as client:
        api = await client.get("/mentor/api/syncs", headers=valid)
        page = await client.get("/", headers=valid)
        mcp = await client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS | valid)
        async with event_stream(app, "/api/events", valid) as stream:
            await stream.wait_for_comments(1)
        refused = {
            name: await client.get("/api/syncs", headers=headers)
            for name, headers in {
                "missing": PROXIED,
                "forged": with_token(certs.token(key=new_key())),
                "expired": with_token(certs.token(exp=int(time.time()) - 60)),
                "other application": with_token(certs.token(aud=["another-application"])),
                "other team": with_token(certs.token(iss="https://elsewhere.cloudflareaccess.com")),
                "unknown key": with_token(certs.token(kid="key-9", key=new_key())),
                "garbage": with_token("not-a-token"),
            }.items()
        }
        refused_mcp = await client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS | PROXIED)
        refused_page = await client.get("/assets/app.js", headers=PROXIED)
        refused_stream = await client.get("/api/events", headers=with_token(certs.token(exp=int(time.time()) - 60)))

    assert [api.status_code, page.status_code, mcp.status_code, stream.status] == [200, 200, 200, 200]
    assert {name: r.status_code for name, r in refused.items()} == dict.fromkeys(refused, 403)
    assert "Cloudflare Access" in refused["missing"].json()["detail"]
    assert "expired" in refused["expired"].json()["detail"]
    assert [refused_mcp.status_code, refused_page.status_code, refused_stream.status_code] == [403, 403, 403]
    assert certs.fetched[0] == f"https://{TEAM_DOMAIN}/cdn-cgi/access/certs"


async def test_only_requests_made_directly_on_this_machine_go_without_a_token(
    published: Config, tmp_path: Path
) -> None:
    app = guarded_app(published, Certs(), tmp_path / "no-bundle")

    async with running(app) as local:
        direct = [
            (await local.get("/api/syncs")).status_code,
            (await local.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)).status_code,
        ]
        # A proxy on this machine connects from loopback too, but says so in its headers.
        relayed = [
            (await local.get("/api/syncs", headers={"X-Forwarded-For": "203.0.113.7"})).status_code,
            (await local.get("/api/syncs", headers={"Cf-Ray": "8a1b2c3d4e5f6071-SJC"})).status_code,
            (await local.get("/api/syncs", headers={"Forwarded": "for=203.0.113.7"})).status_code,
            (await local.get("/api/syncs", headers={"X-Real-IP": "203.0.113.7"})).status_code,
        ]
        transport = httpx.ASGITransport(app=app, client=("192.0.2.10", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7337") as remote:
            from_another_address = (await remote.get("/api/syncs")).status_code

    assert direct == [200, 200]
    assert relayed == [403, 403, 403, 403]
    assert from_another_address == 403


async def test_access_keys_are_cached_and_fetched_again_for_a_rotated_key(published: Config, tmp_path: Path) -> None:
    certs = Certs()

    async with running(guarded_app(published, certs, tmp_path / "no-bundle", refetch_seconds=0)) as client:
        first = await client.get("/api/syncs", headers=with_token(certs.token()))
        second = await client.get("/api/syncs", headers=with_token(certs.token()))
        fetches_before_rotation = len(certs.fetched)
        certs.keys["key-2"] = new_key()
        rotated = await client.get("/api/syncs", headers=with_token(certs.token("key-2")))

    async with running(guarded_app(published, certs, tmp_path / "no-bundle")) as client:
        await client.get("/api/syncs", headers=with_token(certs.token()))
        fetched = len(certs.fetched)
        for kid in ("forged-1", "forged-2", "forged-3"):
            await client.get("/api/syncs", headers=with_token(certs.token(kid, key=new_key())))
        forged_fetches = len(certs.fetched) - fetched

    assert [first.status_code, second.status_code, rotated.status_code] == [200, 200, 200]
    assert fetches_before_rotation == 1
    # Unknown key ids fetch the certs at most once a minute, so forged tokens can't hammer Cloudflare.
    assert forged_fetches == 0


async def test_requests_wait_for_access_keys_that_cannot_be_fetched_with_a_503(
    published: Config, tmp_path: Path
) -> None:
    certs = Certs()
    reachable = False

    def fetch(url: str) -> bytes:
        if not reachable:
            raise OSError("Network is unreachable")
        return certs(url)

    app = create_app(
        replace(published, cf_access_team_domain=TEAM_DOMAIN, cf_access_aud=AUDIENCE),
        FakeTranscriptSource(),
        FakeEmbedder(),
        FakeReranker(),
        FakeChatEngine(),
        static_dir=tmp_path / "no-bundle",
        fetch_access_keys=fetch,
        access_keys_refetch_seconds=0.2,
    )
    async with running(app) as client:
        unreachable = [(await client.get("/api/syncs", headers=with_token(certs.token()))) for _ in range(2)]
        reachable = True
        await asyncio.sleep(0.25)
        recovered = await client.get("/api/syncs", headers=with_token(certs.token()))

    assert [r.status_code for r in unreachable] == [503, 503]
    assert "Cloudflare Access keys" in unreachable[1].json()["detail"]
    assert recovered.status_code == 200
