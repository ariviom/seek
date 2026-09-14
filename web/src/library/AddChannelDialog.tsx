import { useState, type FormEvent } from "react";
import { api, errorText, type Channel, type ChannelProposal } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

export function AddChannelDialog({
  open,
  onOpenChange,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: (channel: Channel) => void;
}) {
  const [query, setQuery] = useState("");
  const [proposal, setProposal] = useState<ChannelProposal | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset(next: boolean) {
    if (!next) {
      setQuery("");
      setProposal(null);
      setName("");
      setError(null);
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
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a channel</DialogTitle>
        </DialogHeader>
        <form onSubmit={proposal === null ? lookUp : add} className="grid gap-3">
          <label className="grid gap-1.5 text-sm">
            YouTube channel URL or handle
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={proposal !== null}
              aria-label="YouTube channel URL or handle"
            />
          </label>
          {proposal !== null && (
            <>
              <p className="text-sm">Found {proposal.name}</p>
              <label className="grid gap-1.5 text-sm">
                Channel name
                <Input value={name} onChange={(e) => setName(e.target.value)} aria-label="Channel name" />
              </label>
            </>
          )}
          {error !== null && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            {proposal === null ? (
              <Button type="submit" disabled={busy || query.trim() === ""}>
                Look up
              </Button>
            ) : (
              <Button type="submit" disabled={busy || name.trim() === ""}>
                Add
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
