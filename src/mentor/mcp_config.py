"""`mentor mcp-config`: the client configuration for Mentor's tools on this machine, and how to use it.

The configuration goes to stdout and the guidance to stderr, so `mentor mcp-config > .mcp.json` saves a file a
client can read while the guidance still shows in the terminal.
"""

from mentor.config import HOST, Config


def mcp_url(config: Config) -> str:
    # Exactly /mcp: the endpoint answers 405 with a trailing slash.
    return f"http://{HOST}:{config.port}/mcp"


def client_config(config: Config) -> dict[str, object]:
    """The `mcpServers` form Claude Code reads from .mcp.json, which other streamable HTTP clients share."""
    return {"mcpServers": {"mentor": {"type": "http", "url": mcp_url(config)}}}


def guidance(config: Config, running: bool) -> str:
    url = mcp_url(config)
    if running:
        state = f"Mentor is answering at http://{HOST}:{config.port}/ now."
    else:
        state = (
            f"Nothing is answering at http://{HOST}:{config.port}/ yet: run `mentor serve` and keep it running while "
            "your agent uses these tools."
        )
    return "\n".join([
        "The JSON on standard output registers Mentor's tools over streamable HTTP at this machine's loopback",
        "address.",
        "No API key or login is needed: the address reaches Mentor only from this machine.",
        "",
        "Claude Code, for every session:",
        f"  claude mcp add --transport http --scope user mentor {url}",
        "or, for one project, save the configuration as .mcp.json in it:",
        "  mentor mcp-config > .mcp.json",
        f"Another client that speaks streamable HTTP takes the same URL: {url}",
        "",
        "This does not register a Claude Desktop custom connector. Desktop reaches connectors from Anthropic's side,",
        "so it needs Mentor's public https URL ending in /mcp, set up as the README's section on publishing through",
        "a reverse proxy describes.",
        "",
        state,
    ])
