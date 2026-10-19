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
} from "../../src/api/generated/types.gen";
import { createQueryClient } from "../../src/lib/query-client";
import { createAppRouter } from "../../src/router";
import { server } from "../msw/server";

const BADGE = "固定応答モード";
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
});
