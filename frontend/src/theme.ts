/** Theme state: Light, Dark or System. Stored in localStorage; applied as the `dark` class on <html>. */
export type ThemeMode = "light" | "dark" | "system";
export const THEME_KEY = "datalens-theme";

export function readMode(storage: Pick<Storage, "getItem"> | null = safeStorage()): ThemeMode {
  try {
    const v = storage?.getItem(THEME_KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}

export function saveMode(mode: ThemeMode, storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try {
    storage?.setItem(THEME_KEY, mode);
  } catch {
    /* private mode or storage disabled: the choice simply won't persist */
  }
}

export function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function resolve(mode: ThemeMode, prefersDark: boolean = systemPrefersDark()): "light" | "dark" {
  return mode === "system" ? (prefersDark ? "dark" : "light") : mode;
}

export function applyTheme(resolved: "light" | "dark", root: HTMLElement = document.documentElement): void {
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
}

function safeStorage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}
