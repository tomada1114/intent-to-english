import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type {
  ProblemDetails,
  SessionResponse,
} from "../../../src/api/generated/types.gen";
import { sessionQueryOptions } from "../../../src/features/conversation";
import {
  entry,
  renderSession,
  SESSION_ID,
  serveSession,
  sessionView,
} from "../../msw/helpers";

const opener = entry("partner_line", {
  text: "What are you studying these days?",
  has_question: true,
  line_kind: "opener",
  restate_mode: null,
});
const intent = entry("intent", { text: "英語を勉強している", is_replacement: false });
const ack = entry("acknowledgment", { line: "いいですね！", build_hint: null });
const english = sessionView({
  stage: "english",
  version: 2,
  entries: [opener, intent, ack],
  allowed_actions: [
    "english",
    "hint",
    "show_answer",
    "rewrite_intent",
    "restate",
    "ask",
    "end",
  ],
});
const feedback = entry("feedback", {
  intent: intent.payload.text,
  feedback: {
    first_line: "元のままでも通じます",
    fixes: [
      {
        number: 1,
        original: "I",
        replacement: "Actually, I",
        reason: "元のままでも通じる",
        tag: "improvement",
      },
    ],
    sentence: "I study English.",
    template: "(①) ____ study English.",
    request_line: "文全体を送ってください",
    readings_noted: [],
  },
});
const done = entry("turn_done", {
  english: "Actually, I study English.",
  end: "accepted",
});
const checkIn = sessionView({
  stage: "check_in",
  version: 4,
  entries: [opener, intent, ack, feedback, done],
  allowed_actions: ["practice_again", "ask", "partner_reply", "end"],
});

async function press(user: ReturnType<typeof userEvent.setup>, name: string | RegExp) {
  const button = screen.getByRole("button", { name });
  act(() => button.focus());
  await user.keyboard("{Enter}");
}

describe("in-session restate control", () => {
  it.each(["shorter", "simpler"] as const)(
    "sends %s from the keyboard while preserving the English draft",
    async (mode) => {
      const label = mode === "shorter" ? "短く" : "簡単に";
      const served = serveSession(english, () =>
        sessionView({
          ...english,
          version: 3,
          entries: [
            ...english.entries,
            entry("partner_line", {
              text: "What do you study?",
              has_question: true,
              line_kind: "restatement",
              restate_mode: mode,
            }),
          ],
        }),
      );
      const user = userEvent.setup();
      renderSession(english);
      await user.type(screen.getByRole("textbox", { name: "あなたの英語" }), "I study");
      await press(user, label);
      await screen.findByText(`言い換え（${label}）`);
      expect(served.bodies).toEqual([{ action: "restate", mode, version: 2 }]);
      expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
        "I study",
      );
    },
  );
});

describe("in-session rewrite control", () => {
  it("closes rewrite mode when another tab finishes the turn", async () => {
    const served = serveSession(english);
    const { queryClient } = renderSession(english);
    const user = userEvent.setup();
    await press(user, "日本語を書き直す");
    await user.type(screen.getByRole("textbox", { name: "あなたの日本語" }), "別の文");
    served.set(checkIn);
    await act(() =>
      queryClient.invalidateQueries({
        queryKey: sessionQueryOptions(SESSION_ID).queryKey,
      }),
    );
    expect(
      screen.queryByRole("textbox", { name: "あなたの日本語" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "もう一度練習" })).toBeEnabled();
  });

  it("keeps both earlier rewrites collapsed and exposes only the latest rewrite control", async () => {
    const twice = sessionView({
      ...english,
      entries: [
        ...english.entries,
        entry("intent", { text: "料理を勉強している", is_replacement: true }),
        ack,
        entry("intent", { text: "最近は写真を勉強している", is_replacement: true }),
        ack,
      ],
    });
    serveSession(twice);
    const user = userEvent.setup();
    renderSession(twice);
    const disclosures = screen.getAllByText("書き直す前のやりとり");
    expect(disclosures).toHaveLength(2);
    expect(screen.getByText(intent.payload.text)).not.toBeVisible();
    expect(screen.getByText("料理を勉強している")).not.toBeVisible();
    expect(screen.getByText("最近は写真を勉強している")).toBeVisible();
    expect(screen.getAllByRole("button", { name: "日本語を書き直す" })).toHaveLength(1);
    await press(user, "日本語を書き直す");
    expect(screen.getByRole("textbox", { name: "あなたの日本語" })).toHaveValue(
      "最近は写真を勉強している",
    );
  });

  it("rejects blank and over-1,000 rewrites and counts code points", async () => {
    serveSession(english);
    const user = userEvent.setup();
    renderSession(english);
    await press(user, "日本語を書き直す");
    const field = screen.getByRole("textbox", { name: "あなたの日本語" });
    const send = screen.getByRole("button", { name: /送信/ });
    await user.clear(field);
    await user.paste("  ");
    expect(send).toBeDisabled();
    await user.clear(field);
    await user.paste("🐈".repeat(1000));
    expect(send).toBeEnabled();
    await user.paste("あ");
    expect(send).toBeDisabled();
  });

  it("keeps an English draft through cancelling and sending a Japanese rewrite", async () => {
    const next = sessionView({
      ...english,
      version: 3,
      entries: [
        ...english.entries,
        entry("intent", { text: "最近は料理を勉強している", is_replacement: true }),
        ack,
      ],
    });
    const served = serveSession(english, () => next);
    const user = userEvent.setup();
    renderSession(english);
    await user.type(screen.getByRole("textbox", { name: "あなたの英語" }), "I study");
    await press(user, "日本語を書き直す");
    expect(screen.getByRole("textbox", { name: "あなたの日本語" })).toHaveValue(
      intent.payload.text,
    );
    await user.click(screen.getByRole("button", { name: "やめる" }));
    expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
      "I study",
    );
    await press(user, "日本語を書き直す");
    const field = screen.getByRole("textbox", { name: "あなたの日本語" });
    expect(field).toHaveAttribute("lang", "ja");
    await user.clear(field);
    await user.type(field, "最近は料理を勉強している");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await screen.findByText("最近は料理を勉強している");
    expect(served.bodies).toEqual([
      { action: "rewrite_intent", text: "最近は料理を勉強している", version: 2 },
    ]);
    expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
      "I study",
    );
    const details = screen.getByText("書き直す前のやりとり").closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByText(intent.payload.text)).not.toBeVisible();
  });
});

describe("in-session Coach question", () => {
  it("returns to the first control when check-in has no main composer", async () => {
    const served = serveSession(checkIn, () =>
      sessionView({
        ...checkIn,
        version: 5,
        entries: [
          ...checkIn.entries,
          entry("coach_answer", { text: "その通りです。" }),
        ],
      }),
    );
    const user = userEvent.setup();
    renderSession(checkIn);
    await press(user, /コーチに質問/);
    await user.type(screen.getByRole("textbox", { name: "質問" }), "これでいい？");
    await user.keyboard("{Enter}");
    await screen.findByText("その通りです。");
    expect(served.bodies).toEqual([
      { action: "ask", text: "これでいい？", version: 4 },
    ]);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "続ける" })).toHaveFocus(),
    );
  });

  it("keeps the question on Esc, answers it without advancing, and returns focus to the composer", async () => {
    const served = serveSession(english, () =>
      sessionView({
        ...english,
        version: 3,
        entries: [
          ...english.entries,
          entry("question", { text: "these days は？" }),
          entry("coach_answer", { text: "最近という意味です。" }),
        ],
      }),
    );
    const user = userEvent.setup();
    renderSession(english);
    const composer = screen.getByRole("textbox", { name: "あなたの英語" });
    await user.type(composer, "I study");
    await press(user, /コーチに質問/);
    await user.type(screen.getByRole("textbox", { name: "質問" }), "these days は？");
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: /コーチに質問/ })).toHaveFocus();
    expect(screen.queryByRole("textbox", { name: "質問" })).not.toBeInTheDocument();
    await press(user, /コーチに質問/);
    expect(screen.getByRole("textbox", { name: "質問" })).toHaveValue(
      "these days は？",
    );
    await user.keyboard("{Enter}");
    await screen.findByText("最近という意味です。");
    expect(served.bodies).toEqual([
      { action: "ask", text: "these days は？", version: 2 },
    ]);
    expect(composer).toHaveValue("I study");
    await waitFor(() => expect(composer).toHaveFocus());
  });

  it("counts code points from 450 and rejects only blank or over-500 questions", async () => {
    serveSession(english);
    const user = userEvent.setup();
    renderSession(english);
    await press(user, /コーチに質問/);
    expect(screen.getByRole("textbox", { name: "質問" })).toHaveFocus();
    const send = screen.getByRole("button", { name: "質問する" });
    expect(send).toBeDisabled();
    await user.paste(" ");
    expect(send).toBeDisabled();
    await user.clear(screen.getByRole("textbox", { name: "質問" }));
    await user.paste("あ");
    expect(send).toBeEnabled();
    await user.clear(screen.getByRole("textbox", { name: "質問" }));
    await user.paste("🐈".repeat(450));
    expect(screen.getByText("450 / 500")).toBeInTheDocument();
    expect(send).toBeEnabled();
    await user.paste("あ".repeat(50));
    expect(send).toBeEnabled();
    await user.paste("あ");
    expect(send).toBeDisabled();
    expect(
      screen.getByText("500字以内にしてください（いま501字）"),
    ).toBeInTheDocument();
  });

  it("keeps a 422 beside the question, with its text intact", async () => {
    serveSession(english, () =>
      HttpResponse.json<ProblemDetails>(
        {
          type: "about:blank",
          status: 422,
          title: "Invalid input",
          code: "invalid_input",
          detail: "質問を確認してください。",
          request_id: "question-request",
        },
        { status: 422 },
      ),
    );
    const user = userEvent.setup();
    renderSession(english);
    await press(user, /コーチに質問/);
    await user.type(screen.getByRole("textbox", { name: "質問" }), "どうして");
    await user.click(screen.getByRole("button", { name: "質問する" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "質問を確認してください。",
    );
    expect(screen.getByRole("textbox", { name: "質問" })).toHaveValue("どうして");
    expect(screen.getByRole("textbox", { name: "質問" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByRole("textbox", { name: "質問" })).toHaveFocus();
  });
});

describe("in-session practice again", () => {
  it("restores the current controls when another tab moves beyond practice", async () => {
    const nextTurn = sessionView({
      ...checkIn,
      stage: "intent",
      turn_index: 2,
      version: 5,
      entries: [...checkIn.entries, entry("partner_line", opener.payload, 2)],
      allowed_actions: ["intent", "english_direct", "practice_again", "ask", "end"],
    });
    const served = serveSession(nextTurn);
    const { queryClient } = renderSession(nextTurn);
    const user = userEvent.setup();
    await press(user, "もう一度練習");
    await user.type(
      screen.getByRole("textbox", { name: "もう一度練習" }),
      "A practice draft",
    );
    served.set(
      sessionView({
        ...english,
        turn_index: 2,
        version: 6,
        entries: [
          ...nextTurn.entries,
          entry("intent", intent.payload, 2),
          entry("acknowledgment", ack.payload, 2),
        ],
      }),
    );
    await act(() =>
      queryClient.invalidateQueries({
        queryKey: sessionQueryOptions(SESSION_ID).queryKey,
      }),
    );
    expect(await screen.findByRole("textbox", { name: "あなたの英語" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "ヒント" }));
    expect(
      screen.getByRole("textbox", { name: "分からないところ" }),
    ).toBeInTheDocument();
  });

  it("restores the new turn's Japanese draft after practicing the previous turn", async () => {
    const nextTurn = sessionView({
      ...checkIn,
      stage: "intent",
      turn_index: 2,
      version: 5,
      entries: [
        ...checkIn.entries,
        entry("partner_line", { ...opener.payload, text: "What do you like?" }, 2),
      ],
      allowed_actions: ["intent", "english_direct", "practice_again", "ask", "end"],
    });
    const served = serveSession(nextTurn, () =>
      sessionView({
        ...nextTurn,
        version: 6,
        entries: [
          ...nextTurn.entries,
          entry(
            "practice",
            { sentence: "Actually, I study English.", turn_index: 1 },
            1,
          ),
          entry(
            "practice_result",
            {
              turn_index: 1,
              result: { line: "もう一度言えました。", readings_noted: [] },
            },
            1,
          ),
        ],
      }),
    );
    const user = userEvent.setup();
    renderSession(nextTurn);
    await user.type(
      screen.getByRole("textbox", { name: "あなたの日本語" }),
      "猫が好き",
    );
    await press(user, "もう一度練習");
    expect(screen.getByText("(①) ____ study English.")).toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: "もう一度練習" }),
      "Actually, I study English.",
    );
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await screen.findByText("もう一度言えました。");
    expect(served.bodies).toEqual([
      { action: "practice_again", text: "Actually, I study English.", version: 5 },
    ]);
    expect(screen.getByRole("textbox", { name: "あなたの日本語" })).toHaveValue(
      "猫が好き",
    );
  });

  it("shows the last template, sends one practice, and returns to check-in controls", async () => {
    const served = serveSession(checkIn, () =>
      sessionView({
        ...checkIn,
        version: 5,
        entries: [
          ...checkIn.entries,
          entry("practice", { sentence: "Actually, I study English.", turn_index: 1 }),
          entry("practice_result", {
            turn_index: 1,
            result: { line: "伝わりました。", readings_noted: [] },
          }),
        ],
      }),
    );
    const user = userEvent.setup();
    renderSession(checkIn);
    await press(user, "もう一度練習");
    const field = screen.getByRole("textbox", { name: "もう一度練習" });
    await user.type(field, "Actually, I study English.");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await screen.findByText("伝わりました。");
    expect(served.bodies).toEqual([
      { action: "practice_again", text: "Actually, I study English.", version: 4 },
    ]);
    expect(
      screen.queryByRole("textbox", { name: "もう一度練習" }),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("group", { name: "操作" })).getByRole("button", {
        name: "続ける",
      }),
    ).toBeInTheDocument();
  });
});

it("keeps the question draft and disclosure through a visit to a past turn", async () => {
  const view = sessionView({
    ...english,
    turn_index: 2,
    version: 6,
    entries: [
      ...checkIn.entries,
      entry("partner_line", opener.payload, 2),
      entry("intent", intent.payload, 2),
      entry("acknowledgment", ack.payload, 2),
    ],
  });
  serveSession(view);
  const user = userEvent.setup();
  renderSession(view);
  await press(user, /コーチに質問/);
  await user.type(screen.getByRole("textbox", { name: "質問" }), "these days は？");
  await user.click(screen.getByRole("button", { name: "Actually, I study English." }));
  expect(screen.queryByRole("textbox", { name: "質問" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "今のターンに戻る" }));
  expect(screen.getByRole("button", { name: /コーチに質問/ })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  expect(screen.getByRole("textbox", { name: "質問" })).toHaveValue("these days は？");
});

it("hides every in-session control when its action is absent", () => {
  const view: SessionResponse = { ...english, allowed_actions: ["english", "end"] };
  serveSession(view);
  renderSession(view);
  for (const name of [
    "短く",
    "簡単に",
    "日本語を書き直す",
    "もう一度練習",
    /コーチに質問/,
  ]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
});

it.each(
  (["ask", "rewrite_intent", "practice_again"] as const).flatMap((action) =>
    (["pending", "failed", "interrupted"] as const).map((state) => ({ action, state })),
  ),
)(
  "restores a newly observed $action draft in $state state",
  async ({ action, state }) => {
    const view = action === "practice_again" ? checkIn : english;
    const served = serveSession(view);
    const { queryClient } = renderSession(view);
    const user = userEvent.setup();
    if (action !== "practice_again")
      await user.type(
        screen.getByRole("textbox", { name: "あなたの英語" }),
        "A main draft",
      );
    served.set({
      ...view,
      last_submission: {
        action,
        input: { text: "Stored side draft" },
        state,
        failure_code:
          state === "pending"
            ? null
            : state === "interrupted"
              ? "interrupted"
              : "model_timeout",
      },
    });
    await act(() =>
      queryClient.invalidateQueries({
        queryKey: sessionQueryOptions(SESSION_ID).queryKey,
      }),
    );
    const label =
      action === "ask"
        ? "質問"
        : action === "rewrite_intent"
          ? "あなたの日本語"
          : "もう一度練習";
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: label })).toHaveValue(
        "Stored side draft",
      ),
    );
    if (action === "ask")
      expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
        "A main draft",
      );
    if (action === "rewrite_intent" && state !== "pending") {
      await user.click(screen.getByRole("button", { name: "やめる" }));
      expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
        "A main draft",
      );
    }
  },
);

it.each(
  (["ask", "rewrite_intent", "practice_again"] as const).flatMap((action) =>
    [false, true].map((edited) => ({ action, edited })),
  ),
)(
  "settles a confirmed lost $action while preserving an edited draft: $edited",
  async ({ action, edited }) => {
    const view = action === "practice_again" ? checkIn : english;
    const served = serveSession(view, () => HttpResponse.error());
    const { queryClient } = renderSession(view);
    const user = userEvent.setup();
    const control =
      action === "ask"
        ? /コーチに質問/
        : action === "rewrite_intent"
          ? "日本語を書き直す"
          : "もう一度練習";
    const label =
      action === "ask"
        ? "質問"
        : action === "rewrite_intent"
          ? "あなたの日本語"
          : "もう一度練習";
    await press(user, control);
    const field = screen.getByRole("textbox", { name: label });
    await user.clear(field);
    await user.type(field, "  Original side  ");
    await user.click(
      screen.getByRole("button", { name: action === "ask" ? "質問する" : /送信/ }),
    );
    await screen.findByText(
      "アプリのサーバーに接続できません。起動しているか確認してください。",
    );
    if (edited) {
      await user.clear(field);
      await user.type(field, "Original side");
    }
    served.set({
      ...view,
      last_submission: {
        action,
        input: { text: "Original side" },
        state: "pending",
        failure_code: null,
      },
    });
    await act(() =>
      queryClient.invalidateQueries({
        queryKey: sessionQueryOptions(SESSION_ID).queryKey,
      }),
    );
    await waitFor(() => expect(field).toBeDisabled());
    const recorded =
      action === "ask"
        ? [
            entry("question", { text: "Original side" }),
            entry("coach_answer", { text: "確認できました。" }),
          ]
        : action === "rewrite_intent"
          ? [
              entry("intent", { text: "Original side", is_replacement: true }),
              entry("acknowledgment", { line: "確認できました。", build_hint: null }),
            ]
          : [
              entry("practice", { sentence: "Original side", turn_index: 1 }),
              entry("practice_result", {
                turn_index: 1,
                result: { line: "確認できました。", readings_noted: [] },
              }),
            ];
    served.set(
      sessionView({
        ...view,
        version: view.version + 1,
        entries: [...view.entries, ...recorded],
      }),
    );
    await act(() =>
      queryClient.invalidateQueries({
        queryKey: sessionQueryOptions(SESSION_ID).queryKey,
      }),
    );
    if (edited) {
      await waitFor(() => expect(field).toBeEnabled());
      expect(field).toHaveValue("Original side");
    } else {
      await waitFor(() =>
        expect(screen.queryByRole("textbox", { name: label })).not.toBeInTheDocument(),
      );
    }
  },
);

it.each(["ask", "rewrite_intent", "practice_again"] as const)(
  "preserves a newer local %s draft when another submission is observed",
  async (action) => {
    const view = action === "practice_again" ? checkIn : english;
    const served = serveSession(view);
    const { queryClient } = renderSession(view);
    const user = userEvent.setup();
    const control =
      action === "ask"
        ? /コーチに質問/
        : action === "rewrite_intent"
          ? "日本語を書き直す"
          : "もう一度練習";
    const label =
      action === "ask"
        ? "質問"
        : action === "rewrite_intent"
          ? "あなたの日本語"
          : "もう一度練習";
    await press(user, control);
    const field = screen.getByRole("textbox", { name: label });
    await user.clear(field);
    await user.type(field, "A newer local draft");

    served.set({
      ...view,
      last_submission: {
        action,
        input: { text: "Another tab's draft" },
        state: "failed",
        failure_code: "model_timeout",
      },
    });
    await act(() =>
      queryClient.invalidateQueries({
        queryKey: sessionQueryOptions(SESSION_ID).queryKey,
      }),
    );
    expect(field).toHaveValue("A newer local draft");
  },
);

it.each(["ask", "rewrite_intent", "practice_again"] as const)(
  "keeps a newer side draft after retrying the earlier %s request",
  async (action) => {
    const view = action === "practice_again" ? checkIn : english;
    let first = true;
    serveSession(view, () => {
      if (first) {
        first = false;
        return HttpResponse.json<ProblemDetails>(
          {
            type: "about:blank",
            status: 503,
            title: "Model unavailable",
            code: "model_unavailable",
            detail: "Unavailable",
            request_id: "side-retry",
          },
          { status: 503 },
        );
      }
      return sessionView({
        ...view,
        version: view.version + 1,
        entries: [...view.entries, entry("coach_answer", { text: "受け取りました。" })],
      });
    });
    const user = userEvent.setup();
    renderSession(view);
    const control =
      action === "ask"
        ? /コーチに質問/
        : action === "rewrite_intent"
          ? "日本語を書き直す"
          : "もう一度練習";
    const label =
      action === "ask"
        ? "質問"
        : action === "rewrite_intent"
          ? "あなたの日本語"
          : "もう一度練習";
    await press(user, control);
    const field = screen.getByRole("textbox", { name: label });
    await user.clear(field);
    await user.type(field, "Original draft");
    await user.click(
      screen.getByRole("button", { name: action === "ask" ? "質問する" : /送信/ }),
    );
    await screen.findByRole("button", { name: "もう一度" });
    await user.clear(field);
    await user.type(field, "New draft");
    await user.click(screen.getByRole("button", { name: "もう一度" }));
    await screen.findByText("受け取りました。");
    expect(screen.getByRole("textbox", { name: label })).toHaveValue("New draft");
  },
);
