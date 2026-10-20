import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type {
  MetaResponse,
  ProblemDetails,
  SessionResponse,
} from "../../src/api/generated/types.gen";
import { createQueryClient } from "../../src/lib/query-client";
import { createAppRouter } from "../../src/router";
import {
  deferred,
  entry,
  SESSION_ID,
  sessionView,
  stubMatchMedia,
} from "../msw/helpers";
import { server } from "../msw/server";

const view = sessionView({
  stage: "intent",
  finished_replies: 4,
  allowed_actions: ["intent", "end"],
  entries: [
    entry("partner_line", {
      text: "Hey! How's it going?",
      has_question: true,
      line_kind: "opener",
      restate_mode: null,
    }),
  ],
});

function problem(status: number, code: string): ProblemDetails {
  return {
    type: "about:blank",
    title: "Error",
    status,
    detail: `${code} detail`,
    code,
    request_id: "req-1",
  };
}

function renderAt(path: string) {
  const queryClient = createQueryClient();
  const history = createMemoryHistory({ initialEntries: [path] });
  const router = createAppRouter(queryClient, { history });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("/sessions/$sessionId", () => {
  it.each([true, false])(
    "hands focus to the transcript after an end retry with wide layout: %s",
    async (wide) => {
      stubMatchMedia(wide);
      let current = view;
      let ends = 0;
      server.use(
        http.get(`/api/sessions/${SESSION_ID}`, () => HttpResponse.json(current)),
        http.post(`/api/sessions/${SESSION_ID}/actions`, () => {
          ends += 1;
          if (ends === 1)
            return HttpResponse.json(problem(500, "internal_error"), { status: 500 });
          current = sessionView({
            ...view,
            status: "ended",
            stage: "ended",
            version: view.version + 1,
            allowed_actions: [],
            wrap_up: { items: [] },
          });
          return HttpResponse.json(current);
        }),
      );
      const user = userEvent.setup();
      renderAt(`/sessions/${SESSION_ID}`);
      await user.click(await screen.findByRole("button", { name: "会話を終える" }));
      await user.click(screen.getByRole("button", { name: "終える" }));
      await user.click(await screen.findByRole("button", { name: "もう一度" }));
      const heading = await screen.findByRole("heading", {
        name: "ターンごとのやりとり",
      });
      await waitFor(() => expect(heading).toHaveFocus());
      expect(heading).toBeVisible();
    },
  );

  it("shows skeletons while the session loads, then the conversation", async () => {
    const gate = deferred();
    server.use(
      http.get(`/api/sessions/${SESSION_ID}`, async () => {
        await gate.promise;
        return HttpResponse.json<SessionResponse>(view);
      }),
    );
    renderAt(`/sessions/${SESSION_ID}`);

    expect(await screen.findByText("読み込んでいます…")).toBeInTheDocument();
    gate.release();

    expect(await screen.findByText("Hey! How's it going?")).toBeInTheDocument();
    expect(screen.queryByText("読み込んでいます…")).not.toBeInTheDocument();
  });

  it("places its header items between the app name and the badge", async () => {
    server.use(
      http.get(`/api/sessions/${SESSION_ID}`, () =>
        HttpResponse.json<SessionResponse>(view),
      ),
      http.get("/api/meta", () =>
        HttpResponse.json<MetaResponse>({ model_mode: "fixed" }),
      ),
    );
    renderAt(`/sessions/${SESSION_ID}`);

    const header = await screen.findByRole("banner");
    const back = await within(header).findByRole("link", { name: "← 会話一覧" });
    expect(back).toHaveAttribute("href", "/");
    expect(within(header).getByText("4往復")).toHaveTextContent(
      "10/17 18:40 から · 4往復",
    );
    const badge = await within(header).findByRole("button", { name: "固定応答モード" });
    const order = [
      within(header).getByRole("link", { name: "Intent to English" }),
      back,
      within(header).getByText("4往復"),
      within(header).getByRole("button", { name: "会話を終える" }),
      badge,
    ];
    for (const [index, element] of order.slice(1).entries()) {
      const before = order[index] as HTMLElement;
      expect(
        before.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("shows S4 when the API answers 404 session_not_found", async () => {
    server.use(
      http.get(`/api/sessions/${SESSION_ID}`, () =>
        HttpResponse.json<ProblemDetails>(problem(404, "session_not_found"), {
          status: 404,
        }),
      ),
    );
    renderAt(`/sessions/${SESSION_ID}`);

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "この会話は見つかりませんでした。",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "会話一覧へ" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [404, "not_found"],
    [500, "internal_error"],
  ])("shows the error display, not S4, for a %i %s", async (status, code) => {
    server.use(
      http.get(`/api/sessions/${SESSION_ID}`, () =>
        HttpResponse.json<ProblemDetails>(problem(status, code), { status }),
      ),
    );
    renderAt(`/sessions/${SESSION_ID}`);

    expect(await screen.findByRole("alert", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(
      screen.queryByText("この会話は見つかりませんでした。"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "コーチ" })).not.toBeInTheDocument();
  });

  it("shows S3 for an ended session", async () => {
    server.use(
      http.get(`/api/sessions/${SESSION_ID}`, () =>
        HttpResponse.json<SessionResponse>({
          ...view,
          status: "ended",
          stage: "ended",
          allowed_actions: [],
          wrap_up: { items: [] },
        }),
      ),
    );
    renderAt(`/sessions/${SESSION_ID}`);

    expect(
      await screen.findByRole("heading", { name: "会話（英文だけの通し）" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "会話を終える" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    { name: "S2", ended: false },
    { name: "S3", ended: true },
  ])(
    "lets $name fill the height the header and any banner leave, never a fixed viewport height",
    async ({ ended }) => {
      server.use(
        http.get(`/api/sessions/${SESSION_ID}`, () =>
          HttpResponse.json<SessionResponse>(
            ended
              ? {
                  ...view,
                  status: "ended",
                  stage: "ended",
                  allowed_actions: [],
                  wrap_up: { items: [] },
                }
              : view,
          ),
        ),
      );
      renderAt(`/sessions/${SESSION_ID}`);
      await screen.findByText("Hey! How's it going?");

      // jsdom has no layout: the structure is what holds the composer in view.
      const main = screen.getByRole("main");
      expect(main).toHaveClass("flex", "min-h-0", "flex-1", "flex-col");
      const fill = main.querySelector("[data-fill-viewport]");
      expect(fill).not.toBeNull();
      expect(fill).toHaveClass("min-h-0", "flex-1");
      expect(main.parentElement?.className).toContain(
        "has-[[data-fill-viewport]]:h-dvh",
      );
      expect(document.body.innerHTML).not.toContain("100dvh");
    },
  );

  it("lets the skeleton fill the height left too", async () => {
    const gate = deferred();
    server.use(
      http.get(`/api/sessions/${SESSION_ID}`, async () => {
        await gate.promise;
        return HttpResponse.json<SessionResponse>(view);
      }),
    );
    renderAt(`/sessions/${SESSION_ID}`);

    await screen.findByText("読み込んでいます…");

    expect(
      screen.getByRole("main").querySelector("[data-fill-viewport]"),
    ).not.toBeNull();
    expect(document.body.innerHTML).not.toContain("100dvh");
    gate.release();
    await screen.findByText("Hey! How's it going?");
  });

  it("keeps S1 to the page's own scroll, filling nothing", async () => {
    renderAt("/");

    await screen.findByText("まだ会話はありません。最初の会話を始めましょう。");

    expect(document.querySelector("[data-fill-viewport]")).toBeNull();
  });
});
