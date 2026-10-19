import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type {
  ProblemDetails,
  SessionResponse,
} from "../../../src/api/generated/types.gen";
import { sessionQueryOptions } from "../../../src/features/conversation";
import { createQueryClient } from "../../../src/lib/query-client";
import { createAppRouter } from "../../../src/router";
import {
  advance,
  deferred,
  entry,
  installFakeClock,
  SESSION_ID,
  sessionView,
} from "../../msw/helpers";
import { server } from "../../msw/server";

const LOAD_FAILED = "この会話を読み込めませんでした。";
const LOADING = "読み込んでいます…";
const OPENER_TEXT = "Hey! How's it going?";

const view = sessionView({
  stage: "intent",
  allowed_actions: ["intent", "end"],
  entries: [
    entry("partner_line", {
      text: OPENER_TEXT,
      has_question: true,
      line_kind: "opener",
      restate_mode: null,
    }),
  ],
});

const internalError: ProblemDetails = {
  type: "about:blank",
  title: "Internal Server Error",
  status: 500,
  detail: "boom",
  code: "internal_error",
  request_id: "req-1",
};

function renderAt(path: string) {
  const queryClient = createQueryClient();
  const history = createMemoryHistory({ initialEntries: [path] });
  const router = createAppRouter(queryClient, { history });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return queryClient;
}

/** GET answers 500 while `failing()`, else the view; counts the reads. */
function serveRead(failing: () => boolean) {
  let reads = 0;
  server.use(
    http.get<never, never, SessionResponse | ProblemDetails>(
      `/api/sessions/${SESSION_ID}`,
      () => {
        reads += 1;
        return failing()
          ? HttpResponse.json<ProblemDetails>(internalError, { status: 500 })
          : HttpResponse.json<SessionResponse>(view);
      },
    ),
  );
  return () => reads;
}

describe("loading a session (REQ-008)", () => {
  it("shows the load-failed banner in place of the panes, and 再読み込み reads it again", async () => {
    let failing = true;
    const reads = serveRead(() => failing);
    const user = userEvent.setup();
    renderAt(`/sessions/${SESSION_ID}`);

    // The query client retries a 5xx once, after a second.
    const banner = await screen.findByRole("alert", {}, { timeout: 3000 });
    expect(banner).toHaveTextContent(LOAD_FAILED);
    expect(screen.queryByRole("region", { name: "コーチ" })).not.toBeInTheDocument();
    expect(reads()).toBe(2);
    failing = false;

    await user.click(within(banner).getByRole("button", { name: "再読み込み" }));

    expect(await screen.findByText(OPENER_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(LOAD_FAILED)).not.toBeInTheDocument();
  });

  it("shows the load-failed banner above the panes when a refetch fails, keeping what is shown", async () => {
    let failing = false;
    serveRead(() => failing);
    const queryClient = renderAt(`/sessions/${SESSION_ID}`);
    expect(await screen.findByText(OPENER_TEXT)).toBeInTheDocument();
    failing = true;

    await act(() =>
      queryClient.invalidateQueries({
        queryKey: sessionQueryOptions(SESSION_ID).queryKey,
      }),
    );

    const banner = await screen.findByRole("alert", {}, { timeout: 3000 });
    expect(banner).toHaveTextContent(LOAD_FAILED);
    expect(within(banner).getByRole("button", { name: "再読み込み" })).toBeEnabled();
    const coach = screen.getByRole("region", { name: "コーチ" });
    expect(
      banner.compareDocumentPosition(coach) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText(OPENER_TEXT)).toBeInTheDocument();
  });

  it("shows the server-unreachable banner, not the load-failed one, for a read with no response", async () => {
    server.use(http.get(`/api/sessions/${SESSION_ID}`, () => HttpResponse.error()));
    renderAt(`/sessions/${SESSION_ID}`);

    expect(
      await screen.findByText(
        "アプリのサーバーに接続できません。起動しているか確認してください。",
        {},
        { timeout: 3000 },
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(LOAD_FAILED)).not.toBeInTheDocument();
  });

  describe("the skeleton's timing", () => {
    /** Serve the session once `release` is called, and open its URL at 0 ms. */
    async function openHeld() {
      installFakeClock();
      const gate = deferred();
      server.use(
        http.get(`/api/sessions/${SESSION_ID}`, async () => {
          await gate.promise;
          return HttpResponse.json<SessionResponse>(view);
        }),
      );
      renderAt(`/sessions/${SESSION_ID}`);
      await advance(0);
      return gate.release;
    }

    it("shows no skeleton for a response at 299 ms", async () => {
      const release = await openHeld();

      await advance(299);
      expect(screen.queryByText(LOADING)).not.toBeInTheDocument();
      release();
      await advance(0);

      expect(screen.getByText(OPENER_TEXT)).toBeInTheDocument();
      expect(screen.queryByText(LOADING)).not.toBeInTheDocument();
    });

    it("shows the skeleton from 300 ms and the session at 800 ms for a response at 301 ms", async () => {
      const release = await openHeld();

      await advance(299);
      expect(screen.queryByText(LOADING)).not.toBeInTheDocument();
      await advance(2);
      expect(screen.getByText(LOADING)).toBeInTheDocument();
      release();
      await advance(0);
      await advance(498);
      expect(screen.getByText(LOADING)).toBeInTheDocument();
      expect(screen.queryByText(OPENER_TEXT)).not.toBeInTheDocument();
      await advance(1);

      expect(screen.getByText(OPENER_TEXT)).toBeInTheDocument();
      expect(screen.queryByText(LOADING)).not.toBeInTheDocument();
    });

    it("shows the skeleton from 300 ms and the session at once for a response at 900 ms", async () => {
      const release = await openHeld();

      await advance(300);
      expect(screen.getByText(LOADING)).toBeInTheDocument();
      await advance(600);
      release();
      await advance(0);

      expect(screen.getByText(OPENER_TEXT)).toBeInTheDocument();
      expect(screen.queryByText(LOADING)).not.toBeInTheDocument();
    });
  });
});
