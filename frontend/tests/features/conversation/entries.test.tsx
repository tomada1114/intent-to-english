import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConversationTimeline, TurnTimeline } from "../../../src/features/conversation";
import { entry, sessionView } from "../../msw/helpers";

const feedback = {
  first_line: "意図は伝わっています。元のままでも通じます",
  fixes: [
    {
      number: 1,
      original: "I",
      replacement: "Actually, I",
      reason: "元のままでも通じる",
      tag: "improvement" as const,
    },
  ],
  sentence: "I watched a movie",
  template: "(①) ____ watched a movie",
  request_line: "(①) を埋めて、文全体をもう一度送ってください",
  readings_noted: [],
};

// Turn 1 holds every kind a turn can hold; turn 2 opens with a reply.
const { entries } = sessionView({
  entries: [
    entry("partner_line", {
      text: "Hey! How's it going?",
      has_question: true,
      line_kind: "opener",
      restate_mode: null,
    }),
    entry("partner_line", {
      text: "What's new?",
      has_question: true,
      line_kind: "restatement",
      restate_mode: "shorter",
    }),
    entry("partner_line", {
      text: "How are you doing?",
      has_question: true,
      line_kind: "restatement",
      restate_mode: "simpler",
    }),
    entry("intent", { text: "映画を見た", is_replacement: false }),
    entry("intent", { text: "久しぶりに映画を見た", is_replacement: true }),
    entry("acknowledgment", {
      line: "いいですね！",
      build_hint: "「久しぶりに」は言い換えると組み立てやすいです",
    }),
    entry("hint_request", { gap: "久しぶり", partial_english: "I watched" }),
    entry("gap_hint", { hint: "「久しぶり」の部分は kind of から始めてみてください" }),
    entry("english", { text: "I watched a movie", is_direct: false }),
    entry("reading_question", { word: "leave", readings: ["leave", "live"] }),
    entry("reading_choice", { word: "leave", chosen: "live" }),
    entry("feedback", { intent: "久しぶりに映画を見た", feedback }),
    entry("retry", { sentence: "I watched a film", submission_number: 1 }),
    entry("retry_result", {
      result: {
        blanks: [1],
        hint: "①がまだ違います。A で始まります",
        readings_noted: [],
      },
    }),
    entry("retry", { sentence: "Also I watched a movie", submission_number: 2 }),
    entry("retry_result", {
      result: {
        line: "①は Actually, I です",
        pieces: [{ number: 1, text: "Actually, I" }],
      },
    }),
    entry("answer", { example: "Actually, I watched a movie." }),
    entry("typed_copy", { text: "Actually, I watched a movie." }),
    entry("question", { text: "film と movie は違いますか" }),
    entry("coach_answer", { text: "会話ではどちらも使えます" }),
    entry("skip", {}),
    entry("turn_done", { english: "Actually, I watched a movie.", end: "accepted" }),
    entry("check_in", {}),
    entry("check_in_answer", { answer: "continue" }),
    entry("practice", { sentence: "Actually, I watched a movie", turn_index: 1 }),
    entry("practice_result", {
      result: { line: "いいですね！伝わります", readings_noted: [] },
      turn_index: 1,
    }),
    entry(
      "partner_line",
      {
        text: "I went for a long walk by the river today.",
        has_question: false,
        line_kind: "reply",
        restate_mode: null,
      },
      2,
    ),
    entry("intent", { text: "いいね", is_replacement: false }, 2),
    entry("english", { text: "Nice", is_direct: true }, 2),
    entry("turn_done", { english: "Nice", end: "no_fix_needed" }, 2),
    entry("check_in_answer", { answer: "end" }, 2),
  ],
});

/** The text of each top-level row of the named list; nested lists stay inside. */
function rows(name: string) {
  const list = screen.getByRole("list", { name });
  return Array.from(list.children, (row) => row.textContent);
}

describe("ConversationTimeline", () => {
  it("shows Partner lines and each turn's final English in order, restatements labelled", () => {
    render(<ConversationTimeline entries={entries} />);

    expect(rows("会話の流れ")).toEqual([
      "PartnerHey! How's it going?",
      "言い換え（短く）What's new?",
      "言い換え（簡単に）How are you doing?",
      "YouActually, I watched a movie.",
      "PartnerI went for a long walk by the river today.",
      "YouNice",
    ]);
    for (const text of [
      "Hey! How's it going?",
      "What's new?",
      "Actually, I watched a movie.",
    ]) {
      expect(screen.getByText(text)).toHaveAttribute("lang", "en");
    }
  });
});

describe("TurnTimeline", () => {
  it("renders every kind of the turn's entries in order without composer or controls", () => {
    render(<TurnTimeline timeline={entries} turn={1} />);

    expect(rows("ターン 1")).toEqual([
      "あなたの日本語映画を見た",
      "あなたの日本語久しぶりに映画を見た",
      "💡 いいですね！組み立てのヒント: 「久しぶりに」は言い換えると組み立てやすいです",
      "分からないところ久しぶり途中までの英語I watched",
      "💡 「久しぶり」の部分は kind of から始めてみてください",
      "あなたの英語I watched a movie",
      "💡 「leave」は leave と live のどちらのつもりですか",
      "live のつもり",
      expect.stringContaining("意図は伝わっています。元のままでも通じます"),
      "言い直しI watched a film",
      "💡 ①がまだ違います。A で始まります",
      "言い直しAlso I watched a movie",
      "💡 ①は Actually, I です① Actually, I",
      "完成例Actually, I watched a movie.",
      "あなたの英語Actually, I watched a movie.",
      "質問film と movie は違いますか",
      "💡 コーチ会話ではどちらも使えます",
      "スキップして会話に戻ります",
      "✓ 言い直しできました",
      "💡 ここで1往復です。続けますか？",
      "続ける",
      "もう一度練習Actually, I watched a movie",
      "✓ いいですね！伝わります",
    ]);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("Hey! How's it going?")).not.toBeInTheDocument();
    expect(screen.getByText("I watched a film")).toHaveAttribute("lang", "en");
  });

  it("labels questions and answers lighter than the turn's own blocks", () => {
    render(<TurnTimeline timeline={entries} turn={1} />);

    expect(screen.getByText("質問").closest("li")).toHaveClass("text-ink-muted");
    expect(screen.getByText("💡 コーチ").closest("li")).toHaveClass("text-ink-muted");
  });

  it("shows only a turn's own entries, with 終わる for an ending check-in answer", () => {
    render(<TurnTimeline timeline={entries} turn={2} />);

    expect(rows("ターン 2")).toEqual([
      "あなたの日本語いいね",
      "あなたの英語Nice",
      "終わる",
    ]);
  });
});
