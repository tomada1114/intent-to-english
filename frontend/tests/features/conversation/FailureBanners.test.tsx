import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type {
  Action,
  ProblemDetails,
  SessionResponse,
} from "../../../src/api/generated/types.gen";
import { sessionQueryOptions } from "../../../src/features/conversation";
import {
  type ActionBody,
  deferred,
  entry,
  renderSession,
  SESSION_ID,
  serveSession,
  sessionView,
  stubMatchMedia,
} from "../../msw/helpers";

const STALE = "別の画面でこの会話が進みました。最新の状態を読み込みました。";
const UNREACHABLE =
  "アプリのサーバーに接続できません。起動しているか確認してください。";

const OPENER = entry("partner_line", {
  text: "Hey! How's it going?",
  has_question: true,
  line_kind: "opener",
  restate_mode: null,
});
const INTENT = entry("intent", { text: "久しぶりに映画を見た", is_replacement: false });
const ACK = entry("acknowledgment", { line: "いいですね！", build_hint: null });
const ENGLISH = entry("english", { text: "I watched a movie", is_direct: false });
const FEEDBACK = entry("feedback", {
  intent: "久しぶりに映画を見た",
  feedback: {
    first_line: "意図は伝わっています。元のままでも通じます",
    fixes: [
      {
        number: 1,
        original: "I",
        replacement: "Actually, I",
        reason: "Actually, で始めると話を続ける感じが出る",
        tag: "improvement",
      },
    ],
    sentence: "I watched a movie",
    template: "(①) ____ watched a movie",
    request_line: "(①) を埋めて、文全体をもう一度送ってください",
    readings_noted: [],
  },
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

const opening = sessionView({
  stage: "opening",
  version: 0,
  allowed_actions: ["open", "end"],
});
const intent = sessionView({
  stage: "intent",
  version: 1,
  entries: [OPENER],
  allowed_actions: ["intent", "english_direct", "end"],
});
const english = sessionView({
  stage: "english",
  version: 2,
  entries: [OPENER, INTENT, ACK],
  allowed_actions: ["english", "hint", "show_answer", "end"],
});
const retry = sessionView({
  stage: "retry",
  version: 3,
  entries: [OPENER, INTENT, ACK, ENGLISH, FEEDBACK],
  allowed_actions: ["retry", "show_answer", "skip", "end"],
});
const partnerTurn = sessionView({
  stage: "partner_turn",
  version: 4,
  finished_replies: 1,
  entries: [
    OPENER,
    INTENT,
    ACK,
    ENGLISH,
    entry("turn_done", { english: "I watched a movie", end: "no_fix_needed" }),
  ],
  allowed_actions: ["partner_reply", "end"],
});
const turnTwo = sessionView({
  stage: "intent",
  version: 5,
  turn_index: 2,
  finished_replies: 1,
  entries: [...partnerTurn.entries, SHARE],
  allowed_actions: ["intent", "end"],
});

function problem(status: number, code: string): ProblemDetails {
  return {
    type: "about:blank",
    title: "Error",
    status,
    detail: `${code} detail`,
    code,
    request_id: "req-42",
  };
}

function answer(status: number, code: string) {
  return HttpResponse.json<ProblemDetails>(problem(status, code), { status });
}

function pane(name: "会話" | "コーチ") {
  return within(screen.getByRole("region", { name }));
}

async function sendEnglish(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByRole("textbox", { name: "あなたの英語" }), text);
  await user.keyboard("{Meta>}{Enter}{/Meta}");
}

/** Answer the first action with `first`, and every later one with `then`. */
function firstThen(
  first: () => Response,
  then: (body: ActionBody, current: SessionResponse) => SessionResponse | Response,
) {
  let calls = 0;
  return (body: ActionBody, current: SessionResponse) => {
    calls += 1;
    return calls === 1 ? first() : then(body, current);
  };
}

const MODEL_CODES = [
  { code: "model_timeout", status: 504, reason: "時間切れ" },
  { code: "model_rate_limited", status: 503, reason: "混み合っています" },
  { code: "model_unavailable", status: 502, reason: "接続できません" },
  {
    code: "model_output_invalid",
    status: 502,
    reason: "返事の形式が正しくありませんでした",
  },
];

describe("ConversationScreen model failure banners (REQ-004)", () => {
  it.each(MODEL_CODES)(
    "shows $code as 「コーチの返事を受け取れませんでした（$reason）。」 and もう一度 resends the action",
    async ({ code, status, reason }) => {
      const served = serveSession(
        english,
        firstThen(
          () => answer(status, code),
          () => retry,
        ),
      );
      const user = userEvent.setup();
      renderSession(english);

      await sendEnglish(user, "I watched a movie");

      const banner = await pane("コーチ").findByRole("alert");
      expect(banner).toHaveTextContent(
        `コーチの返事を受け取れませんでした（${reason}）。`,
      );
      expect(pane("会話").queryByRole("alert")).not.toBeInTheDocument();
      const field = screen.getByRole("textbox", { name: "あなたの英語" });
      expect(field).toHaveValue("I watched a movie");
      expect(field).toBeEnabled();
      expect(field).toHaveAttribute(
        "placeholder",
        "英語にしてみましょう（途中まででOK）",
      );

      await user.click(within(banner).getByRole("button", { name: "もう一度" }));

      expect(
        await screen.findByPlaceholderText("穴を埋めた英文全体を"),
      ).toBeInTheDocument();
      expect(served.bodies).toEqual([
        { action: "english", text: "I watched a movie", version: 2 },
        { action: "english", text: "I watched a movie", version: 2 },
      ]);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );

  it("shows a failed auto-sent partner_reply on the left with もう一度 and never resends it by itself", async () => {
    const served = serveSession(
      partnerTurn,
      firstThen(
        () => answer(503, "model_rate_limited"),
        () => turnTwo,
      ),
    );
    const user = userEvent.setup();
    const { queryClient } = renderSession(partnerTurn, { strict: true });

    const banner = await pane("会話").findByRole("alert");
    expect(banner).toHaveTextContent(
      "Partner の返事を受け取れませんでした（混み合っています）。",
    );
    expect(screen.getByText("👉 次: Partner の返事を待っています")).toBeInTheDocument();
    await act(() =>
      queryClient.invalidateQueries({
        queryKey: sessionQueryOptions(SESSION_ID).queryKey,
      }),
    );
    expect(served.bodies).toEqual([{ action: "partner_reply", version: 4 }]);
    expect(pane("会話").getAllByRole("button", { name: "もう一度" })).toHaveLength(1);

    await user.click(within(banner).getByRole("button", { name: "もう一度" }));

    expect(await pane("会話").findByText(SHARE.payload.text)).toBeInTheDocument();
    expect(served.bodies).toEqual([
      { action: "partner_reply", version: 4 },
      { action: "partner_reply", version: 4 },
    ]);
  });

  it("shows a failed restate on the left, leaves the composer's draft alone, and もう一度 resends it", async () => {
    // No control sends restate before #23; the view a reload reads carries it.
    const view: SessionResponse = {
      ...intent,
      last_submission: {
        action: "restate",
        input: { mode: "shorter" },
        state: "failed",
        failure_code: "model_timeout",
      },
    };
    const served = serveSession(view, () => ({ ...intent, version: 2 }));
    const user = userEvent.setup();
    renderSession(view);
    const field = screen.getByRole("textbox", { name: "あなたの日本語" });
    expect(field).toHaveValue("");
    await user.type(field, "久しぶり");

    const banner = pane("会話").getByRole("alert");
    expect(banner).toHaveTextContent(
      "Partner の返事を受け取れませんでした（時間切れ）。",
    );
    expect(pane("コーチ").queryByRole("alert")).not.toBeInTheDocument();
    await user.click(within(banner).getByRole("button", { name: "もう一度" }));

    await waitFor(() =>
      expect(served.bodies).toEqual([
        { action: "restate", mode: "shorter", version: 1 },
      ]),
    );
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: "あなたの日本語" })).toHaveValue(
      "久しぶり",
    );
  });

  it("shows a failure that names no model reason without one", async () => {
    serveSession(english, () => answer(500, "internal_error"));
    const user = userEvent.setup();
    renderSession(english);

    await sendEnglish(user, "I watched a movie");

    expect(await pane("コーチ").findByRole("alert")).toHaveTextContent(
      "コーチの返事を受け取れませんでした。",
    );
  });
});

describe("ConversationScreen stale state (REQ-005)", () => {
  it.each(["stale_session", "action_in_progress", "action_not_allowed"])(
    "after 409 %s reads the session again and shows the stale banner over the new state, keeping the text",
    async (code) => {
      const moved = { ...retry, version: 8 };
      const served = serveSession({ ...retry, version: 7 }, () => {
        served.set(moved);
        return answer(409, code);
      });
      const user = userEvent.setup();
      renderSession({ ...retry, version: 7 });

      await user.type(
        screen.getByRole("textbox", { name: "あなたの英語" }),
        "Actually, I watched a movie",
      );
      await user.keyboard("{Meta>}{Enter}{/Meta}");

      const banner = await pane("コーチ").findByRole("alert");
      expect(banner).toHaveTextContent(STALE);
      expect(within(banner).queryByRole("button")).not.toBeInTheDocument();
      const scroll = screen.getByTestId("coach-scroll");
      expect(scroll.firstElementChild).toBe(banner);
      expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
        "Actually, I watched a movie",
      );

      await user.keyboard("{Meta>}{Enter}{/Meta}");
      await waitFor(() => expect(served.bodies).toHaveLength(2));
      expect(served.bodies[1]).toEqual({
        action: "retry",
        text: "Actually, I watched a movie",
        version: 8,
      });
    },
  );

  it("after 409 session_ended reads the session again and shows no banner", async () => {
    const ended = sessionView({
      ...english,
      status: "ended",
      stage: "ended",
      version: 3,
      allowed_actions: [],
    });
    const served = serveSession(english, () => {
      served.set(ended);
      return answer(409, "session_ended");
    });
    const user = userEvent.setup();
    renderSession(english);

    await sendEnglish(user, "I watched a movie");

    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ignores 409 action_cancelled silently", async () => {
    serveSession(english, () => answer(409, "action_cancelled"));
    const user = userEvent.setup();
    renderSession(english);

    await sendEnglish(user, "I watched a movie");

    const field = screen.getByRole("textbox", { name: "あなたの英語" });
    await waitFor(() => expect(field).toBeEnabled());
    expect(field).toHaveValue("I watched a movie");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("ConversationScreen with no response (REQ-006)", () => {
  it("shows the server-unreachable banner, keeps the text, and 再試行 resends the same request", async () => {
    const served = serveSession(
      english,
      firstThen(
        () => HttpResponse.error(),
        () => retry,
      ),
    );
    const user = userEvent.setup();
    renderSession(english);

    await sendEnglish(user, "I watched a movie");

    const banner = (await screen.findByText(UNREACHABLE)).closest(
      '[role="alert"]',
    ) as HTMLElement;
    expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
      "I watched a movie",
    );
    expect(pane("コーチ").queryByRole("alert")).not.toBeInTheDocument();

    await user.click(within(banner).getByRole("button", { name: "再試行" }));

    expect(
      await screen.findByPlaceholderText("穴を埋めた英文全体を"),
    ).toBeInTheDocument();
    expect(served.bodies).toEqual([
      { action: "english", text: "I watched a movie", version: 2 },
      { action: "english", text: "I watched a movie", version: 2 },
    ]);
    expect(screen.queryByText(UNREACHABLE)).not.toBeInTheDocument();
  });
});

describe("ConversationScreen auto-sent action with no response (REQ-006)", () => {
  it("offers only the layout's 再試行 for an auto-sent partner_reply, no 「もう一度」 in the pane", async () => {
    const served = serveSession(
      partnerTurn,
      firstThen(
        () => HttpResponse.error(),
        () => turnTwo,
      ),
    );
    const user = userEvent.setup();
    renderSession(partnerTurn);

    const banner = (await screen.findByText(UNREACHABLE)).closest(
      '[role="alert"]',
    ) as HTMLElement;
    expect(
      pane("会話").queryByRole("button", { name: "もう一度" }),
    ).not.toBeInTheDocument();

    await user.click(within(banner).getByRole("button", { name: "再試行" }));

    expect(await pane("会話").findByText(SHARE.payload.text)).toBeInTheDocument();
    expect(served.bodies).toEqual([
      { action: "partner_reply", version: 4 },
      { action: "partner_reply", version: 4 },
    ]);
  });
});

describe("ConversationScreen loaded with a last submission (REQ-007)", () => {
  function withLast(
    view: SessionResponse,
    action: Action,
    state: "failed" | "interrupted",
    input: Record<string, string>,
    failure_code: string | null,
  ): SessionResponse {
    return {
      ...view,
      last_submission: {
        action,
        input,
        state,
        failure_code,
      } as SessionResponse["last_submission"],
    };
  }

  it("pre-fills the composer with a failed submission's text and shows its code's banner", async () => {
    const view = withLast(
      english,
      "english",
      "failed",
      { text: "I watched a movie" },
      "model_timeout",
    );
    const served = serveSession(view, () => retry);
    const user = userEvent.setup();
    renderSession(view);

    const banner = pane("コーチ").getByRole("alert");
    expect(banner).toHaveTextContent(
      "コーチの返事を受け取れませんでした（時間切れ）。",
    );
    expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
      "I watched a movie",
    );

    await user.click(within(banner).getByRole("button", { name: "もう一度" }));

    await screen.findByPlaceholderText("穴を埋めた英文全体を");
    expect(served.bodies).toEqual([
      { action: "english", text: "I watched a movie", version: 2 },
    ]);
  });

  it("restores interrupted direct English in English mode and resends english_direct", async () => {
    const view = withLast(
      intent,
      "english_direct",
      "interrupted",
      { text: "I watched a movie" },
      "interrupted",
    );
    const served = serveSession(view, () => retry);
    const user = userEvent.setup();
    renderSession(view);

    const field = screen.getByRole("textbox", { name: "あなたの英語" });
    expect(field).toHaveAttribute("lang", "en");
    expect(field).toHaveValue("I watched a movie");
    expect(
      screen.queryByRole("textbox", { name: "あなたの日本語" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /送信/ }));

    await screen.findByPlaceholderText("穴を埋めた英文全体を");
    expect(served.bodies).toEqual([
      { action: "english_direct", text: "I watched a movie", version: 1 },
    ]);
  });

  it.each(["failed", "pending"] as const)(
    "restores a %s direct-English submission with the English field",
    (state) => {
      const view: SessionResponse = {
        ...intent,
        last_submission: {
          action: "english_direct",
          input: { text: "I watched a movie" },
          state,
          failure_code: state === "failed" ? "model_timeout" : null,
        },
      };
      serveSession(view);
      renderSession(view);
      expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
        "I watched a movie",
      );
      expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveAttribute(
        "lang",
        "en",
      );
    },
  );

  it("pre-fills the composer with an interrupted intent and offers 送信 with no banner", async () => {
    const view = withLast(
      intent,
      "intent",
      "interrupted",
      { text: "久しぶりに映画を見た" },
      "interrupted",
    );
    const served = serveSession(view, () => english);
    const user = userEvent.setup();
    renderSession(view);

    const field = screen.getByRole("textbox", { name: "あなたの日本語" });
    expect(field).toHaveValue("久しぶりに映画を見た");
    expect(field).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "👉 次: 返したいことを日本語で送ってください（英語で返してもOK）",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /送信/ }));

    await screen.findByRole("textbox", { name: "あなたの英語" });
    expect(served.bodies).toEqual([
      { action: "intent", text: "久しぶりに映画を見た", version: 1 },
    ]);
  });

  it("keeps waiting focus in the selected Coach pane on mobile during an automatic Partner reply", async () => {
    stubMatchMedia(false);
    const hold = deferred();
    const served = serveSession(partnerTurn, async () => {
      await hold.promise;
      return turnTwo;
    });
    renderSession(partnerTurn);
    await waitFor(() =>
      expect(served.bodies.map((body) => body.action)).toEqual(["partner_reply"]),
    );
    expect(screen.getByRole("tab", { name: "コーチ" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const heading = within(screen.getByRole("tabpanel", { name: "コーチ" })).getByRole(
      "heading",
      { level: 2 },
    );
    expect(heading).toBeVisible();
    expect(heading).toHaveFocus();
    hold.release();
    await screen.findByRole("textbox", { name: "あなたの日本語" });
  });

  it.each([
    { action: "open" as const, view: opening, result: intent },
    { action: "partner_reply" as const, view: partnerTurn, result: turnTwo },
  ])(
    "offers もう一度 on the left for an interrupted $action, never sending it by itself",
    async ({ action, view, result }) => {
      const loaded = withLast(view, action, "interrupted", {}, "interrupted");
      const served = serveSession(loaded, () => result);
      const user = userEvent.setup();
      renderSession(loaded, { strict: true });

      const again = pane("会話").getByRole("button", { name: "もう一度" });
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(served.bodies).toEqual([]);

      await user.click(again);

      await waitFor(() =>
        expect(served.bodies).toEqual([{ action, version: view.version }]),
      );
      expect(
        await pane("会話").findByText(
          (result.entries.at(-1) as typeof OPENER).payload.text,
        ),
      ).toBeInTheDocument();
    },
  );

  it("shows a failed open's banner on the left with もう一度", async () => {
    const loaded = withLast(opening, "open", "failed", {}, "model_unavailable");
    serveSession(loaded, () => intent);
    renderSession(loaded);

    const banner = pane("会話").getByRole("alert");
    expect(banner).toHaveTextContent(
      "Partner の返事を受け取れませんでした（接続できません）。",
    );
    expect(pane("会話").getAllByRole("button", { name: "もう一度" })).toHaveLength(1);
  });
});

describe("ConversationScreen retry waiting focus", () => {
  it("returns a rejected hint to its gap field", async () => {
    serveSession(english, () => answer(422, "invalid_input"));
    const user = userEvent.setup();
    renderSession(english);
    await user.click(screen.getByRole("button", { name: "ヒント" }));
    const gap = screen.getByRole("textbox", { name: "分からないところ" });
    await user.type(gap, "久しぶり");
    await user.keyboard("{Enter}");
    await screen.findByRole("alert");
    await waitFor(() => expect(gap).toHaveFocus());
  });

  it("keeps a mounted past-turn heading focused while retrying", async () => {
    const hold = deferred();
    let calls = 0;
    serveSession(turnTwo, async () => {
      calls += 1;
      if (calls === 1) return answer(504, "model_timeout");
      await hold.promise;
      return { ...turnTwo, version: 6 };
    });
    const user = userEvent.setup();
    renderSession(turnTwo);
    await user.type(
      screen.getByRole("textbox", { name: "あなたの日本語" }),
      "猫が好き",
    );
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await pane("コーチ").findByRole("alert");
    await user.click(pane("会話").getByRole("button", { name: "I watched a movie" }));
    const alert = pane("コーチ").getByRole("alert");
    await user.click(within(alert).getByRole("button", { name: "もう一度" }));
    expect(pane("コーチ").getByRole("heading", { level: 2 })).toHaveFocus();
    hold.release();
    await waitFor(() => expect(alert).not.toBeInTheDocument());
  });

  it.each([
    {
      name: "coach",
      initial: english,
      result: retry,
      paneName: "コーチ" as const,
      start: (user: ReturnType<typeof userEvent.setup>) =>
        sendEnglish(user, "I watched a movie"),
    },
    {
      name: "partner",
      initial: partnerTurn,
      result: turnTwo,
      paneName: "会話" as const,
      start: async () => {},
    },
  ])(
    "keeps focus in the $name pane while a retried request runs",
    async ({ initial, result, paneName, start }) => {
      const hold = deferred();
      let calls = 0;
      serveSession(initial, async () => {
        calls += 1;
        if (calls === 1) return answer(504, "model_timeout");
        await hold.promise;
        return result;
      });
      const user = userEvent.setup();
      renderSession(initial);
      await start(user);
      const banner = await pane(paneName).findByRole("alert");
      await user.click(within(banner).getByRole("button", { name: "もう一度" }));
      const heading = pane(paneName).getByRole("heading", { level: 2 });
      expect(heading).toHaveFocus();
      expect(document.activeElement).not.toBe(document.body);
      hold.release();
      await waitFor(() => expect(screen.getByRole("textbox")).toBeEnabled());
      expect(screen.getByRole("textbox")).toHaveFocus();
    },
  );
});
