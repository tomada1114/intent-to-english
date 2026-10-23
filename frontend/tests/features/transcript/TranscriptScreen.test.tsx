import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, onTestFinished } from "vitest";
import type {
  ProblemDetails,
  SessionResponse,
  TimelineEntryResponse,
} from "../../../src/api/generated/types.gen";
import { sessionQueryOptions } from "../../../src/features/conversation";
import { wrapUpFailureLine } from "../../../src/features/transcript";
import { createQueryClient } from "../../../src/lib/query-client";
import { createAppRouter } from "../../../src/router";
import {
  advance,
  entry,
  installFakeClock,
  renderTranscript,
  SESSION_ID,
  serveSession,
  sessionView,
  stubMatchMedia,
} from "../../msw/helpers";

function partner(text: string, turn: number) {
  return entry(
    "partner_line",
    {
      text,
      has_question: true,
      line_kind: turn === 1 ? "opener" : "reply",
      restate_mode: null,
    },
    turn,
  );
}

const FEEDBACK = {
  first_line: "意図は伝わっています。元のままでも通じます",
  fixes: [
    {
      number: 1,
      original: "studying",
      replacement: "have been studying",
      reason: "続いていることは現在完了進行形",
      tag: "miss" as const,
    },
  ],
  sentence: "I studying AWS",
  template: "I (①) ____ AWS",
  request_line: "(①) を埋めて、文全体をもう一度送ってください",
  readings_noted: [],
};

function turnEntries(turn: number, english: string): TimelineEntryResponse[] {
  return [
    entry("intent", { text: `日本語 ${turn}`, is_replacement: false }, turn),
    entry("acknowledgment", { line: `いいですね ${turn}`, build_hint: null }, turn),
    entry("english", { text: `draft ${turn}`, is_direct: false }, turn),
    entry("turn_done", { english, end: "no_fix_needed" }, turn),
  ];
}

const TURN_TWO: TimelineEntryResponse[] = [
  entry("intent", { text: "最近AWSを勉強している", is_replacement: false }, 2),
  entry("acknowledgment", { line: "いいですね！", build_hint: null }, 2),
  entry("english", { text: "I studying AWS", is_direct: false }, 2),
  entry("feedback", { intent: "最近AWSを勉強している", feedback: FEEDBACK }, 2),
  entry("retry", { sentence: "I have been studying AWS", submission_number: 1 }, 2),
  entry("retry_result", { result: { line: "伝わります！", readings_noted: [] } }, 2),
  entry("turn_done", { english: "I have been studying AWS", end: "accepted" }, 2),
];

const ENTRIES: TimelineEntryResponse[] = [
  partner("Hey! How was your day today?", 1),
  ...turnEntries(1, "I feel refreshed today"),
  partner("Oh nice! What kind of things?", 2),
  ...TURN_TWO,
  partner("Cool. Anything else?", 3),
  ...turnEntries(3, "That's all for today"),
];

const WRAP_UP = {
  items: [
    { phrase: "I feel refreshed", note: "自分の気分は -ed" },
    { phrase: "these days", note: "今の状態の「最近」" },
  ],
};

function ended(overrides: Partial<SessionResponse> = {}) {
  return sessionView({
    status: "ended",
    stage: "ended",
    version: 9,
    turn_index: 3,
    finished_replies: 3,
    started_at: new Date(2026, 9, 16, 21, 2).toISOString(),
    ended_at: new Date(2026, 9, 16, 21, 38).toISOString(),
    entries: ENTRIES,
    allowed_actions: [],
    wrap_up: WRAP_UP,
    ...overrides,
  });
}

function problem(status: number, code: string): ProblemDetails {
  return {
    type: "about:blank",
    title: "Error",
    status,
    detail: code,
    code,
    request_id: "r",
  };
}

describe("TranscriptScreen (REQ-001, REQ-002)", () => {
  it("shows the closing section, the wrap-up, and every turn collapsed, with no composer or controls", () => {
    renderTranscript(ended());

    expect(screen.getByText("3往復 · 終了")).toHaveTextContent(
      "10/16 21:02 – 21:38 · 3往復 · 終了",
    );
    expect(
      screen.queryByRole("button", { name: "会話を終える" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const coach = screen.getByRole("region", { name: "コーチ" });
    const headings = within(coach).getAllByRole("heading", { level: 2 });
    expect(headings.map((h) => h.textContent)).toEqual([
      "この会話で出てきた表現",
      "ターンごとのやりとり",
    ]);
    const items = within(coach).getAllByRole("listitem").slice(0, 2);
    expect(items[0]).toHaveTextContent("I feel refreshed（自分の気分は -ed）");
    expect(
      within(items[0] as HTMLElement).getByText("I feel refreshed"),
    ).toHaveAttribute("lang", "en");
    const rows = within(coach).getAllByRole("button", { expanded: false });
    expect(rows.map((row) => row.textContent)).toEqual([
      "▸ターン 1I feel refreshed today",
      "▸ターン 2I have been studying AWS",
      "▸ターン 3That's all for today",
    ]);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/👉 次/)).not.toBeInTheDocument();
    expect(screen.queryByText(/mastered|習得/)).not.toBeInTheDocument();
  });

  it("lists only Partner lines and finished English on the left, in order, in English", () => {
    renderTranscript(ended());

    const left = screen.getByRole("region", { name: "会話" });
    expect(within(left).getByRole("heading", { level: 2 })).toHaveTextContent(
      "会話（英文だけの通し）",
    );
    const lines = within(left)
      .getAllByRole("listitem")
      .map((item) => within(item).getAllByText(/./).at(-1) as HTMLElement);
    expect(lines.map((line) => line.textContent)).toEqual([
      "Hey! How was your day today?",
      "I feel refreshed today",
      "Oh nice! What kind of things?",
      "I have been studying AWS",
      "Cool. Anything else?",
      "That's all for today",
    ]);
    for (const line of lines) expect(line).toHaveAttribute("lang", "en");
    expect(within(left).queryByText("日本語 1")).not.toBeInTheDocument();
  });

  it("puts the closing section behind 「会話」 and selects 「コーチ」 below 1024 px", async () => {
    stubMatchMedia(false);
    const user = userEvent.setup();
    renderTranscript(ended());

    const coachTab = screen.getByRole("tab", { name: "コーチ" });
    expect(coachTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "コーチ" })).toBeVisible();

    await user.click(coachTab);
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "会話" })).toHaveFocus();
    expect(screen.getByRole("tabpanel", { name: "会話" })).toBeVisible();
    await user.keyboard("{End}");
    expect(coachTab).toHaveFocus();
    await user.keyboard("{Home}");
    await user.keyboard("{ArrowRight}");
    expect(coachTab).toHaveAttribute("aria-selected", "true");

    await user.click(screen.getByRole("tab", { name: "会話" }));
    await user.click(screen.getByRole("button", { name: "I have been studying AWS" }));
    expect(coachTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: /ターン 2/ })).toHaveFocus();
  });
});

describe("TranscriptScreen turn list (REQ-003, REQ-004, REQ-005)", () => {
  it("expands a turn to its full timeline on click, Enter, and Space", async () => {
    const user = userEvent.setup();
    renderTranscript(ended());

    const row = screen.getByRole("button", { name: /ターン 2/ });
    await user.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    const turn = screen.getByRole("list", { name: "ターン 2" });
    for (const text of [
      "あなたの日本語",
      "💡 いいですね！",
      "あなたの英語",
      "言い直し",
    ]) {
      expect(within(turn).getByText(text)).toBeInTheDocument();
    }
    expect(
      within(turn).getByText("意図は伝わっています。元のままでも通じます"),
    ).toBeInTheDocument();
    expect(within(turn).getByText("伝わります！")).toBeInTheDocument();

    await user.keyboard("{Enter}");
    expect(row).toHaveAttribute("aria-expanded", "false");
    await user.keyboard(" ");
    expect(row).toHaveAttribute("aria-expanded", "true");
  });

  it("expands a learner line's turn on the right and focuses its row", async () => {
    const user = userEvent.setup();
    renderTranscript(ended());

    await user.click(screen.getByRole("button", { name: "I feel refreshed today" }));

    const row = screen.getByRole("button", { name: /ターン 1/ });
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(row).toHaveFocus();
    expect(screen.getByRole("list", { name: "ターン 1" })).toBeInTheDocument();
  });

  it("starts the right pane with the turn list when the wrap-up has no items", () => {
    renderTranscript(ended({ wrap_up: { items: [] } }));

    const coach = screen.getByRole("region", { name: "コーチ" });
    const [first] = within(coach).getAllByRole("heading", { level: 2 });
    expect(first).toHaveTextContent("ターンごとのやりとり");
    expect(screen.queryByText("この会話で出てきた表現")).not.toBeInTheDocument();
  });

  it("shows 「ターン N」 alone for a turn that ended mid-turn, and its entries when expanded", async () => {
    const user = userEvent.setup();
    renderTranscript(
      ended({
        entries: [
          partner("Hey! How was your day today?", 1),
          entry("intent", { text: "疲れた", is_replacement: false }, 1),
        ],
        finished_replies: 0,
        wrap_up: { items: [] },
      }),
    );

    const row = screen.getByRole("button", { name: /ターン 1/ });
    expect(row).toHaveTextContent(/^▸ターン 1$/);
    await user.click(row);
    expect(
      within(screen.getByRole("list", { name: "ターン 1" })).getByText("疲れた"),
    ).toBeVisible();
  });

  it("leaves the left pane empty and lists no turn for a session ended at opening", () => {
    renderTranscript(
      ended({
        entries: [],
        finished_replies: 0,
        wrap_up: { items: [] },
        ended_at: null,
      }),
    );

    const left = screen.getByRole("region", { name: "会話" });
    expect(within(left).queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.queryByRole("button", { expanded: false })).not.toBeInTheDocument();
    expect(screen.getByText("0往復 · 終了")).toHaveTextContent(
      "10/16 21:02 · 0往復 · 終了",
    );
  });
});

const DUE = { wrap_up: null, allowed_actions: ["wrap_up" as const], version: 9 };

describe("TranscriptScreen wrap-up (REQ-008, REQ-010, REQ-011)", () => {
  it("sends wrap_up once for the version under StrictMode and replaces the waiting line with the items", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const server = serveSession(ended(DUE), async (_body, current) => {
      await gate;
      return { ...current, version: 10, wrap_up: WRAP_UP, allowed_actions: [] };
    });
    renderTranscript(ended(DUE), { strict: true });

    expect(
      await screen.findByText("コーチが振り返りを作っています…"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "もう一度" })).not.toBeInTheDocument();
    release?.();

    expect(await screen.findByText("these days")).toBeInTheDocument();
    expect(
      screen.queryByText("コーチが振り返りを作っています…"),
    ).not.toBeInTheDocument();
    expect(server.bodies).toEqual([{ action: "wrap_up", version: 9 }]);
  });

  it.each([
    ["model_timeout", "振り返りを作れませんでした（時間切れ）。"],
    ["model_rate_limited", "振り返りを作れませんでした（混み合っています）。"],
    ["model_unavailable", "振り返りを作れませんでした（接続できません）。"],
    ["model_error", "振り返りを作れませんでした（接続できません）。"],
    [
      "model_output_invalid",
      "振り返りを作れませんでした（返事の形式が正しくありませんでした）。",
    ],
    ["interrupted", "振り返りを作れませんでした。"],
    [null, "振り返りを作れませんでした。"],
  ])("words a failure coded %s as %s", (code, line) => {
    expect(wrapUpFailureLine(code)).toBe(line);
  });

  it("shows a failed wrap-up with its reason and never resends it by itself", async () => {
    const view = ended({
      ...DUE,
      last_submission: {
        action: "wrap_up",
        state: "failed",
        failure_code: "model_timeout",
        input: {},
      },
    });
    const server = serveSession(view, (_body, current) => ({
      ...current,
      version: 10,
      wrap_up: WRAP_UP,
      allowed_actions: [],
      last_submission: null,
    }));
    const user = userEvent.setup();
    renderTranscript(view, { strict: true });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "振り返りを作れませんでした（時間切れ）。",
    );
    expect(
      screen.getByText("I feel refreshed today", { selector: "button" }),
    ).toBeVisible();
    expect(server.bodies).toEqual([]);

    await user.click(screen.getByRole("button", { name: "もう一度" }));

    expect(await screen.findByText("these days")).toBeInTheDocument();
    expect(server.bodies).toEqual([{ action: "wrap_up", version: 9 }]);
  });

  it("shows an interrupted wrap-up without a reason, and [もう一度] sends it at the current version", async () => {
    const view = ended({
      ...DUE,
      version: 11,
      last_submission: {
        action: "wrap_up",
        state: "interrupted",
        failure_code: "interrupted",
        input: {},
      },
    });
    const server = serveSession(view, () =>
      HttpResponse.json<ProblemDetails>(problem(504, "model_timeout"), { status: 504 }),
    );
    const user = userEvent.setup();
    renderTranscript(view);

    expect(screen.getByRole("alert")).toHaveTextContent(
      /^振り返りを作れませんでした。もう一度$/,
    );
    expect(server.bodies).toEqual([]);

    await user.click(screen.getByRole("button", { name: "もう一度" }));

    expect(
      await screen.findByText("振り返りを作れませんでした（時間切れ）。"),
    ).toBeInTheDocument();
    expect(server.bodies).toEqual([{ action: "wrap_up", version: 11 }]);
  });

  it("leaves a wrap-up with no answer to the layout's banner, with no failure line of its own", async () => {
    const server = serveSession(ended(DUE), () => HttpResponse.error());
    renderTranscript(ended(DUE));

    const banner = (
      await screen.findByText(
        "アプリのサーバーに接続できません。起動しているか確認してください。",
      )
    ).closest('[role="alert"]') as HTMLElement;
    expect(screen.getAllByRole("alert")).toEqual([banner]);
    expect(screen.queryByText(/振り返りを作れませんでした/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "もう一度" })).not.toBeInTheDocument();
    expect(server.bodies).toHaveLength(1);
  });

  it("reports a wrap-up with no answer to the server-unreachable banner, whose 再試行 sends it again", async () => {
    let calls = 0;
    const server = serveSession(ended(DUE), (_, current) => {
      calls += 1;
      return calls === 1
        ? HttpResponse.error()
        : { ...current, version: current.version + 1, wrap_up: { items: [] } };
    });
    const user = userEvent.setup();
    renderTranscript(ended(DUE));

    const banner = (
      await screen.findByText(
        "アプリのサーバーに接続できません。起動しているか確認してください。",
      )
    ).closest('[role="alert"]') as HTMLElement;
    await user.click(within(banner).getByRole("button", { name: "再試行" }));

    await waitFor(() => expect(server.bodies).toHaveLength(2));
    expect(server.bodies[1]).toEqual(server.bodies[0]);
    await waitFor(() =>
      expect(
        screen.queryByText(
          "アプリのサーバーに接続できません。起動しているか確認してください。",
        ),
      ).not.toBeInTheDocument(),
    );
  });

  it("sends the wrap-up over another action's failure from before the end", async () => {
    const view = ended({
      ...DUE,
      last_submission: {
        action: "english",
        state: "failed",
        failure_code: "model_timeout",
        input: { text: "I watched" },
      },
    });
    const server = serveSession(view, (_body, current) => ({
      ...current,
      version: 10,
      wrap_up: WRAP_UP,
      allowed_actions: [],
      last_submission: null,
    }));
    renderTranscript(view, { strict: true });

    expect(await screen.findByText("these days")).toBeInTheDocument();
    expect(server.bodies).toEqual([{ action: "wrap_up", version: 9 }]);
  });

  it("waits for another tab's wrap-up when its own request gets 409 action_in_progress", async () => {
    installFakeClock();
    const pending = ended({
      ...DUE,
      last_submission: {
        action: "wrap_up",
        state: "pending",
        failure_code: null,
        input: {},
      },
    });
    const server = serveSession(ended(DUE), () => {
      server.set(pending);
      return HttpResponse.json<ProblemDetails>(problem(409, "action_in_progress"), {
        status: 409,
      });
    });
    const { queryClient } = renderTranscript(ended(DUE));
    await advance(0);
    // Settle the 409-triggered refetch before anchoring the polling clock.
    await act(
      () =>
        new Promise<void>((resolve) => {
          const finish = () => {
            const state = queryClient.getQueryState(
              sessionQueryOptions(SESSION_ID).queryKey,
            );
            if (
              state?.fetchStatus === "idle" &&
              state.data?.last_submission?.state === "pending"
            ) {
              stop();
              resolve();
            }
          };
          const stop = queryClient.getQueryCache().subscribe(finish);
          onTestFinished(stop);
          finish();
        }),
    );
    await advance(1);
    const baseline = server.reads();
    expect(baseline).toBeGreaterThan(0);
    expect(
      queryClient.getQueryState(sessionQueryOptions(SESSION_ID).queryKey)?.fetchStatus,
    ).toBe("idle");
    expect(
      queryClient.getQueryData(sessionQueryOptions(SESSION_ID).queryKey)
        ?.last_submission,
    ).toEqual(pending.last_submission);
    expect(screen.getByText("コーチが振り返りを作っています…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "もう一度" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(server.bodies).toEqual([{ action: "wrap_up", version: 9 }]);

    await advance(1999);
    expect(server.reads()).toBe(baseline);
    server.set({
      ...pending,
      version: 10,
      wrap_up: WRAP_UP,
      last_submission: null,
      allowed_actions: [],
    });
    await advance(1);

    expect(server.reads()).toBe(baseline + 1);
    expect(screen.getByText("these days")).toBeInTheDocument();
    await advance(6000);
    expect(server.reads()).toBe(baseline + 1);
    expect(server.bodies).toEqual([{ action: "wrap_up", version: 9 }]);
  });

  it("waits for a wrap-up pending elsewhere, reading the session every 2 s until it settles", async () => {
    installFakeClock();
    const view = ended({
      ...DUE,
      last_submission: {
        action: "wrap_up",
        state: "pending",
        failure_code: null,
        input: {},
      },
    });
    const server = serveSession(view);
    renderTranscript(view);
    await advance(1);
    const baseline = server.reads();
    expect(baseline).toBeGreaterThan(0);
    expect(screen.getByText("コーチが振り返りを作っています…")).toBeInTheDocument();

    await advance(1999);
    expect(server.reads()).toBe(baseline);
    server.set({
      ...view,
      version: 10,
      wrap_up: WRAP_UP,
      last_submission: null,
      allowed_actions: [],
    });
    await advance(1);

    expect(server.reads()).toBe(baseline + 1);
    expect(screen.getByText("these days")).toBeInTheDocument();
    await advance(6000);
    expect(server.reads()).toBe(baseline + 1);
    expect(server.bodies).toEqual([]);
  });
});

describe("the session route ending into S3 (REQ-008)", () => {
  it("shows S3 on the same URL when end succeeds on S2, and sends wrap_up once", async () => {
    const inProgress = sessionView({
      stage: "intent",
      version: 4,
      turn_index: 3,
      finished_replies: 2,
      allowed_actions: ["intent", "end"],
      entries: ENTRIES.slice(0, 13),
    });
    const server = serveSession(inProgress, (body, current) =>
      body.action === "end"
        ? {
            ...current,
            status: "ended",
            stage: "ended",
            version: 5,
            ended_at: new Date(2026, 9, 17, 19, 0).toISOString(),
            wrap_up: null,
            allowed_actions: ["wrap_up"],
          }
        : { ...current, version: 6, wrap_up: WRAP_UP, allowed_actions: [] },
    );
    const queryClient = createQueryClient();
    const history = createMemoryHistory({
      initialEntries: [`/sessions/${SESSION_ID}`],
    });
    const router = createAppRouter(queryClient, { history });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "会話を終える" }));
    await user.click(screen.getByRole("button", { name: "終える" }));

    expect(await screen.findByText("these days")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "会話（英文だけの通し）" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/sessions/${SESSION_ID}`);
    await waitFor(() =>
      expect(server.bodies).toEqual([
        { action: "end", version: 4 },
        { action: "wrap_up", version: 5 },
      ]),
    );
  });
});
