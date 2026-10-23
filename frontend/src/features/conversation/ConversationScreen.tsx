import {
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useEffectEvent,
  useId,
  useRef,
  useState,
} from "react";
import type { Action } from "../../api/generated/types.gen";
import { Banner } from "../../lib/Banner";
import { useDelayedLoading } from "../../lib/delayed-loading";
import { formatStart } from "../../lib/format";
import { HeaderItems } from "../../lib/HeaderItems";
import type { ApiError } from "../../lib/problem-details";
import { modelFailureReason } from "../../lib/submission";
import {
  COACH_ENGLISH,
  ENTER,
  FOCUS_RING,
  QUIET_BUTTON,
  SECONDARY_BUTTON,
} from "../../lib/ui";
import { CoachQuestion } from "./CoachQuestion";
import { Composer } from "./Composer";
import { EndSession } from "./EndSession";
import { ConversationTimeline, TurnTimeline } from "./entries";
import { HintRequest } from "./HintRequest";
import {
  type Arrival,
  useAfter,
  useArrivals,
  useFollowBottom,
  useWideLayout,
} from "./hooks";
import {
  type ActionInput,
  type Control,
  lineBeingAnswered,
  paneFor,
  previousTurnLine,
  restoredFields,
  type SessionView,
  stageUi,
  toActionInput,
} from "./session";
import { type SessionActionEvent, useSessionActions } from "./useSessionActions";

/** Actions whose text is the composer's: a success clears it, nothing else does. */
const COMPOSER_ACTIONS: ReadonlySet<Action> = new Set([
  "intent",
  "english_direct",
  "english",
  "retry",
  "typed_copy",
]);

/** From the send, how long a wait runs before it offers [中止] (ux-guidelines § States). */
export const LONG_WAIT_MS = 10_000;

const PARTNER_WAITING = "Partner が返事を考えています…";
const COACH_WAITING = "コーチが確認しています…";
const LONG_WAIT = "時間がかかっています（最大2分）";
const CANCELLED = "中止しました。";
const STALE = "別の画面でこの会話が進みました。最新の状態を読み込みました。";

const HOW_TO = [
  "1. 返したいことを、まず日本語で送ってください",
  "2. それを自分で英語にしてみてください（途中まででOK。詰まったら「ヒント」）",
  "3. 最初から英語で返すときは「英語で直接返す」",
  "4. 「答えを見せて」「スキップ」「会話を終える」はいつでも使えます",
];

type Tab = "conversation" | "coach";

/** How the last action this tab sent (or cancelled) ended, while it matters. */
type Outcome =
  | { kind: "failed"; input: ActionInput; code: string | undefined }
  | {
      kind: "invalid";
      field: "text" | "gap" | "question" | "rewrite" | "practice";
      message: string;
    }
  | { kind: "cancelled"; action: Action }
  | { kind: "stale" };

/** A 422's message for the field the action's input came from, if it names one. */
function fieldMessage(
  error: Extract<ApiError, { kind: "problem" }>,
  field: "text" | "gap",
): string | undefined {
  const messages = error.fieldErrors[field];
  if (messages !== undefined) return messages.join(" ");
  return error.code === "invalid_input" ? (error.detail ?? error.title) : undefined;
}

/** 「コーチの返事を受け取れませんでした（<reason>）。」, or the Partner's, by pane. */
function failureLine(pane: "partner" | "coach", code: string | null | undefined) {
  const reason = modelFailureReason(code);
  const who = pane === "partner" ? "Partner の" : "コーチの";
  return reason === undefined
    ? `${who}返事を受け取れませんでした。`
    : `${who}返事を受け取れませんでした（${reason}）。`;
}

/**
 * The text a stored submission puts back in the fields: a failed or
 * interrupted one's to send again, a pending one's to keep in view while it
 * runs (ux-guidelines § States: the composer keeps its text while waiting).
 */
function restoredFrom(view: SessionView): { text?: string; gap?: string } {
  const stored = view.last_submission;
  return stored === null ||
    ["ask", "rewrite_intent", "practice_again"].includes(stored.action)
    ? {}
    : restoredFields(stored.input);
}

/**
 * S2, the conversation in progress (and, read-only, an ended one): the
 * Partner's pane and the Coach's, side by side from 1024 px and tabs below.
 * Every stage, control, and 👉 次 line comes from the view; the screen sends
 * `open` and `partner_reply` by itself, and writes each result into the
 * session query, so the route re-renders with the server's next stage. A wait
 * shows its line after 300 ms and offers [中止] at 10 s; a failure shows its
 * banner with [もう一度]; nothing the learner typed is lost on the way.
 */
export function ConversationScreen({
  view,
  backLink,
  notice,
}: {
  view: SessionView;
  /** The header's 「← 会話一覧」, which the route supplies as a router link. */
  backLink?: ReactNode;
  /** Above both panes: the route's banner when reading the session again failed. */
  notice?: ReactNode;
}) {
  const wide = useWideLayout();
  const ids = useId();
  const [tab, setTab] = useState<Tab>("coach");
  const [unread, setUnread] = useState(false);
  // A failed or interrupted submission's text comes back in the composer.
  const [text, setText] = useState(() => restoredFrom(view).text ?? "");
  const [gap, setGap] = useState(() => restoredFrom(view).gap ?? "");
  const [directTurn, setDirectTurn] = useState<number | null>(() =>
    view.stage === "intent" && view.last_submission?.action === "english_direct"
      ? view.turn_index
      : null,
  );
  const [hintOpen, setHintOpen] = useState(() => restoredFrom(view).gap !== undefined);
  const [howToOpen, setHowToOpen] = useState(true);
  const [rewriting, setRewriting] = useState(
    view.last_submission?.action === "rewrite_intent",
  );
  const [rewriteText, setRewriteText] = useState(() =>
    view.last_submission?.action === "rewrite_intent" &&
    "text" in view.last_submission.input
      ? view.last_submission.input.text
      : "",
  );
  const [practiceOpen, setPracticeOpen] = useState(
    view.last_submission?.action === "practice_again",
  );
  const [practiceText, setPracticeText] = useState(() =>
    view.last_submission?.action === "practice_again" &&
    "text" in view.last_submission.input
      ? view.last_submission.input.text
      : "",
  );
  const [questionOpen, setQuestionOpen] = useState(
    view.last_submission?.action === "ask",
  );
  const [questionText, setQuestionText] = useState(() =>
    view.last_submission?.action === "ask" && "text" in view.last_submission.input
      ? view.last_submission.input.text
      : "",
  );

  /** A past turn the learner selected on the left, shown read-only on the right. */
  const [pastTurn, setPastTurn] = useState<number | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const backToTurnRef = useRef<HTMLButtonElement>(null);
  /** Where focus goes once the next render is shown, as a control goes away. */
  const focusAfterPast = useRef<"back" | "composer" | "gap" | "again" | null>(null);
  const againRef = useRef<HTMLButtonElement>(null);
  const coachHeadingRef = useRef<HTMLHeadingElement>(null);
  const partnerHeadingRef = useRef<HTMLHeadingElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const gapRef = useRef<HTMLInputElement>(null);
  const controlsRef = useRef<HTMLFieldSetElement>(null);
  const hintButtonRef = useRef<HTMLButtonElement>(null);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({
    conversation: null,
    coach: null,
  });
  const autoSent = useRef<number | null>(null);
  const focusOnResult = useRef<number | null>(null);
  const focusHintButton = useRef(false);

  /** Apply one consumption policy to direct success and every recovered completion. */
  function settleConsumedInput(input: ActionInput) {
    if (COMPOSER_ACTIONS.has(input.action) && "text" in input)
      setText((current) => (current === input.text ? "" : current));
    if (input.action === "hint") {
      setGap((current) => (current === input.gap ? "" : current));
      if (gap === input.gap) setHintOpen(false);
    }
    if (input.action === "rewrite_intent" && rewriteText === input.text)
      setRewriting(false);
    if (input.action === "practice_again" && practiceText === input.text) {
      setPracticeOpen(false);
      setPracticeText("");
    }
    if (input.action === "ask" && questionText === input.text) {
      setQuestionText("");
      setQuestionOpen(false);
    }
  }

  function restoreInput(input: ActionInput, mode: "empty" | "cancelled") {
    if (mode === "cancelled") {
      if ("text" in input) {
        if (input.action === "rewrite_intent") setRewriteText(input.text);
        else if (input.action === "practice_again") setPracticeText(input.text);
        else if (COMPOSER_ACTIONS.has(input.action)) setText(input.text);
      }
      if (input.action === "hint") {
        setGap(input.gap);
        setHintOpen(true);
      }
      return;
    }
    if ("text" in input) {
      const restored = input.text;
      if (input.action === "ask") {
        setQuestionText((current) => (current === "" ? restored : current));
        setQuestionOpen(true);
      } else if (input.action === "rewrite_intent") {
        setRewriteText((current) => (current === "" ? restored : current));
        setRewriting(true);
        setPracticeOpen(false);
      } else if (input.action === "practice_again") {
        setPracticeText((current) => (current === "" ? restored : current));
        setPracticeOpen(true);
        setRewriting(false);
      } else {
        setText((current) => (current === "" ? restored : current));
      }
    }
    if (input.action === "hint") {
      setText((current) => (current === "" ? (input.partial_english ?? "") : current));
      setGap((current) => (current === "" ? input.gap : current));
    }
  }

  function canRestoreRequestFocus() {
    const active = document.activeElement;
    const disabled =
      (active instanceof HTMLButtonElement ||
        active instanceof HTMLTextAreaElement ||
        active instanceof HTMLInputElement) &&
      active.disabled;
    // Preserve any still-enabled control the learner selected during the wait.
    return (
      active === null ||
      active === document.body ||
      active === coachHeadingRef.current ||
      active === partnerHeadingRef.current ||
      disabled
    );
  }

  function showFailure(input: ActionInput, error: ApiError) {
    if (error.kind !== "problem") return;
    const code = error.code;
    const field =
      input.action === "ask"
        ? "question"
        : input.action === "rewrite_intent"
          ? "rewrite"
          : input.action === "practice_again"
            ? "practice"
            : input.action === "hint"
              ? "gap"
              : COMPOSER_ACTIONS.has(input.action)
                ? "text"
                : null;
    const message =
      error.status === 422 && field !== null
        ? fieldMessage(error, field === "gap" ? "gap" : "text")
        : undefined;
    const partnerFailure = input.action === "open" || input.action === "partner_reply";
    const restore = canRestoreRequestFocus() && !partnerFailure;
    focusAfterPast.current =
      restore && field !== "question" ? (field === "gap" ? "gap" : "composer") : null;
    setOutcome(
      field !== null && message !== undefined
        ? { kind: "invalid", field, message }
        : { kind: "failed", input, code },
    );
  }

  function onSessionEvent(event: SessionActionEvent) {
    switch (event.kind) {
      case "started":
        setOutcome(null);
        break;
      case "consumed":
        settleConsumedInput(event.input);
        focusOnResult.current = event.version;
        break;
      case "result":
        focusOnResult.current = event.version;
        break;
      case "restore":
        restoreInput(event.input, event.mode);
        break;
      case "failed":
        showFailure(event.input, event.error);
        break;
      case "cancelled":
        focusAfterPast.current = autoAction !== null ? "again" : "composer";
        setOutcome({ kind: "cancelled", action: event.action });
        break;
      case "stale":
        if (event.restoreFocus && canRestoreRequestFocus())
          focusAfterPast.current = "composer";
        setOutcome({ kind: "stale" });
        break;
      case "ending":
        if (event.retry)
          (backToTurnRef.current ?? coachHeadingRef.current)?.focus({
            preventScroll: true,
          });
        break;
    }
  }

  const {
    send,
    cancel,
    endSession,
    endError,
    endPending,
    storedLive,
    unanswered,
    waitingAction,
    busy,
    waitKey,
    cancelling,
  } = useSessionActions(view, onSessionEvent);
  const waitingPane = waitingAction === undefined ? null : paneFor(waitingAction);
  const lineShown = useDelayedLoading(busy) && busy;
  useEffect(() => {
    if (!busy) return;
    let cancelled = false;
    // Restoring a side editor can replace the focused input in the same
    // commit. Let that replacement finish before dispatching focus/blur.
    queueMicrotask(() => {
      if (cancelled) return;
      const active = document.activeElement;
      const disabled =
        (active instanceof HTMLButtonElement ||
          active instanceof HTMLTextAreaElement ||
          active instanceof HTMLInputElement) &&
        active.disabled;
      if (active !== document.body && !disabled) return;
      // The other mobile pane is hidden even while its request is running.
      const visiblePane = wide ? waitingPane : tab === "coach" ? "coach" : "partner";
      const heading = visiblePane === "partner" ? partnerHeadingRef : coachHeadingRef;
      heading.current?.focus({ preventScroll: true });
    });
    return () => {
      cancelled = true;
    };
  }, [busy, waitingPane, wide, tab]);
  const longWait = useAfter(waitKey, LONG_WAIT_MS);
  const ended = view.status === "ended";

  const autoSend = useEffectEvent((auto: "open" | "partner_reply") => {
    void send({ action: auto });
  });
  const autoAction =
    view.stage === "opening"
      ? "open"
      : view.stage === "partner_turn"
        ? "partner_reply"
        : null;
  useEffect(() => {
    // Never for a submission the server still holds or that failed, and once
    // per version: a failed auto-send stays failed (StrictMode re-runs this
    // effect too); 「もう一度」 sends it again.
    if (autoAction === null || view.last_submission !== null) return;
    if (autoSent.current === view.version) return;
    autoSent.current = view.version;
    autoSend(autoAction);
  }, [autoAction, view.version, view.last_submission]);

  // Once a result's view is shown and nothing is in flight, the composer takes
  // focus, or the first control when the stage hides it.
  useEffect(() => {
    const awaited = focusOnResult.current;
    if (awaited === null || busy || view.version < awaited) return;
    focusOnResult.current = null;
    const active = document.activeElement;
    const typing =
      (active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement) &&
      active !== composerRef.current &&
      !active.disabled;
    if (typing) return;
    const composer = composerRef.current;
    if (composer !== null && !composer.disabled) {
      composer.focus();
    } else {
      controlsRef.current?.querySelector<HTMLButtonElement>("button:enabled")?.focus();
    }
  }, [view.version, busy]);

  useEffect(() => {
    if (hintOpen) {
      gapRef.current?.focus();
    } else if (focusHintButton.current) {
      focusHintButton.current = false;
      hintButtonRef.current?.focus();
    }
  }, [hintOpen]);

  useEffect(() => {
    const target = focusAfterPast.current;
    focusAfterPast.current = null;
    if (target === "back") backToTurnRef.current?.focus();
    if (target === "again") againRef.current?.focus();
    if (target === "gap") gapRef.current?.focus();
    if (target !== "composer") return;
    // The composer, else the stage's first control, else the pane's heading.
    const composer = composerRef.current;
    const control =
      controlsRef.current?.querySelector<HTMLButtonElement>("button:enabled");
    if (composer !== null && !composer.disabled) composer.focus();
    else if (control) control.focus();
    else coachHeadingRef.current?.focus();
  });

  function showPastTurn(turn: number) {
    focusAfterPast.current = "back";
    setPastTurn(turn);
    setTab("coach");
  }

  function backToCurrentTurn() {
    focusAfterPast.current = "composer";
    setPastTurn(null);
  }

  const viewingPast = pastTurn !== null && !ended;

  const arrival = useArrivals(view.entries);
  const markUnread = useEffectEvent((next: Arrival) => {
    if (next.partner && !wide && tab === "coach") setUnread(true);
  });
  useEffect(() => markUnread(arrival), [arrival]);

  const direct = directTurn === view.turn_index && view.stage === "intent";
  const showHint = hintOpen && view.stage === "english";
  const ui = stageUi(view, { direct, hintOpen: showHint });

  // The failure a banner shows: this tab's own, else one the view reports.
  const failure =
    ended || busy
      ? null
      : outcome?.kind === "failed"
        ? { input: outcome.input, code: outcome.code }
        : outcome === null &&
            storedLive?.state === "failed" &&
            storedLive.failure_code !== "interrupted"
          ? { input: toActionInput(storedLive), code: storedLive.failure_code }
          : null;
  const failurePane = failure === null ? null : paneFor(failure.input.action);
  const composerError =
    outcome?.kind === "invalid" && outcome.field === "text"
      ? outcome.message
      : undefined;
  const gapError =
    outcome?.kind === "invalid" && outcome.field === "gap"
      ? outcome.message
      : undefined;
  const cancelledPane =
    outcome?.kind === "cancelled" && !busy ? paneFor(outcome.action) : null;
  // An auto-sent open or partner_reply that failed, was cancelled, or was
  // interrupted is never sent again by itself: 「もう一度」 is the way on.
  const stuck =
    autoAction !== null &&
    !busy &&
    !ended &&
    failure === null &&
    !unanswered &&
    (autoSent.current === view.version || view.last_submission !== null);

  const failureBanner = (pane: "partner" | "coach") =>
    failure !== null && failurePane === pane ? (
      <Banner
        message={failureLine(pane, failure.code)}
        action={{ label: "もう一度", onClick: () => void send(failure.input) }}
      />
    ) : null;

  const cancelButton = (pane: "partner" | "coach") =>
    waitingPane === pane && longWait ? (
      <button
        type="button"
        disabled={cancelling}
        onClick={() => void cancel()}
        className={SECONDARY_BUTTON}
      >
        中止
      </button>
    ) : null;

  const left = useFollowBottom(`${view.entries.length}:${waitingAction ?? ""}`);
  const right = useFollowBottom(
    `${view.entries.length}:${waitingAction ?? ""}:${showHint}`,
  );

  function runControl(control: Control) {
    if (control.input === "toggle_direct") {
      setDirectTurn(direct ? null : view.turn_index);
    } else if (control.input === "open_hint") {
      setHintOpen(true);
    } else if (control.input.action === "end") {
      void endSession();
    } else {
      void send(control.input);
    }
  }

  function closeHint() {
    focusHintButton.current = true;
    setHintOpen(false);
  }

  const startLabel = formatStart(view.started_at);
  const answering = lineBeingAnswered(view);
  const previous = previousTurnLine(view);
  const allowed = new Set(view.allowed_actions);
  const canRewrite = allowed.has("rewrite_intent");
  const showRewrite = rewriting && canRewrite;
  useEffect(() => {
    if (!canRewrite) setRewriting(false);
  }, [canRewrite]);
  const currentIntent = view.entries.findLast(
    (item) => item.turn_index === view.turn_index && item.kind === "intent",
  );
  const practiceTurn =
    view.stage === "check_in" ? view.turn_index : view.turn_index - 1;
  const practiceFeedback = view.entries.findLast(
    (item) => item.turn_index === practiceTurn && item.kind === "feedback",
  );
  const canPractice =
    allowed.has("practice_again") &&
    practiceFeedback?.kind === "feedback" &&
    practiceFeedback.payload.feedback.template !== null;
  const practicing = practiceOpen && canPractice;
  useEffect(() => {
    if (!canPractice) setPracticeOpen(false);
  }, [canPractice]);
  // The server records this practice under its target, the previous turn.
  // Keep the new result visible beside the current turn without changing it.
  const previousPractice =
    practiceTurn < view.turn_index && answering !== null
      ? view.entries.filter(
          (item) =>
            item.turn_index === practiceTurn &&
            item.seq > answering.seq &&
            (item.kind === "practice" || item.kind === "practice_result"),
        )
      : [];
  function startRewrite() {
    if (currentIntent?.kind !== "intent") return;
    setRewriteText(currentIntent.payload.text);
    setRewriting(true);
    setPracticeOpen(false);
    focusAfterPast.current = "composer";
  }
  const rewriteControl = canRewrite ? (
    <button
      type="button"
      disabled={busy}
      className={QUIET_BUTTON}
      onClick={startRewrite}
    >
      日本語を書き直す
    </button>
  ) : undefined;
  const sideError = (field: "question" | "rewrite" | "practice") =>
    outcome?.kind === "invalid" && outcome.field === field
      ? outcome.message
      : undefined;

  const nextLine =
    waitingPane === "coach"
      ? null
      : waitingPane === "partner"
        ? "Partner の返事を待っています"
        : (ui?.next ?? null);

  const conversationPane = (
    <>
      <h2
        ref={partnerHeadingRef}
        tabIndex={-1}
        className={`text-[13px] font-bold tracking-[0.04em] text-ink-muted ${FOCUS_RING}`}
      >
        会話（Partner が聞いている英語）
      </h2>
      <ConversationTimeline
        entries={view.entries}
        {...(ended ? {} : { onSelectTurn: showPastTurn })}
      />
      {allowed.has("restate") && (
        <div className="flex items-center gap-2 text-sm text-ink-muted">
          <span>言い換え:</span>
          <button
            type="button"
            className={QUIET_BUTTON}
            disabled={busy}
            onClick={() => void send({ action: "restate", mode: "shorter" })}
          >
            短く
          </button>
          <span aria-hidden="true">｜</span>
          <button
            type="button"
            className={QUIET_BUTTON}
            disabled={busy}
            onClick={() => void send({ action: "restate", mode: "simpler" })}
          >
            簡単に
          </button>
        </div>
      )}
      <div role="status" className="text-ink-muted">
        {waitingPane === "partner" && lineShown && (
          <p className={ENTER}>{longWait ? LONG_WAIT : PARTNER_WAITING}</p>
        )}
        {cancelledPane === "partner" && <p>{CANCELLED}</p>}
      </div>
      {cancelButton("partner")}
      {failureBanner("partner")}
      {stuck && autoAction !== null && (
        <button
          ref={againRef}
          type="button"
          onClick={() => void send({ action: autoAction })}
          className={SECONDARY_BUTTON}
        >
          もう一度
        </button>
      )}
    </>
  );

  // Shown under whichever turn the Coach pane holds, the current or a past one.
  const coachErrors = (
    <>
      {failureBanner("coach")}
      {endError?.kind === "problem" && (
        <Banner
          message="会話を終えられませんでした。"
          requestId={endError.requestId}
          action={{
            label: "もう一度",
            onClick: () => void endSession(),
            disabled: endPending,
          }}
        />
      )}
    </>
  );

  const coachPane =
    pastTurn !== null && !ended ? (
      <>
        <h2
          ref={coachHeadingRef}
          tabIndex={-1}
          className={`text-[13px] font-bold tracking-[0.04em] text-ink-muted ${FOCUS_RING}`}
        >
          コーチ · ターン {pastTurn}
        </h2>
        <button
          ref={backToTurnRef}
          type="button"
          onClick={backToCurrentTurn}
          className={SECONDARY_BUTTON}
        >
          今のターンに戻る
        </button>
        <TurnTimeline timeline={view.entries} turn={pastTurn} />
        {coachErrors}
      </>
    ) : (
      <>
        <h2
          ref={coachHeadingRef}
          tabIndex={-1}
          className={`text-[13px] font-bold tracking-[0.04em] text-ink-muted ${FOCUS_RING}`}
        >
          コーチ · ターン {view.turn_index}
        </h2>
        {!wide && !ended && answering !== null && (
          <div className="space-y-1 border-b border-line pb-3">
            <p className="text-xs font-bold text-partner-ink">🗣 返事をする発言</p>
            <p lang="en" className={COACH_ENGLISH}>
              {answering.payload.text}
            </p>
          </div>
        )}
        {view.turn_index === 1 && !ended && (
          <div className="space-y-2">
            <button
              type="button"
              aria-expanded={howToOpen}
              aria-controls={`${ids}-howto`}
              onClick={() => setHowToOpen((open) => !open)}
              className={`${QUIET_BUTTON} font-bold text-ink`}
            >
              <span aria-hidden="true">{howToOpen ? "▾ " : "▸ "}</span>
              進め方
            </button>
            {howToOpen && (
              <div
                id={`${ids}-howto`}
                className="space-y-1 text-sm transition-opacity duration-200 starting:opacity-0 motion-reduce:transition-none"
              >
                {HOW_TO.map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
            )}
          </div>
        )}
        {(previous !== null || canPractice) && (
          <div className="flex flex-wrap items-center gap-2">
            {previous !== null && <p className="text-sm text-ink-muted">{previous}</p>}
            {canPractice && (
              <button
                type="button"
                disabled={busy}
                className={QUIET_BUTTON}
                onClick={() => {
                  setPracticeOpen(true);
                  setRewriting(false);
                  focusAfterPast.current = "composer";
                }}
              >
                もう一度練習
              </button>
            )}
          </div>
        )}
        {previousPractice.length > 0 && (
          <section aria-label="前のターンの練習" className="space-y-2">
            <h3 className="text-xs font-bold">前のターンの練習</h3>
            <TurnTimeline
              timeline={previousPractice}
              turn={practiceTurn}
              fresh={arrival.ids}
            />
          </section>
        )}
        <TurnTimeline
          timeline={view.entries}
          turn={view.turn_index}
          fresh={arrival.ids}
          intentControl={rewriteControl}
        />
        {allowed.has("ask") && (
          <CoachQuestion
            disabled={busy}
            error={sideError("question")}
            open={questionOpen}
            onOpenChange={setQuestionOpen}
            text={questionText}
            onTextChange={setQuestionText}
            onSend={(question) => send({ action: "ask", text: question })}
          />
        )}
        {coachErrors}
      </>
    );

  const footer = ui !== null && !viewingPast && (
    <div className="space-y-3 bg-surface px-4 pt-3 pb-4 shadow-[0_-1px_0_var(--color-line)] lg:px-5">
      <div role="status" className="space-y-1">
        {waitingPane === "coach" ? (
          lineShown && (
            <p className="text-ink-muted">{longWait ? LONG_WAIT : COACH_WAITING}</p>
          )
        ) : (
          <>
            {cancelledPane === "coach" && <p className="text-ink-muted">{CANCELLED}</p>}
            {nextLine !== null && <p className="font-bold">{`👉 次: ${nextLine}`}</p>}
          </>
        )}
      </div>
      {cancelButton("coach")}
      {practiceOpen && canPractice && practiceFeedback?.kind === "feedback" ? (
        <div className="space-y-2">
          <p className="text-xs font-bold">穴埋め</p>
          <p lang="en" className={COACH_ENGLISH}>
            {practiceFeedback.payload.feedback.template}
          </p>
          <Composer
            textareaRef={composerRef}
            label="もう一度練習"
            lang="en"
            value={practiceText}
            onChange={setPracticeText}
            disabled={busy}
            error={sideError("practice")}
            onSend={() => void send({ action: "practice_again", text: practiceText })}
          />
          <button
            type="button"
            disabled={busy}
            className={QUIET_BUTTON}
            onClick={() => {
              setPracticeOpen(false);
              focusAfterPast.current = "composer";
            }}
          >
            やめる
          </button>
        </div>
      ) : showRewrite ? (
        <div className="space-y-2">
          <Composer
            textareaRef={composerRef}
            label="あなたの日本語"
            lang="ja"
            value={rewriteText}
            onChange={setRewriteText}
            disabled={busy}
            error={sideError("rewrite")}
            onSend={() => void send({ action: "rewrite_intent", text: rewriteText })}
          />
          <button
            type="button"
            disabled={busy}
            className={QUIET_BUTTON}
            onClick={() => {
              setRewriting(false);
              focusAfterPast.current = "composer";
            }}
          >
            やめる
          </button>
        </div>
      ) : (
        ui.composer !== null && (
          <Composer
            textareaRef={composerRef}
            label={ui.composer.label}
            placeholder={ui.composer.placeholder}
            lang={ui.composer.lang}
            value={text}
            onChange={setText}
            disabled={busy || ui.composer.waiting}
            error={composerError}
            onSend={() => {
              const composer = ui.composer;
              if (composer !== null) void send({ action: composer.action, text });
            }}
          />
        )
      )}
      {showHint && !showRewrite && !practicing && (
        <HintRequest
          inputRef={gapRef}
          value={gap}
          onChange={setGap}
          disabled={busy}
          error={gapError}
          onCancel={closeHint}
          onSubmit={() => void send({ action: "hint", gap, partial_english: text })}
        />
      )}
      {!busy && !showRewrite && !practicing && ui.controls.length > 0 && (
        <fieldset
          ref={controlsRef}
          aria-label="操作"
          className="flex min-w-0 flex-wrap gap-2"
        >
          {ui.controls.map((control) => (
            <button
              key={control.key}
              ref={control.key === "hint" ? hintButtonRef : undefined}
              type="button"
              aria-pressed={control.pressed}
              onClick={() => runControl(control)}
              className={SECONDARY_BUTTON}
            >
              {control.label}
            </button>
          ))}
        </fieldset>
      )}
    </div>
  );

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const target: Tab =
      event.key === "Home"
        ? "conversation"
        : event.key === "End"
          ? "coach"
          : tab === "coach"
            ? "conversation"
            : "coach";
    select(target);
    tabRefs.current[target]?.focus();
  }

  function select(target: Tab) {
    setTab(target);
    if (target === "conversation") setUnread(false);
  }

  const leftScroll = (
    <div
      ref={left.ref}
      onScroll={left.onScroll}
      className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 motion-safe:scroll-smooth lg:p-5"
    >
      {conversationPane}
    </div>
  );
  const rightScroll = (
    <div
      ref={right.ref}
      onScroll={right.onScroll}
      data-testid="coach-scroll"
      className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 motion-safe:scroll-smooth lg:p-5"
    >
      {outcome?.kind === "stale" && <Banner message={STALE} />}
      {coachPane}
    </div>
  );

  return (
    <>
      <HeaderItems>
        {backLink}
        <span className="min-w-0 truncate text-[13px] text-ink-muted tabular-nums">
          <span className="max-lg:hidden">{`${startLabel} から · `}</span>
          {`${view.finished_replies}往復`}
        </span>
        {view.allowed_actions.includes("end") && (
          <span className="ml-auto shrink-0">
            <EndSession ending={endPending} onEnd={() => void endSession()} />
          </span>
        )}
      </HeaderItems>
      <h1 className="sr-only">{`${startLabel} からの会話`}</h1>
      <div role="status" aria-label="お知らせ" aria-atomic="true" className="sr-only">
        {arrival.message !== "" && <span key={arrival.key}>{arrival.message}</span>}
      </div>
      <div data-fill-viewport="" className="flex min-h-0 flex-1 flex-col">
        {notice}
        {wide ? (
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(360px,42fr)_minmax(480px,58fr)]">
            <section
              aria-label="会話"
              className="flex min-h-0 flex-col border-r border-line bg-canvas"
            >
              {leftScroll}
            </section>
            <section aria-label="コーチ" className="flex min-h-0 flex-col bg-surface">
              {rightScroll}
              {footer}
            </section>
          </div>
        ) : (
          <>
            <div
              role="tablist"
              aria-label="会話とコーチ"
              className="flex shrink-0 gap-1 border-b border-line bg-canvas px-2"
            >
              {(["conversation", "coach"] as const).map((name) => (
                <button
                  key={name}
                  ref={(element) => {
                    tabRefs.current[name] = element;
                  }}
                  type="button"
                  role="tab"
                  id={`${ids}-tab-${name}`}
                  aria-selected={tab === name}
                  aria-controls={`${ids}-panel-${name}`}
                  tabIndex={tab === name ? 0 : -1}
                  onClick={() => select(name)}
                  onKeyDown={onTabKey}
                  className={`relative inline-flex min-h-11 items-center gap-1 border-b-2 px-4 font-bold ${tab === name ? "border-ink text-ink" : "border-transparent text-ink-muted"} ${FOCUS_RING}`}
                >
                  {name === "conversation" ? "会話" : "コーチ"}
                  {name === "conversation" && unread && (
                    <>
                      <span
                        aria-hidden="true"
                        className="size-2 rounded-full bg-partner-ink"
                      />
                      <span className="sr-only">（新しい発言）</span>
                    </>
                  )}
                </button>
              ))}
            </div>
            <section
              role="tabpanel"
              id={`${ids}-panel-conversation`}
              aria-labelledby={`${ids}-tab-conversation`}
              hidden={tab !== "conversation"}
              className="flex min-h-0 flex-1 flex-col bg-canvas transition-opacity duration-100 starting:opacity-0"
            >
              {leftScroll}
            </section>
            <section
              role="tabpanel"
              id={`${ids}-panel-coach`}
              aria-labelledby={`${ids}-tab-coach`}
              hidden={tab !== "coach"}
              className="flex min-h-0 flex-1 flex-col bg-surface transition-opacity duration-100 starting:opacity-0"
            >
              {rightScroll}
              {footer}
            </section>
          </>
        )}
      </div>
    </>
  );
}

/** Loading the session: three skeleton blocks in each pane's place. */
export function ConversationSkeleton() {
  return (
    <div
      data-fill-viewport=""
      className="grid min-h-0 flex-1 lg:grid-cols-[minmax(360px,42fr)_minmax(480px,58fr)]"
    >
      <p role="status" className="sr-only">
        読み込んでいます…
      </p>
      {["canvas", "surface"].map((surface) => (
        <div
          key={surface}
          aria-hidden="true"
          className={`space-y-3 p-5 ${surface === "canvas" ? "hidden bg-canvas lg:block" : "bg-surface"}`}
        >
          {[0, 1, 2].map((block) => (
            <div
              key={block}
              className="h-16 rounded-panel bg-line motion-safe:animate-pulse"
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * 「この会話を読み込めませんでした。」 with [再読み込み]: in place of the panes
 * when the session never loaded, or above them when reading it again failed.
 */
export function ConversationLoadError({
  retrying,
  onRetry,
}: {
  retrying: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="p-4">
      <Banner
        message="この会話を読み込めませんでした。"
        action={{ label: "再読み込み", onClick: onRetry, disabled: retrying }}
      />
    </div>
  );
}
