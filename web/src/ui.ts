import { useState } from "react";
import { errorText } from "./api";

export const inputClass =
  "rounded-md border border-stone-300 px-3 py-1.5 text-sm focus:border-stone-500 focus:outline-none";
export const buttonClass =
  "rounded-md bg-stone-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-stone-700 disabled:opacity-50";
export const quietButtonClass =
  "rounded-md px-2 py-1 text-sm text-stone-600 hover:bg-stone-100 hover:text-stone-900 disabled:opacity-50";

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
