import { useEffect, useState } from "react";
import { getHealth, type Health } from "./api";

type State = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error"; message: string };

export function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let current = true;
    getHealth()
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
      <section className="mt-6 rounded-lg border border-stone-200 p-4">
        <h2 className="text-sm font-medium tracking-wide text-stone-500 uppercase">Health</h2>
        {state.kind === "loading" && <p className="mt-2">Checking…</p>}
        {state.kind === "error" && <p className="mt-2 text-red-700">{state.message}</p>}
        {state.kind === "ok" && (
          <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-stone-500">Server</dt>
            <dd>{state.health.status}</dd>
            <dt className="text-stone-500">Database</dt>
            <dd className="font-mono break-all">{state.health.database.path}</dd>
            <dt className="text-stone-500">Journal</dt>
            <dd>{state.health.database.journal_mode}</dd>
            <dt className="text-stone-500">sqlite-vec</dt>
            <dd>{state.health.database.sqlite_vec}</dd>
            <dt className="text-stone-500">FTS5</dt>
            <dd>{state.health.database.fts5 ? "available" : "missing"}</dd>
          </dl>
        )}
      </section>
    </main>
  );
}
