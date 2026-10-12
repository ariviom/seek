import { useRef, useState } from "react";
import { api, errorText, type ImportedBundle, type Sync } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { formatCount, formatSize } from "@/lib/format";
import { isRunning } from "@/lib/sync-status";
import { filtersSummary } from "./ChannelFiltersDialog";

// What the Library does about an import, whichever dialog it was made in.
export type ImportHandlers = {
  onImported: (report: ImportedBundle) => void;
  // A refused import may have come partway, so the Library has changed all the same.
  onRefused: () => void;
};

// Why the path is closed while any Sync is running or queued, in the words the server refuses such an import with.
const SYNC_IN_THE_WAY = "A Sync is running or waiting to run; import when it has finished.";

// The most the server takes, and its sentence for a file over it, said here before the file is sent. The server
// holds the same number, and its own is the one that counts.
const UPLOAD_CAP_BYTES = 2_000_000_000;
const TOO_LARGE = "The file is larger than 2 GB, the most the web UI imports; import it with `seek import`.";

// Importing a Bundle, the second way to add something that both Add dialogs offer. The dialog holds this state,
// since it is the dialog that an import locks and whose content the report takes over.
export function useBundleImport({ onImported, onRefused }: ImportHandlers, syncs: Sync[] | null) {
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportedBundle | null>(null);
  // `importing` lands a render late, and a second click in between would send the file twice.
  const running = useRef(false);
  // The server would refuse the file once all of it had been sent, so it is not sent at all.
  const syncing = syncs?.some(isRunning) ?? false;
  const tooLarge = file !== null && file.size > UPLOAD_CAP_BYTES;

  async function start() {
    if (file === null || tooLarge || syncing || running.current) return;
    running.current = true;
    setError(null);
    setImporting(true);
    try {
      const imported = await api.importBundle(file);
      setReport(imported);
      onImported(imported);
    } catch (e) {
      // The file stays chosen, so an import refused for something that passes can be tried again.
      setError(errorText(e));
      onRefused();
    } finally {
      running.current = false;
      setImporting(false);
    }
  }

  return {
    file,
    choose: (chosen: File | null) => {
      setFile(chosen);
      setError(null);
    },
    importing,
    syncing,
    tooLarge,
    error: tooLarge ? TOO_LARGE : error,
    report,
    start,
    // For the dialog to call as it closes.
    reset: () => {
      setFile(null);
      setError(null);
      setReport(null);
    },
  };
}

export type BundleImport = ReturnType<typeof useBundleImport>;

// The path itself, under a dialog's URL form: a file picker, then the chosen file and an Import button. There is
// no name to give: the Channel or Playlist takes the Bundle's, and Rename is on its page.
export function ImportBundle({ bundle }: { bundle: BundleImport }) {
  const { file, importing, syncing, tooLarge, error } = bundle;
  return (
    <div className="grid gap-3 border-t pt-3">
      <label className="grid gap-1.5 text-sm">
        <span>
          or import a <code>.seek</code> file
        </span>
        <Input
          type="file"
          accept=".seek"
          disabled={importing || syncing}
          onChange={(e) => bundle.choose(e.target.files?.[0] ?? null)}
        />
      </label>
      {syncing && <p className="text-xs text-muted-foreground">{SYNC_IN_THE_WAY}</p>}
      {file !== null && (
        <div className="flex items-center justify-between gap-2 text-sm">
          <span className="min-w-0 truncate">
            {file.name} · {formatSize(file.size)}
          </span>
          {/* Not the form's submit, which is the URL's Look up or Add. */}
          <Button
            type="button"
            size="sm"
            disabled={importing || syncing || tooLarge}
            onClick={() => void bundle.start()}
          >
            {importing ? "Importing…" : "Import"}
          </Button>
        </div>
      )}
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function videos(count: number): string {
  return `${formatCount(count)} ${count === 1 ? "Video" : "Videos"}`;
}

// What an import did, in place of the dialog's form: the lines `seek import` prints, with a button where the
// command names the one to run next.
export function ImportReport({ report, onClose }: { report: ImportedBundle; onClose: () => void }) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const leftOut = Object.entries(report.left_out);
  const arrived = report.created && report.filters !== null ? filtersSummary(report.filters) : "";

  async function startSync() {
    setError(null);
    setStarting(true);
    try {
      await (report.kind === "channel" ? api.startSync(report.id) : api.startPlaylistSync(report.id));
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setStarting(false);
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          Imported the {report.kind === "channel" ? "Channel" : "Playlist"} {report.name}
        </DialogTitle>
      </DialogHeader>
      <div className="grid gap-2 text-sm">
        <p>
          {videos(report.added)} added, {formatCount(report.already_indexed)} already indexed,{" "}
          {formatCount(leftOut.reduce((sum, [, count]) => sum + count, 0))} left out.
        </p>
        {leftOut.length > 0 && (
          <ul className="list-disc pl-5">
            {leftOut.map(([reason, count]) => (
              <li key={reason}>
                {reason}: {formatCount(count)}
              </li>
            ))}
          </ul>
        )}
        {!report.created && <p>It was already in the Library, and keeps its name and settings.</p>}
        {arrived !== "" && <p>It arrived with its filters: {arrived}.</p>}
        <p>The Bundle’s text came from whoever made the file, and is only as trustworthy as they are.</p>
      </div>
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
        <Button disabled={starting} onClick={() => void startSync()}>
          Start a Sync
        </Button>
      </DialogFooter>
    </>
  );
}
