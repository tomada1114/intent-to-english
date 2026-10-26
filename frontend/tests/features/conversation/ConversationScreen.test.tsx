import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type {
  Action,
  FeedbackResponse,
  ProblemDetails,
  SessionResponse,
  TimelineEntryResponse,
} from "../../../src/api/generated/types.gen";
import { sessionQueryOptions } from "../../../src/features/conversation";
import {
  deferred,
  entry,
  renderSession,
  SESSION_ID,
  serveSession,
  sessionView,
  stubMatchMedia,
} from "../../msw/helpers";

const OPENER = entry("partner_line", {
  text: "Hey! How's it going?",
  has_question: true,
  line_kind: "opener",
  restate_mode: null,
});
const SHARE = entry(
  "partner_line",
  {
    text: "I went for a long walk by the river today.",
    has_question: false,
    line_kind: "reply",
    restate_mode: null,
  },
  2,
);
const INTENT = entry("intent", { text: "久しぶりに映画を見た", is_replacement: false });
const ACK = entry("acknowledgment", { line: "いいですね！", build_hint: null });
const ENGLISH = entry("english", { text: "I watched a movie", is_direct: false });
const FEEDBACK: FeedbackResponse = {
  first_line: "意図は伝わっています。元のままでも通じます",
  fixes: [
    {
      number: 1,
      original: "I",
      replacement: "Actually, I",
      reason: "元のままでも通じる。Actually, で始めると話を続ける感じが出る",
      tag: "improvement",
    },
  ],
  sentence: "I watched a movie",
  template: "(①) ____ watched a movie",
  request_line: "(①) を埋めて、文全体をもう一度送ってください",
  readings_noted: [],
};
const FEEDBACK_ENTRY = entry("feedback", {
  intent: "久しぶりに映画を見た",
  feedback: FEEDBACK,
});
const ACCEPTED = entry("retry_result", {
  result: { line: "いいですね！伝わります", readings_noted: [] },
});
const DONE = entry("turn_done", {
  english: "Actually, I watched a movie",
  end: "accepted",
});

const SIDE: Action[] = ["restate", "ask", "end"];

function at(
  stage: SessionResponse["stage"],
  entries: TimelineEntryResponse[],
  allowed: Action[],
  overrides: Partial<SessionResponse> = {},
) {
  return sessionView({ stage, entries, allowed_actions: allowed, ...overrides });
}

const opening = at("opening", [], ["open", "ask", "end"], { version: 0 });
const intent = at("intent", [OPENER], ["intent", "english_direct", ...SIDE], {
  version: 1,
});
const english = at(
  "english",
  [OPENER, INTENT, ACK],
  ["english", "hint", "show_answer", "rewrite_intent", ...SIDE],
  { version: 2 },
);
const retry = at(
  "retry",
  [OPENER, INTENT, ACK, ENGLISH, FEEDBACK_ENTRY],
  ["retry", "show_answer", "skip", "rewrite_intent", ...SIDE],
  { version: 3 },
);
const partnerTurn = at(
  "partner_turn",
  [
    OPENER,
    INTENT,
    ACK,
    ENGLISH,
    FEEDBACK_ENTRY,
    entry("retry", { sentence: "Actually, I watched a movie", submission_number: 1 }),
    ACCEPTED,
    DONE,
  ],
  ["partner_reply", "ask", "end"],
  { version: 4, finished_replies: 1 },
);

function pane(name: "会話" | "コーチ") {
  return screen.getByRole("region", { name });
}

function next(text: string) {
  return within(pane("コーチ")).getByText(`👉 次: ${text}`);
}

const problem = (status: number, code: string, detail: string): ProblemDetails => ({
  type: "about:blank",
  title: "Error",
  status,
  detail,
  code,
  request_id: "req-42",
});

describe("ConversationScreen auto-sent actions (REQ-001)", () => {
  it("sends open once at opening under StrictMode, then shows the how-to and the opener", async () => {
    const server = serveSession(opening, () => intent);
    renderSession(opening, { strict: true });

    expect(await within(pane("会話")).findByText(OPENER.payload.text)).toHaveAttribute(
      "lang",
      "en",
    );
    expect(server.bodies).toEqual([
      { attempt_id: expect.any(String), action: "open", version: 0 },
    ]);
    expect(
      within(pane("コーチ")).getByRole("button", { name: "進め方" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      within(pane("コーチ")).getByText("1. 返したいことを、まず日本語で送ってください"),
    ).toBeInTheDocument();
    expect(
      next("返したいことを日本語で送ってください（英語で返してもOK）"),
    ).toBeVisible();
  });

  it("collapses and expands the how-to", async () => {
    const user = userEvent.setup();
    serveSession(intent);
    renderSession(intent);
    const howTo = screen.getByRole("button", { name: "進め方" });

    await user.click(howTo);
    expect(howTo).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/^1\. /)).not.toBeInTheDocument();

    await user.click(howTo);
    expect(howTo).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/^4\. /)).toBeInTheDocument();
  });

  it("sends partner_reply once at partner_turn and waits for the Partner on the left", async () => {
    const reply = deferred();
    const server = serveSession(partnerTurn, async () => {
      await reply.promise;
      return at("intent", [...partnerTurn.entries, SHARE], ["intent", ...SIDE], {
        version: 5,
        turn_index: 2,
        finished_replies: 1,
      });
    });
    renderSession(partnerTurn, { strict: true });

    expect(
      await within(pane("会話")).findByText("Partner が返事を考えています…"),
    ).toBeInTheDocument();
    reply.release();

    expect(
      await within(pane("会話")).findByText(SHARE.payload.text),
    ).toBeInTheDocument();
    expect(server.bodies).toEqual([
      { attempt_id: expect.any(String), action: "partner_reply", version: 4 },
    ]);
    expect(
      within(pane("会話")).queryByText("Partner が返事を考えています…"),
    ).not.toBeInTheDocument();
  });

  it("never sends again after a failed open, even when the view is read again", async () => {
    const server = serveSession(opening, () =>
      HttpResponse.json<ProblemDetails>(
        problem(502, "model_unavailable", "The model provider failed"),
        { status: 502 },
      ),
    );
    const { queryClient } = renderSession(opening);

    expect(
      await within(pane("会話")).findByText(
        "Partner の返事を受け取れませんでした（接続できません）。",
      ),
    ).toBeInTheDocument();
    await act(() =>
      queryClient.invalidateQueries({
        queryKey: sessionQueryOptions(SESSION_ID).queryKey,
      }),
    );

    expect(server.bodies).toHaveLength(1);
  });

  it.each([
    { state: "pending" as const, shows: "Partner が返事を考えています…" },
    {
      state: "failed" as const,
      shows: "Partner の返事を受け取れませんでした（時間切れ）。",
    },
    { state: "interrupted" as const, shows: "もう一度" },
  ])(
    "sends nothing when the last submission is $state, and shows it",
    async ({ state, shows }) => {
      const view = {
        ...opening,
        last_submission: {
          attempt_id: "00000000-0000-4000-8000-000000000001",
          action: "open" as const,
          input: {},
          state,
          failure_code: state === "pending" ? null : "model_timeout",
        },
      };
      const server = serveSession(view);
      renderSession(view);

      expect(await within(pane("会話")).findByText(shows)).toBeInTheDocument();
      expect(server.bodies).toEqual([]);
    },
  );
});

describe("ConversationScreen panes (REQ-002)", () => {
  const second = at(
    "english",
    [
      ...partnerTurn.entries,
      entry("check_in", {}),
      entry("check_in_answer", { answer: "continue" }),
      { ...SHARE },
      entry(
        "partner_line",
        {
          text: "Nice walk.",
          has_question: false,
          line_kind: "restatement",
          restate_mode: "shorter",
        },
        2,
      ),
      entry("intent", { text: "いいね", is_replacement: false }, 2),
      entry("intent", { text: "いいね、どこを歩いた？", is_replacement: true }, 2),
      entry("acknowledgment", { line: "いいですね！", build_hint: null }, 2),
      entry("question", { text: "walk は名詞ですか" }, 2),
      entry("coach_answer", { text: "ここでは名詞です" }, 2),
    ],
    ["english", ...SIDE],
    { version: 9, turn_index: 2, finished_replies: 1 },
  );

  it("shows the Partner's lines and each finished English on the left", () => {
    serveSession(second);
    renderSession(second);

    const left = within(pane("会話"));
    expect(left.getByRole("heading", { level: 2 })).toHaveTextContent(
      "会話（Partner が聞いている英語）",
    );
    const lines = Array.from(
      left.getByRole("list", { name: "会話の流れ" }).children,
      (row) => row.textContent,
    );
    expect(lines).toEqual([
      `Partner${OPENER.payload.text}`,
      "YouActually, I watched a movie",
      `Partner${SHARE.payload.text}`,
      "言い換え（短く）Nice walk.",
    ]);
    expect(left.queryByText("いいね")).not.toBeInTheDocument();
  });

  it("shows only the current turn's entries on the right, with old intents collapsed", () => {
    serveSession(second);
    renderSession(second);

    const right = within(pane("コーチ"));
    expect(right.getByRole("heading", { level: 2 })).toHaveTextContent(
      "コーチ · ターン 2",
    );
    const rows = Array.from(
      right.getByRole("list", { name: "ターン 2" }).children,
      (row) => row.textContent,
    );
    expect(rows).toEqual([
      "書き直す前のやりとりあなたの日本語いいね",
      "あなたの日本語いいね、どこを歩いた？",
      "💡 いいですね！",
      "質問walk は名詞ですか",
      "💡 コーチここでは名詞です",
    ]);
    expect(right.queryByText(INTENT.payload.text)).not.toBeInTheDocument();
    expect(right.queryByRole("button", { name: "進め方" })).not.toBeInTheDocument();
  });

  it.each([
    { end: "accepted" as const, line: "前のターン: 言い直しできました" },
    { end: "skipped" as const, line: "前のターン: スキップしました" },
    { end: "no_fix_needed" as const, line: null },
  ])(
    "between turns shows the 前のターン line for a turn that ended $end",
    ({ end, line }) => {
      const view = at(
        "intent",
        [OPENER, INTENT, entry("turn_done", { english: "Hi", end }), SHARE],
        ["intent", ...SIDE],
        { turn_index: 2, finished_replies: 1 },
      );
      serveSession(view);
      renderSession(view);

      const right = within(pane("コーチ"));
      if (line === null) {
        expect(right.queryByText(/^前のターン/)).not.toBeInTheDocument();
      } else {
        expect(right.getByText(line)).toBeInTheDocument();
        expect(
          right.queryByRole("button", { name: "もう一度練習" }),
        ).not.toBeInTheDocument();
      }
    },
  );

  it("drops the 前のターン line once the learner replies in the new turn", () => {
    const view = at(
      "intent",
      [
        OPENER,
        DONE,
        SHARE,
        entry("intent", { text: "いいね", is_replacement: false }, 2),
      ],
      ["intent", ...SIDE],
      { turn_index: 2, finished_replies: 1 },
    );
    serveSession(view);
    renderSession(view);

    expect(within(pane("コーチ")).queryByText(/^前のターン/)).not.toBeInTheDocument();
  });

  it("puts the start time, the reply count, and 会話を終える in the header items", () => {
    const view = { ...second, started_at: new Date(2026, 9, 17, 18, 40).toISOString() };
    serveSession(view);
    renderSession(view);

    // Below 1024 px only 「1往復」 shows; the start time is in the same item.
    expect(screen.getByText("1往復")).toHaveTextContent("10/17 18:40 から · 1往復");
    expect(screen.getByRole("button", { name: "会話を終える" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "10/17 18:40 からの会話",
    );
  });
});

interface StageRow {
  name: string;
  view: SessionResponse;
  next: string;
  composer: { label: string; placeholder: string | null; disabled: boolean } | null;
  controls: string[];
}

const readingCheck = at(
  "reading_check",
  [
    OPENER,
    INTENT,
    ACK,
    entry("english", { text: "I want to leave in Canada", is_direct: false }),
    entry("reading_question", { word: "leave", readings: ["leave", "live"] }),
  ],
  ["reading", "rewrite_intent", ...SIDE],
  { version: 3 },
);

const stageRows: StageRow[] = [
  {
    name: "Waiting for the Partner",
    view: {
      ...opening,
      last_submission: {
        attempt_id: "00000000-0000-4000-8000-000000000001",
        action: "open",
        input: {},
        state: "pending",
        failure_code: null,
      },
    },
    next: "Partner の返事を待っています",
    composer: { label: "あなたの日本語", placeholder: null, disabled: true },
    controls: [],
  },
  {
    name: "Intent",
    view: intent,
    next: "返したいことを日本語で送ってください（英語で返してもOK）",
    composer: {
      label: "あなたの日本語",
      placeholder: "返したいことを日本語で",
      disabled: false,
    },
    controls: ["英語で直接返す"],
  },
  {
    name: "Intent after a Partner share",
    view: at("intent", [OPENER, DONE, SHARE], ["intent", ...SIDE], { turn_index: 2 }),
    next: "反応や、相手への質問を日本語で送ってください（英語で返してもOK）",
    composer: {
      label: "あなたの日本語",
      placeholder: "返したいことを日本語で",
      disabled: false,
    },
    controls: [],
  },
  {
    name: "English",
    view: english,
    next: "それを英語にしてみてください（途中まででOK。詰まったら「ヒント」）",
    composer: {
      label: "あなたの英語",
      placeholder: "英語にしてみましょう（途中まででOK）",
      disabled: false,
    },
    controls: ["ヒント", "答えを見せて"],
  },
  {
    name: "After a hint",
    view: at(
      "english",
      [
        ...english.entries,
        entry("hint_request", { gap: "久しぶり", partial_english: "" }),
        entry("gap_hint", {
          hint: "「久しぶり」の部分は kind of から始めてみてください",
        }),
      ],
      english.allowed_actions,
    ),
    next: "ヒントを使って、英語の文全体を送ってください",
    composer: { label: "あなたの英語", placeholder: "英語の文全体を", disabled: false },
    controls: ["ヒント", "答えを見せて"],
  },
  {
    name: "Retry",
    view: retry,
    next: "直し方を見返しながら穴を埋めて、英語の文全体を送ってください（「スキップ」も可）",
    composer: {
      label: "あなたの英語",
      placeholder: "穴を埋めた英文全体を",
      disabled: false,
    },
    controls: ["スキップ", "答えを見せて"],
  },
  {
    name: "One blank still off",
    view: at(
      "retry",
      [
        ...retry.entries,
        entry("retry", { sentence: "Also I watched", submission_number: 1 }),
        entry("retry_result", {
          result: { blanks: [3], hint: "③がまだ違います", readings_noted: [] },
        }),
      ],
      retry.allowed_actions,
    ),
    next: "③の穴だけ埋め直して、英語の文全体をもう一度送ってください",
    composer: {
      label: "あなたの英語",
      placeholder: "穴を埋めた英文全体を",
      disabled: false,
    },
    controls: ["スキップ", "答えを見せて"],
  },
  {
    name: "Answer shown",
    view: at(
      "answer_shown",
      [...retry.entries, entry("answer", { example: "Actually, I watched a movie." })],
      ["typed_copy", "skip", ...SIDE],
    ),
    next: "完成例を見ながら、英語の文全体を1回送ってください（「スキップ」で会話に戻ります）",
    composer: {
      label: "あなたの英語",
      placeholder: "見ながら1回打ってみましょう",
      disabled: false,
    },
    controls: ["スキップ"],
  },
  {
    name: "Reading check",
    view: readingCheck,
    next: "どちらのつもりか選んでください",
    composer: null,
    controls: ["leave のつもり", "live のつもり"],
  },
  {
    name: "Check-in",
    view: at(
      "check_in",
      [...partnerTurn.entries, entry("check_in", {})],
      ["partner_reply", "practice_again", "ask", "end"],
    ),
    next: "「続ける」か「終わる」を選んでください",
    composer: null,
    controls: ["続ける", "終わる"],
  },
];

describe("ConversationScreen stage table (REQ-003)", () => {
  it.each(stageRows)(
    "renders the $name row",
    ({ view, next: line, composer, controls }) => {
      serveSession(view);
      renderSession(view);

      expect(next(line)).toBeInTheDocument();
      const right = within(pane("コーチ"));
      if (composer === null) {
        expect(right.queryByRole("textbox")).not.toBeInTheDocument();
      } else {
        const field = right.getByRole("textbox", { name: composer.label });
        if (composer.placeholder === null) {
          expect(field).not.toHaveAttribute("placeholder");
        } else {
          expect(field).toHaveAttribute("placeholder", composer.placeholder);
        }
        expect(field.hasAttribute("disabled")).toBe(composer.disabled);
      }
      const group = right.queryByRole("group", { name: "操作" });
      const shown =
        group === null
          ? []
          : within(group)
              .getAllByRole("button")
              .map((button) => button.textContent);
      expect(shown).toEqual(controls);
    },
  );

  it("shows a control only when the view allows its action", () => {
    const view = { ...english, allowed_actions: ["english", "end"] as Action[] };
    serveSession(view);
    renderSession(view);

    expect(screen.queryByRole("button", { name: "ヒント" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "答えを見せて" }),
    ).not.toBeInTheDocument();
  });

  it("names every blank a retry result lists", () => {
    const view = at(
      "retry",
      [
        ...retry.entries,
        entry("retry_result", {
          result: { blanks: [1, 3], hint: "①と③がまだ違います", readings_noted: [] },
        }),
      ],
      retry.allowed_actions,
    );
    serveSession(view);
    renderSession(view);

    expect(
      next("①と③の穴だけ埋め直して、英語の文全体をもう一度送ってください"),
    ).toBeInTheDocument();
  });

  it("switches the composer to English with 英語で直接返す, a toggle back to Japanese", async () => {
    const user = userEvent.setup();
    serveSession(intent);
    renderSession(intent);

    const toggle = screen.getByRole("button", { name: "英語で直接返す" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveAttribute(
      "lang",
      "en",
    );
    await user.click(toggle);
    expect(screen.getByRole("textbox", { name: "あなたの日本語" })).toHaveAttribute(
      "lang",
      "ja",
    );
  });

  it("opens the hint box under the composer, keeps the partial English, and Esc closes it", async () => {
    const user = userEvent.setup();
    serveSession(english);
    renderSession(english);

    await user.type(screen.getByRole("textbox", { name: "あなたの英語" }), "I watched");
    await user.click(screen.getByRole("button", { name: "ヒント" }));

    const gap = screen.getByRole("textbox", { name: "分からないところ" });
    expect(gap).toHaveFocus();
    expect(gap).toHaveAttribute(
      "placeholder",
      "分からないところ（例: 「久しぶり」が分からない）",
    );
    expect(
      next("分からないところを書いて、ヒントをもらってください"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ヒントをもらう" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "やめる" })).toBeEnabled();

    await user.keyboard("{Escape}");

    expect(
      screen.queryByRole("textbox", { name: "分からないところ" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ヒント" })).toHaveFocus();
    expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
      "I watched",
    );
  });

  it("closes the hint box with やめる", async () => {
    const user = userEvent.setup();
    serveSession(english);
    renderSession(english);
    await user.click(screen.getByRole("button", { name: "ヒント" }));

    await user.click(screen.getByRole("button", { name: "やめる" }));

    expect(
      screen.queryByRole("textbox", { name: "分からないところ" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ヒント" })).toHaveFocus();
  });

  it("counts the hint gap from 180 and refuses more than 200", async () => {
    const user = userEvent.setup();
    serveSession(english);
    renderSession(english);
    await user.click(screen.getByRole("button", { name: "ヒント" }));

    await user.paste("あ".repeat(180));
    expect(screen.getByText("180 / 200")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ヒントをもらう" })).toBeEnabled();
    await user.paste("あ".repeat(21));

    expect(
      screen.getByText("200字以内にしてください（いま201字）"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ヒントをもらう" })).toBeDisabled();
  });

  it("renders an ended session read-only, with no composer, controls, or 👉 次", () => {
    const view = at("ended", partnerTurn.entries, [], {
      status: "ended",
      ended_at: "2026-10-17T10:00:00Z",
    });
    serveSession(view);
    renderSession(view);

    expect(
      within(pane("会話")).getByText("Actually, I watched a movie"),
    ).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "コーチの添削" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "操作" })).not.toBeInTheDocument();
    expect(screen.queryByText(/👉 次/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "会話を終える" }),
    ).not.toBeInTheDocument();
  });
});

interface SendRow {
  name: string;
  view: SessionResponse;
  act: (user: ReturnType<typeof userEvent.setup>) => Promise<void>;
  body: Record<string, unknown>;
  waiting: "partner" | "coach";
}

async function compose(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
  text: string,
) {
  await user.type(screen.getByRole("textbox", { name: label }), text);
  await user.keyboard("{Meta>}{Enter}{/Meta}");
}

const sendRows: SendRow[] = [
  {
    name: "intent",
    view: intent,
    act: (user) => compose(user, "あなたの日本語", "久しぶりに映画を見た"),
    body: { action: "intent", text: "久しぶりに映画を見た", version: 1 },
    waiting: "coach",
  },
  {
    name: "english_direct",
    view: intent,
    act: async (user) => {
      await user.click(screen.getByRole("button", { name: "英語で直接返す" }));
      await compose(user, "あなたの英語", "I watched a movie");
    },
    body: { action: "english_direct", text: "I watched a movie", version: 1 },
    waiting: "coach",
  },
  {
    name: "english",
    view: english,
    act: (user) => compose(user, "あなたの英語", "I watched a movie"),
    body: { action: "english", text: "I watched a movie", version: 2 },
    waiting: "coach",
  },
  {
    name: "hint",
    view: english,
    act: async (user) => {
      await user.type(
        screen.getByRole("textbox", { name: "あなたの英語" }),
        "I watched",
      );
      await user.click(screen.getByRole("button", { name: "ヒント" }));
      await user.type(
        screen.getByRole("textbox", { name: "分からないところ" }),
        "久しぶり",
      );
      await user.click(screen.getByRole("button", { name: "ヒントをもらう" }));
    },
    body: { action: "hint", gap: "久しぶり", partial_english: "I watched", version: 2 },
    waiting: "coach",
  },
  {
    name: "reading",
    view: readingCheck,
    act: (user) => user.click(screen.getByRole("button", { name: "live のつもり" })),
    body: { action: "reading", reading: "live", version: 3 },
    waiting: "coach",
  },
  {
    name: "retry",
    view: retry,
    act: (user) => compose(user, "あなたの英語", "Actually, I watched a movie"),
    body: { action: "retry", text: "Actually, I watched a movie", version: 3 },
    waiting: "coach",
  },
  {
    name: "show_answer",
    view: retry,
    act: (user) => user.click(screen.getByRole("button", { name: "答えを見せて" })),
    body: { action: "show_answer", version: 3 },
    waiting: "coach",
  },
  {
    name: "typed_copy",
    view: at("answer_shown", retry.entries, ["typed_copy", "skip", ...SIDE], {
      version: 5,
    }),
    act: (user) => compose(user, "あなたの英語", "Actually, I watched a movie."),
    body: { action: "typed_copy", text: "Actually, I watched a movie.", version: 5 },
    waiting: "coach",
  },
  {
    name: "skip",
    view: retry,
    act: (user) => user.click(screen.getByRole("button", { name: "スキップ" })),
    body: { action: "skip", version: 3 },
    waiting: "coach",
  },
  {
    name: "partner_reply at the check-in",
    view: at(
      "check_in",
      [...partnerTurn.entries, entry("check_in", {})],
      ["partner_reply", "end"],
      { version: 6 },
    ),
    act: (user) => user.click(screen.getByRole("button", { name: "続ける" })),
    body: { action: "partner_reply", version: 6 },
    waiting: "partner",
  },
];

describe("ConversationScreen sending (REQ-004)", () => {
  it.each(sendRows)(
    "posts $name with the shown version and waits in place",
    async ({ view, act: perform, body, waiting }) => {
      const hold = deferred();
      const server = serveSession(view, async (_, current) => {
        await hold.promise;
        return current;
      });
      const user = userEvent.setup();
      renderSession(view);

      await perform(user);

      await waitFor(() =>
        expect(server.bodies).toEqual([{ ...body, attempt_id: expect.any(String) }]),
      );
      // The waiting line shows once the request passes 300 ms.
      if (waiting === "partner") {
        expect(
          await within(pane("会話")).findByText("Partner が返事を考えています…"),
        ).toBeInTheDocument();
      } else {
        expect(
          await within(pane("コーチ")).findByText("コーチが確認しています…"),
        ).toBeInTheDocument();
      }
      expect(within(pane("コーチ")).queryByRole("group", { name: "操作" })).toBeNull();
      const field = within(pane("コーチ")).queryByRole("textbox", { name: /あなたの/ });
      if (field !== null) expect(field).toBeDisabled();
      hold.release();
    },
  );

  it("keeps the text in a disabled composer and blocks a second send while in flight", async () => {
    const hold = deferred();
    const server = serveSession(intent, async (_, current) => {
      await hold.promise;
      return current;
    });
    const user = userEvent.setup();
    renderSession(intent);

    await compose(user, "あなたの日本語", "久しぶりに映画を見た");
    const field = screen.getByRole("textbox", { name: "あなたの日本語" });
    await waitFor(() => expect(field).toBeDisabled());
    expect(field).toHaveValue("久しぶりに映画を見た");
    fireEvent.keyDown(field, { key: "Enter", metaKey: true });
    expect(screen.getByRole("button", { name: "送信" })).toBeDisabled();

    expect(server.bodies).toHaveLength(1);
    hold.release();
  });

  it("sends one request for a double ⌘↵ before React re-renders", async () => {
    const server = serveSession(intent, () => english);
    const user = userEvent.setup();
    renderSession(intent);
    const field = screen.getByRole("textbox", { name: "あなたの日本語" });
    await user.type(field, "久しぶりに映画を見た");

    fireEvent.keyDown(field, { key: "Enter", metaKey: true });
    fireEvent.keyDown(field, { key: "Enter", metaKey: true });

    await screen.findByRole("textbox", { name: "あなたの英語" });
    expect(server.bodies).toHaveLength(1);
  });

  it("ends without confirmation with 終わる at the check-in", async () => {
    const view = at(
      "check_in",
      [...partnerTurn.entries, entry("check_in", {})],
      ["partner_reply", "end"],
      { version: 6 },
    );
    const server = serveSession(view, () =>
      at("ended", view.entries, [], { status: "ended", version: 7 }),
    );
    const user = userEvent.setup();
    renderSession(view);

    await user.click(screen.getByRole("button", { name: "終わる" }));

    await waitFor(() => expect(screen.queryByText(/👉 次/)).not.toBeInTheDocument());
    expect(server.bodies).toEqual([
      { attempt_id: expect.any(String), action: "end", version: 6 },
    ]);
  });
});

describe("ConversationScreen focus and announcements (REQ-009)", () => {
  it("moves focus to the composer and announces the Coach's block when a result arrives", async () => {
    const result = at("english", [OPENER, INTENT, ACK], english.allowed_actions, {
      version: 2,
    });
    serveSession(intent, () => result);
    const user = userEvent.setup();
    renderSession(intent);

    await compose(user, "あなたの日本語", "久しぶりに映画を見た");

    const field = await screen.findByRole("textbox", { name: "あなたの英語" });
    expect(field).toHaveAttribute(
      "placeholder",
      "英語にしてみましょう（途中まででOK）",
    );
    await waitFor(() => expect(field).toHaveFocus());
    expect(field).toHaveValue("");
    expect(within(pane("コーチ")).getByText("💡 いいですね！")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "お知らせ" })).toHaveTextContent(
      "コーチ: いいですね！",
    );
  });

  it("announces a new Partner line once", async () => {
    serveSession(opening, () => intent);
    renderSession(opening);

    const status = screen.getByRole("status", { name: "お知らせ" });
    await waitFor(() =>
      expect(status).toHaveTextContent(`Partner: ${OPENER.payload.text}`),
    );
  });

  it("moves focus to the first control when the result hides the composer", async () => {
    serveSession(english, () => readingCheck);
    const user = userEvent.setup();
    renderSession(english);

    await compose(user, "あなたの英語", "I want to leave in Canada");

    const first = await screen.findByRole("button", { name: "leave のつもり" });
    await waitFor(() => expect(first).toHaveFocus());
    expect(screen.getByRole("status", { name: "お知らせ" })).toHaveTextContent(
      "コーチ: 「leave」は leave と live のどちらのつもりですか",
    );
  });

  it("never takes focus from a field the learner is typing in", async () => {
    const reply = deferred();
    serveSession(partnerTurn, async () => {
      await reply.promise;
      return at("intent", [...partnerTurn.entries, SHARE], ["intent", ...SIDE], {
        version: 5,
        turn_index: 2,
      });
    });
    const user = userEvent.setup();
    renderSession(partnerTurn, { before: <input aria-label="メモ" /> });

    await user.type(screen.getByRole("textbox", { name: "メモ" }), "walk");
    reply.release();

    await screen.findByText(SHARE.payload.text);
    expect(screen.getByRole("textbox", { name: "メモ" })).toHaveFocus();
  });
});

describe("ConversationScreen below 1024px (REQ-010)", () => {
  it("is a tablist with コーチ selected and the line being answered pinned", async () => {
    stubMatchMedia(false);
    const user = userEvent.setup();
    serveSession(english);
    renderSession(english);

    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["会話", "コーチ"]);
    const coach = screen.getByRole("tab", { name: "コーチ" });
    expect(coach).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel", { name: "コーチ" });
    expect(within(panel).getByText("🗣 返事をする発言")).toBeInTheDocument();
    expect(within(panel).getByText(OPENER.payload.text)).toHaveAttribute("lang", "en");
    expect(screen.queryByRole("tabpanel", { name: "会話" })).not.toBeInTheDocument();

    await user.click(coach);
    await user.keyboard("{ArrowLeft}");

    const conversation = screen.getByRole("tab", { name: "会話" });
    expect(conversation).toHaveFocus();
    expect(conversation).toHaveAttribute("aria-selected", "true");
    expect(
      within(screen.getByRole("tabpanel", { name: "会話" })).getByText(
        OPENER.payload.text,
      ),
    ).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(coach).toHaveAttribute("aria-selected", "true");
  });

  it("marks 会話 with a dot and hidden text when a new Partner line arrives", async () => {
    stubMatchMedia(false);
    const user = userEvent.setup();
    serveSession(partnerTurn, () =>
      at("intent", [...partnerTurn.entries, SHARE], ["intent", ...SIDE], {
        version: 5,
        turn_index: 2,
      }),
    );
    renderSession(partnerTurn);

    const conversation = await screen.findByRole("tab", { name: "会話（新しい発言）" });
    expect(
      within(screen.getByRole("tabpanel", { name: "コーチ" })).getByText(
        SHARE.payload.text,
      ),
    ).toBeInTheDocument();

    await user.click(conversation);

    expect(screen.getByRole("tab", { name: "会話" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

describe("ConversationScreen pane scrolling", () => {
  function geometry(element: HTMLElement, scrollTop: number) {
    Object.defineProperty(element, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(element, "clientHeight", { configurable: true, value: 400 });
    Object.defineProperty(element, "scrollTop", {
      configurable: true,
      writable: true,
      value: scrollTop,
    });
  }

  it.each([
    { from: 520, scrolled: true },
    { from: 500, scrolled: false },
  ])(
    "from $from px down scrolls to new content: $scrolled",
    async ({ from, scrolled }) => {
      serveSession(intent, () => english);
      const user = userEvent.setup();
      renderSession(intent);
      const scroller = screen.getByTestId("coach-scroll");
      geometry(scroller, from);
      fireEvent.scroll(scroller);

      await compose(user, "あなたの日本語", "久しぶりに映画を見た");
      await screen.findByText("💡 いいですね！");

      expect(scroller.scrollTop).toBe(scrolled ? 1000 : from);
    },
  );
});
