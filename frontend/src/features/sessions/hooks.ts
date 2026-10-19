import { useEffect, useRef, useState } from "react";

/** Nothing shows for a load shorter than this (ux-guidelines § Feedback and loading). */
export const LOADING_DELAY_MS = 300;
/** Once shown, a loading indicator stays at least this long, so it never flashes. */
export const LOADING_MIN_MS = 500;

/**
 * Whether a loading indicator should show while `loading`: not before 300 ms
 * have passed, and once shown, for at least 500 ms even if loading ends sooner.
 */
export function useDelayedLoading(loading: boolean): boolean {
  const [shown, setShown] = useState(false);
  const shownAt = useRef(0);
  useEffect(() => {
    if (loading === shown) return undefined;
    const wait = loading
      ? LOADING_DELAY_MS
      : Math.max(0, shownAt.current + LOADING_MIN_MS - Date.now());
    const timer = window.setTimeout(() => {
      shownAt.current = Date.now();
      setShown(loading);
    }, wait);
    return () => window.clearTimeout(timer);
  }, [loading, shown]);
  return shown;
}
