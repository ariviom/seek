# mentor

Turns YouTube channels into a cited, searchable knowledge base. You add the creators you learn from as Mentors, Sync
their Channels, and then ask questions: in the web UI, or from Claude Code, Codex, or Claude Desktop over MCP. Every
answer links back to the moment in the Video where it was said.

## Requirements

- Linux with systemd (for the service), and [uv](https://docs.astral.sh/uv/)
- Node 22.12 or later and pnpm, to build the web UI during install
- An NVIDIA GPU with about 3.5 GB free, for the embedding and reranking models
- [Deno](https://deno.com) on PATH: yt-dlp needs it to solve YouTube's JavaScript challenges
- For the web chat: Claude Code, logged in to your subscription
- For live backups: the `sqlite3` command

## Install

Clone this repository to, say, `~/src/mentor`, then run these from an ordinary terminal (not one inside an editor or
agent session, whose PATH the service would copy):

```sh
uv tool install ~/src/mentor
uv tool update-shell   # once, if ~/.local/bin isn't on your PATH yet
mentor install-service
```

`mentor install-service` writes `~/.config/systemd/user/mentor.service`, enables it, starts it, and waits until the server
answers on <http://127.0.0.1:7337/>. From then on it starts whenever you log in. To start it at boot without logging in, run
`loginctl enable-linger`. To run it in the foreground instead, use `mentor serve`.

The unit records the `mentor` you ran and the PATH of the shell you ran it from, so the service finds `deno` the same
way you do. Unless `claude_cli_path` is configured, it also records the first `claude` on that PATH as it appears
there (for a standard install, the `~/.local/bin/claude` link, which survives Claude Code updates). It also copies any
`MENTOR_*` variables that are set, plus `HF_HOME`, `HF_HUB_CACHE`, `CUDA_VISIBLE_DEVICES`, `CLAUDE_CONFIG_DIR`,
`XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, and `XDG_DATA_HOME`. It records nothing else, and it removes any
`ANTHROPIC_API_KEY` from the service's environment, because the chat would bill that key instead of your subscription.
It warns if `claude` or `deno` can't be found.

On first start, the models download into the Hugging Face cache (`~/.cache/huggingface`, or `HF_HOME`). They are about
2.2 GB. The page footer shows their progress. Syncs wait until the models are ready, and until then Search answers
that they are still loading.

To upgrade, pull and reinstall, then rerun `mentor install-service`, which restarts the service:

```sh
git -C ~/src/mentor pull
uv tool install --reinstall ~/src/mentor
mentor install-service
```

Recorded variables override the config file, like any `MENTOR_*` variable. That includes the recorded
`MENTOR_CLAUDE_CLI_PATH`. Rerun `mentor install-service` whenever they should change, including after you set
`claude_cli_path`. Other config file changes only need a restart: `systemctl --user restart mentor`.

Status: `systemctl --user status mentor`. Logs: `journalctl --user -u mentor`.

## Sync from the command line or on a schedule

```sh
mentor sync --all                        # every indexed Channel
mentor sync --channel "Wood By Wright"   # one Channel, by its YouTube name or channel id
```

When the server is running, `mentor sync` queues the Syncs there and returns; their progress and any failures show in
the web UI. When it isn't, `mentor sync` loads the embedding model and runs the Syncs itself, returning when they finish
(it exits 1 if any failed). If the service is running but not answering yet, it waits up to 30 seconds for the server
first. Only one process runs Syncs at a time: a server started meanwhile waits for it, and a `mentor sync` started
while another process runs Syncs waits for that process to run its Syncs too.

A Sync lists a Channel's videos and streams tabs (past livestreams included). Once a Channel has completed a Sync, later
Syncs stop listing at the first page of Videos already known, unless the Channel has a most-recent filter or the Sync
retries failures. A Video published in the last week without captions is retried by later Syncs, since YouTube may
still be generating them. When YouTube refuses the captions of three Videos in a row, the Sync stops and the failed
Videos wait for the next one; no Sync runs for `youtube_backoff_seconds`, doubling for each Sync in a row that stops so.

`mentor reindex --all` (or `--channel`) Syncs the same way but first re-cuts and re-embeds every Video already indexed
from its stored Transcript, without fetching from YouTube again. Run it after upgrading to a mentor that indexes
passages differently; until each Video is done again it is out of search.

To Sync every indexed Channel on a schedule, install the service with a timer:

```sh
mentor install-service --timer                    # daily at midnight
mentor install-service --timer "Mon *-*-* 04:00"   # any systemd calendar expression
```

This also writes `mentor-sync.service` and `mentor-sync.timer`, with the same recorded environment. A run missed while
the machine was off happens at the next chance. Rerunning `mentor install-service` without `--timer` keeps an
installed timer's schedule and updates its recorded environment; pass `--timer` again to change the schedule. Next
run: `systemctl --user list-timers mentor-sync.timer`. Logs: `journalctl --user -u mentor-sync`. To turn it off:
`systemctl --user disable --now mentor-sync.timer`.

## Data

Your data lives in `~/.local/share/mentor/` (or `$XDG_DATA_HOME/mentor`, or the `data_dir` setting):

- `mentor.db` holds the whole knowledge base in one SQLite file: Mentors, Channels, Transcripts, Segments, vectors,
  and Conversations.
- `chat/` is the empty working directory the web chat runs the Claude CLI in.

Backup is a copy of `mentor.db`. The database uses WAL mode, so recent changes can sit in `mentor.db-wal` beside it.
Either stop the service and copy both files, or take a consistent single-file copy while it runs:

```sh
sqlite3 ~/.local/share/mentor/mentor.db ".backup $HOME/mentor-backup.db"
```

## Configuration

Settings are read from `~/.config/mentor/config.toml` (or `$XDG_CONFIG_HOME/mentor/config.toml`). An environment
variable `MENTOR_<KEY>` overrides any key; for example, `MENTOR_PORT=7400` overrides `port`. Unknown keys are an error.

```toml
port = 7400
youtube_cookie_file = "/home/me/.config/mentor/cookies.txt"
allowed_hosts = ["mentor.example.com"]
```

| Key | Default | Meaning |
|---|---|---|
| `data_dir` | `~/.local/share/mentor` | Where `mentor.db` lives (an absolute path) |
| `port` | `7337` | Port on 127.0.0.1. The server never listens beyond localhost |
| `min_duration_seconds` | `120` | Shorter Videos, which covers Shorts, are excluded from ingestion |
| `embedding_model` | `Qwen/Qwen3-Embedding-0.6B` | Hugging Face model for Segment vectors |
| `embedding_dimension` | `1024` | Its vector size |
| `reranker_model` | `mixedbread-ai/mxbai-rerank-base-v2` | Hugging Face cross-encoder that reranks search results |
| `reranker_temperature` | `3` | Scores are sigmoid(logit / temperature); higher spreads confident results apart |
| `gentle_recency_half_life_days` | `3650` | "Prefer newer, gently": age penalty half-life |
| `gentle_recency_max_penalty_percent` | `15` | …and the most a Video's score can lose to age |
| `strong_recency_half_life_days` | `1095` | "Prefer newer, strongly": age penalty half-life |
| `strong_recency_max_penalty_percent` | `50` | …and the most a Video's score can lose to age |
| `youtube_delay_seconds` | `10` | Least time between a Sync's YouTube calls |
| `youtube_retries` | `3` | Retries when YouTube rate-limits or can't be reached |
| `youtube_backoff_seconds` | `30` | First wait before a retry, doubling each time |
| `youtube_cookie_file` | none | A Netscape `cookies.txt` exported from a signed-in browser |
| `youtube_cookies_from_browser` | none | Read cookies from a browser profile instead, in yt-dlp's `BROWSER[+KEYRING][:PROFILE][::CONTAINER]` form, e.g. `firefox` or `chrome:Profile 1` |
| `youtube_extractor_args` | `skip = ["hls", "dash"]` | A table of yt-dlp `youtube` extractor arguments merged over the default, e.g. `player_client` or `po_token` |
| `allowed_hosts` | none | Host headers accepted besides loopback, such as your proxy's public hostname |
| `claude_cli_path` | `claude` on PATH | The Claude CLI the web chat drives |
| `cf_access_team_domain` | none | With `cf_access_aud`, requires a Cloudflare Access token on requests from outside this machine (see [Publishing](#publishing-through-a-reverse-proxy)) |
| `cf_access_aud` | none | The Access application's Audience (AUD) tag |

Notes:

- **Embedding model.** A knowledge base keeps the embedding model it was built with. Once it holds vectors, the server
  refuses to start with a different one, so give a new model a new `data_dir`.
- **Rate limits.** Without a cookie file, YouTube tolerates roughly 300 Videos an hour; a signed-in cookie file allows
  about three times that. yt-dlp writes refreshed cookies back to the file, so it must be writable.
  `youtube_cookies_from_browser` reads the browser's own cookie store instead (the browser must be closed for Chrome and
  Chromium); the service then needs access to that profile. Sync waits between YouTube calls are jittered by ±30%.
- **Extractor arguments.** `youtube_extractor_args` is a TOML table whose values are strings or lists of strings:

  ```toml
  [youtube_extractor_args]
  player_client = ["mweb"]
  po_token = "mweb.gvs+<token>"
  ```

  In `MENTOR_YOUTUBE_EXTRACTOR_ARGS`, give the table's body, e.g. `player_client = ["mweb"]`. See yt-dlp's
  documentation of `--extractor-args youtube:` for what it accepts; a wrong value fails the next Sync with yt-dlp's
  message.
- **Allowed hosts.** `allowed_hosts` takes a TOML list, or a comma-separated string in `MENTOR_ALLOWED_HOSTS`.
  `host:*` allows any port. Loopback is always allowed. Every request's `Host`, `X-Forwarded-Host`, and `Origin` must
  name an allowed host, which stops a web page on another site from reaching mentor by pointing its hostname at this
  machine. Pages served from localhost on any port are allowed, so only run local web apps you trust.
  (This key was `mcp_allowed_hosts` before it covered the whole server.)

## Publishing through a reverse proxy

mentor only listens on 127.0.0.1, so to reach it from elsewhere, publish it through a reverse proxy on this machine,
with an identity gate such as Cloudflare Access in front. mentor has no login of its own: anyone who reaches a
published URL gets the whole API, the web chat (on your Claude subscription), and the `sql` tool.

1. Add the public hostname to `allowed_hosts`.
2. Have the proxy send `X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Forwarded-Host`. Traefik and Caddy do by
   default; nginx needs a `proxy_set_header` for each. A proxy that passes the public hostname as `Host` can skip
   `X-Forwarded-Host`; otherwise the `Host` it sends must be loopback (such as `127.0.0.1:7337`) or allowed. mentor uses
   these headers for the URLs it builds, and they tell it the request was relayed: **a proxy that sends none of them
   looks like a local request, so the Cloudflare Access check below lets it through.**
3. To publish under a path such as `https://mentor.example.com/mentor/`, have the proxy send
   `X-Forwarded-Prefix: /mentor`, as Traefik's StripPrefix does. It may strip the prefix or pass it through. The web UI,
   API, event stream, and `/mcp` all work under it, and mentor still answers at the root locally. mentor tells the two
   apart by whether the path starts with the prefix, so don't use one of its own top-level paths (`/api`, `/mcp`,
   `/assets`, `/docs`) as the prefix.
4. Don't let the proxy buffer responses: the event stream sends `X-Accel-Buffering: no` and a keepalive every 15
   seconds, and the web chat streams its answers the same way.

**Cloudflare Access verification** (optional, off by default) guards against a request that reaches the proxy
without going through Access, for example on the machine's own IP address. Set `cf_access_team_domain` to your team
domain (`myteam.cloudflareaccess.com`) and `cf_access_aud` to the application's Audience tag (in Zero Trust, under the
Access application's overview). Then every request needs a valid `Cf-Access-Jwt-Assertion` header, checked against your
team's signing keys, which mentor fetches and caches. The exception is a request made directly on this machine: from
loopback, with no `X-Forwarded-*`, `Forwarded`, `X-Real-IP`, or `Cf-*` headers, such as local agents, `mentor sync`,
and a browser on this machine. Refused requests get 403, and 503 while mentor can't fetch the keys at all. If your session expires while the web UI is open, it says
that live updates stopped; reload the page to sign in again.

## Register mentor with your agents

The MCP endpoint is `http://127.0.0.1:7337/mcp`, exactly: `/mcp/` with a trailing slash answers 405.

**Claude Code**, at user scope so every session has it:

```sh
claude mcp add --transport http --scope user mentor http://127.0.0.1:7337/mcp
```

**Codex:**

```sh
codex mcp add mentor --url http://127.0.0.1:7337/mcp
```

**Claude Desktop** connects to custom connectors from Anthropic's side, so it needs mentor's public URL rather than
localhost. [Publish the server](#publishing-through-a-reverse-proxy), behind an identity gate. Then, in Settings →
Connectors → Add custom connector, enter `https://mentor.example.com/mcp`.

The tools are `list_groups`, `search`, `expand`, `get_video`, and `sql`.

## Web chat

Each Mentor Group card has an Ask button, which answers through your own Claude CLI. Whether it can run shows in the
footer's "Claude CLI" entry, and in the `claude_cli` part of `/api/health` with a message saying what to do:

| State | What to do |
|---|---|
| `ready` | Nothing |
| `missing` | Install Claude Code, or set `claude_cli_path`, then rerun `mentor install-service` |
| `logged_out` | Run `claude auth login` |
| `api_key` | Claude Code would bill an API key instead of your subscription. The message names where the key comes from, for example an `apiKeyHelper` in Claude Code's settings; remove it there |
| `unknown` | `claude auth status` failed, hung, or answered unexpectedly; the message says which |

## Troubleshooting

**An agent says mentor is unreachable.**

1. Check that the server is up: `curl http://127.0.0.1:7337/api/health` should answer with `"status": "ok"`.
2. If it doesn't, check `systemctl --user status mentor` and `journalctl --user -u mentor -e`. Common causes:
   - an invalid config file (the log names the key)
   - another program on the port (set `port`, then update your agents' URLs)
   - a knowledge base built with a different embedding model
3. If the server answers but the agent can't connect, check the URL ends in exactly `/mcp`.
   - **421 "Invalid Host header":** the request came through a hostname not in `allowed_hosts`.
   - **403:** a browser-based client's `Origin` isn't an allowed host, or, with Cloudflare Access verification on, the
     request carried no valid Access token; the response says which.
   - **405:** the URL has a trailing slash.
4. After changing settings, restart the service, then restart the agent session (or `/mcp` in Claude Code to
   reconnect).

**Models fail to load.** The footer shows the error. Usually the GPU is out of memory, because another process holds
it. Free some memory, then `systemctl --user restart mentor`.

**Syncs fail with "Sign in to confirm you're not a bot" or rate limits.** Wait before syncing again, raise
`youtube_delay_seconds`, or add a `youtube_cookie_file`. If Videos fail on JavaScript challenges, check that `deno` is
on the PATH the service recorded, and rerun `mentor install-service` if it isn't.

**A Sync stopped mid-way.** Stopping the service can't interrupt a Sync waiting out YouTube's backoff, so it is killed
after 20 seconds. It resumes when the server starts again.

## Development

```sh
uv sync
pnpm --dir web install
pnpm --dir web run build          # the UI mentor serve uses from a checkout
uv run playwright install chromium  # for the browser smoke test
uv run pytest -q && uv run mypy && pnpm --dir web run typecheck
```

`uv run pytest -m real_youtube` and `uv run pytest -m real_models` run the opt-in tests against YouTube and the real
models.
