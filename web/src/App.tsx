import { useEffect, useState } from "react";
import { api, errorText, type Health, type Mentor, type MentorGroup } from "./api";
import { Groups } from "./Groups";
import { Mentors } from "./Mentors";
import { Search } from "./Search";
import { Syncs } from "./Syncs";

type HealthState = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error"; message: string };

export function App() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const [mentors, setMentors] = useState<Mentor[] | null>(null);
  const [groups, setGroups] = useState<MentorGroup[] | null>(null);

  useEffect(() => {
    let current = true;
    api
      .health()
      .then((health) => current && setState({ kind: "ok", health }))
      .catch(
        (error: unknown) =>
          current && setState({ kind: "error", message: errorText(error) }),
      );
    return () => {
      current = false;
    };
  }, []);

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-panel">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-3 sm:px-8">
          <h1 className="font-condensed text-3xl leading-none font-semibold">mentor</h1>
          {state.kind === "error" && (
            <p role="alert" className="text-sm text-oxide">
              Server unavailable: {state.message}
            </p>
          )}
        </div>
      </header>
      <div className="mx-auto grid max-w-6xl gap-x-10 gap-y-12 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <main className="min-w-0 space-y-12">
          <Search mentors={mentors} groups={groups} />
          <Mentors onLoaded={setMentors} />
          <Groups mentors={mentors} onLoaded={setGroups} />
        </main>
        <aside className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto">
          <Syncs />
        </aside>
      </div>
      <footer className="mx-auto max-w-6xl px-5 pb-8 sm:px-8">
        {state.kind === "ok" && (
          <dl className="flex flex-wrap gap-x-6 gap-y-1 border-t border-rule pt-3 text-[13px] text-pencil">
            <div className="flex gap-1.5">
              <dt>Server</dt>
              <dd className="text-ink">{state.health.status}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt>sqlite-vec</dt>
              <dd className="text-ink">{state.health.database.sqlite_vec}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt>FTS5</dt>
              <dd className="text-ink">{state.health.database.fts5 ? "available" : "missing"}</dd>
            </div>
            <div className="flex min-w-0 gap-1.5">
              <dt>Knowledge base</dt>
              <dd className="truncate text-ink">{state.health.database.path}</dd>
            </div>
          </dl>
        )}
      </footer>
    </div>
  );
}
