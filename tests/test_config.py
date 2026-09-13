from pathlib import Path

import pytest

from mentor.config import Config, ConfigError, load_config


def write_config(config_home: Path, text: str) -> None:
    (config_home / "mentor").mkdir(parents=True)
    (config_home / "mentor" / "config.toml").write_text(text)


def test_defaults_serve_on_7337_with_data_in_xdg_data_home(tmp_path: Path) -> None:
    config = load_config({"XDG_CONFIG_HOME": str(tmp_path), "XDG_DATA_HOME": "/data"})

    assert config == Config(data_dir=Path("/data/mentor"), port=7337)


def test_config_file_sets_values_and_env_overrides_them(tmp_path: Path) -> None:
    write_config(tmp_path, 'port = 7400\ndata_dir = "/from/file"\n')

    config = load_config({"XDG_CONFIG_HOME": str(tmp_path), "MENTOR_DATA_DIR": "/from/env"})

    assert config == Config(data_dir=Path("/from/env"), port=7400)


@pytest.mark.parametrize(
    ("file_text", "env"),
    [
        ("colour = 'red'\n", {}),
        ("port = 'high'\n", {}),
        ("port = true\n", {}),
        ("port = 0\n", {}),
        ("data_dir = 5\n", {}),
        ("data_dir = 'relative/dir'\n", {}),
        ("", {"MENTOR_PORT": "70000"}),
        ("", {"MENTOR_PORT": "seven"}),
        ("", {"MENTOR_DATA_DIR": ""}),
        ("port = \n", {}),
    ],
)
def test_invalid_config_is_rejected_with_a_config_error(
    tmp_path: Path, file_text: str, env: dict[str, str]
) -> None:
    write_config(tmp_path, file_text)

    with pytest.raises(ConfigError):
        load_config({"XDG_CONFIG_HOME": str(tmp_path), **env})
