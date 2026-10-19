import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EndSession } from "../../../src/features/conversation";

const QUESTION = "終えて振り返りを作りますか？";

beforeEach(() => {
  // Fake time also follows the clock, so Testing Library's own zero-delay
  // waits still settle; each test moves it on by the 5 s explicitly.
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

function setup(ending = false) {
  const onEnd = vi.fn();
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const view = render(<EndSession onEnd={onEnd} ending={ending} />);
  return { onEnd, user, view };
}

async function confirm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "会話を終える" }));
}

describe("EndSession", () => {
  it("becomes the in-place confirmation with focus on 戻る", async () => {
    const { user, onEnd } = setup();

    await confirm(user);

    expect(screen.getByRole("group", { name: QUESTION })).toBeInTheDocument();
    expect(screen.getByText(QUESTION)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "戻る" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "終える" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "会話を終える" }),
    ).not.toBeInTheDocument();
    expect(onEnd).not.toHaveBeenCalled();
  });

  it("ends the session once with 終える", async () => {
    const { user, onEnd } = setup();
    await confirm(user);

    await user.click(screen.getByRole("button", { name: "終える" }));

    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("returns to 会話を終える with 戻る, keeping focus on it", async () => {
    const { user, onEnd } = setup();
    await confirm(user);

    await user.click(screen.getByRole("button", { name: "戻る" }));

    expect(screen.getByRole("button", { name: "会話を終える" })).toHaveFocus();
    expect(screen.queryByText(QUESTION)).not.toBeInTheDocument();
    expect(onEnd).not.toHaveBeenCalled();
  });

  it("reverts by itself after 5 s untouched and ends nothing", async () => {
    const { user, onEnd } = setup();
    await confirm(user);

    act(() => vi.advanceTimersByTime(4900));
    expect(screen.getByText(QUESTION)).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(100));
    expect(screen.queryByText(QUESTION)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "会話を終える" })).toHaveFocus();
    expect(onEnd).not.toHaveBeenCalled();
  });

  it("restarts the 5 s whenever the confirmation is touched", async () => {
    const { user } = setup();
    await confirm(user);

    act(() => vi.advanceTimersByTime(4000));
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", { name: "終える" })).toHaveFocus();
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.getByText(QUESTION)).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(1000));
    expect(screen.queryByText(QUESTION)).not.toBeInTheDocument();
  });

  it("disables both answers while the end is being sent", async () => {
    const { user, view } = setup();
    await confirm(user);

    view.rerender(<EndSession onEnd={vi.fn()} ending />);

    expect(screen.getByRole("button", { name: "終える" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "戻る" })).toBeDisabled();
  });
});
