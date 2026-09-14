import { useState } from "react";
import { errorText } from "@/lib/api";

// Runs one change at a time; resolves true when the change itself succeeded.
export type Act = (change: () => Promise<unknown>) => Promise<boolean>;

// Callers disable their controls while busy, so changes and their refreshes never interleave.
export function useChanges(refresh: () => Promise<void>, setError: (message: string | null) => void) {
  const [busy, setBusy] = useState(false);

  const act: Act = async (change) => {
    setError(null);
    setBusy(true);
    try {
      await change();
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      await refresh();
      setBusy(false);
    }
    return true;
  };

  return { act, busy };
}
