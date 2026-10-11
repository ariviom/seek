import { useRef, useState } from "react";
import {
  api,
  errorText,
  type Channel,
  type Group,
  type Playlist,
  type PreferRecent,
  type SearchResult,
} from "@/lib/api";

// Where a search looks: everything, one Group, one Playlist, or the ticked Channels.
export type SearchScope =
  | { kind: "everything" }
  | { kind: "group"; id: number }
  | { kind: "playlist"; id: number }
  | { kind: "channels" };

export type Outcome = {
  // Counts searches, so each outcome's rows start closed even for the same query.
  id: number;
  query: string;
  results: SearchResult[];
  // The Group searched, if any, so "Ask about this" asks the same Group; and how the scope reads in the header.
  groupId: number | null;
  scopeName: string;
};

// The form's state and the last outcome, held above the list column, which is remounted when it moves into a Sheet.
export function useSearch(channels: Channel[] | null, groups: Group[] | null, playlists: Playlist[] | null) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<SearchScope>({ kind: "everything" });
  const [chosen, setChosen] = useState<number[]>([]);
  const [preferRecent, setPreferRecent] = useState<PreferRecent>("gentle");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const searches = useRef(0);

  // Ticked Channels and a chosen Group or Playlist that have since been deleted are dropped rather than sent.
  const chosenIds = chosen.filter((id) => channels?.some((c) => c.id === id));
  const group = scope.kind === "group" ? groups?.find((g) => g.id === scope.id) : undefined;
  const playlist = scope.kind === "playlist" ? playlists?.find((p) => p.id === scope.id) : undefined;
  const shownScope: SearchScope =
    (scope.kind === "group" && group === undefined) || (scope.kind === "playlist" && playlist === undefined)
      ? { kind: "everything" }
      : scope;
  const ready = query.trim() !== "" && (shownScope.kind !== "channels" || chosenIds.length > 0);

  async function run() {
    setError(null);
    setSearching(true);
    try {
      const results = await api.search({
        query,
        prefer_recent: preferRecent,
        ...(shownScope.kind === "channels" ? { channels: chosenIds } : {}),
        ...(group !== undefined ? { group: group.id } : {}),
        ...(playlist !== undefined ? { playlist: playlist.id } : {}),
      });
      const scopeName =
        (group ?? playlist)?.name ??
        (shownScope.kind === "channels"
          ? chosenIds.length === 1
            ? (channels?.find((c) => c.id === chosenIds[0])?.name ?? "1 channel")
            : `${chosenIds.length} channels`
          : "every channel");
      setOutcome({ id: ++searches.current, query: query.trim(), results, groupId: group?.id ?? null, scopeName });
    } catch (e) {
      setOutcome(null);
      setError(errorText(e));
    } finally {
      setSearching(false);
    }
  }

  return {
    query,
    setQuery,
    scope: shownScope,
    setScope,
    chosenIds,
    toggleChannel: (channelId: number, ticked: boolean) =>
      setChosen((ids) => (ticked ? [...ids.filter((id) => id !== channelId), channelId] : ids.filter((id) => id !== channelId))),
    preferRecent,
    setPreferRecent,
    ready,
    searching,
    run,
    outcome,
    error,
  };
}

export type SearchState = ReturnType<typeof useSearch>;
