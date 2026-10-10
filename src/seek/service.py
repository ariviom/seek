"""`seek install-service`: a systemd user unit that runs `seek serve` from login."""

import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from seek.config import Config

UNIT_NAME = "seek.service"
# Variables that decide where seek finds its config, data, models, GPU, and Claude login, so the service uses the
# same ones as this shell. Anything else stays out.
_PASSED_THROUGH = (
    "CLAUDE_CONFIG_DIR",
    "CUDA_VISIBLE_DEVICES",
    "HF_HOME",
    "HF_HUB_CACHE",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
)


@dataclass(frozen=True)
class InstalledService:
    unit_path: Path
    warnings: tuple[str, ...]


def _quoted(value: str) -> str:
    """A double-quoted systemd word, with specifiers (%) kept literal."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("%", "%%")
    return f'"{escaped}"'


def _unquoted(word: str) -> str:
    """The value _quoted wrote. Raises ValueError for anything else."""
    if len(word) < 2 or word[0] != '"' or word[-1] != '"':
        raise ValueError("not a quoted word")
    body = word[1:-1]
    value: list[str] = []
    i = 0
    while i < len(body):
        if body[i] in "\\%":
            pair = body[i : i + 2]
            value.append({"\\\\": "\\", '\\"': '"', "\\n": "\n", "%%": "%"}[pair])
            i += 2
        else:
            value.append(body[i])
            i += 1
    return "".join(value)


def unit_dir(home: Path) -> Path:
    """The directory systemd searches for user units unless its manager was given another XDG_CONFIG_HOME."""
    return home / ".config" / "systemd" / "user"


def unit_environment(unit_path: Path) -> dict[str, str]:
    """The variables an installed unit sets, as install_service wrote them; empty when none is installed.

    Raises OSError if the unit can't be read, and ValueError or KeyError if it isn't in the form written here.
    """
    try:
        text = unit_path.read_text()
    except FileNotFoundError:
        return {}
    environment = {}
    for line in text.splitlines():
        if line.startswith("Environment="):
            key, separator, value = _unquoted(line.removeprefix("Environment=")).partition("=")
            if not separator:
                raise ValueError("not a variable assignment")
            environment[key] = value
    return environment


def install_service(
    config: Config,
    env: Mapping[str, str],
    seek_executable: Path,
    unit_dir: Path,
    systemctl: Callable[[list[str]], None],
) -> InstalledService:
    """Writes the unit into unit_dir, then enables and (re)starts it with `systemctl --user` arguments."""
    search_path = env["PATH"]
    environment = {"PATH": search_path} | {
        key: env[key] for key in sorted(env) if key in _PASSED_THROUGH or key.startswith("SEEK_")
    }
    warnings = []
    if config.claude_cli_path is None:
        claude = shutil.which("claude", path=search_path)
        if claude is None:
            warnings.append(
                "No claude on PATH, so the web chat will report the Claude CLI missing; set claude_cli_path and reinstall"
            )
        else:
            # The link on PATH, not its target: Claude Code updates delete old versions.
            environment["SEEK_CLAUDE_CLI_PATH"] = str(Path(claude).absolute())
    if shutil.which("deno", path=search_path) is None:
        warnings.append(
            "No deno on PATH, which yt-dlp needs to solve YouTube's JavaScript challenges; install Deno and reinstall"
        )

    # $ would expand a variable in a command line.
    command = _quoted(str(seek_executable)).replace("$", "$$")
    lines = [
        "[Unit]",
        "Description=Seek server",
        # A server that can't start (a bad config, the port taken) stops retrying after five quick failures.
        "StartLimitIntervalSec=120",
        "StartLimitBurst=5",
        "",
        "[Service]",
        "Type=exec",
        f"ExecStart={command} serve",
        *(f"Environment={_quoted(f'{key}={value}')}" for key, value in environment.items()),
        # A desktop session can import one into the user manager, and the chat would bill it instead of the
        # subscription.
        "UnsetEnvironment=ANTHROPIC_API_KEY",
        "Restart=on-failure",
        "RestartSec=10",
        "# A Sync waiting out YouTube's backoff can't be interrupted; a killed Sync resumes at the next start.",
        "TimeoutStopSec=20",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]
    unit_path = unit_dir / UNIT_NAME
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path.write_text("\n".join(lines) + "\n")
    systemctl(["daemon-reload"])
    systemctl(["enable", UNIT_NAME])
    # Restarted rather than started, so reinstalling after an upgrade runs the new version.
    systemctl(["restart", UNIT_NAME])
    return InstalledService(unit_path, tuple(warnings))
