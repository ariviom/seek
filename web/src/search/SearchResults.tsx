import { useState } from "react";
import { Play } from "lucide-react";
import { api, errorText, type Expansion as ExpansionShape, type Group, type Scope, type SearchResult } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { formatDuration, plural } from "@/lib/format";
import { playableKey, type Playable, type PlaybackControls } from "@/lib/playback";
import { cn } from "@/lib/utils";
import { Expansion } from "./Expansion";
import type { SearchState } from "./useSearch";

// A result at a second, as the player takes it.
function playableAt(result: SearchResult, seconds: number): Playable {
  const url = new URL(result.url);
  url.searchParams.set("t", `${seconds}s`);
  return { ...result, seconds, url: url.toString() };
}

export function SearchResults({
  search,
  groups,
  playback,
  onAsk,
}: {
  search: SearchState;
  groups: Group[] | null;
  playback: PlaybackControls;
  onAsk: (scope: Scope, draft: string) => void;
}) {
  const { outcome, error, searching } = search;

  // The Group searched, else the result's own Channel.
  function askScope(result: SearchResult, groupId: number | null): { scope: Scope; name: string } {
    const group = groups?.find((g) => g.id === groupId);
    return group === undefined
      ? { scope: { kind: "channel", id: result.channel_id }, name: result.channel_name }
      : { scope: { kind: "group", id: group.id }, name: group.name };
  }

  return (
    <div className="space-y-3">
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {outcome === null ? (
        error === null && (
          <p className="text-sm text-muted-foreground">
            {searching ? "Searching…" : "Search the transcripts from the form, and play the moments that answer it."}
          </p>
        )
      ) : outcome.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nothing matched “{outcome.query}” in {outcome.scopeName}. Try other words or a wider scope.
        </p>
      ) : (
        <>
          <p className={cn("text-xs text-muted-foreground", searching && "opacity-60")}>
            {plural(outcome.results.length, "moment")} in {outcome.scopeName} for “{outcome.query}”
          </p>
          <ol className="divide-y" aria-label={`Results for ${outcome.query}`}>
            {outcome.results.map((result) => (
              <Result
                // A new outcome starts every row closed.
                key={`${outcome.id}:${result.segment_id}`}
                result={result}
                playingKey={playback.playingKey}
                onPlay={(seconds) => playback.play(playableAt(result, seconds))}
                ask={askScope(result, outcome.groupId)}
                onAsk={onAsk}
              />
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

function Result({
  result,
  playingKey,
  onPlay,
  ask,
  onAsk,
}: {
  result: SearchResult;
  playingKey: string | null;
  onPlay: (seconds: number) => void;
  ask: { scope: Scope; name: string };
  onAsk: (scope: Scope, draft: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [expansion, setExpansion] = useState<ExpansionShape | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const matched = Math.floor(result.matched_seconds);
  const playing = playingKey === playableKey({ ...result, seconds: matched });

  async function toggle() {
    const opening = !open;
    setOpen(opening);
    // Fetched on first opening only.
    if (!opening || expansion !== null) return;
    setError(null);
    setLoading(true);
    try {
      setExpansion(await api.expand(result.segment_id));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <li className="py-3.5">
      <p className="text-sm leading-6">{result.text}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-muted-foreground">
        <button
          type="button"
          aria-label={`Play at ${formatDuration(matched)}`}
          aria-current={playing ? "true" : undefined}
          onClick={() => onPlay(matched)}
          className={cn(
            "inline-flex h-6 items-center gap-1 rounded-md border px-1.5 text-foreground tabular-nums outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/50",
            playing && "border-foreground/40 bg-accent",
          )}
        >
          <Play className="size-3" aria-hidden /> {formatDuration(matched)}
        </button>
        <span className="inline-flex items-center gap-1.5">
          <Avatar name={result.channel_name} size="xs" /> {result.channel_name}
        </span>
        <span className="text-foreground">{result.video_title}</span>
        {result.chapter_title !== null && <span>{result.chapter_title}</span>}
        <span className="tabular-nums">{result.published_on}</span>
        <span className="ml-auto flex items-center gap-1">
          <Button
            variant="ghost"
            size="xs"
            className="text-muted-foreground"
            aria-expanded={open}
            disabled={loading}
            onClick={() => void toggle()}
          >
            {loading ? "Loading…" : open ? "Hide transcript" : "Read around it"}
          </Button>
          <Button
            variant="ghost"
            size="xs"
            className="text-muted-foreground"
            onClick={() =>
              onAsk(
                ask.scope,
                `About what ${result.channel_name} says in “${result.video_title}” at ${formatDuration(matched)}: `,
              )
            }
          >
            Ask {ask.name} about this
          </Button>
        </span>
      </div>
      {open && error !== null && (
        <Alert variant="destructive" className="mt-2">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {open && expansion !== null && <Expansion expansion={expansion} matchedSeconds={matched} onPlay={onPlay} />}
    </li>
  );
}
