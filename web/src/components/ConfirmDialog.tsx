import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

// A destructive change the user confirms: the title doubles as the action's label.
export function ConfirmDialog({
  title,
  actionLabel,
  open,
  onOpenChange,
  onConfirm,
  busy = false,
  children,
}: {
  title: string;
  actionLabel: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  // The dialog sits in a portal, outside any fieldset that locks the page while a change runs.
  busy?: boolean;
  children: ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <p className="text-sm">{children}</p>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" disabled={busy} onClick={onConfirm}>
            {actionLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
