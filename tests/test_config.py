from pathlib import Path

import pytest

from mentor.config import Config, ConfigError, load_config


def write_config(config_home: Path, text: str) -> None:
    (config_home / "mentor").mkdir(parents=True)
    (config_home / "mentor" / "config.toml").write_text(text)


def test_defaults_serve_on_7337_with_data_in_xdg_data_home(tmp_path: Path) -> None:
    config = load_config({"XDG_CONFIG_HOME": str(tmp_path), "XDG_DATA_HOME": "/data"})

    assert config == Config(data_dir=Path("/data/mentor"), port=7337)
    assert (config.embedding_model, config.embedding_dimension) == ("Qwen/Qwen3-Embedding-0.6B", 1024)
    assert config.reranker_model == "mixedbread-ai/mxbai-rerank-base-v2"


def test_config_file_sets_values_and_env_overrides_them(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        'port = 7400\ndata_dir = "/from/file"\nmin_duration_seconds = 300\n'
        'embedding_model = "from/file"\nembedding_dimension = 768\n',
    )

    config = load_config(
        {
            "XDG_CONFIG_HOME": str(tmp_path),
            "MENTOR_DATA_DIR": "/from/env",
            "MENTOR_MIN_DURATION_SECONDS": "60",
            "MENTOR_EMBEDDING_DIMENSION": "512",
            "MENTOR_RERANKER_MODEL": "BAAI/bge-reranker-v2-m3",
        }
    )

    assert config == Config(
        data_dir=Path("/from/env"),
        port=7400,
        min_duration_seconds=60,
        embedding_model="from/file",
        embedding_dimension=512,
        reranker_model="BAAI/bge-reranker-v2-m3",
    )


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
        ("min_duration_seconds = -1\n", {}),
        ("", {"MENTOR_MIN_DURATION_SECONDS": "two minutes"}),
        ("embedding_model = 5\n", {}),
        ("", {"MENTOR_EMBEDDING_MODEL": " "}),
        ("embedding_dimension = 0\n", {}),
        ("", {"MENTOR_EMBEDDING_DIMENSION": "9000"}),
    ],
)
def test_invalid_config_is_rejected_with_a_config_error(
    tmp_path: Path, file_text: str, env: dict[str, str]
) -> None:
    write_config(tmp_path, file_text)

    with pytest.raises(ConfigError):
        load_config({"XDG_CONFIG_HOME": str(tmp_path), **env})


def test_youtube_politeness_and_cookie_file_are_configurable(tmp_path: Path) -> None:
    write_config(tmp_path, 'youtube_delay_seconds = 20\nyoutube_cookie_file = "~/cookies.txt"\n')

    defaults = load_config({"XDG_CONFIG_HOME": str(tmp_path / "elsewhere")})
    config = load_config(
        {"XDG_CONFIG_HOME": str(tmp_path), "MENTOR_YOUTUBE_RETRIES": "0", "MENTOR_YOUTUBE_BACKOFF_SECONDS": "90"}
    )

    assert (defaults.youtube_delay_seconds, defaults.youtube_retries, defaults.youtube_backoff_seconds) == (10, 3, 30)
    assert defaults.youtube_cookie_file is None
    assert (config.youtube_delay_seconds, config.youtube_retries, config.youtube_backoff_seconds) == (20, 0, 90)
    assert config.youtube_cookie_file == Path("~/cookies.txt").expanduser()


@pytest.mark.parametrize(
    ("file_text", "env"),
    [
        ("youtube_delay_seconds = -1\n", {}),
        ("", {"MENTOR_YOUTUBE_RETRIES": "many"}),
        ("youtube_backoff_seconds = 0\n", {}),
        ("youtube_cookie_file = 'cookies.txt'\n", {}),
        ("", {"MENTOR_YOUTUBE_COOKIE_FILE": ""}),
    ],
)
def test_invalid_youtube_settings_are_rejected(tmp_path: Path, file_text: str, env: dict[str, str]) -> None:
    write_config(tmp_path, file_text)

    with pytest.raises(ConfigError):
        load_config({"XDG_CONFIG_HOME": str(tmp_path), **env})


def test_search_scoring_and_recency_are_configurable(tmp_path: Path) -> None:
    write_config(tmp_path, "gentle_recency_half_life_days = 1825\nreranker_temperature = 5\n")

    defaults = load_config({"XDG_CONFIG_HOME": str(tmp_path / "elsewhere")})
    config = load_config(
        {
            "XDG_CONFIG_HOME": str(tmp_path),
            "MENTOR_STRONG_RECENCY_HALF_LIFE_DAYS": "365",
            "MENTOR_GENTLE_RECENCY_MAX_PENALTY_PERCENT": "0",
            "MENTOR_STRONG_RECENCY_MAX_PENALTY_PERCENT": "100",
        }
    )

    def settings(c: Config) -> tuple[int, int, int, int, int]:
        return (
            c.reranker_temperature,
            c.gentle_recency_half_life_days,
            c.gentle_recency_max_penalty_percent,
            c.strong_recency_half_life_days,
            c.strong_recency_max_penalty_percent,
        )

    assert settings(defaults) == (3, 3650, 15, 1095, 50)
    assert settings(config) == (5, 1825, 0, 365, 100)


@pytest.mark.parametrize(
    "env",
    [
        {"MENTOR_GENTLE_RECENCY_HALF_LIFE_DAYS": "0"},
        {"MENTOR_STRONG_RECENCY_HALF_LIFE_DAYS": "soon"},
        {"MENTOR_RERANKER_TEMPERATURE": "0"},
        {"MENTOR_GENTLE_RECENCY_MAX_PENALTY_PERCENT": "101"},
        {"MENTOR_STRONG_RECENCY_MAX_PENALTY_PERCENT": "-1"},
    ],
)
def test_invalid_search_settings_are_rejected(tmp_path: Path, env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_config({"XDG_CONFIG_HOME": str(tmp_path), **env})


def test_the_claude_cli_path_is_configurable_and_must_be_absolute(tmp_path: Path) -> None:
    write_config(tmp_path, 'claude_cli_path = "/opt/claude/bin/claude"\n')

    assert load_config({"XDG_CONFIG_HOME": str(tmp_path / "elsewhere")}).claude_cli_path is None
    assert load_config({"XDG_CONFIG_HOME": str(tmp_path)}).claude_cli_path == Path("/opt/claude/bin/claude")
    with pytest.raises(ConfigError):
        load_config({"XDG_CONFIG_HOME": str(tmp_path), "MENTOR_CLAUDE_CLI_PATH": "bin/claude"})


def test_allowed_hosts_come_from_a_list_or_a_comma_separated_variable(tmp_path: Path) -> None:
    write_config(tmp_path, 'allowed_hosts = ["mentor.example.com", "10.0.0.5:*"]\n')

    defaults = load_config({"XDG_CONFIG_HOME": str(tmp_path / "elsewhere")})
    from_file = load_config({"XDG_CONFIG_HOME": str(tmp_path)})
    from_env = load_config({"XDG_CONFIG_HOME": str(tmp_path), "MENTOR_ALLOWED_HOSTS": " a.example , b.example:8443,"})

    assert defaults.allowed_hosts == ()
    assert from_file.allowed_hosts == ("mentor.example.com", "10.0.0.5:*")
    assert from_env.allowed_hosts == ("a.example", "b.example:8443")


@pytest.mark.parametrize(
    ("file_text", "env"),
    [
        ("allowed_hosts = [5]\n", {}),
        ("", {"MENTOR_ALLOWED_HOSTS": "https://mentor.example.com"}),
        ("", {"MENTOR_ALLOWED_HOSTS": "mentor example"}),
    ],
)
def test_invalid_allowed_hosts_are_rejected(tmp_path: Path, file_text: str, env: dict[str, str]) -> None:
    write_config(tmp_path, file_text)

    with pytest.raises(ConfigError):
        load_config({"XDG_CONFIG_HOME": str(tmp_path), **env})


def test_cloudflare_access_verification_takes_the_team_domain_and_audience_together(tmp_path: Path) -> None:
    write_config(tmp_path, 'cf_access_team_domain = "https://woodshop.cloudflareaccess.com/"\n')

    off = load_config({"XDG_CONFIG_HOME": str(tmp_path / "elsewhere")})
    on = load_config({"XDG_CONFIG_HOME": str(tmp_path), "MENTOR_CF_ACCESS_AUD": " 4714c1358e65fe4b408ad6d432a5f878 "})

    assert (off.cf_access_team_domain, off.cf_access_aud) == (None, None)
    assert (on.cf_access_team_domain, on.cf_access_aud) == (
        "woodshop.cloudflareaccess.com",
        "4714c1358e65fe4b408ad6d432a5f878",
    )


@pytest.mark.parametrize(
    ("file_text", "env"),
    [
        ('cf_access_team_domain = "woodshop.cloudflareaccess.com"\n', {}),
        ("", {"MENTOR_CF_ACCESS_AUD": "4714c1358e65fe4b408ad6d432a5f878"}),
        ('cf_access_aud = "abc"\n', {"MENTOR_CF_ACCESS_TEAM_DOMAIN": "woodshop.cloudflareaccess.com/login"}),
        ('cf_access_aud = "abc"\n', {"MENTOR_CF_ACCESS_TEAM_DOMAIN": "http://woodshop.cloudflareaccess.com"}),
        ('cf_access_aud = " "\ncf_access_team_domain = "woodshop.cloudflareaccess.com"\n', {}),
    ],
)
def test_incomplete_or_invalid_cloudflare_access_settings_are_rejected(
    tmp_path: Path, file_text: str, env: dict[str, str]
) -> None:
    write_config(tmp_path, file_text)

    with pytest.raises(ConfigError):
        load_config({"XDG_CONFIG_HOME": str(tmp_path), **env})
