import {
  defaultScheduler,
  notifyManager,
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { type ReactElement, type ReactNode, StrictMode } from "react";
import { afterEach, onTestFinished, vi } from "vitest";
import type {
  CancelSessionRequest,
  PerformSessionActionData,
  SessionResponse,
  SessionSummaryResponse,
  TimelineEntryResponse,
} from "../../src/api/generated/types.gen";
import {
  ConversationScreen,
  sessionQueryOptions,
} from "../../src/features/conversation";
import { TranscriptScreen } from "../../src/features/transcript";
import {
  ServerStatusProvider,
  ServerUnreachableBanner,
} from "../../src/lib/ServerStatus";
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
 * Serve one session: GET answers the server's current view, each posted
 * action is recorded and answered by `respond` — a new view (which becomes the
 * current one) or any other response, such as a Problem Details error — and
 * each cancel is recorded and answered by `cancel`, 204 unless it says otherwise.
 */
export function serveSession(
  initial: SessionResponse,
  respond: (
    body: ActionBody,
    current: SessionResponse,
  ) => SessionResponse | Response | Promise<SessionResponse | Response> = () =>
    HttpResponse.error(),
  cancel: (body: CancelSessionRequest) => Response | Promise<Response> = () =>
    new HttpResponse(null, { status: 204 }),
) {
  let current = initial;
  const bodies: ActionBody[] = [];
  const cancels: CancelSessionRequest[] = [];
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
    http.post(`/api/sessions/${SESSION_ID}/cancel`, async ({ request }) => {
      const body = (await request.json()) as CancelSessionRequest;
      cancels.push(body);
      return cancel(body);
    }),
  );
  return {
    bodies,
    cancels,
    current: () => current,
    /** Change the server's view, as another tab's action would. */
    set: (next: SessionResponse) => {
      current = next;
    },
  };
}

function SessionHarness({
  before,
  screen = "conversation",
}: {
  before?: ReactNode;
  screen?: "conversation" | "transcript";
}) {
  // The route's own read: the screen renders whatever the session query holds.
  const query = useQuery(sessionQueryOptions(SESSION_ID));
  const Screen = screen === "transcript" ? TranscriptScreen : ConversationScreen;
  // The root layout's server-unreachable banner, above the screen.
  return (
    <ServerStatusProvider>
      <ServerUnreachableBanner />
      {before}
      {query.data && <Screen view={query.data} />}
    </ServerStatusProvider>
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

/**
 * Render the ended transcript (S3) over `view`, read from the session query as
 * the route reads it; `strict` renders it under StrictMode.
 */
export function renderTranscript(
  view: SessionResponse,
  { strict = false }: { strict?: boolean } = {},
) {
  const queryClient = newQueryClient();
  queryClient.setQueryData(sessionQueryOptions(SESSION_ID).queryKey, view);
  const harness = <SessionHarness screen="transcript" />;
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

/**
 * Fake timers for a test of behavior driven by time (the 300 ms delay, the
 * 10 s long wait, the 2 s poll), undone when the test finishes. The test moves
 * time only with `advance`, never `findBy` or `waitFor`.
 *
 * - Testing Library recognizes fake timers only through a `jest` global, so
 *   one is stubbed for it to advance them: its async wrapper (which user-event
 *   runs in) waits on a zero-delay timeout.
 * - TanStack Query batches its notifications on a zero-delay timeout, which
 *   fake timers fire 1 ms late when it is set while they run; a microtask
 *   keeps each notification at the instant it belongs to.
 */
export function installFakeClock() {
  vi.useFakeTimers();
  vi.stubGlobal("jest", {
    advanceTimersByTime: (ms: number) => vi.advanceTimersByTime(ms),
  });
  notifyManager.setScheduler(queueMicrotask);
  onTestFinished(() => {
    notifyManager.setScheduler(defaultScheduler);
    vi.useRealTimers();
  });
}

/**
 * Move fake time on by `ms`, then let everything due at that instant settle
 * without moving it further: a response takes several turns of the microtask
 * queue and a zero-delay timer or two to reach the screen.
 */
export async function advance(ms: number) {
  await act(() => vi.advanceTimersByTimeAsync(ms));
  for (let turn = 0; turn < 5; turn += 1) {
    await act(() => vi.advanceTimersByTimeAsync(0));
  }
}
