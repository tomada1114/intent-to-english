import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProblemDetails } from "../../../src/api/generated/types.gen";
import { EndSession } from "../../../src/features/conversation";
import {
  deferred,
  entry,
  renderSession,
  serveSession,
  sessionView,
} from "../../msw/helpers";

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

    // Fake time also follows the wall clock, so the check before 5 s keeps a
    // second of slack for a slow runner.
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.getByText(QUESTION)).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(1000));
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

describe("ConversationScreen ending while a request is in flight (REQ-010)", () => {
  const intent = sessionView({
    stage: "intent",
    version: 1,
    entries: [
      entry("partner_line", {
        text: "Hey! How's it going?",
        has_question: true,
        line_kind: "opener",
        restate_mode: null,
      }),
    ],
    allowed_actions: ["intent", "english_direct", "end"],
  });
  const ended = sessionView({
    ...intent,
    status: "ended",
    stage: "ended",
    version: 2,
    ended_at: "2026-10-17T10:00:00Z",
    allowed_actions: [],
  });
  const cancelled: ProblemDetails = {
    type: "about:blank",
    title: "Conflict",
    status: 409,
    detail: "The action was cancelled",
    code: "action_cancelled",
    request_id: "req-1",
  };

  it("sends one end when the failure retry is activated twice before rendering", async () => {
    const hold = deferred();
    let ends = 0;
    const served = serveSession(intent, async (): Promise<Response> => {
      ends += 1;
      if (ends === 1) {
        return HttpResponse.json<ProblemDetails>(
          {
            type: "about:blank",
            title: "Internal Server Error",
            status: 500,
            detail: "Internal Server Error",
            code: "internal_error",
            request_id: "end-500",
          },
          { status: 500 },
        );
      }
      await hold.promise;
      return HttpResponse.json(ended);
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderSession(intent);
    await confirm(user);
    await user.click(screen.getByRole("button", { name: "終える" }));
    const banner = await screen.findByRole("alert");
    const again = within(banner).getByRole("button", { name: "もう一度" });

    act(() => {
      fireEvent.click(again);
      fireEvent.click(again);
    });
    await waitFor(() => expect(served.bodies).toHaveLength(2));
    hold.release();
    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
    expect(served.bodies).toEqual([
      { action: "end", version: 1 },
      { action: "end", version: 1 },
    ]);
  });

  it("shows a Japanese end failure and lets the learner retry", async () => {
    let ends = 0;
    const served = serveSession(intent, () => {
      ends += 1;
      return ends === 1
        ? HttpResponse.json<ProblemDetails>(
            {
              type: "about:blank",
              title: "Internal Server Error",
              status: 500,
              detail: "Internal Server Error",
              code: "internal_error",
              request_id: "end-500",
            },
            { status: 500 },
          )
        : ended;
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderSession(intent);
    await confirm(user);
    await user.click(screen.getByRole("button", { name: "終える" }));
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("会話を終えられませんでした。");
    expect(banner).toHaveTextContent("リクエストID: end-500");
    expect(banner).not.toHaveAttribute("lang", "en");
    await user.click(within(banner).getByRole("button", { name: "もう一度" }));
    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
    expect(served.bodies).toEqual([
      { action: "end", version: 1 },
      { action: "end", version: 1 },
    ]);
  });

  it("keeps 会話を終える usable, posts end with the shown version, renders the ended view at once, and ignores the abandoned request's 409", async () => {
    const hold = deferred();
    const served = serveSession(intent, async (body) => {
      if (body.action === "end") return ended;
      await hold.promise;
      return HttpResponse.json<ProblemDetails>(cancelled, { status: 409 });
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderSession(intent);

    await user.type(
      screen.getByRole("textbox", { name: "あなたの日本語" }),
      "久しぶりに映画を見た",
    );
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(served.bodies).toHaveLength(1));
    const start = screen.getByRole("button", { name: "会話を終える" });
    expect(start).toBeEnabled();
    await user.click(start);
    await user.click(screen.getByRole("button", { name: "終える" }));

    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
    expect(screen.queryByText(/👉 次/)).not.toBeInTheDocument();
    expect(served.bodies).toEqual([
      { action: "intent", text: "久しぶりに映画を見た", version: 1 },
      { action: "end", version: 1 },
    ]);
    hold.release();
    await act(() => vi.advanceTimersByTimeAsync(1000));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText("Partner が返事を考えています…")).not.toBeInTheDocument();
    expect(screen.queryByText("コーチが確認しています…")).not.toBeInTheDocument();
  });
});
