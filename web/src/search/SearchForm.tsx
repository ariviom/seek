import { useEffect, useRef } from "react";
import { Search } from "lucide-react";
import type { Channel, Group, PreferRecent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { SearchScope, SearchState } from "./useSearch";

const recencyLabels: Record<PreferRecent, string> = {
  off: "Ignore age",
  gentle: "Prefer newer, gently",
  strong: "Prefer newer, strongly",
};

function ScopeOption({ pressed, onClick, label }: { pressed: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "h-6 max-w-full truncate rounded-md border px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        pressed ? "border-foreground/40 bg-accent" : "text-muted-foreground hover:bg-accent",
      )}
    >
      {label}
    </button>
  );
}

// The search form in the list column. `focusRequest` changes whenever ⌘K asks for the question box.
export function SearchForm({
  search,
  channels,
  groups,
  focusRequest,
  onFocused,
  onSearch,
}: {
  search: SearchState;
  channels: Channel[] | null;
  groups: Group[] | null;
  focusRequest: number;
  // Clears the request once met, so a later remount of the form doesn't take focus again.
  onFocused: () => void;
  onSearch: () => void;
}) {
  const question = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusRequest === 0 || question.current === null) return;
    question.current.focus();
    onFocused();
  }, [focusRequest, onFocused]);

  const is = (scope: SearchScope) =>
    search.scope.kind === scope.kind && (scope.kind !== "group" || (search.scope.kind === "group" && search.scope.id === scope.id));

  return (
    <form
      className="space-y-3 pt-1"
      onSubmit={(event) => {
        event.preventDefault();
        if (!search.ready || search.searching) return;
        onSearch();
        void search.run();
      }}
    >
      <div className="relative">
        <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" aria-hidden />
        <Input
          ref={question}
          className="pl-8"
          placeholder="What did they say about…"
          value={search.query}
          onChange={(e) => search.setQuery(e.target.value)}
          aria-label="Question"
        />
      </div>
      <fieldset>
        <legend className="mb-1.5 text-xs font-medium text-muted-foreground">Where</legend>
        <div className="flex flex-wrap gap-1">
          <ScopeOption
            label="Everything"
            pressed={is({ kind: "everything" })}
            onClick={() => search.setScope({ kind: "everything" })}
          />
          {(groups ?? []).map((group) => (
            <ScopeOption
              key={group.id}
              label={group.name}
              pressed={is({ kind: "group", id: group.id })}
              onClick={() => search.setScope({ kind: "group", id: group.id })}
            />
          ))}
          <ScopeOption
            label="Chosen channels"
            pressed={is({ kind: "channels" })}
            onClick={() => search.setScope({ kind: "channels" })}
          />
        </div>
      </fieldset>
      {search.scope.kind === "channels" &&
        (channels === null ? (
          <p className="text-xs text-muted-foreground">Loading channels…</p>
        ) : channels.length === 0 ? (
          <p className="text-xs text-muted-foreground">Add a channel in the Library to search just its videos.</p>
        ) : (
          <ul className="space-y-1" aria-label="Channels to search">
            {channels.map((channel) => (
              <li key={channel.id}>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-3.5 accent-primary"
                    checked={search.chosenIds.includes(channel.id)}
                    onChange={(e) => search.toggleChannel(channel.id, e.target.checked)}
                  />
                  <span className="truncate">{channel.name}</span>
                </label>
              </li>
            ))}
          </ul>
        ))}
      <div>
        <p id="search-age" className="mb-1.5 text-xs font-medium text-muted-foreground">
          Age
        </p>
        <Select value={search.preferRecent} onValueChange={(value) => search.setPreferRecent(value as PreferRecent)}>
          <SelectTrigger aria-labelledby="search-age" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(recencyLabels) as PreferRecent[]).map((level) => (
              <SelectItem key={level} value={level}>
                {recencyLabels[level]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Button className="w-full" type="submit" disabled={!search.ready || search.searching}>
        {search.searching ? "Searching…" : "Search"}
      </Button>
    </form>
  );
}
