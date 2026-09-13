import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 7337


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: int = DEFAULT_PORT

    @property
    def database_path(self) -> Path:
        return self.data_dir / "mentor.db"


def config_file_path(env: Mapping[str, str]) -> Path:
    config_home = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_home / "mentor" / "config.toml"


def load_config(env: Mapping[str, str] = os.environ) -> Config:
    """Config file values, overridden by MENTOR_* environment variables."""
    path = config_file_path(env)
    values: dict[str, object] = {}
    if path.exists():
        try:
            values = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from e

    known = {"data_dir", "port"}
    unknown = set(values) - known
    if unknown:
        raise ConfigError(f"{path}: unknown keys {sorted(unknown)}")
    for key in known:
        env_value = env.get(f"MENTOR_{key.upper()}")
        if env_value is not None:
            values[key] = env_value

    data_home = Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    try:
        return Config(
            data_dir=Path(str(values.get("data_dir", data_home / "mentor"))).expanduser(),
            port=int(str(values.get("port", DEFAULT_PORT))),
        )
    except ValueError as e:
        raise ConfigError(f"invalid config value: {e}") from e
