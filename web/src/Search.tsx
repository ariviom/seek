import { useState, type FormEvent } from "react";
import { api, errorText, type Mentor, type MentorGroup, type PreferRecent, type SearchResult } from "./api";
import {
  alertClass,
  buttonClass,
  chipClass,
  formatDuration,
  hintClass,
  inputClass,
  outlineButtonClass,
  sectionHeadingClass,
} from "./ui";

const recencyLabels: Record<PreferRecent, string> = {
  off: "Ignore age",
  gentle: "Prefer newer, gently",
  strong: "Prefer newer, strongly",
};

type Outcome = { query: string; results: SearchResult[] };

// `mentors` and `groups` are null until their sections have loaded.
export function Search({ mentors, groups }: { mentors: Mentor[] | null; groups: MentorGroup[] | null }) {
  const [query, setQuery] = useState("");
  // "everything", "mentors" (the ticked Mentors), or `group:<id>`.
  const [scope, setScope] = useState("everything");
  const [chosen, setChosen] = useState<number[]>([]);
  const [preferRecent, setPreferRecent] = useState<PreferRecent>("gentle");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  // Ticked Mentors and a chosen Group that have since been deleted are dropped rather than sent.
  const chosenIds = chosen.filter((id) => mentors?.some((m) => m.id === id));
  const groupId = scope.startsWith("group:") ? Number(scope.slice("group:".length)) : null;
  const scopeShown = groupId === null || groups?.some((g) => g.id === groupId) ? scope : "everything";
  const ready = query.trim() !== "" && (scopeShown !== "mentors" || chosenIds.length > 0);

  async function run(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSearching(true);
    try {
      const results = await api.search({
        query,
        prefer_recent: preferRecent,
        ...(scopeShown === "mentors" ? { mentors: chosenIds } : {}),
        ...(scopeShown === scope && groupId !== null ? { group: groupId } : {}),
      });
      setOutcome({ query: query.trim(), results });
    } catch (e) {
      setOutcome(null);
      setError(errorText(e));
    } finally {
      setSearching(false);
    }
  }

  function toggle(mentorId: number, ticked: boolean) {
    setChosen((ids) => (ticked ? [...ids, mentorId] : ids.filter((id) => id !== mentorId)));
  }

  const labelClass = "flex flex-col gap-1 text-sm text-pencil";

  return (
    <section aria-labelledby="search-heading">
      <h2 id="search-heading" className={sectionHeadingClass}>
        Search
      </h2>
      <p className={`mt-2 ${hintClass}`}>Ask a question and find the moments your Mentors answered it.</p>
      <form onSubmit={run} className="mt-4 space-y-3">
        <div className="flex flex-wrap gap-2">
          <input
            className={`${inputClass} min-w-56 flex-1`}
            placeholder="e.g. How do I stop tear-out when planing figured wood?"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Question"
          />
          <button className={buttonClass} type="submit" disabled={!ready || searching}>
            {searching ? "Searching…" : "Search"}
          </button>
        </div>
        <div className="flex flex-wrap gap-3">
          <label className={labelClass}>
            Ask
            <select className={inputClass} value={scopeShown} onChange={(e) => setScope(e.target.value)}>
              <option value="everything">Every Mentor</option>
              {groups !== null && groups.length > 0 && (
                <optgroup label="Mentor Groups">
                  {groups.map((group) => (
                    <option key={group.id} value={`group:${group.id}`}>
                      {group.name}
                    </option>
                  ))}
                </optgroup>
              )}
              <option value="mentors">Chosen Mentors…</option>
            </select>
          </label>
          <label className={labelClass}>
            Recency
            <select
              className={inputClass}
              value={preferRecent}
              onChange={(e) => setPreferRecent(e.target.value as PreferRecent)}
            >
              {(Object.keys(recencyLabels) as PreferRecent[]).map((level) => (
                <option key={level} value={level}>
                  {recencyLabels[level]}
                </option>
              ))}
            </select>
          </label>
        </div>
        {scopeShown === "mentors" &&
          (mentors === null ? (
            <p className={hintClass}>Loading Mentors…</p>
          ) : mentors.length === 0 ? (
            <p className={hintClass}>Add a Mentor below to search just their Videos.</p>
          ) : (
            <ul className="flex flex-wrap gap-2" aria-label="Mentors to search">
              {mentors.map((mentor) => (
                <li key={mentor.id}>
                  <label className={chipClass}>
                    <input
                      type="checkbox"
                      checked={chosenIds.includes(mentor.id)}
                      onChange={(e) => toggle(mentor.id, e.target.checked)}
                    />
                    {mentor.name}
                  </label>
                </li>
              ))}
            </ul>
          ))}
      </form>
      {error && (
        <p role="alert" className={alertClass}>
          {error}
        </p>
      )}
      {outcome !== null &&
        (outcome.results.length === 0 ? (
          <p className={`mt-5 ${hintClass}`}>Nothing matched “{outcome.query}”. Try other words or a wider scope.</p>
        ) : (
          <ol className="mt-5 space-y-4" aria-label={`Results for ${outcome.query}`}>
            {outcome.results.map((result) => (
              <Result key={result.segment_id} result={result} />
            ))}
          </ol>
        ))}
    </section>
  );
}

function Result({ result }: { result: SearchResult }) {
  return (
    <li className="rounded-md bg-panel px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-[13px] text-pencil">
        <p>
          <span className="font-medium text-ink">{result.mentor_name}</span>
          {result.channel_name !== result.mentor_name && ` · ${result.channel_name}`}
        </p>
        <p className="tabular-nums">Published {result.published_on}</p>
      </div>
      <h3 className="mt-1 font-condensed text-[1.375rem] leading-tight font-semibold">{result.video_title}</h3>
      {result.chapter_title && <p className="text-[13px] text-pencil">Chapter: {result.chapter_title}</p>}
      <p className="mt-2 text-[15px] leading-relaxed">{result.text}</p>
      <a className={`mt-3 inline-block ${outlineButtonClass}`} href={result.url} target="_blank" rel="noreferrer">
        Watch at {formatDuration(Math.floor(result.matched_seconds))}
      </a>
    </li>
  );
}
