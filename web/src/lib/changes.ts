import { useRef, useState } from "react";
import { errorText } from "@/lib/api";

// Runs one change at a time; resolves true when the change itself succeeded.
export type Act = (change: () => Promise<unknown>) => Promise<boolean>;

// Callers disable their controls while busy, so changes and their refreshes never interleave. A change asked for while
// one runs is dropped: `busy` lands a render late, and dialog buttons sit outside the controls a caller disables.
export function useChanges(refresh: () => Promise<void>, setError: (message: string | null) => void) {
  const [busy, setBusy] = useState(false);
  const running = useRef(false);

  const act: Act = async (change) => {
    if (running.current) return false;
    running.current = true;
    setError(null);
    setBusy(true);
    try {
      await change();
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      await refresh();
      running.current = false;
      setBusy(false);
    }
    return true;
  };

  return { act, busy };
}
