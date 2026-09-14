import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

const dark = window.matchMedia("(prefers-color-scheme: dark)");

function stored(): Theme {
  const value = localStorage.getItem("theme");
  return value === "light" || value === "dark" ? value : "system";
}

function apply(theme: Theme) {
  const on = theme === "dark" || (theme === "system" && dark.matches);
  document.documentElement.classList.toggle("dark", on);
}

// At module load, so the first paint is already in the chosen theme.
apply(stored());

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(stored);

  useEffect(() => {
    apply(theme);
    if (theme !== "system") return;
    const onChange = () => apply("system");
    dark.addEventListener("change", onChange);
    return () => dark.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    if (next === "system") localStorage.removeItem("theme");
    else localStorage.setItem("theme", next);
    setThemeState(next);
  }, []);

  return { theme, setTheme };
}
