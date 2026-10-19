import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { entry, renderSession, sessionView, stubMatchMedia } from "../../msw/helpers";

// Turn 1 is done; turn 2 waits for the learner's English.
const view = sessionView({
  stage: "english",
  version: 6,
  turn_index: 2,
  finished_replies: 1,
  allowed_actions: ["english", "hint", "show_answer", "end"],
  entries: [
    entry("partner_line", {
      text: "Hey! How's it going?",
      has_question: true,
      line_kind: "opener",
      restate_mode: null,
    }),
    entry("intent", { text: "久しぶりに映画を見た", is_replacement: false }),
    entry("acknowledgment", { line: "いいですね！", build_hint: null }),
    entry("english", { text: "I watched a movie", is_direct: false }),
    entry("turn_done", { english: "I watched a movie", end: "no_fix_needed" }),
    entry(
      "partner_line",
      {
        text: "Nice! Which one?",
        has_question: true,
        line_kind: "reply",
        restate_mode: null,
      },
      2,
    ),
    entry("intent", { text: "古い映画", is_replacement: false }, 2),
    entry("acknowledgment", { line: "なるほど", build_hint: null }, 2),
  ],
});

describe("ConversationScreen past turn (REQ-009)", () => {
  it("shows a selected past turn read-only, and 「今のターンに戻る」 returns with the composer text kept", async () => {
    const user = userEvent.setup();
    renderSession(view);

    await user.type(
      screen.getByRole("textbox", { name: "あなたの英語" }),
      "An old one",
    );
    await user.click(screen.getByRole("button", { name: "I watched a movie" }));

    const coach = screen.getByRole("region", { name: "コーチ" });
    expect(within(coach).getByRole("heading", { level: 2 })).toHaveTextContent(
      "コーチ · ターン 1",
    );
    const back = within(coach).getByRole("button", { name: "今のターンに戻る" });
    expect(back).toHaveFocus();
    expect(within(coach).getByText("久しぶりに映画を見た")).toBeInTheDocument();
    expect(within(coach).queryByText("古い映画")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/👉 次/)).not.toBeInTheDocument();

    await user.click(back);

    const composer = screen.getByRole("textbox", { name: "あなたの英語" });
    expect(composer).toHaveValue("An old one");
    expect(composer).toHaveFocus();
    expect(within(coach).getByText("古い映画")).toBeInTheDocument();
    expect(within(coach).getByRole("heading", { level: 2 })).toHaveTextContent(
      "コーチ · ターン 2",
    );
  });

  it("switches to the Coach tab when a past turn is selected below 1024 px", async () => {
    stubMatchMedia(false);
    const user = userEvent.setup();
    renderSession(view);

    await user.click(screen.getByRole("tab", { name: "会話" }));
    await user.click(screen.getByRole("button", { name: "I watched a movie" }));

    expect(screen.getByRole("tab", { name: "コーチ" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("button", { name: "今のターンに戻る" })).toHaveFocus();
  });
});
