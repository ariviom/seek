import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Rename in place: the button becomes the form, and the form goes back to the button once it saves.
export function RenameForm({
  label,
  name,
  onRename,
}: {
  label: string;
  name: string;
  onRename: (name: string) => Promise<boolean>;
}) {
  const [renaming, setRenaming] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (renaming !== null && (await onRename(renaming))) setRenaming(null);
  }

  if (renaming === null) {
    return (
      <Button size="sm" variant="ghost" onClick={() => setRenaming(name)}>
        Rename
      </Button>
    );
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
      <Input className="w-56" value={renaming} onChange={(e) => setRenaming(e.target.value)} aria-label={label} />
      <Button size="sm" type="submit" disabled={renaming.trim() === ""}>
        Save
      </Button>
      <Button size="sm" variant="ghost" type="button" onClick={() => setRenaming(null)}>
        Cancel
      </Button>
    </form>
  );
}
