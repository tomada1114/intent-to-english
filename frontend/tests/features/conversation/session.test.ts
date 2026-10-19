import { describe, expect, it } from "vitest";
import { announcementFor, circled } from "../../../src/features/conversation/session";
import { entry, sessionView } from "../../msw/helpers";

const { entries } = sessionView({
  entries: [
    entry("partner_line", {
      text: "Hey! How's it going?",
      has_question: true,
      line_kind: "opener",
      restate_mode: null,
    }),
    entry("intent", { text: "映画を見た", is_replacement: false }),
    entry("acknowledgment", { line: "いいですね！", build_hint: null }),
    entry("gap_hint", { hint: "kind of から始めてみてください" }),
    entry("reading_question", { word: "leave", readings: ["leave", "live"] }),
    entry("feedback", {
      intent: null,
      feedback: {
        first_line: "元のままでも通じます",
        fixes: [],
        sentence: null,
        template: null,
        request_line: null,
        readings_noted: [],
      },
    }),
    entry("retry_result", {
      result: { blanks: [2], hint: "②がまだ違います", readings_noted: [] },
    }),
    entry("practice_result", {
      result: { line: "いいですね！伝わります", readings_noted: [] },
      turn_index: 1,
    }),
    entry("answer", { example: "I had a relaxing day." }),
    entry("coach_answer", { text: "どちらも使えます" }),
    entry("turn_done", { english: "Hi", end: "no_fix_needed" }),
    entry("check_in", {}),
    entry("skip", {}),
  ],
});

describe("announcementFor", () => {
  it("announces Partner lines and each Coach block by its first line, nothing else", () => {
    expect(entries.map((item) => announcementFor(item, entries))).toEqual([
      "Partner: Hey! How's it going?",
      null,
      "コーチ: いいですね！",
      "コーチ: kind of から始めてみてください",
      "コーチ: 「leave」は leave と live のどちらのつもりですか",
      "コーチ: 元のままでも通じます",
      "コーチ: ②がまだ違います",
      "コーチ: いいですね！伝わります",
      "コーチ: I had a relaxing day.",
      "コーチ: どちらも使えます",
      null,
      "コーチ: ここで1往復です。続けますか？",
      null,
    ]);
  });
});

describe("circled", () => {
  it.each([
    [1, "①"],
    [3, "③"],
    [20, "⑳"],
    [21, "(21)"],
  ])("writes %i as %s", (number, expected) => {
    expect(circled(number)).toBe(expected);
  });
});
