import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_PORT = 7337
DEFAULT_MIN_DURATION_SECONDS = 120
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_EMBEDDING_DIMENSION = 1024
# Loads natively through sentence-transformers' CrossEncoder; BAAI/bge-reranker-v2-m3 also does, at twice the size.
DEFAULT_RERANKER_MODEL = "mixedbread-ai/mxbai-rerank-base-v2"
# The most dimensions a sqlite-vec float vector column accepts.
MAX_EMBEDDING_DIMENSION = 8192
# Unauthenticated, YouTube tolerates roughly 300 Videos an hour; a signed-in cookie file allows about three times that.
DEFAULT_YOUTUBE_DELAY_SECONDS = 10
DEFAULT_YOUTUBE_RETRIES = 3
DEFAULT_YOUTUBE_BACKOFF_SECONDS = 30
# Search scores a result as sigmoid(reranker logit / temperature). mxbai-rerank-base-v2 gives relevant passages logits
# of about 5 to 10, which a temperature of 3 keeps apart (0.84 to 0.97) instead of all near 1.
DEFAULT_RERANKER_TEMPERATURE = 3
# Age then takes a penalty that closes half its distance to the max penalty every half-life. Gentle breaks near-ties
# toward newer Videos (a two-year-old Video keeps 98% of its score, a ten-year-old 92.5%, never less than 85%); strong
# prefers newer Videos plainly (82%, 55%, never less than 50%).
DEFAULT_GENTLE_RECENCY_HALF_LIFE_DAYS = 3650
DEFAULT_GENTLE_RECENCY_MAX_PENALTY_PERCENT = 15
DEFAULT_STRONG_RECENCY_HALF_LIFE_DAYS = 1095
DEFAULT_STRONG_RECENCY_MAX_PENALTY_PERCENT = 50


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: int = DEFAULT_PORT
    # Videos shorter than this are excluded from ingestion.
    min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS
    # A knowledge base keeps the model it was embedded with; starting with another one is refused.
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    # Models are Hugging Face repository names, downloaded on first use.
    reranker_model: str = DEFAULT_RERANKER_MODEL
    # The least time between a Sync's YouTube calls: each listing, and each Video with its captions.
    youtube_delay_seconds: int = DEFAULT_YOUTUBE_DELAY_SECONDS
    # Retries after YouTube rate limits a request or can't be reached, waiting youtube_backoff_seconds and doubling.
    youtube_retries: int = DEFAULT_YOUTUBE_RETRIES
    youtube_backoff_seconds: int = DEFAULT_YOUTUBE_BACKOFF_SECONDS
    # A Netscape-format cookies.txt exported from a signed-in browser; yt-dlp also writes refreshed cookies back to it.
    youtube_cookie_file: Path | None = None
    reranker_temperature: int = DEFAULT_RERANKER_TEMPERATURE
    # Search's prefer_recent levels "gentle" (the default) and "strong".
    gentle_recency_half_life_days: int = DEFAULT_GENTLE_RECENCY_HALF_LIFE_DAYS
    gentle_recency_max_penalty_percent: int = DEFAULT_GENTLE_RECENCY_MAX_PENALTY_PERCENT
    strong_recency_half_life_days: int = DEFAULT_STRONG_RECENCY_HALF_LIFE_DAYS
    strong_recency_max_penalty_percent: int = DEFAULT_STRONG_RECENCY_MAX_PENALTY_PERCENT

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


def _text(key: str, value: object, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source}: {key} must be a non-empty string")
    return value.strip()


def _absolute_path(key: str, value: object, source: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{source}: {key} must be a non-empty path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"{source}: {key} must be an absolute path")
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
        data_dir = _absolute_path("data_dir", *raw["data_dir"])
    port = _integer("port", *raw["port"], 1, 65535) if "port" in raw else DEFAULT_PORT
    min_duration = DEFAULT_MIN_DURATION_SECONDS
    if "min_duration_seconds" in raw:
        min_duration = _integer("min_duration_seconds", *raw["min_duration_seconds"], 0, 24 * 60 * 60)
    embedding_model = DEFAULT_EMBEDDING_MODEL
    if "embedding_model" in raw:
        embedding_model = _text("embedding_model", *raw["embedding_model"])
    embedding_dimension = DEFAULT_EMBEDDING_DIMENSION
    if "embedding_dimension" in raw:
        embedding_dimension = _integer("embedding_dimension", *raw["embedding_dimension"], 1, MAX_EMBEDDING_DIMENSION)
    reranker_model = DEFAULT_RERANKER_MODEL
    if "reranker_model" in raw:
        reranker_model = _text("reranker_model", *raw["reranker_model"])
    youtube_delay = DEFAULT_YOUTUBE_DELAY_SECONDS
    if "youtube_delay_seconds" in raw:
        youtube_delay = _integer("youtube_delay_seconds", *raw["youtube_delay_seconds"], 0, 3600)
    youtube_retries = DEFAULT_YOUTUBE_RETRIES
    if "youtube_retries" in raw:
        youtube_retries = _integer("youtube_retries", *raw["youtube_retries"], 0, 10)
    youtube_backoff = DEFAULT_YOUTUBE_BACKOFF_SECONDS
    if "youtube_backoff_seconds" in raw:
        youtube_backoff = _integer("youtube_backoff_seconds", *raw["youtube_backoff_seconds"], 1, 3600)
    cookie_file = None
    if "youtube_cookie_file" in raw:
        cookie_file = _absolute_path("youtube_cookie_file", *raw["youtube_cookie_file"])
    temperature = DEFAULT_RERANKER_TEMPERATURE
    if "reranker_temperature" in raw:
        temperature = _integer("reranker_temperature", *raw["reranker_temperature"], 1, 100)
    gentle_half_life = DEFAULT_GENTLE_RECENCY_HALF_LIFE_DAYS
    if "gentle_recency_half_life_days" in raw:
        gentle_half_life = _integer("gentle_recency_half_life_days", *raw["gentle_recency_half_life_days"], 1, 36500)
    gentle_penalty = DEFAULT_GENTLE_RECENCY_MAX_PENALTY_PERCENT
    if "gentle_recency_max_penalty_percent" in raw:
        gentle_penalty = _integer(
            "gentle_recency_max_penalty_percent", *raw["gentle_recency_max_penalty_percent"], 0, 100
        )
    strong_half_life = DEFAULT_STRONG_RECENCY_HALF_LIFE_DAYS
    if "strong_recency_half_life_days" in raw:
        strong_half_life = _integer("strong_recency_half_life_days", *raw["strong_recency_half_life_days"], 1, 36500)
    strong_penalty = DEFAULT_STRONG_RECENCY_MAX_PENALTY_PERCENT
    if "strong_recency_max_penalty_percent" in raw:
        strong_penalty = _integer(
            "strong_recency_max_penalty_percent", *raw["strong_recency_max_penalty_percent"], 0, 100
        )
    return Config(
        data_dir=data_dir,
        port=port,
        min_duration_seconds=min_duration,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        reranker_model=reranker_model,
        youtube_delay_seconds=youtube_delay,
        youtube_retries=youtube_retries,
        youtube_backoff_seconds=youtube_backoff,
        youtube_cookie_file=cookie_file,
        reranker_temperature=temperature,
        gentle_recency_half_life_days=gentle_half_life,
        gentle_recency_max_penalty_percent=gentle_penalty,
        strong_recency_half_life_days=strong_half_life,
        strong_recency_max_penalty_percent=strong_penalty,
    )
