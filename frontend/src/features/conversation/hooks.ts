import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { announcementFor, type Entry } from "./session";

const WIDE = "(min-width: 1024px)";

function subscribe(onChange: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(WIDE);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function wideNow() {
  // Without matchMedia (a test DOM), the desktop layout is the default.
  return typeof window.matchMedia === "function"
    ? window.matchMedia(WIDE).matches
    : true;
}

/** Whether the viewport is at least 1024 px wide: two panes, else tabs. */
export function useWideLayout(): boolean {
  return useSyncExternalStore(subscribe, wideNow, () => true);
}

/** How close to its bottom a pane must be for new content to scroll it. */
const NEAR_BOTTOM_PX = 80;

/**
 * Keep a scrolling pane at its newest content while the learner is reading
 * there: when `content` changes, the pane scrolls to its bottom only if it was
 * within 80 px of it. Smoothness is the pane's CSS (instant when reduced).
 */
export function useFollowBottom(content: unknown) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useRef(true);
  const shown = useRef<unknown>(undefined);
  useEffect(() => {
    if (Object.is(shown.current, content)) return;
    shown.current = content;
    const pane = ref.current;
    if (pane !== null && near.current) pane.scrollTop = pane.scrollHeight;
  }, [content]);
  return {
    ref,
    onScroll: () => {
      const pane = ref.current;
      if (pane === null) return;
      near.current =
        pane.scrollHeight - pane.scrollTop - pane.clientHeight <= NEAR_BOTTOM_PX;
    },
  };
}

export interface Arrival {
  /** Counts arrivals, so the live region can re-key the same text. */
  key: number;
  ids: ReadonlySet<string>;
  /** 「Partner: …」 and 「コーチ: …」 for each new line or block, in order. */
  message: string;
  partner: boolean;
}

/**
 * The entries that arrived since the last render, never those present when the
 * screen opened: what the live region announces once.
 */
export function useArrivals(entries: readonly Entry[]): Arrival {
  const seen = useRef<Set<string> | null>(null);
  if (seen.current === null) seen.current = new Set(entries.map((item) => item.id));
  const [arrival, setArrival] = useState<Arrival>({
    key: 0,
    ids: new Set(),
    message: "",
    partner: false,
  });
  useEffect(() => {
    const known = seen.current ?? new Set<string>();
    const arrived = entries.filter((item) => !known.has(item.id));
    if (arrived.length === 0) return;
    for (const item of arrived) known.add(item.id);
    setArrival((previous) => ({
      key: previous.key + 1,
      ids: new Set(arrived.map((item) => item.id)),
      message: arrived
        .map((item) => announcementFor(item, entries))
        .filter((line) => line !== null)
        .join("\n"),
      partner: arrived.some((item) => item.kind === "partner_line"),
    }));
  }, [entries]);
  return arrival;
}

/**
 * Whether `ms` have passed since `key` last changed to a value other than
 * null: a wait's own clock, which restarts for each new key.
 */
export function useAfter(key: string | null, ms: number): boolean {
  const [passed, setPassed] = useState<string | null>(null);
  useEffect(() => {
    if (key === null) return undefined;
    const timer = window.setTimeout(() => setPassed(key), ms);
    return () => window.clearTimeout(timer);
  }, [key, ms]);
  return key !== null && passed === key;
}
