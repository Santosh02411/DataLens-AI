import { Monitor, Moon, Sun } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { applyTheme, readMode, resolve, saveMode, systemPrefersDark, type ThemeMode } from "./theme";

interface ThemeState {
  mode: ThemeMode;
  resolved: "light" | "dark";
  setMode: (m: ThemeMode) => void;
}

const Ctx = createContext<ThemeState>({ mode: "system", resolved: "light", setMode: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => readMode());
  const [prefersDark, setPrefersDark] = useState(systemPrefersDark);
  const resolved = resolve(mode, prefersDark);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => setPrefersDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    applyTheme(resolved);
    // Enable colour transitions only after the first paint, so startup never animates.
    requestAnimationFrame(() => document.documentElement.classList.add("theme-ready"));
  }, [resolved]);

  const value = useMemo(() => ({ mode, resolved, setMode: (m: ThemeMode) => { saveMode(m); setModeState(m); } }), [mode, resolved]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

export interface ChartColors {
  grid: string; axis: string; text: string; surface: string; line: string; caution: string; muted: string; series: string[]; cursor: string;
}

const LIGHT_SERIES = ["#0F766E", "#3B5BA9", "#B45309", "#7C3AED", "#64748B", "#0891B2"];
const DARK_SERIES = ["#A78BFA", "#2DD4BF", "#F472B6", "#FBBF24", "#60A5FA", "#94A3B8"];

/** Concrete colours for Recharts (SVG attributes), derived from the active theme's tokens. */
export function useChartColors(): ChartColors {
  const { resolved } = useTheme();
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    const rgb = (name: string) => `rgb(${css.getPropertyValue(`--${name}`).trim().split(/\s+/).join(",")})`;
    return {
      grid: resolved === "dark" ? "rgba(255,255,255,0.07)" : "#EEF1F5",
      axis: rgb("ink-muted"),
      text: rgb("ink"),
      muted: rgb("ink-muted"),
      surface: rgb("surface"),
      line: rgb("line"),
      caution: rgb("caution"),
      cursor: resolved === "dark" ? "rgba(167,139,250,0.10)" : "rgba(15,118,110,0.06)",
      series: resolved === "dark" ? DARK_SERIES : LIGHT_SERIES,
    };
  }, [resolved]);
}

const OPTIONS: { mode: ThemeMode; label: string; Icon: typeof Sun }[] = [
  { mode: "light", label: "Light", Icon: Sun },
  { mode: "dark", label: "Dark", Icon: Moon },
  { mode: "system", label: "System", Icon: Monitor },
];

/** Accessible segmented control (radiogroup with arrow-key navigation). */
export function ThemeToggle({ tone = "sidebar" }: { tone?: "sidebar" | "page" }) {
  const { mode, setMode } = useTheme();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = OPTIONS.findIndex((o) => o.mode === mode);
  const move = (delta: number) => {
    const next = (idx + delta + OPTIONS.length) % OPTIONS.length;
    setMode(OPTIONS[next].mode);
    refs.current[next]?.focus();
  };
  const base = tone === "sidebar" ? "bg-surface-2 ring-line" : "bg-surface ring-line";
  return (
    <div role="radiogroup" aria-label="Colour theme" className={`inline-flex rounded-lg p-0.5 ring-1 ${base}`}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); move(1); }
        if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      }}>
      {OPTIONS.map(({ mode: m, label, Icon }, i) => {
        const active = m === mode;
        const cls = tone === "sidebar"
          ? active ? "bg-ink text-canvas" : "text-ink-muted hover:text-ink"
          : active ? "bg-ink text-canvas" : "text-ink-muted hover:text-ink";
        return (
          <button key={m} ref={(el) => { refs.current[i] = el; }} role="radio" aria-checked={active} tabIndex={active ? 0 : -1}
            onClick={() => setMode(m)} title={`${label} theme`}
            className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium ${cls}`}>
            <Icon className="h-3.5 w-3.5" aria-hidden /> {label}
          </button>
        );
      })}
    </div>
  );
}
