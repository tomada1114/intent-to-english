import { getSessionOptions } from "../../api/generated/@tanstack/react-query.gen";
import type {
  Action,
  ActionInputResponse,
  BlankOffResponse,
  LastSubmissionResponse,
  PerformSessionActionData,
  PieceGivenResponse,
  RetryAcceptedResponse,
  RetryResultResponse,
  SessionResponse,
  TimelineEntryResponse,
} from "../../api/generated/types.gen";
import { formatCount } from "../../lib/format";

export type SessionView = SessionResponse;
export type Entry = TimelineEntryResponse;
export type EntryOf<K extends Entry["kind"]> = Extract<Entry, { kind: K }>;

type ActionBody = PerformSessionActionData["body"];
/** An action's body without the version, which the screen adds when it sends. */
export type ActionInput = ActionBody extends infer Body
  ? Body extends unknown
    ? Omit<Body, "version">
    : never
  : never;

/** The one query key the route reads and every action result is written to. */
export function sessionQueryOptions(sessionId: string) {
  return getSessionOptions({ path: { session_id: sessionId } });
}

export const COMPOSER_LIMIT = 1000;
export const GAP_LIMIT = 200;

/** ① for 1 through ⑳ for 20, the numbers the feedback uses. */
export function circled(number: number): string {
  return number >= 1 && number <= 20
    ? String.fromCodePoint(0x2460 + number - 1)
    : `(${number})`;
}

/** A field's length in code points, as the API counts it, against its limit. */
export function measure(text: string, limit: number) {
  const count = Array.from(text).length;
  return {
    count,
    showCounter: count >= limit * 0.9,
    over: count > limit,
    blank: text.trim() === "",
    counter: `${formatCount(count)} / ${formatCount(limit)}`,
    overMessage: `${formatCount(limit)}字以内にしてください（いま${formatCount(count)}字）`,
  };
}

export function isBlankOff(result: RetryResultResponse): result is BlankOffResponse {
  return "blanks" in result;
}

export function isPieceGiven(
  result: RetryResultResponse,
): result is PieceGivenResponse {
  return "pieces" in result;
}

export function isAccepted(
  result: RetryResultResponse,
): result is RetryAcceptedResponse {
  return !isBlankOff(result) && !isPieceGiven(result);
}

/** The first line a retry check shows, whichever result it is. */
export function retryResultLine(result: RetryResultResponse): string {
  return isBlankOff(result) ? result.hint : result.line;
}

/** The check-in's reply count: the turns finished up to that check-in. */
export function checkInCount(entries: readonly Entry[], checkIn: Entry): number {
  return entries.filter((item) => item.kind === "turn_done" && item.seq < checkIn.seq)
    .length;
}

export function checkInLine(count: number): string {
  return `ここで${count}往復です。続けますか？`;
}

export function readingQuestionLine(entry: EntryOf<"reading_question">): string {
  const [first, second] = entry.payload.readings;
  return `「${entry.payload.word}」は ${first} と ${second} のどちらのつもりですか`;
}

/** What the live region says for a new Partner line or Coach block, if anything. */
export function announcementFor(
  entry: Entry,
  entries: readonly Entry[],
): string | null {
  const coach = (line: string) => `コーチ: ${line}`;
  switch (entry.kind) {
    case "partner_line":
      return `Partner: ${entry.payload.text}`;
    case "acknowledgment":
      return coach(entry.payload.line);
    case "gap_hint":
      return coach(entry.payload.hint);
    case "reading_question":
      return coach(readingQuestionLine(entry));
    case "feedback":
      return coach(entry.payload.feedback.first_line);
    case "retry_result":
    case "practice_result":
      return coach(retryResultLine(entry.payload.result));
    case "answer":
      return coach(entry.payload.example);
    case "coach_answer":
      return coach(entry.payload.text);
    case "check_in":
      return coach(checkInLine(checkInCount(entries, entry)));
    default:
      return null;
  }
}

/**
 * The action a stored submission names, as the screen sends it again: the
 * server kept exactly this action's input fields.
 */
export function toActionInput(submission: LastSubmissionResponse): ActionInput {
  return { action: submission.action, ...submission.input } as ActionInput;
}

/** What a stored input puts back in the composer and the hint box, if anything. */
export function restoredFields(input: ActionInputResponse): {
  text?: string;
  gap?: string;
} {
  if ("gap" in input && "partial_english" in input) {
    return { text: input.partial_english, gap: input.gap };
  }
  if ("text" in input && typeof input.text === "string") return { text: input.text };
  return {};
}

const PARTNER_ACTIONS: readonly Action[] = ["open", "partner_reply", "restate"];

/** Which pane waits for an action's result: the Partner's, or the Coach's. */
export function paneFor(action: Action): "partner" | "coach" {
  return PARTNER_ACTIONS.includes(action) ? "partner" : "coach";
}

/** The current turn's entries, which the Coach pane shows. */
export function currentTurnEntries(view: SessionView): Entry[] {
  return view.entries.filter((item) => item.turn_index === view.turn_index);
}

/** The latest original Partner line of the current turn: the one being answered. */
export function lineBeingAnswered(view: SessionView): EntryOf<"partner_line"> | null {
  let found: EntryOf<"partner_line"> | null = null;
  for (const item of currentTurnEntries(view)) {
    if (item.kind === "partner_line" && item.payload.line_kind !== "restatement") {
      found = item;
    }
  }
  return found;
}

const LEARNER_REPLIES: ReadonlySet<Entry["kind"]> = new Set(["intent", "english"]);

/**
 * 「前のターン: …」 between turns: the previous turn ended accepted or skipped,
 * and the learner has not replied in the current turn yet.
 */
export function previousTurnLine(view: SessionView): string | null {
  if (view.stage !== "intent" && view.stage !== "check_in") return null;
  if (
    view.stage === "intent" &&
    currentTurnEntries(view).some((item) => LEARNER_REPLIES.has(item.kind))
  ) {
    return null;
  }
  const done = view.entries.findLast(
    (item): item is EntryOf<"turn_done"> =>
      item.kind === "turn_done" &&
      item.turn_index ===
        (view.stage === "check_in" ? view.turn_index : view.turn_index - 1),
  );
  if (done?.payload.end === "accepted") return "前のターン: 言い直しできました";
  if (done?.payload.end === "skipped") return "前のターン: スキップしました";
  return null;
}

export interface Control {
  key: string;
  label: string;
  input: ActionInput | "toggle_direct" | "open_hint";
  pressed?: boolean;
}

export interface Composer {
  action: "intent" | "english_direct" | "english" | "retry" | "typed_copy";
  label: string;
  placeholder: string | undefined;
  lang: "ja" | "en";
  /** Shown, but nothing can be sent at this stage (waiting for the Partner). */
  waiting: boolean;
}

export interface StageUi {
  next: string;
  composer: Composer | null;
  controls: Control[];
}

const JAPANESE = "あなたの日本語";
const ENGLISH = "あなたの英語";

function afterLatest<K extends Entry["kind"]>(
  entries: readonly Entry[],
  anchor: Entry["kind"],
  kind: K,
): EntryOf<K> | undefined {
  const start = entries.findLastIndex((item) => item.kind === anchor);
  return entries
    .slice(start + 1)
    .findLast((item): item is EntryOf<K> => item.kind === kind);
}

/**
 * The § Stage table row for the view: the 👉 次 line, the composer, and the
 * controls the stage's allowed actions permit. The server chose the stage; this
 * only renders it.
 */
export function stageUi(
  view: SessionView,
  local: { direct: boolean; hintOpen: boolean },
): StageUi | null {
  const allowed = new Set(view.allowed_actions);
  const turn = currentTurnEntries(view);
  const only = (controls: Control[]) =>
    controls.filter((control) => {
      if (control.input === "toggle_direct") return allowed.has("english_direct");
      if (control.input === "open_hint") return allowed.has("hint");
      return allowed.has(control.input.action);
    });
  const hint: Control = { key: "hint", label: "ヒント", input: "open_hint" };
  const showAnswer: Control = {
    key: "show_answer",
    label: "答えを見せて",
    input: { action: "show_answer" },
  };
  const skip: Control = { key: "skip", label: "スキップ", input: { action: "skip" } };

  switch (view.stage) {
    case "opening":
    case "partner_turn":
      return {
        next: "Partner の返事を待っています",
        composer: {
          action: "intent",
          label: JAPANESE,
          placeholder: undefined,
          lang: "ja",
          waiting: true,
        },
        controls: [],
      };
    case "intent": {
      const share = lineBeingAnswered(view)?.payload.has_question === false;
      return {
        next: share
          ? "反応や、相手への質問を日本語で送ってください（英語で返してもOK）"
          : "返したいことを日本語で送ってください（英語で返してもOK）",
        composer: local.direct
          ? {
              action: "english_direct",
              label: ENGLISH,
              placeholder: "返したいことを英語で",
              lang: "en",
              waiting: false,
            }
          : {
              action: "intent",
              label: JAPANESE,
              placeholder: "返したいことを日本語で",
              lang: "ja",
              waiting: false,
            },
        controls: only([
          {
            key: "direct",
            label: "英語で直接返す",
            input: "toggle_direct",
            pressed: local.direct,
          },
        ]),
      };
    }
    case "english": {
      const hinted = afterLatest(turn, "intent", "gap_hint") !== undefined;
      return {
        next: local.hintOpen
          ? "分からないところを書いて、ヒントをもらってください"
          : hinted
            ? "ヒントを使って、英語の文全体を送ってください"
            : "それを英語にしてみてください（途中まででOK。詰まったら「ヒント」）",
        composer: {
          action: "english",
          label: ENGLISH,
          placeholder: hinted
            ? "英語の文全体を"
            : "英語にしてみましょう（途中まででOK）",
          lang: "en",
          waiting: false,
        },
        controls: local.hintOpen ? [] : only([hint, showAnswer]),
      };
    }
    case "retry": {
      const result = afterLatest(turn, "feedback", "retry_result")?.payload.result;
      const blanks = result && isBlankOff(result) ? result.blanks : [];
      return {
        next:
          blanks.length > 0
            ? `${blanks.map(circled).join("と")}の穴だけ埋め直して、英語の文全体をもう一度送ってください`
            : "直し方を見返しながら穴を埋めて、英語の文全体を送ってください（「スキップ」も可）",
        composer: {
          action: "retry",
          label: ENGLISH,
          placeholder: "穴を埋めた英文全体を",
          lang: "en",
          waiting: false,
        },
        controls: only([skip, showAnswer]),
      };
    }
    case "answer_shown":
      return {
        next: "完成例を見ながら、英語の文全体を1回送ってください（「スキップ」で会話に戻ります）",
        composer: {
          action: "typed_copy",
          label: ENGLISH,
          placeholder: "見ながら1回打ってみましょう",
          lang: "en",
          waiting: false,
        },
        controls: only([skip]),
      };
    case "reading_check": {
      const question = turn.findLast(
        (item): item is EntryOf<"reading_question"> => item.kind === "reading_question",
      );
      return {
        next: "どちらのつもりか選んでください",
        composer: null,
        controls: only(
          (question?.payload.readings ?? []).map((reading) => ({
            key: `reading-${reading}`,
            label: `${reading} のつもり`,
            input: { action: "reading", reading },
          })),
        ),
      };
    }
    case "check_in":
      return {
        next: "「続ける」か「終わる」を選んでください",
        composer: null,
        controls: only([
          { key: "continue", label: "続ける", input: { action: "partner_reply" } },
          { key: "end", label: "終わる", input: { action: "end" } },
        ]),
      };
    case "ended":
      return null;
  }
}
