import { useCallback, useEffect, useRef, useState } from "react";
import type { Models, Sync, Video } from "@/lib/api";

export type ServerEvent =
  | { type: "ready" }
  | { type: "sync"; sync: Sync }
  | { type: "video"; channel_id: number; video: Video }
  | { type: "videos"; channel_id: number }
  | { type: "syncs" }
  | { type: "models"; models: Models };

type Listener = (event: ServerEvent) => void;

// One stream for the whole page, open while anything listens.
const listeners = new Set<Listener>();
let source: EventSource | null = null;
let reopenTimer: number | undefined;
// True while the server refuses the stream, e.g. once a Cloudflare Access session has expired.
let refused = false;
const refusedListeners = new Set<(refused: boolean) => void>();

function setRefused(value: boolean) {
  if (refused === value) return;
  refused = value;
  for (const listener of refusedListeners) listener(value);
}

function open() {
  // Relative, so it follows any reverse-proxy path prefix.
  const opened = new EventSource("api/events");
  opened.onmessage = (message: MessageEvent<string>) => {
    const event = JSON.parse(message.data) as ServerEvent;
    if (event.type === "ready") setRefused(false);
    for (const listener of listeners) listener(event);
  };
  opened.onerror = () => {
    // EventSource reconnects by itself unless the server answered with an error; then retry later.
    if (opened.readyState !== EventSource.CLOSED || source !== opened) return;
    setRefused(true);
    source = null;
    reopenTimer = window.setTimeout(() => {
      if (listeners.size > 0 && source === null) source = open();
    }, 5000);
  };
  return opened;
}

export function useServerEvents(onEvent: Listener) {
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  });
  useEffect(() => {
    const listener: Listener = (event) => handler.current(event);
    listeners.add(listener);
    if (source === null) source = open();
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) {
        source?.close();
        source = null;
        window.clearTimeout(reopenTimer);
      }
    };
  }, []);
}

// Whether live updates have stopped because the server refused the event stream.
export function useLiveUpdatesStopped(): boolean {
  const [value, setValue] = useState(refused);
  useEffect(() => {
    refusedListeners.add(setValue);
    setValue(refused);
    return () => {
      refusedListeners.delete(setValue);
    };
  }, []);
  return value;
}

// What an event means for a list: reload it, update it, or nothing.
export type Reaction<T> = "reload" | ((items: T[]) => T[]) | null;

// A list loaded from the API and kept current by server events. It reloads whenever the stream (re)connects,
// since events may have been missed. Updates that arrive while a load is in flight are applied on top of its
// result too, so a load that read older state can't undo a newer event.
export function useLiveList<T>(load: () => Promise<T[]>, react: (event: ServerEvent) => Reaction<T>) {
  const [items, setItems] = useState<T[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const inFlight = useRef<((items: T[]) => T[])[] | null>(null);

  const retryTimer = useRef<number | undefined>(undefined);

  const reload = useCallback(async () => {
    window.clearTimeout(retryTimer.current);
    const updates: ((items: T[]) => T[])[] = [];
    inFlight.current = updates;
    try {
      const loaded = await load();
      if (inFlight.current !== updates) return;
      setItems(updates.reduce((current, update) => update(current), loaded));
      setError(null);
    } catch (e) {
      if (inFlight.current !== updates) return;
      setError(e);
      // A stream that stays connected sends no "ready" to reload on.
      retryTimer.current = window.setTimeout(() => void reload(), 5000);
    } finally {
      if (inFlight.current === updates) inFlight.current = null;
    }
  }, [load]);

  useEffect(() => {
    void reload();
    return () => window.clearTimeout(retryTimer.current);
  }, [reload]);

  useServerEvents((event) => {
    const reaction = event.type === "ready" ? "reload" : react(event);
    if (reaction === "reload") {
      void reload();
    } else if (reaction !== null) {
      inFlight.current?.push(reaction);
      setItems((current) => current && reaction(current));
    }
  });

  return { items, error };
}
