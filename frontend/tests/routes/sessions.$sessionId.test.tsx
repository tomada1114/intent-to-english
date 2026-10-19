import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type {
  MetaResponse,
  ProblemDetails,
  SessionResponse,
} from "../../src/api/generated/types.gen";
import { createQueryClient } from "../../src/lib/query-client";
import { createAppRouter } from "../../src/router";
import { deferred, entry, SESSION_ID, sessionView } from "../msw/helpers";
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

  it("shows the error display when the session cannot be read", async () => {
    server.use(
      http.get(`/api/sessions/${SESSION_ID}`, () =>
        HttpResponse.json<ProblemDetails>(
          {
            type: "about:blank",
            title: "Not Found",
            status: 404,
            detail: "Session not found",
            code: "session_not_found",
            request_id: "req-1",
          },
          { status: 404 },
        ),
      ),
    );
    renderAt(`/sessions/${SESSION_ID}`);

    expect(await screen.findByRole("alert")).toHaveTextContent("Session not found");
    expect(screen.queryByRole("region", { name: "コーチ" })).not.toBeInTheDocument();
  });
});
