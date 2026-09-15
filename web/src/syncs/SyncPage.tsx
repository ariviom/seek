import { useState } from "react";
import { api, errorText, type Sync } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { plural } from "@/lib/format";
import { StageRule } from "./StageRule";
import { syncStatus, when } from "./useSyncs";

export function SyncPage({ syncId, syncs }: { syncId: number; syncs: Sync[] | null }) {
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const sync = syncs?.find((s) => s.id === syncId) ?? null;

  // Only the 50 newest Syncs are listed, so a linked older one has nothing left to show.
  if (sync === null) {
    return syncs === null ? null : <p className="text-sm text-muted-foreground">This sync is no longer listed.</p>;
  }

  const finished = sync.status === "done" || sync.status === "failed";

  // The retry queues a new Sync; it arrives as an event.
  async function retryFailed(channelId: number) {
    setRetryError(null);
    setRetrying(true);
    try {
      await api.retryFailed(channelId);
    } catch (e) {
      setRetryError(errorText(e));
    } finally {
      setRetrying(false);
    }
  }

  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{sync.channel_name}</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {syncStatus[sync.status].label} · {when(sync)}
          {sync.new_videos > 0 && ` · ${plural(sync.new_videos, "new video")}`}
        </p>
        {sync.status === "running" && sync.fetching !== null && (
          <p className="mt-1 truncate text-xs text-muted-foreground" title={sync.fetching}>
            Fetching “{sync.fetching}”
          </p>
        )}
      </div>
      {sync.error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{sync.error}</AlertDescription>
        </Alert>
      )}
      <div className="rounded-lg border bg-card p-4">
        <StageRule counts={sync.stage_counts} detailed />
      </div>
      {retryError !== null && (
        <Alert variant="destructive">
          <AlertDescription>Could not retry the failed videos: {retryError}</AlertDescription>
        </Alert>
      )}
      {finished && sync.stage_counts.failed > 0 && (
        <Button
          variant="outline"
          size="sm"
          disabled={retrying}
          onClick={() => void retryFailed(sync.channel_id)}
        >
          Retry failed videos
        </Button>
      )}
    </section>
  );
}

export function SyncsEmpty() {
  return <p className="text-sm text-muted-foreground">Pick a sync to see its progress.</p>;
}
