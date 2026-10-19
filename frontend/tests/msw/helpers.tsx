import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { type ReactElement, type ReactNode, StrictMode } from "react";
import { afterEach, vi } from "vitest";
import type {
  PerformSessionActionData,
  SessionResponse,
  SessionSummaryResponse,
  TimelineEntryResponse,
} from "../../src/api/generated/types.gen";
import {
  ConversationScreen,
  sessionQueryOptions,
} from "../../src/features/conversation";
import { server } from "./server";

const clients = new Set<QueryClient>();
afterEach(() => {
  for (const client of clients) client.clear();
  clients.clear();
});

export function renderWithQuery(ui: ReactElement, queryClient = newQueryClient()) {
  return {
    ...render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>),
    queryClient,
  };
}

function newQueryClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.add(queryClient);
  return queryClient;
}

export const SESSION_ID = "0199c1f0-0000-7000-8000-0000000000aa";

/**
 * A typed row of the session list: an in-progress session started 10/17 18:40
 * local time with the first fixed opener, unless overridden.
 */
export function sessionRow(
  overrides: Partial<SessionSummaryResponse> = {},
): SessionSummaryResponse {
  return {
    id: SESSION_ID,
    started_at: new Date(2026, 9, 17, 18, 40).toISOString(),
    status: "in_progress",
    finished_replies: 0,
    opener: "Hey! How's it going?",
    ...overrides,
  };
}

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

export type ActionBody = PerformSessionActionData["body"];

/**
 * Serve one session: GET answers the server's current view, and each posted
 * action is recorded and answered by `respond` — a new view (which becomes the
 * current one) or any other response, such as a Problem Details error.
 */
export function serveSession(
  initial: SessionResponse,
  respond: (
    body: ActionBody,
    current: SessionResponse,
  ) => SessionResponse | Response | Promise<SessionResponse | Response> = () =>
    HttpResponse.error(),
) {
  let current = initial;
  const bodies: ActionBody[] = [];
  server.use(
    http.get(`/api/sessions/${SESSION_ID}`, () =>
      HttpResponse.json<SessionResponse>(current),
    ),
    http.post(`/api/sessions/${SESSION_ID}/actions`, async ({ request }) => {
      const body = (await request.json()) as ActionBody;
      bodies.push(body);
      const result = await respond(body, current);
      if (result instanceof Response) return result;
      current = result;
      return HttpResponse.json<SessionResponse>(result);
    }),
  );
  return { bodies, current: () => current };
}

function SessionHarness({ before }: { before?: ReactNode }) {
  // The route's own read: the screen renders whatever the session query holds.
  const query = useQuery(sessionQueryOptions(SESSION_ID));
  return (
    <>
      {before}
      {query.data && <ConversationScreen view={query.data} />}
    </>
  );
}

/**
 * Render the conversation screen over `view`, read from the session query as
 * the route reads it; `strict` renders it under StrictMode.
 */
export function renderSession(
  view: SessionResponse,
  { strict = false, before }: { strict?: boolean; before?: ReactNode } = {},
) {
  const queryClient = newQueryClient();
  queryClient.setQueryData(sessionQueryOptions(SESSION_ID).queryKey, view);
  const harness = <SessionHarness before={before} />;
  return renderWithQuery(
    strict ? <StrictMode>{harness}</StrictMode> : harness,
    queryClient,
  );
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
