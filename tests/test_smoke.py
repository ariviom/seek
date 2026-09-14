import asyncio
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from harness import fake_channel, fake_video, said, serving
from playwright.async_api import ConsoleMessage, Locator, async_playwright, expect

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import ChatDone, TextDelta

WEB = Path(__file__).parents[1] / "web"


async def embedded_at(player: Locator) -> tuple[str, str, list[str]]:
    """The embed's host, path, and start seconds."""
    await expect(player).to_be_visible()
    src = urlsplit(await player.get_attribute("src") or "")
    return src.netloc, src.path, parse_qs(src.query)["start"]


async def test_add_a_channel_sync_search_and_watch_citations(
    config: Config,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    tmp_path: Path,
) -> None:
    # Built fresh, so the test never runs a stale bundle.
    bundle = tmp_path / "bundle"
    await asyncio.to_thread(
        subprocess.run,
        ["pnpm", "exec", "vite", "build", "--outDir", str(bundle), "--emptyOutDir", "--logLevel", "error"],
        cwd=WEB,
        check=True,
    )
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video(
            "bench-flat1",
            "Flattening a Workbench",
            cues=said(
                "Welcome back to the shop",
                "Today we flatten the bench",
                "First check it with winding sticks",
                "Then plane across the grain with a jack plane",
                "Finish along the grain",
            ),
        )
    )
    engine.script = [
        TextDelta("Plane across the grain first: **[Wright, 1:05](https://youtube.com/watch?v=bench-flat1&t=1m5s)**."),
        ChatDone("session-1"),
    ]
    app = create_app(config, transcripts, embedder, reranker, engine, static_dir=bundle)

    async with serving(app) as base_url, async_playwright() as playwright:
        async with await playwright.chromium.launch() as browser:
            page = await browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def console(message: ConsoleMessage) -> None:
                if message.type == "error":
                    errors.append(message.text)

            page.on("console", console)
            # Only the players' attributes are asserted, so nothing outside the server is loaded, YouTube included.
            await page.route(
                "**/*",
                lambda route: route.continue_() if route.request.url.startswith(base_url) else route.abort(),
            )
            await page.goto(base_url)

            await page.get_by_label("YouTube Channel URL or handle").fill("@woodbywright")
            await page.get_by_role("button", name="Look up").click()
            await page.get_by_label("Channel name").fill("Wright")
            await page.get_by_role("button", name="Add Channel").click()

            await page.get_by_role("button", name="Sync", exact=True).click()
            await expect(page.get_by_role("region", name="Syncs").get_by_text("Done", exact=True)).to_be_visible()

            await page.get_by_label("Question", exact=True).fill("plane across the grain")
            await page.get_by_role("button", name="Search", exact=True).click()
            result = (
                page.get_by_role("list", name="Results for plane across the grain")
                .get_by_role("listitem")
                .filter(has_text="Flattening a Workbench")
            )
            await result.get_by_role("link", name="Watch at 0:15").click()
            embed = ("www.youtube-nocookie.com", "/embed/bench-flat1")
            assert await embedded_at(result.locator("iframe")) == (*embed, ["15"])

            await page.get_by_label("Mentor Group name", exact=True).fill("Benches")
            await page.get_by_role("button", name="Create Group").click()
            member = page.get_by_role("list", name="Channels in Benches").get_by_label("Wright")
            # Ticked once the server has saved it.
            await member.click()
            await expect(member).to_be_checked()
            await page.get_by_role("button", name="Ask", exact=True).click()
            chat = page.get_by_role("region", name="Ask Benches")
            await chat.get_by_label("Question for the Mentor Group").fill("How do I flatten a bench?")
            await chat.get_by_role("button", name="Ask", exact=True).click()
            conversation = chat.get_by_role("list", name="Conversation")
            await conversation.get_by_role("link", name="Wright, 1:05").click()
            assert await embedded_at(conversation.locator("iframe")) == (*embed, ["65"])

    assert errors == []
