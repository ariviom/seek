import { errorText, type Sync } from "@/lib/api";
import type { Selection } from "@/lib/url-state";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { isRunning, syncProgress, useNow } from "@/lib/sync-status";
import { ListRow } from "@/shell/ListRow";
import { syncStatus, when } from "./useSyncs";

export function SyncList({
  syncs,
  error,
  selection,
  select,
  syncAllError,
}: {
  syncs: Sync[] | null;
  error: unknown;
  selection: Selection;
  select: (selection: Selection) => void;
  syncAllError: string | null;
}) {
  const now = useNow(syncs?.some(isRunning) === true ? 10 : 0);

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
          {syncs.map((sync) => (
            <li key={sync.id}>
              <ListRow selected={selection.sync === sync.id} onClick={() => select({ sync: sync.id })}>
                <span aria-hidden className={`size-2 shrink-0 rounded-full ${syncStatus[sync.status].dot}`} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{sync.channel_name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {isRunning(sync)
                      ? syncProgress(sync, now).label
                      : `${syncStatus[sync.status].label} · ${when(sync)}`}
                  </span>
                </span>
              </ListRow>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
