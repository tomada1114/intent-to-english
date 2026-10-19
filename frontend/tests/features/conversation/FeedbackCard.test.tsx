import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FeedbackResponse } from "../../../src/api/generated/types.gen";
import { FeedbackCard } from "../../../src/features/conversation";

const improvement: FeedbackResponse = {
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

function card() {
  return screen.getByRole("article", { name: "コーチの添削" });
}

/** The English of one labelled part of the card: あなたの文 or 穴埋め. */
function part(feedback: HTMLElement, name: string): HTMLElement {
  const english = within(feedback)
    .getByRole("heading", { name })
    .parentElement?.querySelector<HTMLElement>('[lang="en"]');
  if (english === null || english === undefined)
    throw new Error(`${name} holds no English`);
  return english;
}

describe("FeedbackCard", () => {
  it("shows one 改善 fix, the learner's sentence with its 元 marked, and the numbered slot", () => {
    render(<FeedbackCard feedback={improvement} />);

    const feedback = card();
    expect(
      within(feedback).getByText("意図は伝わっています。元のままでも通じます"),
    ).toBeInTheDocument();

    const fixes = within(feedback).getByRole("list", { name: "直し方" });
    const fix = within(fixes).getByRole("listitem");
    expect(fix).toHaveTextContent("①");
    expect(within(fix).getByText("I")).toHaveAttribute("lang", "en");
    expect(within(fix).getByText("Actually, I")).toHaveAttribute("lang", "en");
    expect(within(fix).getByText("改善")).toBeInTheDocument();
    expect(fix).toHaveTextContent(
      "なぜ: 元のままでも通じる。Actually, で始めると話を続ける感じが出る",
    );

    const sentence = part(feedback, "あなたの文");
    expect(sentence).toHaveAttribute("lang", "en");
    expect(sentence).toHaveTextContent("I① watched a movie");
    const marked = sentence.querySelector("mark");
    expect(marked).toHaveTextContent("I①");

    const template = part(feedback, "穴埋め");
    expect(template).toHaveAttribute("lang", "en");
    expect(template.textContent).toBe("(①) ____ watched a movie");

    expect(
      within(feedback).getByText("(①) を埋めて、文全体をもう一度送ってください"),
    ).toBeInTheDocument();
  });

  it("shows only its line when no fix is needed", () => {
    render(
      <FeedbackCard
        feedback={{
          first_line: "いいですね！そのままで伝わります",
          fixes: [],
          sentence: null,
          template: null,
          request_line: null,
          readings_noted: [{ written: "leave", read_as: "live" }],
        }}
      />,
    );

    const feedback = card();
    expect(feedback).toHaveTextContent("いいですね！そのままで伝わります");
    expect(within(feedback).queryByText("直し方")).not.toBeInTheDocument();
    expect(within(feedback).queryByText("あなたの文")).not.toBeInTheDocument();
    expect(within(feedback).queryByText("穴埋め")).not.toBeInTheDocument();
    expect(feedback).toHaveTextContent("leave は live として読みました");
  });

  it("orders fixes by number, tags ミス, shows 「（なし）」, and marks each found 元", () => {
    render(
      <FeedbackCard
        feedback={{
          first_line: "「よく」が伝わっていません",
          fixes: [
            {
              number: 2,
              original: "at workplace",
              replacement: "at work",
              reason: "職場は at work",
              tag: "miss",
            },
            {
              number: 1,
              original: null,
              replacement: "widely",
              reason: "「よく」まで伝えるなら widely used",
              tag: "improvement",
            },
            {
              number: 3,
              original: "also … don't you",
              replacement: "too",
              reason: "驚きは too",
              tag: "miss",
            },
          ],
          sentence: "AWS is used at workplace, you also build it, don't you?",
          template: "AWS is (①) ____ used (②) ____, you build it (③) ____?",
          request_line: null,
          readings_noted: [],
        }}
      />,
    );

    const items = within(screen.getByRole("list", { name: "直し方" })).getAllByRole(
      "listitem",
    );
    expect(items.map((item) => item.textContent?.slice(0, 1))).toEqual(["①", "②", "③"]);
    expect(items[0]).toHaveTextContent("（なし）");
    expect(within(items[1] as HTMLElement).getByText("ミス")).toBeInTheDocument();

    const sentence = part(card(), "あなたの文");
    const marks = Array.from(
      sentence.querySelectorAll("mark"),
      (mark) => mark.textContent,
    );
    expect(marks).toEqual(["at workplace②", "also③", "don't you③"]);
    expect(sentence).toHaveTextContent(
      "AWS is used at workplace②, you also③ build it, don't you③?",
    );

    const template = part(card(), "穴埋め");
    expect(template.textContent).toBe(
      "AWS is (①) ____ used (②) ____, you build it (③) ____?",
    );
  });

  it("draws the success edge when its retry was just accepted", () => {
    const { rerender } = render(<FeedbackCard feedback={improvement} />);
    expect(screen.queryByTestId("success-edge")).not.toBeInTheDocument();

    rerender(<FeedbackCard feedback={improvement} celebrate />);

    expect(screen.getByTestId("success-edge")).toHaveAttribute("aria-hidden", "true");
  });
});
