from pathlib import Path

from mentor.config import Config
from mentor.service import install_service


def executable(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


class Systemctl:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> None:
        self.calls.append(args)


def test_installs_a_user_unit_that_serves_at_login_as_this_shell_would(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    executable(bin_dir, "claude")
    executable(bin_dir, "deno")
    env = {
        "PATH": f"{bin_dir}:/usr/bin",
        "SHELL": "/bin/bash",
        "XDG_CONFIG_HOME": "/home/someone/config",
        "HF_HOME": "/models/hf",
        "CUDA_VISIBLE_DEVICES": "1",
        "MENTOR_PORT": "7400",
        "ANTHROPIC_API_KEY": "sk-not-for-the-service",
    }
    systemctl = Systemctl()

    installed = install_service(
        Config(data_dir=tmp_path / "data"), env, Path("/tools/bin/mentor"), tmp_path / "units", systemctl
    )

    assert installed.unit_path == tmp_path / "units" / "mentor.service"
    assert installed.warnings == ()
    assert installed.unit_path.read_text() == f"""\
[Unit]
Description=mentor server
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=exec
ExecStart="/tools/bin/mentor" serve
Environment="PATH={bin_dir}:/usr/bin"
Environment="CUDA_VISIBLE_DEVICES=1"
Environment="HF_HOME=/models/hf"
Environment="MENTOR_PORT=7400"
Environment="XDG_CONFIG_HOME=/home/someone/config"
Environment="MENTOR_CLAUDE_CLI_PATH={bin_dir / "claude"}"
UnsetEnvironment=ANTHROPIC_API_KEY
Restart=on-failure
RestartSec=10
# A Sync waiting out YouTube's backoff can't be interrupted; a killed Sync resumes at the next start.
TimeoutStopSec=20

[Install]
WantedBy=default.target
"""
    assert systemctl.calls == [
        ["daemon-reload"],
        ["enable", "mentor.service"],
        ["restart", "mentor.service"],
    ]


def test_a_claude_cli_path_in_the_config_file_is_left_to_it(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    executable(bin_dir, "claude")
    executable(bin_dir, "deno")
    configured = Config(data_dir=tmp_path / "data", claude_cli_path=Path("/opt/claude"))

    installed = install_service(
        configured, {"PATH": str(bin_dir)}, Path("/tools/bin/mentor"), tmp_path / "units", Systemctl()
    )

    assert "MENTOR_CLAUDE_CLI_PATH" not in installed.unit_path.read_text()
    assert installed.warnings == ()


def test_warns_when_the_chat_or_youtube_would_be_missing_a_tool(tmp_path: Path) -> None:
    env = {"PATH": str(tmp_path / "empty")}

    installed = install_service(
        Config(data_dir=tmp_path / "data"), env, Path("/tools/bin/mentor"), tmp_path / "units", Systemctl()
    )

    assert "MENTOR_CLAUDE_CLI_PATH" not in installed.unit_path.read_text()
    assert installed.warnings == (
        "No claude on PATH, so the web chat will report the Claude CLI missing; set claude_cli_path and reinstall",
        "No deno on PATH, which yt-dlp needs to solve YouTube's JavaScript challenges; install Deno and reinstall",
    )


def test_quotes_values_for_systemd(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin", "MENTOR_DATA_DIR": '/data/100% "mine" \\ $HOME\nExecStartPre=/bin/false'}

    installed = install_service(
        Config(data_dir=tmp_path / "data"), env, Path("/my tools/$bin/mentor%"), tmp_path / "units", Systemctl()
    )

    unit = installed.unit_path.read_text()
    assert 'ExecStart="/my tools/$$bin/mentor%%" serve\n' in unit
    assert 'Environment="MENTOR_DATA_DIR=/data/100%% \\"mine\\" \\\\ $HOME\\nExecStartPre=/bin/false"\n' in unit
    assert "\nExecStartPre" not in unit
