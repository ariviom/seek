import { useEffect, useState } from "react";
import { api, type Health } from "./api";
import { Mentors } from "./Mentors";

type HealthState = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error"; message: string };

export function App() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    let current = true;
    api
      .health()
      .then((health) => current && setState({ kind: "ok", health }))
      .catch(
        (error: unknown) =>
          current && setState({ kind: "error", message: error instanceof Error ? error.message : String(error) }),
      );
    return () => {
      current = false;
    };
  }, []);

  return (
    <main className="mx-auto max-w-2xl p-8 font-sans text-stone-900">
      <h1 className="text-2xl font-semibold">mentor</h1>
      <Mentors />
      <footer className="mt-12 border-t border-stone-200 pt-3 text-xs text-stone-500">
        {state.kind === "loading" && "Checking server…"}
        {state.kind === "error" && <span className="text-red-700">Server unavailable: {state.message}</span>}
        {state.kind === "ok" && (
          <span>
            Server {state.health.status} · sqlite-vec {state.health.database.sqlite_vec} · FTS5{" "}
            {state.health.database.fts5 ? "available" : "missing"} ·{" "}
            <span className="font-mono">{state.health.database.path}</span>
          </span>
        )}
      </footer>
    </main>
  );
}
