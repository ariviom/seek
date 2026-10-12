import asyncio
import re
import subprocess
from itertools import groupby
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2
import pytest
from api_transport import Provider, ToolUse, answer
from harness import (
    WRIGHT_AVATAR,
    Gate,
    add_channel,
    add_group,
    add_playlist,
    bundle_config,
    fake_channel,
    fake_storyboard,
    fake_video,
    list_playlist_videos,
    said,
    serving,
    start_playlist_sync,
    sync,
    wait_for_syncs,
)
from playwright.async_api import ConsoleMessage, Locator, Page, Route, async_playwright, expect

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakePlaylist, FakeReranker, FakeSecrets, FakeTranscriptSource
from seek.ports import ChatDone, ChatEngineStatus, TextDelta, VideoUnavailable

WEB = Path(__file__).parents[1] / "web"
# A storyboard sheet as the page would load one: three by three tiles of 320x180.
QUESTION = "plane across the grain"
SHEET = b'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><rect width="960" height="540" fill="#444"/></svg>'
AVATAR = b'<svg xmlns="http://www.w3.org/2000/svg" width="176" height="176"><rect width="176" height="176" fill="#a52"/></svg>'



@pytest.fixture(scope="session")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The web bundle, built once per session, so no test can run a stale one."""
    built = tmp_path_factory.mktemp("bundle")
    subprocess.run(
        ["pnpm", "exec", "vite", "build", "--outDir", str(built), "--emptyOutDir", "--logLevel", "error"],
        cwd=WEB,
        check=True,
    )
    return built


@asynccontextmanager
async def browsing(base_url: str) -> AsyncIterator[tuple[Page, list[str]]]:
    """A page on the served app, collecting its console and page errors.

    Every request that isn't to the server is aborted, so nothing outside it is loaded, YouTube included.
    """
    async with async_playwright() as playwright:
        async with await playwright.chromium.launch() as browser:
            page = await browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def console(message: ConsoleMessage) -> None:
                if message.type == "error":
                    errors.append(message.text)

            page.on("console", console)
            await page.route(
                "**/*",
                lambda route: route.continue_() if route.request.url.startswith(base_url) else route.abort(),
            )
            # Storyboard sheets are answered here with a grid-sized image, since the page must be able to load one
            # and must not load it from YouTube. Registered last, which is what gives it priority over the abort.
            await page.route("**/sb/**", lambda route: route.fulfill(body=SHEET, content_type="image/svg+xml"))
            # Channel avatars likewise, so a Channel with one shows it rather than falling back to initials.
            await page.route(
                "https://yt3.googleusercontent.com/**",
                lambda route: route.fulfill(body=AVATAR, content_type="image/svg+xml"),
            )
            yield page, errors


async def peek_width(peek: Locator) -> float:
    """The width of the card a frame opens, which is one fixed size for every storyboard tier."""
    box = await peek.bounding_box()
    assert box is not None
    return float(box["width"])


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
    bundle: Path,
    tmp_path: Path,
) -> None:
    # The first fetch is held, so the live status is on screen long enough to read.
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video(
            "bench-flat1",
            "Flattening a Workbench",
            before_fetch=gate,
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

    async with serving(app) as base_url:
        # Only the players' attributes are asserted, so nothing outside the server is needed.
        async with browsing(base_url) as (page, errors):
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

            # The Videos card and the Library row follow the Sync live, then settle on what was synced.
            channel_row = library.get_by_role("button").filter(has_text="Wright")
            videos_card = main.locator("section").filter(has=page.get_by_role("heading", name="Videos"))
            await main.get_by_role("button", name="Sync now").click()
            await expect(channel_row).to_contain_text("Syncing", timeout=15_000)
            await expect(videos_card).to_contain_text("Syncing", timeout=15_000)
            gate.released.set()
            await expect(channel_row).to_contain_text(re.compile(r"1 video · synced "), timeout=15_000)
            await expect(videos_card).to_contain_text("last synced", timeout=15_000)

            # A second Sync started from the Syncs view, so the list proves it updates live: its row arrives above
            # the first and finishes in place.
            await rail.get_by_role("button", name="Syncs").click()
            syncs = page.get_by_role("complementary", name="Syncs")
            await syncs.get_by_role("button", name="Sync all").click()
            wright_rows = syncs.get_by_role("button").filter(has_text="Wright")
            await expect(wright_rows).to_have_count(2, timeout=15_000)
            sync_row = wright_rows.first
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
            await composer.get_by_role("button", name="Add chat context").click()
            await page.get_by_label("Project directory").fill(str(tmp_path))
            await page.get_by_role("switch", name="Browse the web").click()
            await page.keyboard.press("Escape")
            await composer.get_by_label("Question for Benches").fill("How do I flatten a bench?")
            await composer.get_by_role("button", name="Ask", exact=True).click()
            conversation = main.get_by_role("list", name="Conversation")
            await conversation.get_by_role("link", name="Wright, 1:05").click()
            sources = page.get_by_role("complementary", name="Sources")
            assert await embedded_at(sources.locator("iframe")) == (*embed, ["65"])
            # The saved Citation is listed once in the panel, and the chat is filed under its Group.
            await expect(sources.get_by_role("button").filter(has_text="Flattening a Workbench")).to_have_count(1)
            # Under the answer its Sources stay folded behind their count until asked for.
            answer_sources = conversation.get_by_role("list", name="Sources")
            referenced = conversation.get_by_role("button", name="1 Video Referenced")
            await expect(referenced).to_have_attribute("aria-expanded", "false")
            await expect(answer_sources).to_have_count(0)
            await referenced.click()
            await expect(answer_sources.get_by_role("button").first).to_contain_text("Flattening a Workbench")
            chats = page.get_by_role("complementary", name="Chats")
            await expect(chats.get_by_role("button", name=re.compile(r"^Benches"))).to_be_visible()
            await expect(chats.get_by_role("button").filter(has_text="How do I flatten a bench?")).to_be_visible()
            await expect(composer.get_by_role("button", name=re.compile(r"^Chat context:"))).to_be_visible()

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

            # Health names both engines and which one answers, from the `chat` field that replaced
            # `claude_cli`: a client still reading the old one would render nothing here.
            await rail.get_by_role("button", name=re.compile("^Health:")).click()
            health = page.get_by_role("dialog", name="Server health")
            await expect(health).to_contain_text("Chat engine")
            await expect(health).to_contain_text("Anthropic API")
            await expect(health).to_contain_text("Claude CLI")
            # The API engine has no key here, and says where to get one rather than just failing.
            await expect(health).to_contain_text("console.anthropic.com")

    assert errors == []
    [chat_request] = engine.requests
    assert (chat_request.workspace, chat_request.web_access) == (tmp_path.resolve(), True)


async def test_setting_up_chat_in_the_app_and_seeing_what_a_conversation_used(
    config: Config,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A friend with neither engine ready reaches chat through the settings screen, without editing a file."""
    # The real API engine over a fake credential store, so entering a key is what makes chat possible, and a
    # scripted provider, so every answer and every token count is deterministic.
    def answered() -> bytes:
        return answer(
            "Plane across the grain: [Wright, 1:05](https://youtube.com/watch?v=bench-flat1&t=1m5s).",
            input_tokens=100,
            output_tokens=20,
            cache_read_tokens=5,
        )

    # Three answered turns, then a turn that reports its first request's usage and fails on its second, so the
    # totals have to show an incomplete count rather than losing what was already reported.
    provider = Provider(
        script=[
            answered(),
            answered(),
            answered(),
            answer(
                "Looking.",
                tools=[ToolUse("call-1", "search", {"query": "flatten a bench"})],
                stop_reason="tool_use",
                input_tokens=100,
                output_tokens=20,
                cache_read_tokens=5,
            ),
            500,
        ]
    )
    turns = provider.hook()

    async def send(client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: object) -> httpx2.Response:
        # Entering a key lists models once; everything else is a chat turn.
        if request.url.path == "/v1/models":
            return httpx2.Response(
                200, json={"data": [], "has_more": False, "first_id": None, "last_id": None}, request=request
            )
        return await turns(client, request, **kwargs)

    monkeypatch.setattr(httpx2.AsyncClient, "send", send)
    cli = FakeChatEngine(
        "cli", engine_status=ChatEngineStatus("cli", "missing", None, "The Claude CLI was not found on PATH")
    )
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("bench-flat1", "Flattening a Workbench", cues=said("Plane across the grain with a jack plane"))
    )
    app = create_app(config, transcripts, embedder, reranker, cli, static_dir=bundle, secrets=FakeSecrets())

    async with serving(app) as base_url:
        # The Channel is seeded through the API: this test is about what happens after there is something to ask.
        async with httpx.AsyncClient(base_url=base_url) as seed:
            channel = await add_channel(seed, "@woodbywright", "Wright")
            await sync(seed, channel)
            await add_group(seed, "Benches", channel)

        async with browsing(base_url) as (page, errors):
            await page.goto(base_url)
            rail = page.get_by_role("navigation", name="Sections")
            main = page.get_by_role("main")

            # Everything that doesn't need an engine works with no key at all.
            await rail.get_by_role("button", name="Library").click()
            await expect(page.get_by_role("complementary", name="Library")).to_contain_text("Wright")
            await rail.get_by_role("button", name="Syncs").click()
            await expect(
                page.get_by_role("complementary", name="Syncs").get_by_role("button").filter(has_text="Wright")
            ).to_have_count(1)
            await page.keyboard.press("ControlOrMeta+k")
            search = page.get_by_role("complementary", name="Search")
            await search.get_by_label("Question", exact=True).fill("plane across the grain")
            await search.get_by_role("button", name="Search", exact=True).click()
            await expect(main.get_by_role("list", name="Results for plane across the grain")).to_contain_text(
                "Flattening a Workbench"
            )

            # Chat is the one dead end, and it is a signpost: the question box is disabled and says where to go.
            await rail.get_by_role("button", name="Chats").click()
            chats = page.get_by_role("complementary", name="Chats")
            await chats.get_by_role("button", name="New chat", exact=True).click()
            await page.get_by_role("menuitem", name="Benches").click()
            composer = main.get_by_role("form", name="Ask Benches")
            question = composer.get_by_label("Question for Benches")
            await expect(question).to_be_disabled()
            await expect(composer.get_by_role("button", name="Ask", exact=True)).to_be_disabled()
            await main.get_by_role("button", name="Open settings").click()

            # The settings screen says what each engine needs, before anything has been chosen.
            settings = main.get_by_role("region", name="Settings")
            await expect(settings).to_contain_text("console.anthropic.com")
            await expect(settings).to_contain_text("The Claude CLI was not found on PATH")

            await settings.get_by_label("Anthropic API key").fill("sk-ant-smoke-test-key")
            await settings.get_by_role("button", name="Save key").click()
            await expect(settings).to_contain_text("Key accepted", timeout=15_000)
            # Nothing reads the key back into the page.
            await expect(settings.get_by_label("Anthropic API key")).to_have_value("")
            assert "sk-ant-smoke-test-key" not in await page.content()

            # Back in the chat that was a dead end a moment ago: alive, and without a reload.
            await rail.get_by_role("button", name="Chats").click()
            await expect(composer).to_be_visible()
            await expect(question).to_be_enabled(timeout=15_000)
            await question.fill("How do I flatten a bench?")
            await composer.get_by_role("button", name="Ask", exact=True).click()
            await expect(main.get_by_role("list", name="Conversation")).to_contain_text(
                "Plane across the grain", timeout=15_000
            )
            # What the provider reported for this Conversation, counted rather than priced.
            await expect(main).to_contain_text("100 in · 20 out · 5 cache read", timeout=15_000)

            # The default model is a preference, and it survives a reload.
            await rail.get_by_role("button", name="Settings").click()
            await expect(settings).to_be_visible()
            await settings.get_by_label("Default model").click()
            await page.get_by_role("option", name=re.compile("^Deep")).click()
            await expect(settings.get_by_label("Default model")).to_contain_text("Opus 5")
            await page.reload()
            await expect(settings.get_by_label("Default model")).to_contain_text("Opus 5", timeout=15_000)

            # This Conversation pinned nothing, so its next question follows the new default.
            await rail.get_by_role("button", name="Chats").click()
            await expect(composer).to_be_visible()
            await expect(composer).to_contain_text("Default: Opus 5 (deep)", timeout=15_000)
            await question.fill("And the legs?")
            await composer.get_by_role("button", name="Ask", exact=True).click()
            await expect(main).to_contain_text("200 in · 40 out · 10 cache read", timeout=15_000)

            # A pinned Conversation keeps its own model whatever the default becomes, and says which it is.
            await chats.get_by_role("button", name="New chat", exact=True).click()
            await page.get_by_role("menuitem", name="Benches").click()
            await composer.get_by_label("Model").click()
            await page.get_by_role("option", name="Sonnet 5 (fast)").click()
            await question.fill("What about the vise?")
            await composer.get_by_role("button", name="Ask", exact=True).click()
            await expect(main.get_by_role("list", name="Conversation")).to_contain_text(
                "Plane across the grain", timeout=15_000
            )
            await expect(composer).to_contain_text("Pinned: Sonnet 5 (fast)")

            # A turn that fails after the provider reported one request keeps that count, and says the total is
            # only a floor rather than pretending the failure cost nothing.
            await question.fill("And the top?")
            await composer.get_by_role("button", name="Ask", exact=True).click()
            await expect(main).to_contain_text("200 in · 40 out · 10 cache read", timeout=15_000)
            await expect(main).to_contain_text("Some turns didn’t report theirs")

            # Deleting the key takes chat back to where it started, which is how a friend undoes the setup.
            await rail.get_by_role("button", name="Settings").click()
            await expect(settings).to_be_visible()
            await settings.get_by_role("button", name="Delete key").click()
            confirm = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Delete key"))
            await confirm.get_by_role("button", name="Delete key").click()
            await expect(settings).to_contain_text("No key saved yet.", timeout=15_000)
            await rail.get_by_role("button", name="Chats").click()
            await expect(question).to_be_disabled(timeout=15_000)

    assert errors == []
    # Each turn's first request, in order: the unpinned Conversation followed the default from fast to deep, and
    # the pinned one stayed on Sonnet 5 however the default moved. The rest are the last turn's tool step and the
    # SDK's retries of the failure, all on that same pinned model.
    models = [body["model"] for body in provider.bodies]
    assert models[:4] == ["claude-sonnet-5", "claude-opus-5", "claude-sonnet-5", "claude-sonnet-5"]
    assert set(models[4:]) == {"claude-sonnet-5"}


async def test_adding_a_channel_advises_starting_small_and_a_running_sync_reports_what_is_ready(
    config: Config,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    bundle: Path,
    tmp_path: Path,
) -> None:
    # Held across browser assertions rather than API calls, so the holds outlast a page load.
    first = Gate(seconds=30)
    last = Gate(seconds=30)
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-one", "Winding sticks", before_fetch=first, cues=said("Check it with winding sticks")),
        fake_video("v-two", "Jack plane", cues=said("Plane across the grain")),
        fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only video", permanent=True)),
        fake_video("v-three", "Sharpening", cues=said("Hone the chisel")),
        fake_video("v-four", "Finishing", before_fetch=last, cues=said("Then oil it")),
    ]
    app = create_app(config, transcripts, embedder, reranker, engine, static_dir=bundle)

    async with serving(app) as base_url:
        # YouTube offers no avatar for this one.
        async with httpx.AsyncClient(base_url=base_url) as api:
            await add_channel(api, "@rexkrueger")
        async with browsing(base_url) as (page, errors):
            await page.goto(base_url)
            main = page.get_by_role("main")
            await page.get_by_role("navigation", name="Sections").get_by_role("button", name="Library").click()
            library = page.get_by_role("complementary", name="Library")
            await library.get_by_role("button", name="Add channel").click()
            add = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Add a channel"))
            # The advice is there to be read while the choice of Channel is still open.
            await expect(add).to_contain_text("Start with a small channel")
            await add.get_by_label("YouTube channel URL or handle").fill("@woodbywright")
            await add.get_by_role("button", name="Look up").click()
            await add.get_by_role("button", name="Add", exact=True).click()

            # The added Channel shows the avatar YouTube offered, loaded rather than fallen back from; the one
            # without an avatar shows its initials.
            wright_row = library.get_by_role("listitem").filter(has_text="Wood By Wright")
            avatar = wright_row.locator("img")
            await expect(avatar).to_have_attribute("src", WRIGHT_AVATAR)
            await expect(avatar).to_have_js_property("naturalWidth", 176)
            rex_row = library.get_by_role("listitem").filter(has_text="Rex Krueger")
            await expect(rex_row).to_contain_text("RK")
            await expect(rex_row.locator("img")).to_have_count(0)

            videos_card = main.locator("section").filter(has=page.get_by_role("heading", name="Videos"))
            await main.get_by_role("button", name="Sync now").click()
            # Discovery has found the work, but one Video in nothing is claimed about how fast it will go.
            await expect(videos_card).to_contain_text("0 of 5 videos", timeout=15_000)
            await expect(videos_card).to_contain_text("measuring speed")
            first.released.set()

            # Four Videos have been worked through; the one that failed is not among those a question can use.
            await expect(videos_card).to_contain_text("4 of 5 videos", timeout=15_000)
            await expect(videos_card).to_contain_text("3 ready, 1 failed")

            # A reload shows the same Sync at the same point, now with an observed rate behind its estimate.
            await page.reload()
            await expect(videos_card).to_contain_text("4 of 5 videos", timeout=15_000)
            await expect(videos_card).to_contain_text("3 ready, 1 failed")
            await expect(videos_card).to_contain_text(re.compile(r"(videos?/min|min/video)"))
            await expect(videos_card).to_contain_text(re.compile(r"about .+ left"))

            # The failure keeps its reason and its own retry, so one unavailable Video is a thing a friend can act on.
            await main.get_by_role("button", name="Videos", exact=True).click()
            failed_row = main.get_by_role("row").filter(has_text="Members stream")
            await expect(failed_row).to_contain_text("Members-only video")
            await expect(failed_row.get_by_role("button", name="Retry")).to_be_visible()

            last.released.set()
            await expect(videos_card).to_contain_text("last synced", timeout=15_000)

    assert errors == []


async def test_frames_of_the_cited_moment_in_search_and_sources_and_turning_them_off(
    config: Config,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    bundle: Path,
) -> None:
    # Long enough to be cut into several Segments, so a run of results from one Video shares one strip.
    planing = said(*(["Plane across the grain", "Then check it flat"] * 12))
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-bench", "Flattening a bench", cues=planing, storyboard=fake_storyboard()),
        # The tier a quarter of Videos offer: its frames upscale soft in the preview, which is not resized for them.
        fake_video(
            "v-plane",
            "Setting a plane",
            cues=said("Plane across the grain on a test board"),
            storyboard=fake_storyboard(columns=5, rows=5, width=160, height=90),
        ),
        # No storyboard: this one shows no frames and keeps its title wherever it appears.
        fake_video("v-vlog", "A week in the shop", cues=said("Plane across the yard")),
    ]
    engine.script = [
        TextDelta("Plane across the grain: **[Wright, 0:20](https://youtube.com/watch?v=v-bench&t=20s)**."),
        ChatDone("session-1"),
    ]
    app = create_app(config, transcripts, embedder, reranker, engine, static_dir=bundle)

    async with serving(app) as base_url:
        # The Channel and Group are set up over the API: what this test is about starts at the search results.
        async with httpx.AsyncClient(base_url=base_url) as api:
            wright = await add_channel(api, "@woodbywright", "Wright")
            await sync(api, wright)
            await add_group(api, "Benches", wright)
            # The ranking the page will be given, so what the rows do with it can be checked against it.
            ranked = (await api.post("/api/search", json={"query": QUESTION, "prefer_recent": "gentle"})).json()
        # Which Videos have frames, and the consecutive runs the ranking fell into: one strip per run.
        framed = {result["video_id"] for result in ranked if result["youtube_video_id"] in ("v-bench", "v-plane")}
        bench = next(result["video_id"] for result in ranked if result["youtube_video_id"] == "v-bench")
        runs = [video_id for video_id, _ in groupby(result["video_id"] for result in ranked)]
        strips = sum(1 for video_id in runs if video_id in framed)
        async with browsing(base_url) as (page, errors):
            await page.goto(base_url)
            rail = page.get_by_role("navigation", name="Sections")
            main = page.get_by_role("main")

            await rail.get_by_role("button", name="Search").click()
            search = page.get_by_role("complementary", name="Search")
            await search.get_by_label("Question", exact=True).fill(QUESTION)
            await search.get_by_role("button", name="Search", exact=True).click()
            results = main.get_by_role("list", name=f"Results for {QUESTION}")
            frames = results.get_by_role("img", name=re.compile(r"^Frame at "))
            await expect(frames).to_have_count(5 * strips)

            # Grouping is of consecutive results only: every result the ranking returned is still a row, in order.
            assert await results.locator("li > p").all_text_contents() == [result["text"] for result in ranked]
            # One title line per run of the Video's results, so the rows a strip covers stop repeating it.
            await expect(results.get_by_text("Flattening a bench", exact=True)).to_have_count(runs.count(bench))
            # The Video with no storyboard shows no frames and goes on naming itself in every row.
            vlog = results.get_by_role("listitem").filter(has_text="A week in the shop")
            await expect(vlog).to_have_count(sum(1 for result in ranked if result["youtube_video_id"] == "v-vlog"))
            await expect(vlog.get_by_role("img", name=re.compile(r"^Frame at "))).to_have_count(0)

            # Hover opens the frame under the cursor, at one width whatever tier the Video has.
            await frames.nth(1).hover()
            peek = page.get_by_role("tooltip")
            await expect(peek).to_contain_text("Flattening a bench")
            wide = await peek_width(peek)
            await page.mouse.move(0, 0)
            await expect(peek).to_be_hidden()
            soft = results.get_by_role("listitem").filter(has_text="Setting a plane").first
            await soft.get_by_role("img", name=re.compile(r"^Frame at ")).first.hover()
            await expect(peek).to_contain_text("Setting a plane")
            # The 160x90 tier gets the same card as the 320x180 one and upscales soft in it, rather than a
            # card that changes size with the Video.
            assert await peek_width(peek) == wide
            await page.mouse.move(0, 0)
            await expect(peek).to_be_hidden()

            # Keyboard focus opens the same preview, so the frames are not a pointer-only affordance.
            await frames.first.focus()
            await expect(peek).to_be_visible()

            # The Sources column of a chat carries a strip per cited Video, and its rows lead with the moment.
            await rail.get_by_role("button", name="Chats").click()
            chats = page.get_by_role("complementary", name="Chats")
            await chats.get_by_role("button", name="New chat in Benches").click()
            composer = main.get_by_role("form", name="Ask Benches")
            await composer.get_by_label("Question for Benches").fill("How do I flatten a bench?")
            await composer.get_by_role("button", name="Ask", exact=True).click()
            sources = page.get_by_role("complementary", name="Sources")
            cited = sources.get_by_role("button", name="Play Flattening a bench at 0:20")
            await expect(cited).to_have_count(1)
            row = sources.get_by_role("listitem").first
            await expect(row).to_contain_text("0:20")
            await expect(row).not_to_contain_text("Flattening a bench")
            # Every frame of the strip plays the moment it shows, which is the moment its label announces.
            await sources.get_by_role("button", name="Play Flattening a bench at 0:40").click()
            embed = ("www.youtube-nocookie.com", "/embed/v-bench")
            assert await embedded_at(sources.locator("iframe")) == (*embed, ["40"])
            await cited.click()
            assert await embedded_at(sources.locator("iframe")) == (*embed, ["20"])

            # One preference, in the panel's own header, governing this column and the search view both.
            await sources.get_by_role("switch", name="Thumbnails").click()
            await expect(sources.get_by_role("button", name=re.compile(r"^Play Flattening"))).to_have_count(0)
            await expect(row).to_contain_text("Flattening a bench")

            # It survives a reload, and search is governed by it too.
            await page.reload()
            await rail.get_by_role("button", name="Search").click()
            await search.get_by_label("Question", exact=True).fill(QUESTION)
            await search.get_by_role("button", name="Search", exact=True).click()
            await expect(results.get_by_role("img", name=re.compile(r"^Frame at "))).to_have_count(0)
            await expect(results.get_by_role("listitem").filter(has_text="Flattening a bench")).not_to_have_count(0)

            # Switched on again from Settings, which is where a friend who never opens a chat would find it.
            await rail.get_by_role("button", name="Settings", exact=True).click()
            await main.get_by_role("switch", name="Thumbnails").click()
            await page.reload()
            await rail.get_by_role("button", name="Search").click()
            await search.get_by_label("Question", exact=True).fill(QUESTION)
            await search.get_by_role("button", name="Search", exact=True).click()
            await expect(results.get_by_role("img", name=re.compile(r"^Frame at "))).not_to_have_count(0)

    assert errors == []
    # Frames are stored geometry only: showing them asked YouTube for nothing beyond the Videos' own ingestion.
    assert [method for method, _ in transcripts.calls if method == "fetch_storyboard"] == []


async def test_choosing_how_often_a_channel_is_checked_persists_and_says_when_the_next_check_is(
    config: Config,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    bundle: Path,
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-one", "Winding sticks", cues=said("Check it with winding sticks"))
    )
    app = create_app(config, transcripts, embedder, reranker, engine, static_dir=bundle)

    async with serving(app) as base_url:
        async with browsing(base_url) as (page, errors):
            await page.goto(base_url)
            main = page.get_by_role("main")
            await page.get_by_role("navigation", name="Sections").get_by_role("button", name="Library").click()
            library = page.get_by_role("complementary", name="Library")
            await library.get_by_role("button", name="Add channel").click()
            add = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Add a channel"))
            await add.get_by_label("YouTube channel URL or handle").fill("@woodbywright")
            await add.get_by_role("button", name="Look up").click()
            await add.get_by_role("button", name="Add", exact=True).click()

            videos_card = main.locator("section").filter(has=page.get_by_role("heading", name="Videos"))
            checks = main.get_by_role("combobox", name="Check for new videos")
            # A new Channel checks daily, but only once its first Sync, which the user starts, has run.
            await expect(checks).to_have_text("Daily")
            await expect(videos_card).to_contain_text("Checks start after its first sync.")
            await main.get_by_role("button", name="Sync now").click()
            await expect(videos_card).to_contain_text("last synced", timeout=15_000)
            await expect(videos_card).to_contain_text("Next check around ")

            await checks.click()
            await page.get_by_role("option", name="Weekly").click()
            await expect(checks).to_have_text("Weekly")
            await page.reload()
            await expect(checks).to_have_text("Weekly")
            async with httpx.AsyncClient(base_url=base_url) as client:
                [listed] = (await client.get("api/channels")).json()
            assert listed["check_every_hours"] == 168

            # Pausing keeps the setting but stops the checks, and says so.
            await main.get_by_role("button", name="Pause channel").click()
            await expect(videos_card).to_contain_text("Paused channels aren’t checked.")
            await expect(checks).to_have_text("Weekly")
            await main.get_by_role("button", name="Resume channel").click()
            await checks.click()
            await page.get_by_role("option", name="Off").click()
            await expect(checks).to_have_text("Off")
            await expect(videos_card).not_to_contain_text("Next check")

    assert errors == []


async def test_a_playlists_sync_is_named_in_the_syncs_list_and_retried_from_its_page(
    config: Config,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    bundle: Path,
) -> None:
    live = fake_video("v-live", "Live Q&A", failure=VideoUnavailable("Premieres in 3 days", permanent=False))
    fake_channel(transcripts, "UC-rex").videos.append(live)
    transcripts.playlists["PL-rex"] = FakePlaylist("Rex picks", [("UC-rex", "v-live")])
    app = create_app(config, transcripts, embedder, reranker, engine, static_dir=bundle, secrets=FakeSecrets())

    async with serving(app) as base_url:
        # Seeded through the API; the Library's own Add playlist flow has its test below.
        async with httpx.AsyncClient(base_url=base_url) as seed:
            playlist = await add_playlist(seed, "PL-rex", "Sharpening")
            await start_playlist_sync(seed, playlist["id"])
            await wait_for_syncs(seed)

        async with browsing(base_url) as (page, errors):
            await page.goto(base_url)
            main = page.get_by_role("main")
            await page.get_by_role("navigation", name="Sections").get_by_role("button", name="Syncs").click()
            rows = page.get_by_role("complementary", name="Syncs").get_by_role("button").filter(has_text="Sharpening")
            await expect(rows).to_have_count(1)
            await rows.click()
            await expect(main.get_by_role("heading", name="Sharpening")).to_be_visible()

            live.failure = None
            await main.get_by_role("button", name="Retry failed videos").click()
            # The retry is a second Sync of the Playlist, which arrives above the first and finishes.
            await expect(rows).to_have_count(2)
            await expect(rows.first).to_contain_text("Done", timeout=15_000)
            async with httpx.AsyncClient(base_url=base_url) as client:
                [video] = await list_playlist_videos(client, playlist["id"])
            assert video["stage"] == "done"

    assert errors == []


async def test_adding_a_playlist_in_the_library_syncing_it_and_seeing_its_videos_with_their_creators(
    config: Config,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    bundle: Path,
) -> None:
    first = Gate(seconds=30)
    live = fake_video("v-live", "Live Q&A", failure=VideoUnavailable("Premieres in 3 days", permanent=False))
    fake_channel(transcripts, "UC-rex").videos += [
        fake_video("v-hone", "Honing a chisel", before_fetch=first, cues=said("Hone the chisel")),
        live,
    ]
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("bench-flat1", "Flattening a Workbench", cues=said("Today we flatten the bench"))
    )
    # In an order that is neither creator's nor by date, so only the playlist's own order explains the table.
    transcripts.playlists["PL-picks"] = FakePlaylist(
        "Hand tool picks", [("UC-rex", "v-hone"), ("UC-wright", "bench-flat1"), ("UC-rex", "v-live")]
    )
    transcripts.playlists["PL-other"] = FakePlaylist("Other picks", [])
    engine.script = [
        TextDelta("A jack plane: [Wood By Wright, 0:05](https://youtube.com/watch?v=bench-flat1&t=5s)."),
        ChatDone("session-1"),
    ]
    app = create_app(config, transcripts, embedder, reranker, engine, static_dir=bundle, secrets=FakeSecrets())

    async with serving(app) as base_url:
        async with browsing(base_url) as (page, errors):
            await page.goto(base_url)
            main = page.get_by_role("main")
            await page.get_by_role("navigation", name="Sections").get_by_role("button", name="Library").click()
            library = page.get_by_role("complementary", name="Library")
            await library.get_by_role("tab", name="Playlists").click()
            await library.get_by_role("button", name="Add playlist").click()
            add = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Add a playlist"))
            url = add.get_by_label("YouTube playlist URL")

            await url.fill("https://www.youtube.com/playlist?list=PL-gone")
            await add.get_by_role("button", name="Look up").click()
            await expect(add).to_contain_text("This playlist doesn't exist or is private.")

            # A link copied from a video playing in the playlist works as well as the playlist's own.
            await url.fill("https://www.youtube.com/watch?v=v-hone&list=PL-picks")
            await add.get_by_role("button", name="Look up").click()
            await expect(add).to_contain_text("Found Hand tool picks · 3 videos")
            await expect(add.get_by_label("Playlist name")).to_have_value("Hand tool picks")
            await add.get_by_role("button", name="Add", exact=True).click()

            await expect(main.get_by_role("heading", name="Hand tool picks")).to_be_visible()
            assert parse_qs(urlsplit(page.url).query) == {"view": ["library"], "tab": ["playlists"], "playlist": ["1"]}
            # Adding it started nothing: the first Sync is the user's.
            videos_card = main.locator("section").filter(has=page.get_by_role("heading", name="Videos"))
            await expect(videos_card).to_contain_text("No videos yet. Sync this playlist to find them.")

            await library.get_by_role("button", name="Add playlist").click()
            await url.fill("PL-picks")
            await add.get_by_role("button", name="Look up").click()
            await add.get_by_role("button", name="Add", exact=True).click()
            await expect(add).to_contain_text("The playlist 'Hand tool picks' is already added as 'Hand tool picks'")
            await url.fill("PL-other")
            await add.get_by_role("button", name="Look up").click()
            await expect(add).to_contain_text("Found Other picks · 0 videos")
            await add.get_by_label("Playlist name").fill("hand tool picks")
            await add.get_by_role("button", name="Add", exact=True).click()
            await expect(add).to_contain_text("A Playlist named 'Hand tool picks' already exists")
            await page.keyboard.press("Escape")

            await main.get_by_role("button", name="Sync now").click()
            await expect(videos_card).to_contain_text("0 of 3 videos", timeout=15_000)
            first.released.set()
            await expect(videos_card).to_contain_text("last synced", timeout=15_000)

            # Playlist order, each Video under the creator who made it. Neither creator is in the Library; the one
            # YouTube offers an avatar for shows it, the other their initials.
            rows = main.get_by_role("row")
            await expect(rows).to_have_count(4)
            await expect(rows.nth(1)).to_contain_text("Honing a chisel")
            await expect(rows.nth(1)).to_contain_text("Rex Krueger")
            await expect(rows.nth(1)).to_contain_text("RK")
            await expect(rows.nth(1).locator("img")).to_have_count(0)
            await expect(rows.nth(2)).to_contain_text("Flattening a Workbench")
            await expect(rows.nth(2)).to_contain_text("Wood By Wright")
            avatar = rows.nth(2).locator("img")
            await expect(avatar).to_have_attribute("src", WRIGHT_AVATAR)
            await expect(avatar).to_have_js_property("naturalWidth", 176)
            await expect(rows.nth(3)).to_contain_text("Live Q&A")
            await expect(rows.nth(3)).to_contain_text("Premieres in 3 days")

            playlist_row = library.get_by_role("listitem").filter(has_text="Hand tool picks")
            await expect(playlist_row).to_contain_text("2 videos")
            await library.get_by_role("tab", name="Channels").click()
            # Its creators stay out of the Library's Channels.
            await expect(library).to_contain_text("Add a channel to start")
            await library.get_by_role("tab", name="Playlists").click()

            live.failure = None
            await main.get_by_role("button", name="Retry failed videos").click()
            await expect(rows.nth(3)).to_contain_text("Done", timeout=15_000)

            await page.reload()
            await expect(main.get_by_role("heading", name="Hand tool picks")).to_be_visible()
            await expect(library.get_by_role("tab", name="Playlists")).to_have_attribute("aria-selected", "true")
            await expect(rows).to_have_count(4)

            # The Playlist is a Search scope of its own, and its creators, though outside the Library, are searched
            # through it and through Everything, under their own names and avatars.
            await page.get_by_role("navigation", name="Sections").get_by_role("button", name="Search").click()
            search = page.get_by_role("complementary", name="Search")
            picks = search.get_by_role("button", name="Hand tool picks")
            await expect(search.get_by_role("button", name="Everything")).to_have_attribute("aria-pressed", "true")
            await picks.click()
            await expect(picks).to_have_attribute("aria-pressed", "true")
            await expect(search.get_by_role("button", name="Everything")).to_have_attribute("aria-pressed", "false")
            await search.get_by_label("Question", exact=True).fill("flatten the bench")
            await search.get_by_role("button", name="Search", exact=True).click()
            await expect(main).to_contain_text("in Hand tool picks for “flatten the bench”")
            results = main.get_by_role("list", name="Results for flatten the bench").get_by_role("listitem")
            result = results.filter(has_text="Today we flatten the bench")
            await expect(result).to_contain_text("Wood By Wright")
            await expect(result.locator("img")).to_have_attribute("src", WRIGHT_AVATAR)
            ask = result.get_by_role("button", name="Ask Hand tool picks about this")
            await expect(ask).to_be_visible()
            await search.get_by_role("button", name="Everything").click()
            await search.get_by_role("button", name="Search", exact=True).click()
            await expect(main).to_contain_text("in Everything for “flatten the bench”")
            await expect(result).to_contain_text("Wood By Wright")

            # Wood By Wright isn't in the Library, so asking about its Video opens a chat in the Playlist that
            # includes it, where its creators answer and the question is ready to finish.
            await ask.click()
            await expect(main.get_by_role("heading", name="New chat in Hand tool picks")).to_be_visible()
            await expect(main).to_contain_text("Only this playlist’s videos are consulted")
            answering = main.locator("section").filter(has=page.get_by_role("heading", name="Who answers"))
            await expect(answering.get_by_role("listitem")).to_have_text(["RKRex Krueger", "Wood By Wright"])
            composer = main.get_by_role("form", name="Ask Hand tool picks")
            question = composer.get_by_label("Question for Hand tool picks")
            await expect(question).to_have_value("About what Wood By Wright says in “Flattening a Workbench” at 0:00: ")
            await question.press_sequentially("which plane?")
            await composer.get_by_role("button", name="Ask", exact=True).click()
            await expect(main.get_by_role("list", name="Conversation")).to_contain_text("A jack plane")
            # The Video is in the Playlist, so the link to it is a Citation, and the chat is filed under the Playlist.
            sources = page.get_by_role("complementary", name="Sources")
            await expect(sources.get_by_role("listitem").filter(has_text="Flattening a Workbench")).to_have_count(1)
            chats = page.get_by_role("complementary", name="Chats")
            await expect(chats.get_by_role("button", name=re.compile(r"^Hand tool picks"))).to_be_visible()
            await expect(chats.get_by_role("button").filter(has_text="which plane?")).to_be_visible()
            await page.reload()
            await expect(main.get_by_role("list", name="Conversation")).to_contain_text("A jack plane")
            await expect(main.get_by_role("form", name="Ask Hand tool picks")).to_be_visible()

            # A Playlist starts a chat from the Chats list and from its own page, as a Group or Channel does.
            await chats.get_by_role("button", name="New chat", exact=True).click()
            await page.get_by_role("menuitem", name="Hand tool picks").click()
            await expect(main.get_by_role("heading", name="New chat in Hand tool picks")).to_be_visible()
            await page.get_by_role("navigation", name="Sections").get_by_role("button", name="Library").click()
            await main.get_by_role("button", name="New chat").click()
            await expect(main.get_by_role("heading", name="New chat in Hand tool picks")).to_be_visible()

            # Its page renames it, on its chats too, and says when it is next checked.
            sections = page.get_by_role("navigation", name="Sections")
            await sections.get_by_role("button", name="Library").click()
            await main.get_by_role("button", name="Rename").click()
            await main.get_by_label("Playlist name").fill("Edge picks")
            await main.get_by_role("button", name="Save").click()
            await expect(main.get_by_role("heading", name="Edge picks")).to_be_visible()
            await expect(main.get_by_role("combobox", name="Check for changes")).to_have_text("Daily")
            await expect(videos_card).to_contain_text("Next check around ")
            await sections.get_by_role("button", name="Chats").click()
            await expect(chats.get_by_role("button", name=re.compile(r"^Edge picks"))).to_be_visible()
            await expect(chats.get_by_role("button", name=re.compile(r"^Hand tool picks"))).to_have_count(0)

            # Paused, it isn't checked and can't start a chat, until it is resumed.
            await sections.get_by_role("button", name="Library").click()
            await main.get_by_role("button", name="Pause playlist").click()
            await expect(videos_card).to_contain_text("Paused playlists aren’t checked.")
            await expect(main.get_by_text("Paused", exact=True)).to_be_visible()
            await expect(main.get_by_role("button", name="New chat")).to_be_disabled()
            async with httpx.AsyncClient(base_url=base_url) as client:
                [listed] = (await client.get("api/playlists")).json()
            assert (listed["name"], listed["indexed"]) == ("Edge picks", False)
            await main.get_by_role("button", name="Resume playlist").click()
            await expect(main.get_by_role("button", name="New chat")).to_be_enabled()
            await expect(videos_card).to_contain_text("Next check around ")

            # Removed from its page, it goes with its Videos, which nothing else in the Library includes. Its chat
            # stays to read, filed under Removed, and can't be continued.
            await main.get_by_role("button", name="Remove playlist").click()
            confirm = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Remove playlist"))
            await expect(confirm).to_contain_text("Remove Edge picks?")
            await confirm.get_by_role("button", name="Remove playlist").click()
            await expect(main).to_contain_text("Pick a channel, group, or playlist")
            await expect(library).to_contain_text("No playlists yet")
            await expect(page).not_to_have_url(re.compile(r"playlist="))
            assert parse_qs(urlsplit(page.url).query) == {"view": ["library"], "tab": ["playlists"]}
            async with httpx.AsyncClient(base_url=base_url) as client:
                still_found = (await client.post("api/search", json={"query": "flatten the bench"})).json()
            assert still_found == []
            await sections.get_by_role("button", name="Chats").click()
            await expect(chats.get_by_role("button", name=re.compile(r"^Removed"))).to_be_visible()
            await expect(chats.get_by_role("button", name=re.compile(r"^Edge picks"))).to_have_count(0)
            await chats.get_by_role("button").filter(has_text="which plane?").click()
            await expect(main).to_contain_text(
                "The playlist Edge picks was removed, so this chat can be read but not continued."
            )
            await expect(main.get_by_role("list", name="Conversation")).to_contain_text("A jack plane")

    # The browser logs each refusal the dialog showed, and nothing else went wrong.
    refused = "Failed to load resource: the server responded with a status of"
    assert errors == [f"{refused} 422 (Unprocessable Content)", f"{refused} 409 (Conflict)", f"{refused} 409 (Conflict)"]


async def test_exporting_a_channel_from_its_page_downloads_its_bundle_under_the_channels_name(
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    bundle: Path,
    tmp_path: Path,
) -> None:
    config = bundle_config(tmp_path / "data")
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone")),
        fake_video("v-saws", "Saws", cues=said("Sharpen the saw with a fine file")),
    ]
    transcripts.playlists["PL-joinery"] = FakePlaylist("Joinery", [("UC-wright", "v-chisels"), ("UC-wright", "v-saws")])
    filters = {"published_after": None, "published_before": None, "playlist_id": "PL-joinery", "most_recent": None}
    app = create_app(config, transcripts, embedder, reranker, engine, static_dir=bundle)
    no_videos = "The Channel 'Wood By Wright' has no indexed Videos to export"

    async with serving(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as seed:
            wright = await add_channel(seed, "@woodbywright")
            assert (await seed.patch(f"api/channels/{wright['id']}", json={"filters": filters})).status_code == 200
            await sync(seed, wright)
            # Added and never synced, so it has nothing to export.
            await add_channel(seed, "@rexkrueger")

        async with browsing(base_url) as (page, errors):
            await page.goto(base_url)
            main = page.get_by_role("main")
            await page.get_by_role("navigation", name="Sections").get_by_role("button", name="Library").click()
            library = page.get_by_role("complementary", name="Library")
            # A row is one click that selects: Export is on the Channel's page only.
            await expect(library.get_by_role("button", name="Export")).to_have_count(0)
            await library.get_by_role("button").filter(has_text="Wood By Wright").click()

            await main.get_by_role("button", name="Export").click()
            dialog = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Export Wood By Wright"))
            await expect(dialog).to_contain_text("2 indexed Videos")
            await expect(dialog).to_contain_text(
                "The file contains the creators’ full Transcripts, so choose who you share it with."
            )
            # This Channel keeps only a playlist's Videos, which the recipient's Seek won't be told.
            await expect(dialog).to_contain_text(
                "The Channel’s Playlist filter is left out, so the recipient’s Syncs will bring in its other Videos."
            )
            await expect(dialog.get_by_role("button", name="Cancel")).to_be_enabled()

            # A refusal is the server's sentence, in the dialog, which stays open; the page behind shows no alert.
            builds = "**/api/channels/*/bundles"
            await page.route(builds, lambda route: route.fulfill(status=422, json={"detail": no_videos}))
            await dialog.get_by_role("button", name="Export").click()
            await expect(dialog.get_by_role("alert")).to_have_text(no_videos)
            await expect(main.get_by_role("alert")).to_have_count(0)
            await page.unroute(builds)

            # The build is held, so "Building…" is on screen long enough to read.
            release = asyncio.Event()

            async def hold(route: Route) -> None:
                await release.wait()
                await route.continue_()

            await page.route(builds, hold)
            async with page.expect_download() as downloading:
                await dialog.get_by_role("button", name="Export").click()
                await expect(dialog.get_by_role("button", name="Building…")).to_be_disabled()
                await expect(dialog.get_by_role("alert")).to_have_count(0)
                release.set()
            download = await downloading.value
            assert download.suggested_filename == "Wood By Wright.seek"
            assert await download.failure() is None
            saved = tmp_path / "saved.seek"
            await download.save_as(saved)
            assert saved.stat().st_size > 0
            # The download closed the dialog and left the app where it was.
            await expect(dialog).to_be_hidden()
            await expect(main.get_by_role("heading", name="Wood By Wright")).to_be_visible()
            assert page.url.startswith(base_url)

            # Nothing indexed, nothing to export: the button says why, though a disabled control raises no hover.
            await library.get_by_role("button").filter(has_text="Rex Krueger").click()
            export = main.get_by_role("button", name="Export")
            await expect(export).to_be_disabled()
            await export.hover(force=True)
            await expect(page.get_by_role("tooltip")).to_have_text("No indexed Videos to export yet.")
            await expect(page.get_by_text("No indexed Videos to export yet.").first).to_be_visible()

    # The browser logs the refusal the dialog showed, in the words of the test's own answer, and nothing else went
    # wrong.
    assert errors == ["Failed to load resource: the server responded with a status of 422 (Unprocessable Entity)"]
    # Nothing of the Bundle stays on the server once the browser has it.
    assert list(config.temporary_dir.iterdir()) == []


async def test_exporting_a_playlist_from_its_page_downloads_its_bundle_under_the_playlists_name(
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    bundle: Path,
    tmp_path: Path,
) -> None:
    config = bundle_config(tmp_path / "data")
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone"))
    )
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-knives", "Knives", cues=said("Strop the knife on leather"))
    )
    transcripts.playlists["PL-picks"] = FakePlaylist(
        "Hand tool picks", [("UC-wright", "v-chisels"), ("UC-rex", "v-knives")]
    )
    transcripts.playlists["PL-other"] = FakePlaylist("Other picks", [("UC-rex", "v-knives")])
    app = create_app(config, transcripts, embedder, reranker, engine, static_dir=bundle)

    async with serving(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as seed:
            picks = await add_playlist(seed, "PL-picks")
            await start_playlist_sync(seed, picks["id"])
            await wait_for_syncs(seed)
            # Added and never synced, so it has nothing to export.
            await add_playlist(seed, "PL-other")

        async with browsing(base_url) as (page, errors):
            await page.goto(base_url)
            main = page.get_by_role("main")
            await page.get_by_role("navigation", name="Sections").get_by_role("button", name="Library").click()
            library = page.get_by_role("complementary", name="Library")
            await library.get_by_role("tab", name="Playlists").click()
            await expect(library.get_by_role("button", name="Export")).to_have_count(0)
            await library.get_by_role("button").filter(has_text="Hand tool picks").click()

            # The dialog a Channel's page opens, without the line about a Channel's Playlist filter.
            await main.get_by_role("button", name="Export").click()
            dialog = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Export Hand tool picks"))
            await expect(dialog).to_contain_text("2 indexed Videos")
            await expect(dialog).to_contain_text(
                "The file contains the creators’ full Transcripts, so choose who you share it with."
            )
            await expect(dialog).not_to_contain_text("Playlist filter")

            async with page.expect_download() as downloading:
                await dialog.get_by_role("button", name="Export").click()
            download = await downloading.value
            assert download.suggested_filename == "Hand tool picks.seek"
            assert await download.failure() is None
            await expect(dialog).to_be_hidden()
            await expect(main.get_by_role("heading", name="Hand tool picks")).to_be_visible()

            await library.get_by_role("button").filter(has_text="Other picks").click()
            export = main.get_by_role("button", name="Export")
            await expect(export).to_be_disabled()
            await export.hover(force=True)
            await expect(page.get_by_role("tooltip")).to_have_text("No indexed Videos to export yet.")

    assert errors == []
    assert list(config.temporary_dir.iterdir()) == []
