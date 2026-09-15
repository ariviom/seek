"""`mentor status` and `mentor list`: read from the running server, or from the store when no server answers."""

import asyncio
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, TypeAdapter, ValidationError

from mentor import channels, db, groups, syncs
from mentor.channels import Channel
from mentor.config import HOST, Config
from mentor.groups import Group
from mentor.ports import ChatEngine, ChatEngineStatus, ModelStatus
from mentor.sync_command import SyncCommandError, answers, request
from mentor.syncs import Sync


class _Health(BaseModel):
    models: dict[str, ModelStatus]
    claude_cli: ChatEngineStatus


@dataclass(frozen=True)
class StatusReport:
    # The server that answered, or None if none is running.
    server_url: str | None
    # By role; None without a server, since only the server loads them.
    models: dict[str, ModelStatus] | None
    claude_cli: ChatEngineStatus
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
            f"The server at {url} answered in a form this mentor doesn't know; restart it after upgrading"
        ) from e


def _unfinished(all_syncs: list[Sync]) -> list[Sync]:
    return sorted((s for s in all_syncs if s.status in ("queued", "running")), key=lambda s: s.id)


async def status(config: Config, chat_engine: ChatEngine) -> StatusReport:
    """chat_engine checks the Claude CLI only when no server answers."""
    url = await asyncio.to_thread(_server_url, config)
    if url is not None:
        health = _parse(url, TypeAdapter(_Health), await asyncio.to_thread(request, f"{url}api/health"))
        listed = _parse(url, TypeAdapter(list[Sync]), await asyncio.to_thread(request, f"{url}api/syncs"))
        return StatusReport(url, health.models, health.claude_cli, _unfinished(listed))
    stored: list[Sync] = await _read_store(config, lambda conn: syncs.list_syncs(conn), [])
    return StatusReport(None, None, await chat_engine.status(), _unfinished(stored))


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
        # The knowledge base belongs to a newer mentor.
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
    cli = report.claude_cli
    lines.append(f"Claude CLI: {cli.state}" + (f" ({cli.cli_path})" if cli.cli_path else ""))
    if cli.message:
        lines.append(f"  {cli.message}")
    running = sum(s.status == "running" for s in report.syncs)
    lines.append(f"Syncs: {running} running, {len(report.syncs) - running} queued")
    for s in report.syncs:
        lines.append(f"  {s.status:<8} {s.channel_name}")
    return "\n".join(lines)


def _model_state(model: ModelStatus) -> str:
    text = f"{model.state} ({model.name})"
    if model.state == "downloading" and model.downloaded_bytes is not None:
        total = f" of {model.total_bytes // 1_000_000} MB" if model.total_bytes else ""
        text += f", {model.downloaded_bytes // 1_000_000} MB{total}"
    if model.error:
        text += f": {model.error}"
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
