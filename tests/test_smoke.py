import asyncio
import re
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


async def test_add_a_channel_sync_search_group_chat_theme_and_reload(
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

            rail = page.get_by_role("navigation", name="Sections")
            main = page.get_by_role("main")
            # The app opens on Chats; every other section is reached from the rail.
            await expect(rail.get_by_role("button", name="Chats")).to_have_attribute("aria-current", "page")

            await rail.get_by_role("button", name="Library").click()
            # The add buttons live under the list column's tabs, not in the main pane.
            library = page.get_by_role("complementary", name="Library")
            await library.get_by_role("button", name="Add channel").click()
            add = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Add a channel"))
            await add.get_by_label("YouTube channel URL or handle").fill("@woodbywright")
            await add.get_by_role("button", name="Look up").click()
            await add.get_by_label("Channel name").fill("Wright")
            await add.get_by_role("button", name="Add", exact=True).click()

            # The added Channel is selected, so its page opens.
            await expect(main.get_by_role("heading", name="Wright")).to_be_visible()

            # Started from the Syncs view, so the list proves it updates live: the row arrives and finishes in place.
            await rail.get_by_role("button", name="Syncs").click()
            syncs = page.get_by_role("complementary", name="Syncs")
            await syncs.get_by_role("button", name="Sync all").click()
            sync_row = syncs.get_by_role("button").filter(has_text="Wright")
            await expect(sync_row).to_be_visible(timeout=15_000)
            await expect(sync_row).to_contain_text("Done", timeout=15_000)
            await sync_row.click()
            # The rule's legend counts the one Video the Channel published.
            await expect(main.get_by_role("img", name="1 done", exact=True)).to_be_visible()

            # ⌘K goes to Search with the cursor in the question; the form lives in the list column.
            await page.keyboard.press("ControlOrMeta+k")
            await expect(rail.get_by_role("button", name="Search")).to_have_attribute("aria-current", "page")
            search = page.get_by_role("complementary", name="Search")
            question = search.get_by_label("Question", exact=True)
            await expect(question).to_be_focused()
            await question.fill("plane across the grain")
            await search.get_by_role("button", name="Search", exact=True).click()
            result = (
                main.get_by_role("list", name="Results for plane across the grain")
                .get_by_role("listitem")
                .filter(has_text="Flattening a Workbench")
            )
            await result.get_by_role("button", name="Play at 0:15").click()
            embed = ("www.youtube-nocookie.com", "/embed/bench-flat1")
            # A result plays in the inspector, titled for what it does in this section.
            playing = page.get_by_role("complementary", name="Playing")
            assert await embedded_at(playing.locator("iframe")) == (*embed, ["15"])
            await playing.get_by_role("button", name="Show large").click()
            lightbox = page.get_by_role("dialog", name="Flattening a Workbench")
            assert await embedded_at(lightbox.locator("iframe")) == (*embed, ["15"])
            # Two players never run: the card gives its video to the lightbox until Esc brings it back.
            await expect(playing.locator("iframe")).to_have_count(0)
            await page.keyboard.press("Escape")
            await expect(lightbox).to_be_hidden()
            await expect(playing.locator("iframe")).to_have_count(1)

            await rail.get_by_role("button", name="Library").click()
            await library.get_by_role("tab", name="Groups").click()
            await library.get_by_role("button", name="New group").click()
            new_group = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="New group"))
            await new_group.get_by_label("Group name").fill("Benches")
            await new_group.get_by_role("button", name="Create").click()

            member = main.get_by_role("switch", name="Wright in Benches")
            await member.click()
            # Ticked once the server has saved it, which is also what enables the chat.
            await expect(member).to_be_checked()
            await main.get_by_role("button", name="New chat").click()

            await expect(main.get_by_role("heading", name="New chat in Benches")).to_be_visible()
            composer = main.get_by_role("form", name="Ask Benches")
            await composer.get_by_label("Question for Benches").fill("How do I flatten a bench?")
            await composer.get_by_role("button", name="Ask", exact=True).click()
            conversation = main.get_by_role("list", name="Conversation")
            await conversation.get_by_role("link", name="Wright, 1:05").click()
            sources = page.get_by_role("complementary", name="Sources")
            assert await embedded_at(sources.locator("iframe")) == (*embed, ["65"])
            # The saved Citation is listed once in the panel, and the chat is filed under its Group.
            await expect(sources.get_by_role("button").filter(has_text="Flattening a Workbench")).to_have_count(1)
            chats = page.get_by_role("complementary", name="Chats")
            await expect(chats.get_by_role("button", name=re.compile(r"^Benches"))).to_be_visible()
            await expect(chats.get_by_role("button").filter(has_text="How do I flatten a bench?")).to_be_visible()

            html = page.locator("html")
            await rail.get_by_role("button", name="Theme").click()
            await page.get_by_role("menuitem", name="Dark").click()
            await expect(html).to_have_class(re.compile(r"\bdark\b"))
            await rail.get_by_role("button", name="Theme").click()
            await page.get_by_role("menuitem", name="System").click()
            # The test browser reports a light system preference.
            await expect(html).not_to_have_class(re.compile(r"\bdark\b"))

            # The query string holds the view and the open Conversation, so a reload comes back to the same chat.
            opened = parse_qs(urlsplit(page.url).query)
            assert opened["view"] == ["chats"]
            conversation_id = opened["conversation"]
            assert conversation_id == [conversation_id[0]] and conversation_id[0].isdigit()
            await page.reload()
            reloaded = parse_qs(urlsplit(page.url).query)
            assert reloaded["view"] == ["chats"] and reloaded["conversation"] == conversation_id
            await expect(main.get_by_role("list", name="Conversation")).to_contain_text("Plane across the grain first")
            await expect(main.get_by_role("form", name="Ask Benches")).to_be_visible()
            await expect(rail.get_by_role("button", name="Chats")).to_have_attribute("aria-current", "page")

    assert errors == []
