import { useState, type FormEvent } from "react";
import { api, errorText, type Channel, type ChannelProposal, type Sync } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ImportBundle, ImportReport, useBundleImport, type ImportHandlers } from "./ImportBundle";

export function AddChannelDialog({
  open,
  onOpenChange,
  onAdded,
  imports,
  syncs,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: (channel: Channel) => void;
  // A Bundle imported here may be of either kind, so what it added is the Library's to select.
  imports: ImportHandlers;
  // Every Sync, live: importing waits while one is running or queued.
  syncs: Sync[] | null;
}) {
  const [query, setQuery] = useState("");
  const [proposal, setProposal] = useState<ChannelProposal | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bundle = useBundleImport(imports, syncs);

  function reset(next: boolean) {
    // Not while a Bundle is importing: its report, or its refusal, would have nowhere to show.
    if (bundle.importing) return;
    if (!next) {
      setQuery("");
      setProposal(null);
      setName("");
      setError(null);
      bundle.reset();
    }
    onOpenChange(next);
  }

  async function lookUp(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const found = await api.resolveChannel(query);
      setProposal(found);
      setName(found.name);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    if (proposal === null) return;
    setError(null);
    setBusy(true);
    try {
      const channel = await api.createChannel(proposal.youtube_channel_id, name);
      reset(false);
      onAdded(channel);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogContent showCloseButton={!bundle.importing && bundle.report === null}>
        {bundle.report !== null ? (
          <ImportReport report={bundle.report} onClose={() => reset(false)} />
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Add a channel</DialogTitle>
              {/* Said here, where it can still change the choice: how long the first Sync takes is decided now. */}
              <DialogDescription>
                Start with a small channel. Seek fetches and indexes every video it finds, so a large back catalogue
                can take hours. You can add more once you have seen how the first one goes.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={proposal === null ? lookUp : add} className="grid gap-3">
              <label className="grid gap-1.5 text-sm">
                YouTube channel URL or handle
                {/* Editing the URL drops the proposal, so a refused Add (already added) can be tried on another URL. */}
                <Input
                  value={query}
                  disabled={bundle.importing}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setProposal(null);
                    setError(null);
                  }}
                />
              </label>
              {proposal !== null && (
                <>
                  <p className="text-sm">Found {proposal.name}</p>
                  <label className="grid gap-1.5 text-sm">
                    Channel name
                    <Input value={name} disabled={bundle.importing} onChange={(e) => setName(e.target.value)} />
                  </label>
                </>
              )}
              {error !== null && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              <ImportBundle bundle={bundle} />
              <DialogFooter>
                {proposal === null ? (
                  <Button type="submit" disabled={busy || bundle.importing || query.trim() === ""}>
                    Look up
                  </Button>
                ) : (
                  <Button type="submit" disabled={busy || bundle.importing || name.trim() === ""}>
                    Add
                  </Button>
                )}
              </DialogFooter>
            </form>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
