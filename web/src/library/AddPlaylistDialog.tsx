import { useState, type FormEvent } from "react";
import { api, errorText, type Playlist, type PlaylistProposal } from "@/lib/api";
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
import { plural } from "@/lib/format";

export function AddPlaylistDialog({
  open,
  onOpenChange,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: (playlist: Playlist) => void;
}) {
  const [query, setQuery] = useState("");
  const [proposal, setProposal] = useState<PlaylistProposal | null>(null);
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
      const found = await api.resolvePlaylist(query);
      setProposal(found);
      setName(found.title);
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
      const playlist = await api.createPlaylist(proposal.youtube_playlist_id, name);
      reset(false);
      onAdded(playlist);
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
          <DialogTitle>Add a playlist</DialogTitle>
          <DialogDescription>
            Seek fetches and indexes every video in the playlist, each credited to the creator who made it. The
            creators aren’t added to your channels.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={proposal === null ? lookUp : add} className="grid gap-3">
          <label className="grid gap-1.5 text-sm">
            YouTube playlist URL
            {/* Editing the URL drops the proposal, so a refused Add (already added) can be tried on another URL. */}
            <Input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setProposal(null);
                setError(null);
              }}
            />
          </label>
          {proposal !== null && (
            <>
              <p className="text-sm">
                Found {proposal.title} · {plural(proposal.video_count, "video")}
              </p>
              <label className="grid gap-1.5 text-sm">
                Playlist name
                <Input value={name} onChange={(e) => setName(e.target.value)} />
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
