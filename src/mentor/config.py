import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_PORT = 7337
DEFAULT_MIN_DURATION_SECONDS = 120


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: int = DEFAULT_PORT
    # Videos shorter than this are excluded from ingestion.
    min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS

    @property
    def database_path(self) -> Path:
        return self.data_dir / "mentor.db"


def _xdg_dir(env: Mapping[str, str], var: str, fallback: str) -> Path:
    return Path(env.get(var) or Path.home() / fallback)


def _integer(key: str, value: object, source: str, low: int, high: int) -> int:
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            raise ConfigError(f"{source}: {key} must be an integer") from None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ConfigError(f"{source}: {key} must be an integer from {low} to {high}")
    return value


def _data_dir(value: object, source: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{source}: data_dir must be a non-empty path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"{source}: data_dir must be an absolute path")
    return path


def load_config(env: Mapping[str, str] = os.environ) -> Config:
    """Config file values, overridden by MENTOR_* environment variables."""
    path = _xdg_dir(env, "XDG_CONFIG_HOME", ".config") / "mentor" / "config.toml"
    raw: dict[str, tuple[object, str]] = {}
    if path.exists():
        try:
            file_values = tomllib.loads(path.read_text())
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
            raise ConfigError(f"{path}: {e}") from e
        raw = {key: (value, str(path)) for key, value in file_values.items()}

    known = {f.name for f in fields(Config)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{path}: unknown keys {sorted(unknown)}")
    for key in known:
        env_name = f"MENTOR_{key.upper()}"
        if env_name in env:
            raw[key] = (env[env_name], env_name)

    data_dir = _xdg_dir(env, "XDG_DATA_HOME", ".local/share") / "mentor"
    if "data_dir" in raw:
        data_dir = _data_dir(*raw["data_dir"])
    port = _integer("port", *raw["port"], 1, 65535) if "port" in raw else DEFAULT_PORT
    min_duration = DEFAULT_MIN_DURATION_SECONDS
    if "min_duration_seconds" in raw:
        min_duration = _integer("min_duration_seconds", *raw["min_duration_seconds"], 0, 24 * 60 * 60)
    return Config(data_dir=data_dir, port=port, min_duration_seconds=min_duration)
