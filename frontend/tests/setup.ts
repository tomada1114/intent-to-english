import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// Testing Library cleans up on its own only when the runner injects a global
// afterEach, which Vitest does not without `globals: true`.
afterEach(cleanup);

// jsdom has no layout, so it implements no scrolling; the router's scroll
// restoration calls window.scrollTo on every navigation. Restored after each
// test by unstubGlobals.
beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
