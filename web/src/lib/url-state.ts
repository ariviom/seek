import { useCallback, useEffect, useState } from "react";

export type View = "chats" | "search" | "library" | "syncs";
export type Selection = {
  conversation?: number;
  channel?: number;
  group?: number;
  sync?: number;
  tab?: "channels" | "groups";
};

const views: View[] = ["chats", "search", "library", "syncs"];
const ids = ["conversation", "channel", "group", "sync"] as const;

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
  if (tab === "channels" || tab === "groups") selection.tab = tab;
  return selection;
}

function write(view: View, selection: Selection) {
  const params = new URLSearchParams();
  params.set("view", view);
  for (const key of ids) {
    const value = selection[key];
    if (value !== undefined) params.set(key, String(value));
  }
  if (selection.tab !== undefined) params.set("tab", selection.tab);
  history.replaceState(null, "", `?${params.toString()}${window.location.hash}`);
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

  const setView = useCallback((view: View) => {
    setState((current) => {
      write(view, current.selection);
      return { ...current, view };
    });
  }, []);

  // Only the keys given change; an explicit `undefined` clears one.
  const select = useCallback((selection: Selection) => {
    setState((current) => {
      const next = { ...current.selection };
      for (const [key, value] of Object.entries(selection)) {
        if (value === undefined) delete next[key as keyof Selection];
        else Object.assign(next, { [key]: value });
      }
      write(current.view, next);
      return { ...current, selection: next };
    });
  }, []);

  return { view: state.view, selection: state.selection, setView, select };
}
