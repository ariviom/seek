"""`seek status` and `seek list`: read from the running server, or from the store when no server answers."""

import asyncio
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel, TypeAdapter, ValidationError

from seek import channels, db, groups, syncs
from seek.channels import Channel
from seek.config import HOST, Config
from seek.engines import active_engine
from seek.groups import Group
from seek.ports import ChatEngine, ChatEngineStatus, EngineName, ModelStatus
from seek.settings import Settings, read_settings
from seek.sync_command import SyncCommandError, answers, request
from seek.syncs import Sync


class ChatHealth(BaseModel):
    """Both engines' availability and which one would answer the next turn; neither probes a provider."""

    active: EngineName | None
    engines: dict[EngineName, ChatEngineStatus]


class Health(BaseModel):
    """What `/api/health` reports that the command-line tools read."""

    models: dict[str, ModelStatus]
    chat: ChatHealth


@dataclass(frozen=True)
class StatusReport:
    # The server that answered, or None if none is running.
    server_url: str | None
    # By role; None without a server, since only the server loads them.
    models: dict[str, ModelStatus] | None
    chat: ChatHealth
    # Running and queued, oldest first.
    syncs: list[Sync]


@dataclass(frozen=True)
class ListReport:
    server_url: str | None
    channels: list[Channel]
    groups: list[Group]


def _server_url(config: Config) -> str | None:
    url = f"http://{HOST}:{config.port}/"
    return url if answers(f"{url}api/syncs", 0) else None


def _parse[T](url: str, adapter: TypeAdapter[T], body: bytes) -> T:
    try:
        return adapter.validate_json(body)
    except ValidationError as e:
        raise SyncCommandError(
            f"The server at {url} answered in a form this Seek doesn't know; restart it after upgrading"
        ) from e


def _unfinished(all_syncs: list[Sync]) -> list[Sync]:
    return sorted((s for s in all_syncs if s.status in ("queued", "running")), key=lambda s: s.id)


async def status(config: Config, engines: Mapping[EngineName, ChatEngine]) -> StatusReport:
    """The engines are asked directly only when no server answers; neither call reaches a provider."""
    url = await asyncio.to_thread(_server_url, config)
    if url is not None:
        health = _parse(url, TypeAdapter(Health), await asyncio.to_thread(request, f"{url}api/health"))
        listed = _parse(url, TypeAdapter(list[Sync]), await asyncio.to_thread(request, f"{url}api/syncs"))
        return StatusReport(url, health.models, health.chat, _unfinished(listed))
    stored: list[Sync] = await _read_store(config, lambda conn: syncs.list_syncs(conn), [])
    statuses = {name: await engine.status() for name, engine in engines.items()}
    settings = await _read_store(config, read_settings, Settings())
    chat = ChatHealth(active=active_engine(settings.engine, statuses), engines=statuses)
    return StatusReport(None, None, chat, _unfinished(stored))


async def list_all(config: Config) -> ListReport:
    url = await asyncio.to_thread(_server_url, config)
    if url is not None:
        listed_channels = await asyncio.to_thread(request, f"{url}api/channels")
        listed_groups = await asyncio.to_thread(request, f"{url}api/groups")
        return ListReport(
            url,
            _parse(url, TypeAdapter(list[Channel]), listed_channels),
            _parse(url, TypeAdapter(list[Group]), listed_groups),
        )
    return ListReport(
        None,
        await _read_store(config, channels.list_channels, []),
        await _read_store(config, groups.list_groups, []),
    )


async def _read_store[T](config: Config, read: Callable[[sqlite3.Connection], T], empty: T) -> T:
    # No knowledge base yet: nothing added, nothing to create just to read it.
    if not config.database_path.exists():
        return empty

    def migrated(conn: sqlite3.Connection) -> T:
        db.migrate(conn)
        return read(conn)

    try:
        return await db.Database(config.database_path).run(migrated)
    except RuntimeError as e:
        # The knowledge base belongs to a newer seek.
        raise SyncCommandError(str(e)) from e


def format_status(report: StatusReport) -> str:
    lines = []
    if report.server_url is None:
        lines.append("Server: not running (the models load when it starts)")
    else:
        lines.append(f"Server: running at {report.server_url}")
        lines.append("Models:")
        for role, model in (report.models or {}).items():
            lines.append(f"  {role}: {_model_state(model)}")
    lines.append(f"Chat: {report.chat.active or 'no engine ready'}")
    for name, engine in report.chat.engines.items():
        where = f" ({engine.cli_path})" if engine.cli_path else ""
        lines.append(f"  {name}: {engine.state}{where}")
        if engine.message:
            lines.append(f"    {engine.message}")
    running = sum(s.status == "running" for s in report.syncs)
    lines.append(f"Syncs: {running} running, {len(report.syncs) - running} queued")
    for s in report.syncs:
        lines.append(f"  {s.status:<8} {s.source_name}")
    return "\n".join(lines)


def _model_state(model: ModelStatus) -> str:
    text = f"{model.state} ({model.name})"
    if model.device is not None:
        text += f", {model.device} / {model.precision}"
    if model.state == "downloading" and model.downloaded_bytes is not None:
        total = f" of {model.total_bytes // 1_000_000} MB" if model.total_bytes else ""
        text += f", {model.downloaded_bytes // 1_000_000} MB{total}"
    if model.error:
        text += f": {model.error}"
    if model.fallback_reason:
        text += f"; CPU fallback: {model.fallback_reason}"
    return text


def format_list(report: ListReport) -> str:
    if not report.channels and not report.groups:
        return "No Channels yet."
    lines = ["Channels:" if report.channels else "Channels: none"]
    for c in report.channels:
        paused = "" if c.indexed else ", paused"
        synced = f"last synced {c.last_synced_at}" if c.last_synced_at else "never synced"
        lines.append(
            f"  {c.name} ({c.youtube_channel_id}{paused}): {c.indexed_videos} ready, {c.failed_videos} failed, "
            f"{c.excluded_videos} excluded; {synced}"
        )
    if report.groups:
        lines.append("Groups:")
        for group in report.groups:
            members = ", ".join(c.name for c in group.channels) or "no Channels"
            lines.append(f"  {group.name}: {members}")
    return "\n".join(lines)
