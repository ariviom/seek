import { useCallback, useEffect, useState } from "react";

export type View = "chats" | "search" | "library" | "syncs" | "settings";
export type LibraryTab = "channels" | "groups" | "playlists";
export type Selection = {
  conversation?: number;
  channel?: number;
  group?: number;
  playlist?: number;
  sync?: number;
  tab?: LibraryTab;
};

const views: View[] = ["chats", "search", "library", "syncs", "settings"];
const ids = ["conversation", "channel", "group", "playlist", "sync"] as const;

function readView(params: URLSearchParams): View {
  const value = params.get("view");
  return views.find((v) => v === value) ?? "chats";
}

function readSelection(params: URLSearchParams): Selection {
  const selection: Selection = {};
  for (const key of ids) {
    const value = Number(params.get(key));
    // Unknown or malformed values are ignored, so a hand-edited URL still opens.
    if (params.get(key) !== null && Number.isInteger(value) && value > 0) selection[key] = value;
  }
  const tab = params.get("tab");
  if (tab === "channels" || tab === "groups" || tab === "playlists") selection.tab = tab;
  return selection;
}

const keys = [...ids, "tab"] as const;

function query(view: View, selection: Selection): string {
  const params = new URLSearchParams();
  params.set("view", view);
  for (const key of ids) {
    const value = selection[key];
    if (value !== undefined) params.set(key, String(value));
  }
  if (selection.tab !== undefined) params.set("tab", selection.tab);
  return params.toString();
}

// The view and selection live in the query string, so reload and links restore what was open.
export function useUrlState() {
  const [state, setState] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return { view: readView(params), selection: readSelection(params) };
  });

  useEffect(() => {
    const onPop = () => {
      const params = new URLSearchParams(window.location.search);
      setState({ view: readView(params), selection: readSelection(params) });
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Written from an effect, not from the updater: StrictMode double-invokes updaters.
  useEffect(() => {
    history.replaceState(null, "", `?${query(state.view, state.selection)}${window.location.hash}`);
  }, [state]);

  const setView = useCallback((view: View) => {
    setState((current) => ({ ...current, view }));
  }, []);

  // Only the keys given change; an explicit `undefined` clears one.
  const select = useCallback((selection: Selection) => {
    setState((current) => {
      const next: Selection = { ...current.selection, ...selection };
      for (const key of keys) {
        if (next[key] === undefined) delete next[key];
      }
      return { ...current, selection: next };
    });
  }, []);

  return { view: state.view, selection: state.selection, setView, select };
}
