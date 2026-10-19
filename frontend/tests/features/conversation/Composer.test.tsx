import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ProblemDetails } from "../../../src/api/generated/types.gen";
import { Composer } from "../../../src/features/conversation";
import { entry, renderSession, serveSession, sessionView } from "../../msw/helpers";

function Harness({
  onSend,
  initial = "",
  error,
}: {
  onSend: () => void;
  initial?: string;
  error?: string;
}) {
  const [value, setValue] = useState(initial);
  return (
    <Composer
      label="あなたの英語"
      lang="en"
      placeholder="英語にしてみましょう（途中まででOK）"
      value={value}
      onChange={setValue}
      onSend={onSend}
      error={error}
    />
  );
}

function field() {
  return screen.getByRole("textbox", { name: "あなたの英語" });
}

function send() {
  return screen.getByRole("button", { name: "送信" });
}

describe("Composer", () => {
  it.each([
    { length: 899, counter: null, sendable: true },
    { length: 900, counter: "900 / 1,000", sendable: true },
    { length: 1000, counter: "1,000 / 1,000", sendable: true },
    { length: 1001, counter: "1,001 / 1,000", sendable: false },
  ])(
    "at $length code points shows $counter and sendable is $sendable",
    ({ length, counter, sendable }) => {
      // Each 😀 is two UTF-16 units but one code point, as the API counts.
      render(<Harness onSend={vi.fn()} initial={"😀".repeat(length)} />);

      if (counter === null) {
        expect(screen.queryByText(/\/ 1,000$/)).not.toBeInTheDocument();
      } else {
        expect(screen.getByText(counter)).toBeInTheDocument();
      }
      if (sendable) {
        expect(send()).toBeEnabled();
        expect(field()).not.toHaveAttribute("aria-invalid");
      } else {
        expect(send()).toBeDisabled();
      }
    },
  );

  it("disables sending past 1,000 with a message tied to the field", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);

    await user.click(field());
    await user.paste("a".repeat(1034));

    const message = screen.getByText("1,000字以内にしてください（いま1,034字）");
    expect(send()).toBeDisabled();
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field().getAttribute("aria-describedby")).toContain(message.id);
    expect(field()).not.toHaveAttribute("maxlength");
    expect(field()).toHaveValue("a".repeat(1034));
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("keeps sending disabled for empty or whitespace-only text", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);
    expect(send()).toBeDisabled();

    await user.type(field(), "   ");
    expect(send()).toBeDisabled();
    await user.keyboard("{Control>}{Enter}{/Control}");

    expect(onSend).not.toHaveBeenCalled();
  });

  it("sends with ⌘↵ and with Ctrl+Enter, and Enter inserts a newline", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);

    await user.type(field(), "I watched{Enter}a movie");
    expect(field()).toHaveValue("I watched\na movie");
    expect(onSend).not.toHaveBeenCalled();

    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(onSend).toHaveBeenCalledTimes(1);
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(onSend).toHaveBeenCalledTimes(2);
    expect(field()).toHaveValue("I watched\na movie");
  });

  it("sends with the 送信 button", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} initial="I watched a movie" />);

    await user.click(send());

    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it.each([
    { name: "isComposing", init: { isComposing: true } },
    { name: "Safari's keyCode 229", init: { keyCode: 229 } },
  ])("never sends during IME composition ($name)", ({ init }) => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} initial="久しぶり" />);

    fireEvent.keyDown(field(), { key: "Enter", metaKey: true, ...init });
    fireEvent.keyDown(field(), { key: "Enter", ctrlKey: true, ...init });

    expect(onSend).not.toHaveBeenCalled();
  });

  it("shows a server message under the field and marks it invalid", () => {
    render(
      <Harness
        onSend={vi.fn()}
        initial="I watched a movie"
        error="1,000字以内にしてください"
      />,
    );

    const message = screen.getByRole("alert");
    expect(message).toHaveTextContent("1,000字以内にしてください");
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field()).toHaveAttribute("aria-describedby", message.id);
  });

  it("carries the language of what it holds", () => {
    render(<Harness onSend={vi.fn()} />);

    expect(field()).toHaveAttribute("lang", "en");
    expect(field()).toHaveAttribute(
      "placeholder",
      "英語にしてみましょう（途中まででOK）",
    );
  });
});

const intent = sessionView({
  stage: "intent",
  version: 1,
  allowed_actions: ["intent", "end"],
  entries: [
    entry("partner_line", {
      text: "Hey! How's it going?",
      has_question: true,
      line_kind: "opener",
      restate_mode: null,
    }),
  ],
});
const english = sessionView({
  stage: "english",
  version: 2,
  allowed_actions: ["english", "hint", "end"],
  entries: [
    ...intent.entries,
    entry("intent", { text: "久しぶりに映画を見た", is_replacement: false }),
    entry("acknowledgment", { line: "いいですね！", build_hint: null }),
  ],
});

function rejected(body: Partial<ProblemDetails> & { status: number }) {
  return HttpResponse.json<ProblemDetails>(
    {
      type: "about:blank",
      title: "Unprocessable Content",
      detail: "The input is outside its limits",
      code: "invalid_input",
      request_id: "req-7",
      ...body,
    },
    { status: body.status },
  );
}

async function sendIntent(text: string) {
  const user = userEvent.setup();
  const field = screen.getByRole("textbox", { name: "あなたの日本語" });
  await user.type(field, text);
  await user.keyboard("{Meta>}{Enter}{/Meta}");
  return field;
}

describe("Composer on the conversation screen (REQ-005)", () => {
  it("is cleared by a successful send", async () => {
    serveSession(intent, () => english);
    renderSession(intent);

    await sendIntent("久しぶりに映画を見た");

    const field = await screen.findByRole("textbox", { name: "あなたの英語" });
    expect(field).toHaveValue("");
  });

  it("keeps the text and shows a field's 422 under it", async () => {
    serveSession(intent, () =>
      rejected({
        status: 422,
        code: "request_invalid",
        errors: [
          { loc: ["body", "text"], message: "Text is too long", type: "too_long" },
        ],
      }),
    );
    renderSession(intent);

    const field = await sendIntent("久しぶりに映画を見た");

    const message = await screen.findByRole("alert");
    expect(message).toHaveTextContent("Text is too long");
    expect(field).toHaveValue("久しぶりに映画を見た");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAttribute("aria-describedby", message.id);
    expect(field).toBeEnabled();
  });

  it("shows the domain invalid_input 422 under the field", async () => {
    serveSession(intent, () => rejected({ status: 422 }));
    renderSession(intent);

    const field = await sendIntent("久しぶりに映画を見た");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The input is outside its limits",
    );
    expect(field).toHaveAttribute("aria-invalid", "true");
  });

  it("keeps the text and shows any other error through ErrorMessage", async () => {
    serveSession(intent, () => rejected({ status: 500, code: "internal_error" }));
    renderSession(intent);

    const field = await sendIntent("久しぶりに映画を見た");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side. Try again.");
    expect(alert).toHaveTextContent("Request ID: req-7");
    expect(field).toHaveValue("久しぶりに映画を見た");
    expect(field).not.toHaveAttribute("aria-invalid");
  });

  it("keeps the text when the server cannot be reached", async () => {
    serveSession(intent, () => HttpResponse.error());
    renderSession(intent);

    const field = await sendIntent("久しぶりに映画を見た");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach the server. Check your connection and try again.",
    );
    await waitFor(() => expect(field).toBeEnabled());
    expect(field).toHaveValue("久しぶりに映画を見た");
  });

  it("shows a hint's 422 under the gap field and keeps both texts", async () => {
    serveSession(english, () =>
      rejected({
        status: 422,
        code: "request_invalid",
        errors: [
          { loc: ["body", "gap"], message: "Gap is too long", type: "too_long" },
        ],
      }),
    );
    const user = userEvent.setup();
    renderSession(english);
    await user.type(screen.getByRole("textbox", { name: "あなたの英語" }), "I watched");
    await user.click(screen.getByRole("button", { name: "ヒント" }));
    const gap = screen.getByRole("textbox", { name: "分からないところ" });
    await user.type(gap, "久しぶり{Enter}");

    const message = await screen.findByRole("alert");
    expect(message).toHaveTextContent("Gap is too long");
    expect(gap).toHaveAttribute("aria-describedby", message.id);
    expect(gap).toHaveValue("久しぶり");
    expect(screen.getByRole("textbox", { name: "あなたの英語" })).toHaveValue(
      "I watched",
    );
  });

  it("closes the hint box and keeps the partial English after a hint", async () => {
    const hinted = sessionView({
      ...english,
      version: 3,
      entries: [
        ...english.entries,
        entry("hint_request", { gap: "久しぶり", partial_english: "I watched" }),
        entry("gap_hint", {
          hint: "「久しぶり」の部分は kind of から始めてみてください",
        }),
      ],
    });
    serveSession(english, () => hinted);
    const user = userEvent.setup();
    renderSession(english);
    await user.type(screen.getByRole("textbox", { name: "あなたの英語" }), "I watched");
    await user.click(screen.getByRole("button", { name: "ヒント" }));
    await user.type(
      screen.getByRole("textbox", { name: "分からないところ" }),
      "久しぶり",
    );
    await user.click(screen.getByRole("button", { name: "ヒントをもらう" }));

    expect(
      await screen.findByText("💡 「久しぶり」の部分は kind of から始めてみてください"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "分からないところ" })).toBeNull();
    const field = screen.getByRole("textbox", { name: "あなたの英語" });
    expect(field).toHaveValue("I watched");
    await waitFor(() => expect(field).toHaveFocus());
  });
});
