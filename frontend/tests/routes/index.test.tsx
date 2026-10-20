import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionPageResponse } from "../../src/api/generated/types.gen";
import { createQueryClient } from "../../src/lib/query-client";
import { createAppRouter } from "../../src/router";
import {
  entry,
  SESSION_ID,
  serveSession,
  sessionRow,
  sessionView,
} from "../msw/helpers";
import { server } from "../msw/server";

// On a line of its own: the bootstrap rewrites it to a display name of up to
// 60 characters, which must not push any line past Biome's 88 columns.
const APP_NAME = "Intent to English";
const TAGLINE = "英語で話す前に、日本語で言いたいことを決める練習";

function renderAt(path: string) {
  const queryClient = createQueryClient();
  const history = createMemoryHistory({ initialEntries: [path] });
  const router = createAppRouter(queryClient, { history });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

// Longer than TanStack Query's default five-minute lifetime for a query no
// screen is reading, which is how long S1's list sits unread during a session.
const LONG_SESSION_MS = 6 * 60 * 1000;

describe("/", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the home screen inside the root layout", async () => {
    renderAt("/");

    expect(
      await screen.findByRole("heading", { level: 1, name: TAGLINE }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "新しい会話を始める" })).toHaveFocus();
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: APP_NAME })).toBeInTheDocument();
  });

  it.each([
    { name: "at once", awayMs: 0 },
    {
      name: "after a session longer than the cache's default",
      awayMs: LONG_SESSION_MS,
    },
  ])(
    "keeps the pages already loaded when the learner comes back from a session $name",
    async ({ awayMs }) => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const older = Array.from({ length: 20 }, (_, index) =>
        sessionRow({
          id: `0199c1f0-0000-7000-8000-${String(100 - index).padStart(12, "0")}`,
          status: "ended",
          opener: `Opener ${index}`,
        }),
      );
      const last = sessionRow({ status: "ended", opener: "The last one" });
      const requests: (string | null)[] = [];
      server.use(
        http.get("/api/sessions", ({ request }) => {
          const cursor = new URL(request.url).searchParams.get("cursor");
          requests.push(cursor);
          return HttpResponse.json<SessionPageResponse>(
            cursor === null
              ? { items: older, next_cursor: "page-2" }
              : { items: [last], next_cursor: null },
          );
        }),
      );
      serveSession(
        sessionView({
          status: "ended",
          stage: "ended",
          ended_at: new Date(2026, 9, 17, 19, 0).toISOString(),
          entries: [
            entry("partner_line", {
              text: "The last one",
              has_question: true,
              line_kind: "opener",
              restate_mode: null,
            }),
          ],
        }),
      );
      const router = renderAt("/");
      await user.click(await screen.findByRole("button", { name: "さらに表示" }));
      await user.click(await screen.findByRole("link", { name: /The last one/ }));
      expect(router.state.location.pathname).toBe(`/sessions/${SESSION_ID}`);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(awayMs);
      });

      router.history.back();

      expect(
        await screen.findByRole("link", { name: /The last one/ }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "さらに表示" }),
      ).not.toBeInTheDocument();
      expect(router.options.scrollRestoration).toBe(true);
    },
  );

  it("gives the router the query client in its context", () => {
    const queryClient = createQueryClient();

    const router = createAppRouter(queryClient);

    expect(router.options.context.queryClient).toBe(queryClient);
  });

  it("restores S1 by pathname through return links while other pages keep their history key", () => {
    const router = createAppRouter(createQueryClient());
    const location = router.state.location;
    const key = router.options.getScrollRestorationKey;
    for (const historyKey of ["first-home-visit", "return-link-visit"]) {
      expect(
        key?.({
          ...location,
          pathname: "/",
          state: { ...location.state, __TSR_key: historyKey },
        }),
      ).toBe("/");
    }
    expect(
      key?.({
        ...location,
        pathname: "/sessions/one",
        state: { ...location.state, __TSR_key: "session-visit" },
      }),
    ).toBe("session-visit");
  });
});
