import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type {
  ProblemDetails,
  SessionPageResponse,
  SessionResponse,
  SessionSummaryResponse,
} from "../../../src/api/generated/types.gen";
import { HomeScreen } from "../../../src/features/sessions";
import {
  deferred,
  renderWithQuery,
  SESSION_ID,
  sessionRow,
  sessionView,
} from "../../msw/helpers";
import { server } from "../../msw/server";

const TAGLINE = "英語で話す前に、日本語で言いたいことを決める練習";
const EMPTY = "まだ会話はありません。最初の会話を始めましょう。";
const LIST_FAILED = "会話の一覧を読み込めませんでした。";
/** The server's answer to a failed list read: Problem Details, not silence. */
const LIST_ERROR = { status: 500, title: "Internal Server Error" };

/** The home screen at `/`, with a stand-in S2 route to navigate to. */
function renderHome() {
  const root = createRootRoute({ component: Outlet });
  const home = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: HomeScreen,
  });
  const session = createRoute({
    getParentRoute: () => root,
    path: "/sessions/$sessionId",
    component: () => <p>S2 stand-in</p>,
  });
  const router = createRouter({
    routeTree: root.addChildren([home, session]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  renderWithQuery(<RouterProvider router={router} />);
  return router;
}

/** A session id whose last digits are `n`, so ids sort as their numbers do. */
function idOf(n: number) {
  return `0199c1f0-0000-7000-8000-${String(n).padStart(12, "0")}`;
}

/** Serve `rows` as the list, `pageSize` per page, newest first as given. */
function serveList(rows: SessionSummaryResponse[], pageSize = 20) {
  const cursors: (string | null)[] = [];
  server.use(
    http.get("/api/sessions", ({ request }) => {
      const cursor = new URL(request.url).searchParams.get("cursor");
      cursors.push(cursor);
      const start = cursor === null ? 0 : Number(cursor);
      const end = start + pageSize;
      return HttpResponse.json<SessionPageResponse>({
        items: rows.slice(start, end),
        next_cursor: end < rows.length ? String(end) : null,
      });
    }),
  );
  return cursors;
}

function rows(count: number) {
  return Array.from({ length: count }, (_, index) =>
    sessionRow({
      id: idOf(count - index),
      status: "ended",
      finished_replies: 2,
      opener: `Opener number ${count - index}`,
    }),
  );
}

function sessionLinks() {
  const list = screen.getByRole("list", { name: "これまでの会話" });
  return within(list).getAllByRole("link");
}

describe("HomeScreen", () => {
  it("shows the tagline as the page heading and focuses the start button", async () => {
    renderHome();

    expect(
      await screen.findByRole("heading", { level: 1, name: TAGLINE }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新しい会話を始める" })).toHaveFocus();
  });

  it("starts a session and opens it", async () => {
    const user = userEvent.setup();
    let posts = 0;
    server.use(
      http.post("/api/sessions", () => {
        posts += 1;
        return HttpResponse.json<SessionResponse>(
          sessionView({ stage: "opening", version: 0 }),
          { status: 201 },
        );
      }),
    );
    const router = renderHome();

    await user.click(await screen.findByRole("button", { name: "新しい会話を始める" }));

    expect(await screen.findByText("S2 stand-in")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/sessions/${SESSION_ID}`);
    expect(posts).toBe(1);
  });

  it("shows the error display under the button when starting fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/sessions", () =>
        HttpResponse.json<ProblemDetails>(
          {
            type: "about:blank",
            title: "Internal Server Error",
            status: 500,
            detail: "Internal Server Error",
            code: "internal_error",
            request_id: "request-500",
          },
          { status: 500 },
        ),
      ),
    );
    const router = renderHome();
    const start = await screen.findByRole("button", { name: "新しい会話を始める" });

    await user.click(start);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side. Try again.");
    expect(alert).toHaveTextContent("Request ID: request-500");
    expect(router.state.location.pathname).toBe("/");
    expect(start).toBeEnabled();
  });

  it("shows only the empty copy when there are no sessions", async () => {
    renderHome();

    expect(await screen.findByText(EMPTY)).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "続きから" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "これまでの会話" }),
    ).not.toBeInTheDocument();
  });

  it("lists each session newest first, the whole row linking to it", async () => {
    serveList([
      sessionRow({
        id: idOf(2),
        started_at: new Date(2026, 9, 17, 18, 40).toISOString(),
        status: "in_progress",
        finished_replies: 4,
        opener: "Hey! How was your weekend?",
      }),
      sessionRow({
        id: idOf(1),
        started_at: new Date(2026, 9, 16, 21, 2).toISOString(),
        status: "ended",
        finished_replies: 9,
        opener: "Hi! How's it going?",
      }),
    ]);
    renderHome();

    expect(
      await screen.findByRole("heading", { level: 2, name: "これまでの会話" }),
    ).toBeInTheDocument();
    const [first, second] = sessionLinks();
    expect(first).toHaveAccessibleName(
      "10/17 18:40 進行中 4往復 Hey! How was your weekend?",
    );
    expect(first).toHaveAttribute("href", `/sessions/${idOf(2)}`);
    expect(second).toHaveAccessibleName("10/16 21:02 終了 9往復 Hi! How's it going?");
    expect(second).toHaveAttribute("href", `/sessions/${idOf(1)}`);
    expect(
      within(first as HTMLElement).getByText("Hey! How was your weekend?"),
    ).toHaveAttribute("lang", "en");
  });

  it("shows a 60-character opener whole and cuts a 61-character one at 60", async () => {
    const sixty = `${"a".repeat(59)}b`;
    const sixtyOne = `${"c".repeat(60)}d`;
    serveList([
      sessionRow({ id: idOf(2), status: "ended", opener: sixty }),
      sessionRow({ id: idOf(1), status: "ended", opener: sixtyOne }),
    ]);
    renderHome();

    expect(await screen.findByText(sixty)).toBeInTheDocument();
    expect(screen.getByText(`${"c".repeat(60)}…`)).toBeInTheDocument();
    expect(screen.queryByText(sixtyOne)).not.toBeInTheDocument();
  });

  it("shows a session still opening with 0往復 and an empty opener cell", async () => {
    serveList([
      sessionRow({
        id: idOf(1),
        status: "in_progress",
        finished_replies: 0,
        opener: null,
      }),
    ]);
    renderHome();

    await screen.findByRole("heading", { level: 2, name: "これまでの会話" });
    const [row] = sessionLinks();
    expect(row).toHaveAccessibleName("10/17 18:40 進行中 0往復");
  });

  it("shows no さらに表示 when exactly 20 sessions are stored", async () => {
    serveList(rows(20));
    renderHome();

    await screen.findByRole("heading", { level: 2, name: "これまでの会話" });
    expect(sessionLinks()).toHaveLength(20);
    expect(
      screen.queryByRole("button", { name: "さらに表示" }),
    ).not.toBeInTheDocument();
  });

  it("loads the 21st session after さらに表示 and then hides the button", async () => {
    const user = userEvent.setup();
    const all = rows(21);
    const long = `${"x".repeat(60)}y`;
    all[3] = sessionRow({ ...all[3], opener: long });
    const cursors = serveList(all);
    renderHome();

    const more = await screen.findByRole("button", { name: "さらに表示" });
    expect(sessionLinks()).toHaveLength(20);
    expect(screen.getByText(`${"x".repeat(60)}…`)).toBeInTheDocument();

    await user.click(more);

    expect(await screen.findByText("Opener number 1")).toBeInTheDocument();
    expect(sessionLinks()).toHaveLength(21);
    expect(
      screen.queryByRole("button", { name: "さらに表示" }),
    ).not.toBeInTheDocument();
    expect(cursors).toEqual([null, "20"]);
  });

  it("offers the newest in-progress session as the resume card", async () => {
    const user = userEvent.setup();
    serveList([
      sessionRow({ id: idOf(3), status: "ended", opener: "Newest but ended" }),
      sessionRow({
        id: idOf(2),
        status: "in_progress",
        finished_replies: 4,
        opener: "Hey! How was your weekend?",
      }),
      sessionRow({ id: idOf(1), status: "in_progress", opener: "Older in progress" }),
    ]);
    const router = renderHome();

    const card = await screen.findByRole("region", { name: "続きから" });
    expect(within(card).getByText("Hey! How was your weekend?")).toHaveAttribute(
      "lang",
      "en",
    );
    expect(within(card).getByText("10/17 18:40 から · 4往復")).toBeInTheDocument();
    expect(within(card).queryByText("Older in progress")).not.toBeInTheDocument();

    await user.click(within(card).getByRole("link", { name: "続ける" }));

    expect(await screen.findByText("S2 stand-in")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/sessions/${idOf(2)}`);
  });

  it("shows no resume card when every session has ended", async () => {
    serveList(rows(2));
    renderHome();

    await screen.findByRole("heading", { level: 2, name: "これまでの会話" });
    expect(screen.queryByRole("region", { name: "続きから" })).not.toBeInTheDocument();
  });

  it("replaces the list with a banner when it fails, and 再読み込み reloads it", async () => {
    const user = userEvent.setup();
    let fail = true;
    server.use(
      http.get("/api/sessions", () =>
        fail
          ? HttpResponse.json(
              { status: 500, title: "Internal Server Error" },
              { status: 500 },
            )
          : HttpResponse.json<SessionPageResponse>({
              items: [sessionRow({ status: "ended" })],
              next_cursor: null,
            }),
      ),
    );
    renderHome();

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(LIST_FAILED);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    fail = false;

    await user.click(within(banner).getByRole("button", { name: "再読み込み" }));

    expect(
      await screen.findByRole("list", { name: "これまでの会話" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(LIST_FAILED)).not.toBeInTheDocument();
  });

  it("keeps the loaded rows when the next page fails, and 再読み込み loads it", async () => {
    const user = userEvent.setup();
    const all = rows(21);
    let failNext = true;
    server.use(
      http.get("/api/sessions", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        if (cursor === null) {
          return HttpResponse.json<SessionPageResponse>({
            items: all.slice(0, 20),
            next_cursor: "20",
          });
        }
        if (failNext) return HttpResponse.json(LIST_ERROR, { status: 500 });
        return HttpResponse.json<SessionPageResponse>({
          items: all.slice(20),
          next_cursor: null,
        });
      }),
    );
    renderHome();

    await user.click(await screen.findByRole("button", { name: "さらに表示" }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(LIST_FAILED);
    expect(sessionLinks()).toHaveLength(20);
    expect(
      screen.queryByRole("button", { name: "さらに表示" }),
    ).not.toBeInTheDocument();
    failNext = false;

    await user.click(within(banner).getByRole("button", { name: "再読み込み" }));

    expect(await screen.findByText("Opener number 1")).toBeInTheDocument();
    expect(sessionLinks()).toHaveLength(21);
    expect(screen.queryByText(LIST_FAILED)).not.toBeInTheDocument();
  });

  it("still starts a session while the list has failed", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/sessions", () => HttpResponse.json(LIST_ERROR, { status: 500 })),
      http.post("/api/sessions", () =>
        HttpResponse.json<SessionResponse>(sessionView({ stage: "opening" }), {
          status: 201,
        }),
      ),
    );
    const router = renderHome();
    await screen.findByText(LIST_FAILED);

    await user.click(screen.getByRole("button", { name: "新しい会話を始める" }));

    await waitFor(() =>
      expect(router.state.location.pathname).toBe(`/sessions/${SESSION_ID}`),
    );
  });

  it("shows no skeleton at first, then three skeleton rows while the list loads", async () => {
    const user = userEvent.setup();
    const gate = deferred();
    server.use(
      http.get("/api/sessions", async () => {
        await gate.promise;
        return HttpResponse.json<SessionPageResponse>({
          items: [sessionRow({ status: "ended" })],
          next_cursor: null,
        });
      }),
      http.post("/api/sessions", () =>
        HttpResponse.json<SessionResponse>(sessionView({ stage: "opening" }), {
          status: 201,
        }),
      ),
    );
    const router = renderHome();
    const start = await screen.findByRole("button", { name: "新しい会話を始める" });

    expect(screen.queryByText("読み込んでいます…")).not.toBeInTheDocument();
    expect(await screen.findByText("読み込んでいます…")).toBeInTheDocument();
    expect(document.querySelectorAll("[data-skeleton-row]")).toHaveLength(3);
    expect(start).toBeEnabled();
    gate.release();

    expect(
      await screen.findByRole("list", { name: "これまでの会話" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("読み込んでいます…")).not.toBeInTheDocument();
    await user.click(start);
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(`/sessions/${SESSION_ID}`),
    );
  });
});
