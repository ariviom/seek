import { useRef, useState } from "react";
import { bundleUrl, errorText, type BuiltBundle } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatCount } from "@/lib/format";

// Followed as a link carrying `download`, so the browser saves the file itself instead of the page holding it in
// memory, and a link that fails is a failed download, never a navigation away from the app.
function download(url: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
}

// The Export button of a Channel's or a Playlist's page.
export function ExportButton({ indexedVideos, onClick }: { indexedVideos: number; onClick: () => void }) {
  if (indexedVideos > 0) {
    return (
      <Button size="sm" variant="ghost" onClick={onClick}>
        Export
      </Button>
    );
  }
  return (
    <Tooltip>
      {/* A disabled button raises no pointer events, so the tooltip hangs on a wrapper that does. */}
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex">
          <Button size="sm" variant="ghost" disabled>
            Export
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent>No indexed Videos to export yet.</TooltipContent>
    </Tooltip>
  );
}

// Says what an export shares, builds the Bundle, and hands it to the browser to download.
export function ExportDialog({
  name,
  indexedVideos,
  playlistFilterLeftOut = false,
  build,
  open,
  onOpenChange,
}: {
  name: string;
  indexedVideos: number;
  // A Channel's Playlist filter, which a Bundle never carries.
  playlistFilterLeftOut?: boolean;
  build: () => Promise<BuiltBundle>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // The build's own state, apart from the page's runner of changes: a refusal belongs in this dialog, and a build
  // changes nothing the page would have to reload.
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // `building` lands a render late, and a second click in between would build a second Bundle.
  const running = useRef(false);

  function change(next: boolean) {
    // Not while it builds: the download would start with nothing on screen to explain it.
    if (running.current) return;
    if (!next) setError(null);
    onOpenChange(next);
  }

  async function exportBundle() {
    if (running.current) return;
    running.current = true;
    setError(null);
    setBuilding(true);
    try {
      const built = await build();
      download(bundleUrl(built.id));
      onOpenChange(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      running.current = false;
      setBuilding(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogContent showCloseButton={!building}>
        <DialogHeader>
          <DialogTitle>Export {name}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-2 text-sm">
          <p>
            {formatCount(indexedVideos)} indexed {indexedVideos === 1 ? "Video goes" : "Videos go"} into one{" "}
            <code>.seek</code> file.
          </p>
          <p>The file contains the creators’ full Transcripts, so choose who you share it with.</p>
          {playlistFilterLeftOut && (
            <p>
              The Channel’s Playlist filter is left out, so the recipient’s Syncs will bring in its other Videos.
            </p>
          )}
        </div>
        {error !== null && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="ghost" disabled={building} onClick={() => change(false)}>
            Cancel
          </Button>
          <Button disabled={building} onClick={() => void exportBundle()}>
            {building ? "Building…" : "Export"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
