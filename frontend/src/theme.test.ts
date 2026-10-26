import { readFileSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { applyTheme, readMode, resolve, saveMode, THEME_KEY } from "./theme";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return { getItem: (k: string) => (k in data ? data[k] : null), setItem: (k: string, v: string) => { data[k] = v; }, data };
}

describe("theme persistence", () => {
  it("defaults to system when nothing or something invalid is stored", () => {
    expect(readMode(memoryStorage())).toBe("system");
    expect(readMode(memoryStorage({ [THEME_KEY]: "purple" }))).toBe("system");
  });

  it("round-trips every mode through storage", () => {
    const s = memoryStorage();
    for (const m of ["light", "dark", "system"] as const) {
      saveMode(m, s);
      expect(readMode(s)).toBe(m);
    }
  });

  it("survives storage that throws (private mode)", () => {
    const broken = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };
    expect(readMode(broken)).toBe("system");
    expect(() => saveMode("dark", broken)).not.toThrow();
  });

  it("resolves system mode from the OS preference", () => {
    expect(resolve("system", true)).toBe("dark");
    expect(resolve("system", false)).toBe("light");
    expect(resolve("light", true)).toBe("light");
    expect(resolve("dark", false)).toBe("dark");
  });

  it("applies the class and color-scheme to the root element", () => {
    const root = document.createElement("html");
    applyTheme("dark", root);
    expect(root.classList.contains("dark")).toBe(true);
    expect(root.style.colorScheme).toBe("dark");
    applyTheme("light", root);
    expect(root.classList.contains("dark")).toBe(false);
    expect(root.style.colorScheme).toBe("light");
  });
});

describe("no-flash startup script in index.html", () => {
  const html = readFileSync(resolvePath(process.cwd(), "index.html"), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)![1];

  function runStartup(stored: string | null, osDark: boolean) {
    localStorage.clear();
    if (stored !== null) localStorage.setItem(THEME_KEY, stored);
    document.documentElement.className = "";
    window.matchMedia = ((q: string) => ({ matches: q.includes("dark") && osDark })) as unknown as typeof window.matchMedia;
    new Function(script)();
    return document.documentElement.classList.contains("dark");
  }

  beforeEach(() => localStorage.clear());

  it.each([
    ["dark", false, true],
    ["light", true, false],
    ["system", true, true],
    ["system", false, false],
    [null, true, true],
    ["bogus", false, false],
  ])("stored=%s osDark=%s -> dark=%s, matching theme.ts", (stored, osDark, expected) => {
    expect(runStartup(stored as string | null, osDark as boolean)).toBe(expected);
    const mode = readMode(memoryStorage(stored === null ? {} : { [THEME_KEY]: stored as string }));
    expect(resolve(mode, osDark as boolean) === "dark").toBe(expected);
  });
});
