import { readFileSync } from "node:fs";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type {
  MetaResponse,
  ProblemDetails,
  SessionPageResponse,
  SessionResponse,
} from "../../src/api/generated/types.gen";
import { createQueryClient } from "../../src/lib/query-client";
import { createAppRouter } from "../../src/router";
import {
  deferred,
  SESSION_ID,
  serveSession,
  sessionRow,
  sessionView,
} from "../msw/helpers";
import { server } from "../msw/server";

const BADGE = "固定応答モード";
const UNREACHABLE =
  "アプリのサーバーに接続できません。起動しているか確認してください。";
const TOOLTIP =
  "OpenRouter のキーが未設定のため、決まった応答で動いています。品質の確認には使えません。";

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

function useMeta(model_mode: MetaResponse["model_mode"]) {
  let requests = 0;
  server.use(
    http.get("/api/meta", () => {
      requests += 1;
      return HttpResponse.json<MetaResponse>({ model_mode });
    }),
  );
  return () => requests;
}

describe("the root layout", () => {
  it("renders the header with the app name linking home and no badge for openrouter", async () => {
    const requests = useMeta("openrouter");
    renderAt("/");

    const header = await screen.findByRole("banner");
    const home = within(header).getByRole("link", { name: "Intent to English" });
    expect(home).toHaveAttribute("href", "/");
    await waitFor(() => expect(requests()).toBe(1));
    expect(within(header).queryByText(BADGE)).not.toBeInTheDocument();
    expect(within(header).queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("shows the fixed-response badge whose tooltip is its description and opens on focus", async () => {
    useMeta("fixed");
    const user = userEvent.setup();
    renderAt("/");

    const badge = await screen.findByRole("button", { name: BADGE });
    expect(badge).toHaveAccessibleDescription(TOOLTIP);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    // S1 focuses its start button on load; walk the header from the page's top.
    expect(screen.getByRole("button", { name: "新しい会話を始める" })).toHaveFocus();
    act(() => (document.activeElement as HTMLElement).blur());

    await user.tab();
    expect(screen.getByRole("link", { name: "Intent to English" })).toHaveFocus();
    await user.tab();
    expect(badge).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent(TOOLTIP);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(badge).toHaveFocus();

    await user.tab();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("opens the tooltip on hover and closes it when the pointer leaves", async () => {
    useMeta("fixed");
    const user = userEvent.setup();
    renderAt("/");

    const badge = await screen.findByRole("button", { name: BADGE });
    await user.hover(badge);
    expect(screen.getByRole("tooltip")).toHaveTextContent(TOOLTIP);

    await user.unhover(badge);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows no badge when the meta request fails", async () => {
    let requests = 0;
    server.use(
      http.get("/api/meta", () => {
        requests += 1;
        return HttpResponse.json<ProblemDetails>(
          {
            type: "about:blank",
            title: "Internal Server Error",
            status: 500,
            detail: "boom",
            code: "internal_error",
            request_id: "req-1",
          },
          { status: 500 },
        );
      }),
    );
    renderAt("/");

    await screen.findByRole("banner");
    // The query client retries a 5xx once, after its default one-second delay.
    await waitFor(() => expect(requests).toBe(2), { timeout: 3000 });
    expect(screen.queryByText(BADGE)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("declares a Japanese page and pads scrolling below the sticky header", () => {
    const html = readFileSync("index.html", "utf8");

    expect(html).toMatch(/<html lang="ja" class="scroll-pt-14">/);
  });

  it.each(["/settings", "/sessions/"])(
    "renders S4 inside the header frame for %s",
    async (path) => {
      useMeta("openrouter");
      renderAt(path);

      expect(
        await screen.findByRole("heading", {
          level: 1,
          name: "この会話は見つかりませんでした。",
        }),
      ).toBeInTheDocument();
      expect(screen.getByRole("banner")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "会話一覧へ" })).toHaveAttribute(
        "href",
        "/",
      );
    },
  );

  it("shows the server-unreachable banner under the header on S1, and 再試行 reads the list again", async () => {
    useMeta("openrouter");
    let reachable = false;
    let requests = 0;
    server.use(
      http.get("/api/sessions", () => {
        requests += 1;
        return reachable
          ? HttpResponse.json<SessionPageResponse>({ items: [], next_cursor: null })
          : HttpResponse.error();
      }),
    );
    const user = userEvent.setup();
    renderAt("/");

    // The query client retries a request with no response once, after a second.
    const banner = await screen.findByText(
      "アプリのサーバーに接続できません。起動しているか確認してください。",
      {},
      { timeout: 3000 },
    );
    const alert = banner.closest('[role="alert"]') as HTMLElement;
    expect(
      screen.getByRole("banner").compareDocumentPosition(alert) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(requests).toBe(2);
    // One outage, one alert: S1's own load-failed banner stays out of it, also
    // once the skeleton's minimum has ended.
    await waitFor(() => expect(screen.queryByText("読み込んでいます…")).toBeNull());
    expect(screen.getAllByRole("alert")).toEqual([alert]);
    expect(
      screen.queryByText("会話の一覧を読み込めませんでした。"),
    ).not.toBeInTheDocument();
    reachable = true;

    await user.click(within(alert).getByRole("button", { name: "再試行" }));

    expect(
      await screen.findByText("まだ会話はありません。最初の会話を始めましょう。"),
    ).toBeInTheDocument();
    expect(requests).toBe(3);
    expect(
      screen.queryByText(
        "アプリのサーバーに接続できません。起動しているか確認してください。",
      ),
    ).not.toBeInTheDocument();
  });

  it.each(["none", "running", "failed"] as const)(
    "retries the failed forward page with its stored cursor during background refetch: %s",
    async (backgroundRefetch) => {
      useMeta("openrouter");
      const first = Array.from({ length: 20 }, (_, index) =>
        sessionRow({
          id: `0199c1f0-0000-7000-8000-${String(index).padStart(12, "0")}`,
          status: "ended",
          opener: `Stored opener ${index}`,
        }),
      );
      const last = sessionRow({
        id: "0199c1f0-0000-7000-8000-999999999999",
        status: "ended",
        opener: "Twenty-first opener",
      });
      const cursors: (string | null)[] = [];
      let reachable = false;
      const gate = deferred();
      let headRequests = 0;
      server.use(
        http.get("/api/sessions", async ({ request }) => {
          const cursor = new URL(request.url).searchParams.get("cursor");
          cursors.push(cursor);
          if (cursor === null) {
            headRequests += 1;
            if (backgroundRefetch === "running" && headRequests > 1) await gate.promise;
            if (backgroundRefetch === "failed" && headRequests > 1 && !reachable)
              return HttpResponse.error();
            return HttpResponse.json<SessionPageResponse>({
              items: first,
              next_cursor: "stored-next-cursor",
            });
          }
          return reachable
            ? HttpResponse.json<SessionPageResponse>({
                items: [last],
                next_cursor: null,
              })
            : HttpResponse.error();
        }),
      );
      const user = userEvent.setup();
      const router = renderAt("/");
      await user.click(await screen.findByRole("button", { name: "さらに表示" }));
      const alert = (
        await screen.findByText(UNREACHABLE, {}, { timeout: 3000 })
      ).closest('[role="alert"]') as HTMLElement;
      expect(screen.getAllByRole("alert")).toEqual([alert]);
      if (backgroundRefetch !== "none") {
        const refetch = router.options.context.queryClient.refetchQueries({
          queryKey: [{ _id: "listSessions" }],
        });
        if (backgroundRefetch === "failed") await refetch;
        else await waitFor(() => expect(headRequests).toBe(2));
      }
      reachable = true;

      await user.click(within(alert).getByRole("button", { name: "再試行" }));
      gate.release();

      expect(await screen.findByText("Twenty-first opener")).toBeInTheDocument();
      expect(cursors).toEqual([
        null,
        "stored-next-cursor",
        "stored-next-cursor",
        ...(backgroundRefetch === "running"
          ? [null]
          : backgroundRefetch === "failed"
            ? [null, null]
            : []),
        "stored-next-cursor",
      ]);
      expect(screen.queryByText(UNREACHABLE)).not.toBeInTheDocument();
    },
  );

  it("shows the server-unreachable banner on S4 when the header's own request gets no response", async () => {
    server.use(http.get("/api/meta", () => HttpResponse.error()));
    renderAt("/settings");

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "この会話は見つかりませんでした。",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "再試行" }, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("shows the server-unreachable banner for S1's start with no response, and 再試行 starts it again", async () => {
    useMeta("openrouter");
    serveSession(sessionView());
    let starts = 0;
    server.use(
      http.post("/api/sessions", () => {
        starts += 1;
        return starts === 1
          ? HttpResponse.error()
          : HttpResponse.json<SessionResponse>(sessionView(), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    const router = renderAt("/");

    await user.click(await screen.findByRole("button", { name: "新しい会話を始める" }));

    const banner = (await screen.findByText(UNREACHABLE)).closest(
      '[role="alert"]',
    ) as HTMLElement;
    expect(screen.getAllByRole("alert")).toEqual([banner]);
    await user.click(within(banner).getByRole("button", { name: "再試行" }));

    await waitFor(() =>
      expect(router.state.location.pathname).toBe(`/sessions/${SESSION_ID}`),
    );
    expect(starts).toBe(2);
    expect(screen.queryByText(UNREACHABLE)).not.toBeInTheDocument();
  });

  it("hides the server-unreachable banner once the screen whose read failed is left for a healthy one", async () => {
    useMeta("openrouter");
    server.use(http.get(`/api/sessions/${SESSION_ID}`, () => HttpResponse.error()));
    const user = userEvent.setup();
    const router = renderAt(`/sessions/${SESSION_ID}`);
    expect(
      await screen.findByText(UNREACHABLE, {}, { timeout: 3000 }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Intent to English" }));

    expect(
      await screen.findByText("まだ会話はありません。最初の会話を始めましょう。"),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
    expect(screen.queryByText(UNREACHABLE)).not.toBeInTheDocument();
  });

  it("hides the server-unreachable banner once a later read gets an answer, even an error (S4)", async () => {
    useMeta("openrouter");
    let reads = 0;
    server.use(
      http.get(`/api/sessions/${SESSION_ID}`, () => {
        reads += 1;
        return reads <= 2
          ? HttpResponse.error()
          : HttpResponse.json<ProblemDetails>(
              {
                type: "about:blank",
                title: "Not Found",
                status: 404,
                detail: "No such session",
                code: "session_not_found",
                request_id: "req-9",
              },
              { status: 404 },
            );
      }),
    );
    const router = renderAt(`/sessions/${SESSION_ID}`);
    expect(
      await screen.findByText(UNREACHABLE, {}, { timeout: 3000 }),
    ).toBeInTheDocument();

    // A read the screen makes by itself (not the banner's 再試行) gets an answer.
    await act(() =>
      router.options.context.queryClient.invalidateQueries({
        queryKey: [{ _id: "getSession" }],
      }),
    );

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "この会話は見つかりませんでした。",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText(UNREACHABLE)).not.toBeInTheDocument();
  });
});

it("keeps retry waiting focus on the main region while a root retry runs", async () => {
  useMeta("openrouter");
  const hold = deferred();
  let retrying = false;
  server.use(
    http.get("/api/sessions", async () => {
      if (!retrying) return HttpResponse.error();
      await hold.promise;
      return HttpResponse.json<SessionPageResponse>({ items: [], next_cursor: null });
    }),
  );
  const user = userEvent.setup();
  renderAt("/");
  const again = await screen.findByRole(
    "button",
    { name: "再試行" },
    { timeout: 3000 },
  );
  retrying = true;
  await user.click(again);
  expect(screen.getByRole("main")).toHaveFocus();
  expect(document.activeElement).not.toBe(document.body);
  hold.release();
  await screen.findByText("まだ会話はありません。最初の会話を始めましょう。");
});
