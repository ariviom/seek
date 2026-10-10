import type { ReactNode } from "react";

// Helper text that is a pane's only content, centred in the space the pane has left. Its parent must be a column
// that fills the pane, as the main pane's is.
export function PaneMessage({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center px-6 py-6">
      <p className="max-w-sm text-center text-sm text-balance text-muted-foreground">{children}</p>
    </div>
  );
}
