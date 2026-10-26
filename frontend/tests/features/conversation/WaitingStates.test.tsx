import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ProblemDetails,
  SessionResponse,
} from "../../../src/api/generated/types.gen";
import {
  advance,
  deferred,
  entry,
  installFakeClock,
  renderSession,
  SESSION_ID,
  serveSession,
  sessionView,
} from "../../msw/helpers";
import { server as msw } from "../../msw/server";

const COACH_WAITING = "コーチが確認しています…";
const PARTNER_WAITING = "Partner が返事を考えています…";
const LONG_WAIT = "時間がかかっています（最大2分）";
const CANCELLED = "中止しました。";
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

const cancelledProblem: ProblemDetails = {
  type: "about:blank",
  title: "Conflict",
  status: 409,
  detail: "The action was cancelled",
  code: "action_cancelled",
  request_id: "req-1",
};

beforeEach(() => {
  installFakeClock();
});

afterEach(() => {
  vi.useRealTimers();
});

function coach() {
  return within(screen.getByRole("region", { name: "コーチ" }));
}

function partner() {
  return within(screen.getByRole("region", { name: "会話" }));
}

/** Render `view` with its first action held until `release`, then let the screen settle. */
async function open(
  view: SessionResponse,
  result: SessionResponse | Response = retry,
  cancel?: () => Promise<Response>,
) {
  const hold = deferred();
  const served = serveSession(
    view,
    async (body) => {
      await hold.promise;
      return body.version === view.version ? result : HttpResponse.error();
    },
    cancel,
  );
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  renderSession(view);
  await advance(0);
  return { served, user, release: hold.release };
}

/** Type the English and send it with ⌘↵: the send is at the current fake time. */
async function sendEnglish(user: ReturnType<typeof userEvent.setup>) {
  await user.type(
    screen.getByRole("textbox", { name: "あなたの英語" }),
    "I watched a movie",
  );
  await user.keyboard("{Meta>}{Enter}{/Meta}");
}

/** The retry stage's composer: the result of the english action rendered. */
function resultShown() {
  return (
    screen
      .queryByRole("textbox", { name: "あなたの英語" })
      ?.getAttribute("placeholder") === "穴を埋めた英文全体を"
  );
}

describe("ConversationScreen waiting line timing (REQ-001)", () => {
  it("shows no waiting line for a response at 299 ms", async () => {
    const { user, release } = await open(english);
    await sendEnglish(user);

    await advance(299);
    expect(coach().queryByText(COACH_WAITING)).not.toBeInTheDocument();
    release();
    await advance(0);

    expect(resultShown()).toBe(true);
    await advance(1000);
    expect(screen.queryByText(COACH_WAITING)).not.toBeInTheDocument();
  });

  it("shows the line from 300 ms and the result at 800 ms for a response at 301 ms", async () => {
    const { user, release } = await open(english);
    await sendEnglish(user);

    await advance(299);
    expect(coach().queryByText(COACH_WAITING)).not.toBeInTheDocument();
    await advance(1);
    expect(coach().getByText(COACH_WAITING)).toBeInTheDocument();
    await advance(1);
    release();
    await advance(0);
    await advance(498);
    expect(coach().getByText(COACH_WAITING)).toBeInTheDocument();
    expect(resultShown()).toBe(false);
    await advance(1);

    expect(resultShown()).toBe(true);
    expect(coach().queryByText(COACH_WAITING)).not.toBeInTheDocument();
  });

  it("shows the line from 300 ms and the result at once for a response at 900 ms", async () => {
    const { user, release } = await open(english);
    await sendEnglish(user);

    await advance(300);
    expect(coach().getByText(COACH_WAITING)).toBeInTheDocument();
    await advance(600);
    release();
    await advance(0);

    expect(resultShown()).toBe(true);
    expect(coach().queryByText(COACH_WAITING)).not.toBeInTheDocument();
  });

  it("disables the composer at once and keeps its text while the line is still hidden", async () => {
    const { user, release } = await open(english);
    await sendEnglish(user);

    await advance(100);

    const field = screen.getByRole("textbox", { name: "あなたの英語" });
    expect(field).toBeDisabled();
    expect(field).toHaveValue("I watched a movie");
    expect(coach().queryByText(/👉 次/)).not.toBeInTheDocument();
    release();
    await advance(0);
  });

  it("shows the Partner's waiting line on the left from 300 ms for an auto-sent partner_reply", async () => {
    const { release } = await open(partnerTurn, turnTwo);

    await advance(299);
    expect(partner().queryByText(PARTNER_WAITING)).not.toBeInTheDocument();
    await advance(1);
    expect(partner().getByText(PARTNER_WAITING)).toBeInTheDocument();
    release();
    await advance(0);
    await advance(500);

    expect(partner().getByText(SHARE.payload.text)).toBeInTheDocument();
    expect(partner().queryByText(PARTNER_WAITING)).not.toBeInTheDocument();
  });
});

describe("ConversationScreen long wait (REQ-002)", () => {
  it("at 10 s from the send reads 時間がかかっています（最大2分） and offers 中止", async () => {
    const { user, release } = await open(english);
    await sendEnglish(user);

    await advance(9999);
    expect(coach().getByText(COACH_WAITING)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "中止" })).not.toBeInTheDocument();
    await advance(1);

    expect(coach().getByText(LONG_WAIT)).toBeInTheDocument();
    expect(coach().queryByText(COACH_WAITING)).not.toBeInTheDocument();
    expect(coach().getByRole("button", { name: "中止" })).toBeEnabled();
    release();
    await advance(0);
  });

  it("never shows 中止 for a response at 9,999 ms", async () => {
    const { user, release } = await open(english);
    await sendEnglish(user);

    await advance(9999);
    release();
    await advance(0);
    await advance(5000);

    expect(resultShown()).toBe(true);
    expect(screen.queryByRole("button", { name: "中止" })).not.toBeInTheDocument();
    expect(screen.queryByText(LONG_WAIT)).not.toBeInTheDocument();
  });

  it("still shows the long wait and no banner at 60 s with the request held", async () => {
    const { user, release } = await open(english);
    await sendEnglish(user);

    await advance(60_000);

    expect(coach().getByText(LONG_WAIT)).toBeInTheDocument();
    expect(coach().getByRole("button", { name: "中止" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    release();
    await advance(0);
  });

  it("offers 中止 on the left for a long Partner wait", async () => {
    const { release } = await open(partnerTurn, turnTwo);

    await advance(10_000);

    expect(partner().getByText(LONG_WAIT)).toBeInTheDocument();
    expect(partner().getByRole("button", { name: "中止" })).toBeInTheDocument();
    release();
    await advance(0);
  });
});

describe("ConversationScreen cancel (REQ-003)", () => {
  it("cancels at 12 s with the awaited version, returns the text once the 204 arrives, and discards the late result", async () => {
    const cancelled = deferred();
    const { served, user, release } = await open(english, retry, async () => {
      await cancelled.promise;
      return new HttpResponse(null, { status: 204 });
    });
    await sendEnglish(user);
    await advance(12_000);

    await user.click(coach().getByRole("button", { name: "中止" }));
    await advance(0);

    expect(served.bodies[0]?.attempt_id).toEqual(expect.any(String));
    expect(served.cancels).toEqual([
      { version: 2, attempt_id: served.bodies[0]?.attempt_id },
    ]);
    const field = screen.getByRole("textbox", { name: "あなたの英語" });
    expect(field).toBeDisabled();
    expect(screen.queryByText(CANCELLED)).not.toBeInTheDocument();
    cancelled.release();
    await advance(0);

    expect(field).toBeEnabled();
    expect(field).toHaveValue("I watched a movie");
    expect(coach().getByText(CANCELLED)).toBeInTheDocument();
    expect(screen.queryByText(LONG_WAIT)).not.toBeInTheDocument();
    expect(
      coach().getByText(
        "👉 次: それを英語にしてみてください（途中まででOK。詰まったら「ヒント」）",
      ),
    ).toBeInTheDocument();
    release();
    await advance(1000);

    expect(resultShown()).toBe(false);
    expect(field).toHaveValue("I watched a movie");
    expect(coach().getByText(CANCELLED)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders a result that arrives before the cancel's 204, with no 中止しました。", async () => {
    const cancelled = deferred();
    const { user, release } = await open(english, retry, async () => {
      await cancelled.promise;
      return new HttpResponse(null, { status: 204 });
    });
    await sendEnglish(user);
    await advance(10_000);
    await user.click(coach().getByRole("button", { name: "中止" }));

    release();
    await advance(0);
    expect(resultShown()).toBe(true);
    cancelled.release();
    await advance(0);

    expect(resultShown()).toBe(true);
    expect(screen.queryByText(CANCELLED)).not.toBeInTheDocument();
  });

  it("clears 中止しました。 when a new action starts", async () => {
    const { served, user, release } = await open(english);
    await sendEnglish(user);
    await advance(10_000);
    await user.click(coach().getByRole("button", { name: "中止" }));
    await advance(0);
    expect(coach().getByText(CANCELLED)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveFocus();

    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await advance(0);

    expect(screen.queryByText(CANCELLED)).not.toBeInTheDocument();
    expect(served.bodies).toHaveLength(2);
    release();
    await advance(1000);
  });

  it("after a cancelled partner_reply shows 中止しました。 and もう一度 on the left, which sends it again", async () => {
    const { served, user, release } = await open(
      partnerTurn,
      HttpResponse.json<ProblemDetails>(cancelledProblem, { status: 409 }),
    );
    await advance(10_000);

    await user.click(partner().getByRole("button", { name: "中止" }));
    await advance(0);
    release();
    await advance(0);

    expect(served.cancels).toEqual([{ attempt_id: expect.any(String), version: 4 }]);
    expect(partner().getByText(CANCELLED)).toBeInTheDocument();
    expect(partner().getByRole("button", { name: "もう一度" })).toHaveFocus();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(served.bodies).toHaveLength(1);
    await user.click(partner().getByRole("button", { name: "もう一度" }));
    await advance(0);

    expect(served.bodies).toEqual([
      { attempt_id: expect.any(String), action: "partner_reply", version: 4 },
      { attempt_id: expect.any(String), action: "partner_reply", version: 4 },
    ]);
    expect(served.bodies[1]?.attempt_id).not.toBe(served.bodies[0]?.attempt_id);
    expect(screen.queryByText(CANCELLED)).not.toBeInTheDocument();
  });
});

describe("ConversationScreen pending from elsewhere (REQ-009)", () => {
  const pending: SessionResponse = {
    ...english,
    last_submission: {
      attempt_id: "00000000-0000-4000-8000-000000000001",
      action: "english",
      input: { text: "I watched a movie" },
      state: "pending",
      failure_code: null,
    },
  };

  function serveReads(answers: SessionResponse[]) {
    let reads = 0;
    const posts: unknown[] = [];
    msw.use(
      http.get(`/api/sessions/${SESSION_ID}`, () => {
        const answer = answers[Math.min(reads, answers.length - 1)] as SessionResponse;
        reads += 1;
        return HttpResponse.json<SessionResponse>(answer);
      }),
      http.post(`/api/sessions/${SESSION_ID}/actions`, async ({ request }) => {
        posts.push(await request.json());
        return HttpResponse.error();
      }),
      http.post(`/api/sessions/${SESSION_ID}/cancel`, async ({ request }) => {
        posts.push(await request.json());
        return new HttpResponse(null, { status: 204 });
      }),
    );
    return { reads: () => reads, posts };
  }

  it("waits, reads the session every 2 s while it is pending, and renders the stored result", async () => {
    const served = serveReads([pending, pending, retry]);
    renderSession(pending);
    await advance(0);
    expect(served.reads()).toBe(1);

    await advance(299);
    expect(coach().queryByText(COACH_WAITING)).not.toBeInTheDocument();
    await advance(1);
    expect(coach().getByText(COACH_WAITING)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "あなたの英語" })).toBeDisabled();
    // Each read is 2 s after the last one settled; fake timers set a timer
    // 1 ms late while they run, so each check keeps a little slack.
    await advance(1690);
    expect(served.reads()).toBe(1);
    await advance(20);
    expect(served.reads()).toBe(2);
    expect(resultShown()).toBe(false);
    await advance(2000);

    expect(served.reads()).toBe(3);
    expect(resultShown()).toBe(true);
    expect(coach().queryByText(COACH_WAITING)).not.toBeInTheDocument();
    await advance(6000);
    expect(served.reads()).toBe(3);
    expect(served.posts).toEqual([]);
  });

  it("keeps a pending english's text in the disabled composer while it waits, and clears it once the result arrives", async () => {
    serveReads([pending, pending, retry]);
    renderSession(pending);
    await advance(0);

    const field = screen.getByRole("textbox", { name: "あなたの英語" });
    expect(field).toBeDisabled();
    expect(field).toHaveValue("I watched a movie");
    await advance(2010);
    expect(field).toHaveValue("I watched a movie");
    await advance(2000);

    expect(resultShown()).toBe(true);
    const composer = screen.getByRole("textbox", { name: "あなたの英語" });
    expect(composer).toBeEnabled();
    expect(composer).toHaveValue("");
    expect(composer).toHaveFocus();
  });

  it("offers 中止 at 10 s, cancels the view's version, and returns the submitted text", async () => {
    const served = serveReads([pending]);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderSession(pending);
    await advance(10_000);
    expect(coach().getByText(LONG_WAIT)).toBeInTheDocument();
    served.posts.length = 0;
    msw.use(
      http.get(`/api/sessions/${SESSION_ID}`, () =>
        HttpResponse.json<SessionResponse>(english),
      ),
    );

    await user.click(coach().getByRole("button", { name: "中止" }));
    await advance(0);

    expect(served.posts).toEqual([{ attempt_id: expect.any(String), version: 2 }]);
    const field = screen.getByRole("textbox", { name: "あなたの英語" });
    expect(field).toBeEnabled();
    expect(field).toHaveFocus();
    expect(field).toHaveValue("I watched a movie");
    expect(coach().getByText(CANCELLED)).toBeInTheDocument();
    await advance(6000);
    expect(field).toBeEnabled();
  });

  it("waits again for a new pending submission at the same version once the cancelled one is gone", async () => {
    let reads = 0;
    let afterCancel = false;
    msw.use(
      http.get(`/api/sessions/${SESSION_ID}`, () => {
        reads += 1;
        // Another tab sends the same action again at the same version.
        return HttpResponse.json<SessionResponse>({
          ...pending,
          last_submission: {
            action: "english",
            input: { text: "I watched a movie" },
            state: "pending",
            failure_code: null,
            attempt_id: afterCancel
              ? "00000000-0000-4000-8000-000000000002"
              : "00000000-0000-4000-8000-000000000001",
          },
        });
      }),
      http.post(`/api/sessions/${SESSION_ID}/cancel`, () => {
        afterCancel = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderSession(pending);
    await advance(10_000);

    await user.click(coach().getByRole("button", { name: "中止" }));
    await advance(0);
    expect(afterCancel).toBe(true);
    const readsAfterCancel = reads;

    const field = screen.getByRole("textbox", { name: "あなたの英語" });
    expect(field).toBeDisabled();
    expect(field).toHaveValue("I watched a movie");
    await advance(2010);
    expect(reads).toBeGreaterThan(readsAfterCancel);
    expect(coach().getByText(COACH_WAITING)).toBeInTheDocument();
  });
});

describe("ConversationScreen cancel with no response (REQ-003, REQ-006)", () => {
  it("clears the server-unreachable banner once the awaited action settles anyway", async () => {
    const { user, release } = await open(english, retry, async () =>
      HttpResponse.error(),
    );
    await sendEnglish(user);
    await advance(10_000);
    await user.click(coach().getByRole("button", { name: "中止" }));
    await advance(0);
    expect(screen.getByText(UNREACHABLE)).toBeInTheDocument();

    release();
    await advance(1000);

    expect(resultShown()).toBe(true);
    expect(screen.queryByText(UNREACHABLE)).not.toBeInTheDocument();
  });
});
