import { errorText } from "@/lib/api";
import type { Selection } from "@/lib/url-state";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { syncStatus, useSyncs, when } from "./useSyncs";

export function SyncList({
  selection,
  select,
  syncAllError,
}: {
  selection: Selection;
  select: (selection: Selection) => void;
  syncAllError: string | null;
}) {
  const { items: syncs, error } = useSyncs();

  return (
    <div className="space-y-2">
      {syncAllError !== null && (
        <Alert variant="destructive">
          <AlertDescription>Could not start the syncs: {syncAllError}</AlertDescription>
        </Alert>
      )}
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>Could not load syncs: {errorText(error)}</AlertDescription>
        </Alert>
      )}
      {syncs !== null && syncs.length === 0 && (
        <p className="px-1 py-2 text-xs text-muted-foreground">No syncs yet. Sync a channel from the Library.</p>
      )}
      {syncs !== null && syncs.length > 0 && (
        <ul className="space-y-0.5">
          {syncs.map((sync) => {
            const selected = selection.sync === sync.id;
            return (
              <li key={sync.id}>
                <button
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  onClick={() => select({ sync: sync.id })}
                  className={`flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted ${
                    selected ? "bg-muted" : ""
                  }`}
                >
                  <span aria-hidden className={`mt-1.5 size-2 shrink-0 rounded-full ${syncStatus[sync.status].dot}`} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{sync.channel_name}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {syncStatus[sync.status].label} · {when(sync)}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
