import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, vi } from "vitest";
import type {
  SessionResponse,
  TimelineEntryResponse,
  TodoResponse,
} from "../../src/api/generated/types.gen";

const clients = new Set<QueryClient>();
afterEach(() => {
  for (const client of clients) client.clear();
  clients.clear();
});

export function renderWithQuery(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.add(queryClient);
  return {
    ...render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>),
    queryClient,
  };
}

export function todo(
  title: string,
  id = "0199c1f0-0000-7000-8000-000000000001",
): TodoResponse {
  return { id, title, completed: false, created_at: "2026-10-08T09:00:00Z" };
}

export const SESSION_ID = "0199c1f0-0000-7000-8000-0000000000aa";

type EntryKind = TimelineEntryResponse["kind"];
type EntryOf<K extends EntryKind> = Extract<TimelineEntryResponse, { kind: K }>;

/**
 * A typed timeline entry of `kind` in `turn`. `sessionView` numbers the
 * entries it is given, so `seq` and `id` here are placeholders.
 */
export function entry<K extends EntryKind>(
  kind: K,
  payload: EntryOf<K>["payload"],
  turn = 1,
): EntryOf<K> {
  return {
    id: "",
    session_id: SESSION_ID,
    seq: 0,
    turn_index: turn,
    created_at: "2026-10-17T09:40:00Z",
    kind,
    payload,
  } as EntryOf<K>;
}

/**
 * A typed session view: an in-progress session at `intent` unless overridden,
 * with its entries numbered 1, 2, … in the order given.
 */
export function sessionView(overrides: Partial<SessionResponse> = {}): SessionResponse {
  const view: SessionResponse = {
    id: SESSION_ID,
    status: "in_progress",
    stage: "intent",
    version: 1,
    turn_index: 1,
    finished_replies: 0,
    started_at: new Date(2026, 9, 17, 18, 40).toISOString(),
    ended_at: null,
    allowed_actions: [],
    entries: [],
    last_submission: null,
    wrap_up: null,
    ...overrides,
  };
  return {
    ...view,
    entries: view.entries.map((item, index) => ({
      ...item,
      seq: index + 1,
      id: `0199c1f0-0000-7000-8000-${String(index + 1).padStart(12, "0")}`,
    })),
  };
}

/** Stub `window.matchMedia` so every query reports `matches`. */
export function stubMatchMedia(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

export function deferred() {
  let resolve: (() => void) | undefined;
  const promise = new Promise<void>((release) => {
    resolve = release;
  });
  return {
    promise,
    release: () => {
      if (!resolve) throw new Error("Deferred barrier was not initialized");
      resolve();
    },
  };
}
