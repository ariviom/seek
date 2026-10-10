# Seek

Turns YouTube channels into a cited, searchable knowledge base. You add the YouTube channels you learn from, Sync
them, group them, and then ask questions: in the web UI, or from Claude Code, Codex, or Claude Desktop over MCP. Every
answer links back to the moment in the Video where it was said.

## Requirements

- [uv](https://docs.astral.sh/uv/); the optional Linux service also requires systemd
- Node 22.12 or later and pnpm, to build the web UI during install
- Inference uses NVIDIA CUDA when available, then Apple Silicon MPS, then CPU. CPU is supported but slower.
- [Deno](https://deno.com) on PATH: yt-dlp needs it to solve YouTube's JavaScript challenges
- For the web chat: either an Anthropic API key, or Claude Code installed and logged in to your subscription
- For live backups: the `sqlite3` command

## Install

Clone this repository to, say, `~/src/seek`, then install and run it in a terminal:

```sh
uv tool install ~/src/seek
uv tool update-shell   # once, if ~/.local/bin isn't on your PATH yet
seek serve
```

Foreground startup prints the loopback URL using the configured port (normally
<http://127.0.0.1:7337/>) and tells you that closing the terminal stops Seek. The startup
message announces the attempt; wait for Uvicorn's startup/listening confirmation before
opening the URL. Errors stay in the terminal. Use Ctrl+C to stop it. Initial startup creates
missing config and data directories, preserving any existing configuration and database.

Foreground mode does not need systemd. Off Linux, Sync is manual through the UI or
`seek sync`; `seek install-service` refuses with a pointer to `seek serve`, including
when `--timer` was requested. Apple Silicon hardware checks are currently deferred, so these
path and lifecycle rules do not claim a verified Mac installation. Windows path resolution
is preparatory work, not a supported native Windows release.

### Optional Linux service

Run `seek install-service` from an ordinary terminal (not an editor or agent session,
whose PATH the service would copy).

`seek install-service` writes `~/.config/systemd/user/seek.service`, enables it, starts it, and waits until the server
answers on <http://127.0.0.1:7337/>. From then on it starts whenever you log in. To start it at boot without logging in, run
`loginctl enable-linger`. To run it in the foreground instead, use `seek serve`.

The unit records the `seek` you ran and the PATH of the shell you ran it from, so the service finds `deno` the same
way you do. Unless `claude_cli_path` is configured, it also records the first `claude` on that PATH as it appears
there (for a standard install, the `~/.local/bin/claude` link, which survives Claude Code updates). It also copies any
`SEEK_*` variables that are set, plus `HF_HOME`, `HF_HUB_CACHE`, `CUDA_VISIBLE_DEVICES`, `CLAUDE_CONFIG_DIR`,
`XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, and `XDG_DATA_HOME`. It records nothing else, and it removes any
`ANTHROPIC_API_KEY` from the service's environment, because the chat would bill that key instead of your subscription.
It warns if `claude` or `deno` can't be found.

On first start, the models download into the Hugging Face cache (`~/.cache/huggingface`, or `HF_HOME`). They are about
2.2 GB. The health dot at the foot of the rail shows their progress: hover it for the reason, click it for the
details. Syncs wait until the models are ready, and until then Search answers
that they are still loading.

To upgrade a foreground installation, stop Seek with Ctrl+C, pull and reinstall, then start it again:

```sh
git -C ~/src/seek pull
uv tool install --reinstall ~/src/seek
seek serve
```

For a Linux service installation, replace the final command with `seek install-service`,
which refreshes the recorded environment and restarts the service.

Recorded variables override the config file, like any `SEEK_*` variable. That includes the recorded
`SEEK_CLAUDE_CLI_PATH`. Rerun `seek install-service` whenever they should change, including after you set
`claude_cli_path`. Other config file changes only need a restart: `systemctl --user restart seek`.

Status: `systemctl --user status seek`. Logs: `journalctl --user -u seek`.

## Sync from the command line or on a schedule

```sh
seek sync --all                        # every active Channel
seek sync --channel "Wood By Wright"   # one Channel, by its YouTube name or channel id
```

When the server is running, `seek sync` queues the Syncs there and returns; their progress and any failures show in
the web UI. When it isn't, `seek sync` loads the embedding model and runs the Syncs itself, returning when they finish
(it exits 1 if any failed). If the service is running but not answering yet, it waits up to 30 seconds for the server
first. Only one process runs Syncs at a time: a server started meanwhile waits for it, and a `seek sync` started
while another process runs Syncs waits for that process to run its Syncs too.

A Sync lists a Channel's videos and streams tabs (past livestreams included). Once a Channel has completed a Sync, later
Syncs stop listing at the first page of Videos already known, unless the Channel has a most-recent filter or the Sync
retries failures. A Video published in the last week without captions is retried by later Syncs, since YouTube may
still be generating them. When YouTube refuses the captions of three Videos in a row, the Sync stops and the failed
Videos wait for the next one; no Sync runs for `youtube_backoff_seconds`, doubling for each Sync in a row that stops so.

`seek reindex --all` (or `--channel`) Syncs the same way but first re-cuts and re-embeds every Video already indexed
from its stored Transcript, without fetching from YouTube again. Run it after upgrading to a Seek that indexes
passages differently; until each Video is done again it is out of search.

On Linux, to Sync every active Channel on a schedule, install the service with a timer:

```sh
seek install-service --timer                    # daily at midnight
seek install-service --timer "Mon *-*-* 04:00"   # any systemd calendar expression
```

This also writes `seek-sync.service` and `seek-sync.timer`, with the same recorded environment. A run missed while
the machine was off happens at the next chance. Rerunning `seek install-service` without `--timer` keeps an
installed timer's schedule and updates its recorded environment; pass `--timer` again to change the schedule. Next
run: `systemctl --user list-timers seek-sync.timer`. Logs: `journalctl --user -u seek-sync`. To turn it off:
`systemctl --user disable --now seek-sync.timer`.

## Check on it from the command line

```sh
seek status   # the server, its models, both chat engines, and running and queued Syncs
seek list     # Channels, active or paused, with ready, failed, and excluded Videos and when each last synced, then Groups with their Channels
```

Both ask the running server. When none answers, they read the knowledge base instead: `seek status` then says the
server isn't running (only the server loads the models) and checks both chat engines itself.

When something is wrong, `seek doctor` prints one block to paste to whoever is helping: versions, platform, paths,
settings, each model's device and state, both chat engines, yt-dlp and JavaScript runtimes, the database's schema and
row counts, and the latest stored errors. The API key, YouTube extractor argument values and cookie settings are
redacted everywhere in it. Without a server it reads what it safely can and says what it couldn't; it never loads a
model, creates or migrates the database, or contacts a provider.

## Data

Default directories depend on the platform:

| Platform | Configuration directory | Data directory |
| --- | --- | --- |
| Linux | `~/.config/seek` | `~/.local/share/seek` |
| macOS | `~/Library/Application Support/seek` | `~/Library/Application Support/seek` |
| Windows (preparatory) | `%APPDATA%\seek` | `%LOCALAPPDATA%\seek` |

On Windows, missing application-data variables fall back to `~/AppData/Roaming/seek` for
config and `~/AppData/Local/seek` for data. An explicit `XDG_CONFIG_HOME` or `XDG_DATA_HOME`
takes precedence on **every** platform, with `seek` appended. The `data_dir` setting or
`SEEK_DATA_DIR` overrides the data location independently of the config directory.
All commands use the same resolution rules. `status` and `list` do not create an empty
knowledge base just to report that none exists.

The data directory contains:

- `seek.db` holds the whole knowledge base in one SQLite file: Channels, Groups, Transcripts, Segments, vectors,
  and Conversations.
- `chat/` is the empty working directory the web chat runs the Claude CLI in when no project directory is attached.

Backup is a copy of `seek.db`. The database uses WAL mode, so recent changes can sit in `seek.db-wal` beside it.
Either stop the service and copy both files, or take a consistent single-file copy while it runs:

```sh
# Linux default; substitute your platform's data directory or configured override.
sqlite3 ~/.local/share/seek/seek.db ".backup $HOME/seek-backup.db"
```

## Configuration

The config file holds operational settings, the database `settings` table holds user preferences,
and the OS keychain holds secrets (with a private fallback file where necessary). The Settings screen
in the app (the gear in the rail) manages the preferences and the key; these never belong in `config.toml`,
and nothing in `config.toml` is editable from the app.

`GET /api/settings` reads preferences; `PATCH /api/settings` updates supplied fields only:
`engine` accepts `api`, `cli`, or `null` (automatic); `provider` is `anthropic`; `model` is
`fast` (default) or `deep`. These preferences persist across restarts, and a change reaches your next
question rather than one already being answered. See [Web chat](#web-chat) for what each engine does
with them.

`PUT /api/credentials/anthropic` accepts a JSON `key` field, stores it, and makes one authenticated
[model-list request](https://platform.claude.com/docs/en/api/models/list) with no retries or generated tokens.
GET reads presence, last-known validity, and whether the key is in the keychain or the private fallback
file, with the reason; DELETE removes the credential without a restart.
Responses never contain the key. Validity is `valid`, `invalid` after authentication rejection,
or `unverified` when validation cannot complete (for example, offline or rate limited).
Health never contacts Anthropic. `ANTHROPIC_API_KEY` is never a credential fallback.
Successful writes publish `settings` or `credentials` events so clients can reload safe state.

Credentials normally live in the OS keychain via `keyring`. If the keychain is unavailable, locked,
or refuses access, Seek uses owner-only `secrets.json` in the data directory. That file also
records which credential copy is current so an old copy cannot return after replacement or deletion.
Keep it with the data directory. If a keychain read fails after a restart and no fallback copy exists,
Seek reports the credential unavailable until the keychain is unlocked or the key is replaced.
On macOS, replacing the interpreter during an upgrade can trigger a keychain allow/always-allow prompt.
Real Mac verification remains deferred until hardware is available.

Operational settings are read from `config.toml` in the configuration directory above. The file is optional;
startup creates the directory, not a replacement config file. An environment variable `SEEK_<KEY>`
overrides any key; for example, `SEEK_PORT=7400` overrides `port`. Unknown keys are an error.

```toml
port = 7400
youtube_cookie_file = "/home/me/.config/seek/cookies.txt"
allowed_hosts = ["seek.example.com"]
```

| Key | Default | Meaning |
|---|---|---|
| `data_dir` | Platform data directory above | Where `seek.db` lives (an absolute path) |
| `port` | `7337` | Port on 127.0.0.1 (and every interface with `listen_all_interfaces`) |
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
| `claude_cli_path` | `claude` on PATH | The Claude CLI the web chat drives on the Claude CLI engine |
| `cf_access_team_domain` | none | With `cf_access_aud`, requires a Cloudflare Access token on requests from outside this machine (see [Publishing](#publishing-through-a-reverse-proxy)) |
| `cf_access_aud` | none | The Access application's Audience (AUD) tag |
| `listen_all_interfaces` | `false` | Listen on every network interface, not only 127.0.0.1; needs the two Access keys (see [Publishing](#publishing-through-a-reverse-proxy)) |

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

  In `SEEK_YOUTUBE_EXTRACTOR_ARGS`, give the table's body, e.g. `player_client = ["mweb"]`. See yt-dlp's
  documentation of `--extractor-args youtube:` for what it accepts; a wrong value fails the next Sync with yt-dlp's
  message.
- **Allowed hosts.** `allowed_hosts` takes a TOML list, or a comma-separated string in `SEEK_ALLOWED_HOSTS`.
  `host:*` allows any port. Loopback is always allowed. Every request's `Host`, `X-Forwarded-Host`, and `Origin` must
  name an allowed host, which stops a web page on another site from reaching Seek by pointing its hostname at this
  machine. Pages served from localhost on any port are allowed, so only run local web apps you trust.
  (This key was `mcp_allowed_hosts` before it covered the whole server.)

## Publishing through a reverse proxy

Seek listens on 127.0.0.1, so to reach it from elsewhere, publish it through a reverse proxy on this machine,
with an identity gate such as Cloudflare Access in front, or [let Cloudflare reach it directly](#without-a-proxy). Seek has no login of its own: anyone who reaches a
published URL gets the whole API, the web chat (on your Claude subscription), and the `sql` tool.

1. Add the public hostname to `allowed_hosts`.
2. Have the proxy send `X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Forwarded-Host`. Traefik and Caddy do by
   default; nginx needs a `proxy_set_header` for each. A proxy that passes the public hostname as `Host` can skip
   `X-Forwarded-Host`; otherwise the `Host` it sends must be loopback (such as `127.0.0.1:7337`) or allowed. Seek uses
   these headers for the URLs it builds, and they tell it the request was relayed: **a proxy that sends none of them
   looks like a local request, so the Cloudflare Access check below lets it through.**
3. To publish under a path such as `https://seek.example.com/seek/`, have the proxy send
   `X-Forwarded-Prefix: /seek`, as Traefik's StripPrefix does. It may strip the prefix or pass it through. The web UI,
   API, event stream, and `/mcp` all work under it, and Seek still answers at the root locally. Seek tells the two
   apart by whether the path starts with the prefix, so don't use one of its own top-level paths (`/api`, `/mcp`,
   `/assets`, `/docs`) as the prefix.
4. Don't let the proxy buffer responses: the event stream sends `X-Accel-Buffering: no` and a keepalive every 15
   seconds, and the web chat streams its answers the same way.

**Cloudflare Access verification** (optional, off by default) guards against a request that reaches the proxy
without going through Access, for example on the machine's own IP address. Set `cf_access_team_domain` to your team
domain (`myteam.cloudflareaccess.com`) and `cf_access_aud` to the application's Audience tag (in Zero Trust, under the
Access application's overview). Then every request needs a valid `Cf-Access-Jwt-Assertion` header, checked against your
team's signing keys, which Seek fetches and caches. The exception is a request made directly on this machine: from
loopback, with no `X-Forwarded-*`, `Forwarded`, `X-Real-IP`, or `Cf-*` headers, such as local agents, `seek sync`,
and a browser on this machine. Refused requests get 403, and 503 while Seek can't fetch the keys at all. If your session expires while the web UI is open, it says
that live updates stopped; reload the page to sign in again.

### Without a proxy

If your Cloudflare-proxied hostname already reaches this machine's port (a router forwarding it, as for other apps
on the machine), Seek can listen on every interface instead:

```toml
allowed_hosts = ["seek.example.com"]
cf_access_team_domain = "myteam.cloudflareaccess.com"
cf_access_aud = "…"
listen_all_interfaces = true
```

Seek refuses to start this way without the two Access keys. With them, a request from any other machine needs a
valid Access token, so reaching the port directly (on your public IP or from the LAN) gets 403; only requests through
Access, and requests made on this machine, get through. Restart the service after changing it.

## Register Seek with your agents

The MCP endpoint is `http://127.0.0.1:7337/mcp`, exactly: `/mcp/` with a trailing slash answers 405.
`seek mcp-config` prints the client configuration for the configured port as JSON on stdout, with registration
instructions on stderr, so `seek mcp-config > .mcp.json` saves a project configuration Claude Code reads.

**Claude Code**, at user scope so every session has it:

```sh
claude mcp add --transport http --scope user seek http://127.0.0.1:7337/mcp
```

**Codex:**

```sh
codex mcp add seek --url http://127.0.0.1:7337/mcp
```

**Claude Desktop** connects to custom connectors from Anthropic's side, so it needs Seek's public URL rather than
localhost. [Publish the server](#publishing-through-a-reverse-proxy), behind an identity gate. Then, in Settings →
Connectors → Add custom connector, enter `https://seek.example.com/mcp`.

The tools are `list_groups`, `list_channels`, `search` (scoped to a `group` or a list of `channels`), `expand`,
`get_video`, and `sql`.

## Settings

The gear in the rail opens Settings, which is everything that is yours: which engine answers, the Anthropic API key,
and the default model. It also shows, read-only, what each engine needs before it can answer and which device and
precision the embedding and reranking models are running at.

Pasting a key validates it there and says whether Anthropic accepted it, rejected it, or didn't answer. The key
is never shown again, never returned by the server, and never kept in the browser. If the keychain refused it,
or cannot be read, the screen says so and still lets you replace or delete the key. Accepting a key brings the
chat box to life in every open tab without a reload, unless you have chosen the Claude CLI as your engine; and
whenever the engine that would answer can't, the chat box is disabled and points here instead of failing a
question you have already typed.

Changing the default model reaches your next question. A chat that pinned its own model keeps it and says
`Pinned: …`; one following the setting says `Default: …`.

## Web chat

A chat in a Group or a Channel answers through one of two engines: the **Anthropic API**, using a key you store in
Settings (or `PUT /api/credentials/anthropic`), or your own **Claude CLI**, using the Claude Code login you already
have. Both get
the same scoped Seek tools, the same grounded-advisor prompt, and the same streamed answers with Citations.

Chat is the only thing an engine gates. Search, the Library, Syncs and the MCP tools work without either.

With no stored preference, Seek uses the API engine when a key is present and the Claude CLI otherwise. Set
`engine` in `PATCH /api/settings` to `"api"` or `"cli"` to choose deliberately, or to `null` to go back to automatic.
A preference whose requirement is missing is an error that says what to add, not a quiet switch to the other engine.

Both engines' availability shows in the rail's health dot (hover it for the reason, click it for the details) and in
the `chat` part of `/api/health`, which reports `active` — the engine the next turn would use, or `null` when neither
can answer — and a state per engine with a message saying what to do:

| Engine | State | What to do |
|---|---|---|
| both | `ready` | Nothing |
| api | `no_key` | Store an Anthropic API key; create one at <https://console.anthropic.com/settings/keys> |
| api | `invalid_key` | The stored key was rejected when it was entered or during a turn; replace it |
| cli | `missing` | Install Claude Code, or set `claude_cli_path`, then rerun `seek install-service` |
| cli | `logged_out` | Run `claude auth login` |
| cli | `api_key` | Claude Code would bill an API key instead of your subscription. Seek already keeps `ANTHROPIC_API_KEY` out of the CLI it runs, so this names another source, such as an `apiKeyHelper` in Claude Code's settings; remove it there |
| both | `unknown` | The credential store or `claude auth status` couldn't be read; the message says which |

Health never calls the provider: it reports the last known state of the key, so an offline machine says what it knew
rather than flapping. A key is checked once when you store it, and again only by a turn that it fails.

`model` in `PATCH /api/settings` picks `"fast"` or `"deep"`, which each engine maps to its own identifier — the API
engine to `claude-sonnet-5` and `claude-opus-5`, the Claude CLI to its `sonnet` and `opus` aliases. A model set on a
Conversation is a pin and wins for that Conversation; the rest follow the setting from their next question, including
mid-thread. A pin travels between engines — a Conversation pinned to `opus` on the Claude CLI asks the API engine for
`claude-opus-5`, and back again — and a pin the API engine cannot express is refused before the question is saved rather than
quietly changed (the Claude CLI accepts names Seek doesn't know, so it does its own rejecting). Note
that an unpinned Conversation on the Claude CLI now asks for `sonnet` explicitly; letting Claude Code pick its own
default is no longer an option, because the setting has to mean something on both engines. Each message records the engine and model that produced it, and each question records what its turn
reported using, so a Conversation can total its tokens. A turn that failed or was stopped keeps what it had already
reported and says the total is incomplete rather than claiming to be a bill. The chat shows those totals under the
chat box — input, output and cache reads — and says the real total is higher when a turn didn't report what it
used. Older Conversations say their usage wasn't recorded rather than showing a zero.

The **Add context** control beside the chat box can give a new Conversation read-only access to one local project
directory, the public web, or both. Those tools are Claude Code built-ins, so they are a Claude CLI capability only:
the control is hidden while the API engine is active, and the API engine refuses such a Conversation before making any
request rather than answering without them. A Conversation that already has context keeps showing what it holds even
on the API engine, with a line saying to switch this chat to the Claude CLI or start a new one; nothing is removed. Context is fixed after the first question so a resumed Claude session keeps
the same working directory and capabilities. Project access exposes only file reading, listing, and search within the
selected directory; web access exposes Claude Code's web search and fetch tools. User settings, plugins, skills, other
MCP servers, file editing, and shell commands stay disabled. Channel-derived advice still needs Seek's timestamped
citations, while observations from a project or web page are identified separately.

## Troubleshooting

**An agent says Seek is unreachable.**

1. Check that the server is up: `curl http://127.0.0.1:7337/api/health` should answer with `"status": "ok"`.
2. If it doesn't, check `systemctl --user status seek` and `journalctl --user -u seek -e`. Common causes:
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

**Models fail to load.** The rail's health dot turns red; hover it for the reason, click it for the details.
`seek status` and Server health show each model's device, precision and fallback reason. CUDA uses bfloat16 where
supported and float32 otherwise; MPS and CPU use float32. If MPS reranking fails during warm-up or a search, only
the reranker retries on CPU. If that also fails, search still returns fused results without reranking; their order
may be less accurate. The embedding model must be ready for search and Syncs.

If CUDA runs out of memory, free GPU memory and restart Seek. A Video that runs out of CUDA memory during
embedding can be retried without losing its transcript. Allocation failures on MPS or CPU are reported as model
failures. A missing model cache needs an online restart to download it; download progress remains visible in
the terminal and web UI. With both models fully cached, `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 seek serve`
starts and searches locally without network access. YouTube Sync and provider chat still need connectivity.

**Syncs fail with "Sign in to confirm you're not a bot" or rate limits.** Wait before syncing again, raise
`youtube_delay_seconds`, or add a `youtube_cookie_file`. If Videos fail on JavaScript challenges, check that `deno` is
on the PATH the service recorded, and rerun `seek install-service` if it isn't.

**A Sync stopped mid-way.** Stopping the service can't interrupt a Sync waiting out YouTube's backoff, so it is killed
after 20 seconds. It resumes when the server starts again.

## Development

```sh
uv sync
pnpm --dir web install
pnpm --dir web run build          # the UI seek serve uses from a checkout
uv run playwright install chromium  # for the browser smoke test
uv run pytest -q && uv run mypy && pnpm --dir web run typecheck
```

`uv run pytest -m real_youtube` and `uv run pytest -m real_models` run the opt-in tests against YouTube and the real
models.
