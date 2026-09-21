"""`mentor doctor`: one block a friend can paste into a group chat, with every secret redacted.

It reads only what is already known: the running server when one answers, otherwise the config, the credential
store and the knowledge base on disk, opened read-only. It never loads a model, calls a provider, starts a Sync, or
creates or migrates a database.
"""

import asyncio
import importlib.metadata
import platform
import re
import shutil
import sqlite3
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from mentor import db
from mentor.config import HOST, Config, ConfigError, load_config
from mentor.credentials import Credentials, CredentialStatus
from mentor.devices import DeviceProbe, probe_device, select_device
from mentor.engines import active_engine
from mentor.events import Events
from mentor.ports import ChatEngine, EngineName, ModelStatus, Secrets, SecretsUnavailable
from mentor.service import unit_environment
from mentor.settings import Settings, read_settings
from mentor.status_command import ChatHealth, Health
from mentor.sync_command import SyncCommandError, answers, request

REDACTED = "[redacted]"
# An Anthropic key's shape, for one the credential store couldn't give back to be redacted by value.
_KEY_SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_-]+")
# Shorter values can't be credentials, and replacing them would mangle ordinary words.
_SHORTEST_SECRET = 4
# The runtimes yt-dlp can solve YouTube's JavaScript challenges with.
JS_RUNTIMES = ("deno", "node", "bun")
# How many failed Videos and failed Syncs to show; the counts cover the rest.
RECENT = 5
NO_DATABASE = "none yet; `mentor serve` creates it on first start"
_COUNTED = ("channels", "groups", "videos", "segments", "syncs", "conversations", "messages")


class Redactor:
    """Replaces every known secret value, and anything shaped like an Anthropic key, wherever it appears."""

    def __init__(self, secrets: Iterable[str]) -> None:
        # Longest first, so a secret that contains another is replaced whole.
        self._secrets = sorted({s for s in secrets if len(s) >= _SHORTEST_SECRET}, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return _KEY_SHAPE.sub(REDACTED, text)


def config_secrets(config: Config) -> list[str]:
    """Configured values that can carry a credential: extractor arguments (a PO token) and cookie settings.

    Compound values count part by part too: a PO token is given as CLIENT+TOKEN and a browser as
    BROWSER+KEYRING:PROFILE, and a message may quote either part alone.
    """
    compound = [value for values in config.youtube_extractor_args.values() for value in values]
    if config.youtube_cookies_from_browser is not None:
        compound.append(config.youtube_cookies_from_browser)
    values = [*compound, *(part.strip() for value in compound for part in re.split(r"[+:,]", value))]
    if config.youtube_cookie_file is not None:
        values.append(str(config.youtube_cookie_file))
    return values


def _ytdlp_version() -> str:
    return importlib.metadata.version("yt-dlp")


@dataclass(frozen=True)
class Machine:
    """What doctor asks of this machine beyond Mentor's own files; tests replace each part."""

    probe_device: Callable[[], DeviceProbe] = probe_device
    ytdlp_version: Callable[[], str] = _ytdlp_version
    which: Callable[[str], str | None] = shutil.which


@dataclass(frozen=True)
class _Live:
    url: str
    health: Health
    settings: Settings
    # Where the key is kept, or why the server couldn't say.
    credentials: CredentialStatus | str


@dataclass
class _Stored:
    """What the knowledge base on disk holds, as a read-only connection sees it."""

    schema: int
    counts: dict[str, int] = field(default_factory=dict)
    settings: Settings | str = "not stored yet"
    failed_video_count: int = 0
    failed_videos: list[str] = field(default_factory=list)
    failed_sync_count: int = 0
    failed_syncs: list[str] = field(default_factory=list)


async def diagnose(
    config: Config,
    config_file: Path,
    config_problem: str | None,
    secrets: Secrets,
    engines: Mapping[EngineName, ChatEngine],
    machine: Machine = Machine(),
    service_unit: Path | None = None,
) -> str:
    """The whole report, already redacted.

    `config_problem` is why the config couldn't be loaded, in which case `config` holds the defaults. `engines`
    are asked only when no server answers, as `mentor status` does; neither reaches a provider. `service_unit` is
    the installed service's unit, whose environment can give the server settings this shell doesn't have.

    Text that a server or a Sync wrote is withheld when the secrets it could quote can't all be known.
    """
    key, key_problem = await _stored_key(secrets)
    service_secrets, service_problem = _service_secrets(service_unit)
    redact = Redactor([*config_secrets(config), *service_secrets, *([key] if key else [])])
    withhold = None
    if config_problem is not None:
        withhold = "withheld until the config file can be read"
    elif service_problem is not None:
        withhold = f"withheld because {service_problem}"
    live, live_problem = await _live(config)
    stored = await asyncio.to_thread(_read_database, config.database_path)

    lines = ["Mentor diagnostics (secrets are redacted; paste the whole block)"]
    lines += await _section("Versions", _versions())
    if live is not None:
        lines.append(f"Server: running at {live.url}")
    elif live_problem is not None:
        lines.append(f"Server: {live_problem}; runtime details below are from this machine instead")
    else:
        lines.append(f"Server: not running at http://{HOST}:{config.port}/; start it with `mentor serve`")
    lines += _paths(config, config_file, config_problem)
    lines += _operational(config)
    lines += _preferences(live, stored)
    lines += await _section("Models", _models(config, live, machine, withhold))
    lines += _secret_store(live, secrets, key_problem, withhold)
    lines += await _section("Chat", _chat(live, stored, engines, withhold))
    lines += await _section("YouTube", _youtube(machine))
    lines += _database(stored)
    lines += _recent_errors(live, stored, withhold)
    return redact("\n".join(lines))


async def _section(title: str, lines: Awaitable[list[str]]) -> list[str]:
    """One part of the report; a failure here is reported in its place rather than losing the rest."""
    try:
        return await lines
    except Exception as e:
        return [f"{title}: could not be inspected ({type(e).__name__}: {e})"]


def _service_secrets(unit: Path | None) -> tuple[list[str], str | None]:
    """What the installed service's own settings could quote, or why they can't be known.

    install_service records the shell's MENTOR_* and XDG_* variables in the unit, so the server may run with an
    extractor argument, a cookie file or a config file this shell no longer has.
    """
    if unit is None:
        return [], None
    try:
        environment = unit_environment(unit)
    except (OSError, ValueError, KeyError):
        return [], "the installed service's unit could not be read"
    if not environment:
        return [], None
    try:
        return config_secrets(load_config(environment)), None
    except ConfigError:
        return [], "the installed service's configuration could not be read"


async def _stored_key(secrets: Secrets) -> tuple[str | None, str | None]:
    """The stored key, read only so it can be redacted, or why it couldn't be read."""
    try:
        credential = await Credentials(secrets, Events()).current()
    except SecretsUnavailable as e:
        return None, str(e)
    return (credential.key if credential else None), None


async def _live(config: Config) -> tuple[_Live | None, str | None]:
    url = f"http://{HOST}:{config.port}/"
    if not await asyncio.to_thread(answers, f"{url}api/syncs", 0):
        return None, None
    try:
        health = TypeAdapter(Health).validate_json(await asyncio.to_thread(request, f"{url}api/health"))
        settings = Settings.model_validate_json(await asyncio.to_thread(request, f"{url}api/settings"))
    except SyncCommandError as e:
        return None, f"a server answers at {url} but couldn't report ({e})"
    except ValidationError:
        return None, f"a server answers at {url} in a form this mentor doesn't know; restart it after upgrading"
    try:
        body = await asyncio.to_thread(request, f"{url}api/credentials/anthropic")
        credentials: CredentialStatus | str = TypeAdapter(CredentialStatus).validate_json(body)
    except SyncCommandError as e:
        credentials = str(e)
    except ValidationError:
        credentials = "the server reported it in a form this mentor doesn't know"
    return _Live(url, health, settings, credentials), None


async def _versions() -> list[str]:
    try:
        mentor = importlib.metadata.version("mentor")
    except importlib.metadata.PackageNotFoundError:
        mentor = "unknown (not installed as a package)"
    return [f"Mentor {mentor}, Python {platform.python_version()}, {platform.platform()} ({platform.machine()})"]


def _paths(config: Config, config_file: Path, problem: str | None) -> list[str]:
    if problem is not None:
        state = f"could not be read, so defaults are shown: {problem}"
    else:
        state = "present" if config_file.exists() else "absent, so defaults apply"
    lines = [
        "Paths:",
        f"  config file: {config_file} ({state})",
        f"  data directory: {config.data_dir}",
        f"  database: {config.database_path}",
    ]
    if problem is not None:
        lines.append("  these paths, the port and the settings below are defaults; a running server may use others")
    return lines


def _operational(config: Config) -> list[str]:
    """Named settings only, never a dump: the cookie and extractor settings say whether they're set, not to what."""
    extractor = ", ".join(f"{name}={REDACTED}" for name in sorted(config.youtube_extractor_args)) or "none"
    access = "on" if config.cf_access_team_domain is not None else "off"
    hosts = ", ".join(config.allowed_hosts) or "loopback only"
    return [
        "Operational settings:",
        f"  port: {config.port}",
        f"  embedding model: {config.embedding_model} ({config.embedding_dimension} dimensions)",
        f"  reranker model: {config.reranker_model}, temperature {config.reranker_temperature}",
        f"  minimum Video length: {config.min_duration_seconds} s",
        f"  YouTube pacing: {config.youtube_delay_seconds} s between calls, {config.youtube_retries} retries "
        f"backing off from {config.youtube_backoff_seconds} s",
        f"  YouTube cookie file: {'set (path redacted)' if config.youtube_cookie_file else 'not set'}",
        f"  YouTube browser cookies: {'set (redacted)' if config.youtube_cookies_from_browser else 'not set'}",
        f"  YouTube extractor arguments: {extractor}",
        f"  recency: gentle {config.gentle_recency_half_life_days} days / "
        f"{config.gentle_recency_max_penalty_percent}%, strong {config.strong_recency_half_life_days} days / "
        f"{config.strong_recency_max_penalty_percent}%",
        f"  Claude CLI path: {config.claude_cli_path or 'from PATH'}",
        f"  allowed hosts: {hosts}; Cloudflare Access {access}; listening on {config.listen_host}",
    ]


def _preferences(live: _Live | None, stored: _Stored | str) -> list[str]:
    if live is not None:
        settings: Settings | str = live.settings
    elif stored == NO_DATABASE:
        # Nothing stored means nothing chosen yet.
        settings = Settings()
    elif isinstance(stored, str):
        settings = "the database could not be read"
    else:
        settings = stored.settings
    if isinstance(settings, str):
        return [f"Preferences: unavailable ({settings})"]
    engine = settings.engine or "automatic"
    return [f"Preferences: engine {engine}, provider {settings.provider}, model {settings.model}"]


def _model_line(role: str, model: ModelStatus, withhold: str | None) -> str:
    text = f"  {role}: {model.state} ({model.name})"
    if model.device is not None:
        text += f", {model.device} / {model.precision}"
    if model.fallback_reason:
        text += f"; CPU fallback: {_text(model.fallback_reason, withhold)}"
    return text


def _text(text: str, withhold: str | None) -> str:
    """Text a server or a Sync wrote, unless it could quote a secret the redaction doesn't know."""
    return text if withhold is None else f"[{withhold}]"


async def _models(config: Config, live: _Live | None, machine: Machine, withhold: str | None) -> list[str]:
    if live is not None:
        return ["Models:", *(_model_line(role, model, withhold) for role, model in live.health.models.items())]
    lines = [
        "Models: state unavailable, since only a running server loads them",
        f"  embedding: {config.embedding_model}",
        f"  reranker: {config.reranker_model}",
    ]
    try:
        # Asks torch which hardware is present; no model is loaded.
        selection = select_device(await asyncio.to_thread(machine.probe_device))
        lines.append(f"  expected device: {selection.device} / {selection.precision}")
    except Exception as e:
        lines.append(f"  expected device: unavailable ({type(e).__name__}: {e})")
    return lines


def _secret_store(
    live: _Live | None, secrets: Secrets, key_problem: str | None, withhold: str | None
) -> list[str]:
    if live is not None:
        if isinstance(live.credentials, str):
            return [f"Secret store: unavailable ({_text(live.credentials, withhold)})"]
        store = live.credentials.store
        reason = live.credentials.fallback_reason and _text(live.credentials.fallback_reason, withhold)
    else:
        store, reason = secrets.status.store, secrets.status.fallback_reason
    lines = [f"Secret store: {'OS keychain' if store == 'keychain' else 'private fallback file'}"]
    if reason:
        lines.append(f"  {reason}")
    if live is None and key_problem and key_problem != reason:
        lines.append(f"  {key_problem}")
    return lines


async def _chat(
    live: _Live | None, stored: _Stored | str, engines: Mapping[EngineName, ChatEngine], withhold: str | None
) -> list[str]:
    if live is not None:
        chat = live.health.chat
        # The server's own messages; the ones asked for below are this process's.
        messages: dict[EngineName, str | None] = {
            name: engine.message and _text(engine.message, withhold) for name, engine in chat.engines.items()
        }
    else:
        statuses = {name: await engine.status() for name, engine in engines.items()}
        preference = None if isinstance(stored, str) or isinstance(stored.settings, str) else stored.settings.engine
        chat = ChatHealth(active=active_engine(preference, statuses), engines=statuses)
        messages = {name: engine.message for name, engine in statuses.items()}
    lines = [f"Chat: {chat.active or 'no engine ready'}"]
    for name, engine in chat.engines.items():
        where = f" ({engine.cli_path})" if engine.cli_path else ""
        lines.append(f"  {name}: {engine.state}{where}")
        if messages[name]:
            lines.append(f"    {messages[name]}")
    return lines


async def _youtube(machine: Machine) -> list[str]:
    try:
        ytdlp = await asyncio.to_thread(machine.ytdlp_version)
    except Exception as e:
        ytdlp = f"unavailable ({type(e).__name__})"
    found = {name: machine.which(name) for name in JS_RUNTIMES}
    runtimes = ", ".join(f"{name} {path}" if path else f"{name} not found" for name, path in found.items())
    return [f"YouTube: yt-dlp {ytdlp}; JavaScript runtimes: {runtimes}"]


def _read_database(path: Path) -> _Stored | str:
    """The knowledge base's schema, counts, preferences and failures, or why they couldn't be read.

    Opened read-only, so a missing file stays missing and an older schema stays unmigrated. SQLite may still add
    its -wal and -shm files beside a database in WAL mode, as any reader does.
    """
    if not path.exists():
        return NO_DATABASE
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return f"could not be opened ({e})"
    try:
        schema: int = conn.execute("PRAGMA user_version").fetchone()[0]
        stored = _Stored(schema)
        # Each read on its own, so a table an older schema lacks costs only its own line.
        for table in _COUNTED:
            try:
                stored.counts[table] = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            except sqlite3.Error:
                pass
        try:
            conn.row_factory = sqlite3.Row
            stored.settings = read_settings(conn)
        except (sqlite3.Error, ValidationError):
            stored.settings = "the stored preferences could not be read"
        try:
            stored.failed_video_count = conn.execute(
                "SELECT count(*) FROM videos WHERE failure_stage IS NOT NULL AND excluded_reason IS NULL"
            ).fetchone()[0]
            stored.failed_videos = [
                f"Video {row['youtube_video_id']} ({row['title']}): {row['failure_reason']}"
                for row in conn.execute(
                    "SELECT youtube_video_id, title, failure_reason FROM videos "
                    "WHERE failure_stage IS NOT NULL AND excluded_reason IS NULL ORDER BY id DESC LIMIT ?",
                    (RECENT,),
                )
            ]
        except sqlite3.Error:
            pass
        try:
            stored.failed_sync_count = conn.execute("SELECT count(*) FROM syncs WHERE status = 'failed'").fetchone()[0]
            stored.failed_syncs = [
                f"Sync of {row['name']} at {row['finished_at']}: {row['error']}"
                for row in conn.execute(
                    "SELECT channels.name, syncs.finished_at, syncs.error FROM syncs "
                    "JOIN channels ON channels.id = syncs.channel_id WHERE syncs.status = 'failed' "
                    "ORDER BY syncs.id DESC LIMIT ?",
                    (RECENT,),
                )
            ]
        except sqlite3.Error:
            pass
        return stored
    except sqlite3.Error as e:
        return f"could not be read ({e})"
    finally:
        conn.close()


def _database(stored: _Stored | str) -> list[str]:
    if isinstance(stored, str):
        return [f"Database: {stored}"]
    known = len(db.MIGRATIONS)
    if stored.schema == known:
        schema = f"schema {stored.schema} (current)"
    elif stored.schema < known:
        schema = f"schema {stored.schema} of {known}; `mentor serve` migrates it on start"
    else:
        schema = f"schema {stored.schema}, newer than this mentor knows ({known}); upgrade mentor"
    counts = ", ".join(f"{count} {table}" for table, count in stored.counts.items())
    return [f"Database: {schema}", f"  rows: {counts or 'none readable'}"]


def _recent_errors(live: _Live | None, stored: _Stored | str, withhold: str | None) -> list[str]:
    lines: list[str] = []
    if live is not None:
        lines += [f"  {role} model: {_text(m.error, withhold)}" for role, m in live.health.models.items() if m.error]
    if not isinstance(stored, str):
        if withhold is not None and (stored.failed_video_count or stored.failed_sync_count):
            # The cookie and extractor values to redact are unknown.
            lines.append(
                f"  {stored.failed_video_count} failed Videos and {stored.failed_sync_count} failed Syncs; their "
                f"messages are {withhold}"
            )
        else:
            if stored.failed_video_count:
                lines.append(f"  failed Videos: {stored.failed_video_count}, latest first:")
                lines += [f"    {line}" for line in stored.failed_videos]
            if stored.failed_sync_count:
                lines.append(f"  failed Syncs: {stored.failed_sync_count}, latest first:")
                lines += [f"    {line}" for line in stored.failed_syncs]
    return ["Recent errors:", *lines] if lines else ["Recent errors: none stored"]
