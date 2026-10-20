import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useEffectEvent,
  useId,
  useRef,
  useState,
} from "react";
import {
  cancelSessionActionMutation,
  performSessionActionMutation,
} from "../../api/generated/@tanstack/react-query.gen";
import type { Action, SessionResponse } from "../../api/generated/types.gen";
import { Banner } from "../../lib/Banner";
import { settleAfterMinimum, useDelayedLoading } from "../../lib/delayed-loading";
import { ErrorMessage } from "../../lib/ErrorMessage";
import { formatStart } from "../../lib/format";
import { HeaderItems } from "../../lib/HeaderItems";
import { type ApiError, toApiError } from "../../lib/problem-details";
import { useServerStatus } from "../../lib/ServerStatus";
import {
  modelFailureReason,
  SUBMISSION_POLL_MS,
  submissionPending,
} from "../../lib/submission";
import {
  COACH_ENGLISH,
  ENTER,
  FOCUS_RING,
  QUIET_BUTTON,
  SECONDARY_BUTTON,
} from "../../lib/ui";
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
  hasMatchingSubmission,
  hasRecordedInput,
  lineBeingAnswered,
  paneFor,
  previousTurnLine,
  restoredFields,
  type SessionView,
  sessionQueryOptions,
  stageUi,
  toActionInput,
} from "./session";

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

/** Conflicts that mean the shown view is out of date: read it again, then say so. */
const STALE_CODES: ReadonlySet<string> = new Set([
  "stale_session",
  "action_in_progress",
  "action_not_allowed",
]);

/** The keys this screen reports a request with no response under. */
const UNANSWERED = {
  action: "session-action",
  cancel: "session-cancel",
  end: "session-end",
};

const HOW_TO = [
  "1. 返したいことを、まず日本語で送ってください",
  "2. それを自分で英語にしてみてください（途中まででOK。詰まったら「ヒント」）",
  "3. 最初から英語で返すときは「英語で直接返す」",
  "4. 「答えを見せて」「スキップ」「会話を終える」はいつでも使えます",
];

type Tab = "conversation" | "coach";

/** One request this tab is waiting for. */
interface Attempt {
  id: number;
  input: ActionInput;
  /** The version the action answers, which a cancel names. */
  version: number;
  /** Last timeline entry before this send, excluding older identical input. */
  afterSeq: number;
  /** The stored record before this send cannot prove this request arrived. */
  storedKey: string | null;
  /** [中止] was pressed and its 204 has not arrived yet. */
  cancelling: boolean;
}

/** How the last action this tab sent (or cancelled) ended, while it matters. */
type Outcome =
  | { kind: "failed"; input: ActionInput; code: string | undefined }
  | { kind: "invalid"; field: "text" | "gap"; message: string }
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
  return stored === null ? {} : restoredFields(stored.input);
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
  const queryClient = useQueryClient();
  const sessionKey = sessionQueryOptions(view.id).queryKey;
  const status = useServerStatus();
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
  /** A past turn the learner selected on the left, shown read-only on the right. */
  const [pastTurn, setPastTurn] = useState<number | null>(null);
  const [attempt, setAttemptState] = useState<Attempt | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [endError, setEndError] = useState<ApiError | null>(null);
  /** The stored submission this tab has since sent over or cancelled. */
  const [settledKey, setSettledKey] = useState<string | null>(null);
  /** Counts cleared markers: a stored wait's clock restarts for each new one. */
  const [storedRound, setStoredRound] = useState(0);
  const [cancellingStored, setCancellingStored] = useState<string | null>(null);
  /** The last action got no response: the layout's [再試行] is its way on. */
  const [unanswered, setUnanswered] = useState<Attempt | null>(null);
  const backToTurnRef = useRef<HTMLButtonElement>(null);
  /** Where focus goes once the next render is shown, as a control goes away. */
  const focusAfterPast = useRef<"back" | "composer" | "again" | null>(null);
  const againRef = useRef<HTMLButtonElement>(null);
  const coachHeadingRef = useRef<HTMLHeadingElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const gapRef = useRef<HTMLInputElement>(null);
  const controlsRef = useRef<HTMLFieldSetElement>(null);
  const hintButtonRef = useRef<HTMLButtonElement>(null);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({
    conversation: null,
    coach: null,
  });
  // The request being waited for, read by settling requests: a second send can
  // arrive before React renders the disabled state, and a cancelled or
  // superseded request's late answer must find it gone.
  const attemptRef = useRef<Attempt | null>(null);
  const receivedAttempt = useRef<Attempt | null>(null);
  const attempts = useRef(0);
  const autoSent = useRef<number | null>(null);
  /** The version of a result that should take focus once it is shown. */
  const focusOnResult = useRef<number | null>(null);
  const focusHintButton = useRef(false);
  const latestVersion = useRef(view.version);
  const stored = view.last_submission;
  const storedKey =
    stored === null ? null : `${view.version}:${JSON.stringify(stored)}`;

  // A later read can prove that a request whose response was lost did land.
  // Drop its retry before it can resend old input at the newer stage.
  useEffect(() => {
    if (unanswered === null) return;
    const advanced = view.version > unanswered.version;
    if (
      !advanced &&
      (storedKey === unanswered.storedKey ||
        !hasMatchingSubmission(view.last_submission, unanswered.input))
    )
      return;
    const input = unanswered.input;
    if (!advanced && view.last_submission?.state === "pending")
      receivedAttempt.current = unanswered;
    setUnanswered(null);
    status.resolve(UNANSWERED.action);
    const consumed = hasRecordedInput(view, input, unanswered.afterSeq);
    if (consumed && COMPOSER_ACTIONS.has(input.action) && "text" in input) {
      // The learner may have edited the now-enabled field since the failure.
      setText((current) => (current === input.text ? "" : current));
    }
    if (consumed && input.action === "hint") {
      setGap((current) => (current === input.gap ? "" : current));
      if (gap === input.gap) setHintOpen(false);
    }
    focusOnResult.current = view.version;
  }, [unanswered, view, status, gap, storedKey]);

  /** Whether the request `id` is still the one being waited for. */
  function waitingFor(id: number) {
    return attemptRef.current?.id === id;
  }

  function setAttempt(next: Attempt | null) {
    attemptRef.current = next;
    setAttemptState(next);
  }

  const storedLive = stored !== null && storedKey !== settledKey ? stored : null;
  // The marker holds only while the view still shows that submission: a later
  // one with the same version, action, and state is another submission.
  useEffect(() => {
    if (settledKey !== null && storedKey !== settledKey) setSettledKey(null);
  }, [settledKey, storedKey]);
  // A submission the server still runs that this tab did not send (a reload,
  // another tab): wait for it, reading the session every 2 s.
  const storedPending =
    attempt === null && storedLive?.state === "pending" ? storedLive : null;

  useQuery({
    ...sessionQueryOptions(view.id),
    refetchInterval: (query) =>
      submissionPending(query.state.data) && attemptRef.current === null
        ? SUBMISSION_POLL_MS
        : false,
  });

  async function writeView(next: SessionResponse) {
    // A result for an older version (an action an `end` superseded) never
    // replaces a newer view.
    queryClient.setQueryData<SessionResponse>(sessionKey, (old) =>
      old === undefined || next.version >= old.version ? next : old,
    );
    await queryClient.invalidateQueries({ queryKey: [{ _id: "listSessions" }] });
  }

  const readAgain = () => queryClient.invalidateQueries({ queryKey: sessionKey });

  const action = useMutation({
    ...performSessionActionMutation(),
    // A read that started before the action must not overwrite its result.
    onMutate: () => queryClient.cancelQueries({ queryKey: sessionKey }),
  });
  const cancelAction = useMutation(cancelSessionActionMutation());
  const end = useMutation({
    ...performSessionActionMutation(),
    onMutate: () => queryClient.cancelQueries({ queryKey: sessionKey }),
  });

  async function send(input: ActionInput) {
    if (attemptRef.current !== null) return;
    receivedAttempt.current = null;
    attempts.current += 1;
    const sent: Attempt = {
      id: attempts.current,
      input,
      version: view.version,
      afterSeq: view.entries.at(-1)?.seq ?? 0,
      storedKey,
      cancelling: false,
    };
    setAttempt(sent);
    setOutcome(null);
    setSettledKey(storedKey);
    setUnanswered(null);
    status.resolve(UNANSWERED.action);
    let next: SessionResponse;
    try {
      // A slow answer waits out the waiting line's 500 ms minimum.
      next = await settleAfterMinimum(() =>
        action.mutateAsync({
          path: { session_id: view.id },
          body: { ...input, version: sent.version },
        }),
      );
    } catch (error) {
      if (waitingFor(sent.id)) await fail(sent, toApiError(error));
      return;
    }
    // Cancelled, or superseded by `end`: the answer is discarded.
    if (!waitingFor(sent.id)) return;
    setAttempt(null);
    if (COMPOSER_ACTIONS.has(input.action) && "text" in input)
      setText((current) => (current === input.text ? "" : current));
    if (input.action === "hint") {
      setGap((current) => (current === input.gap ? "" : current));
      if (gap === input.gap) setHintOpen(false);
    }
    focusOnResult.current = next.version;
    await writeView(next);
  }

  async function fail(sent: Attempt, error: ApiError) {
    const code = error.kind === "problem" ? error.code : undefined;
    if (code === "action_cancelled") {
      // Ours: the cancel's 204 finishes it. Another tab's: read what it did.
      if (attemptRef.current?.cancelling === true) return;
      setAttempt(null);
      await readAgain();
      return;
    }
    setAttempt(null);
    if (error.kind === "unknown") {
      setUnanswered(sent);
      status.report(UNANSWERED.action, () => void latest.current.send(sent.input));
      return;
    }
    if (code !== undefined && STALE_CODES.has(code)) {
      await readAgain();
      setOutcome({ kind: "stale" });
      return;
    }
    if (code === "session_ended") {
      await readAgain();
      return;
    }
    const field =
      sent.input.action === "hint"
        ? "gap"
        : COMPOSER_ACTIONS.has(sent.input.action)
          ? "text"
          : null;
    const message =
      error.status === 422 && field !== null ? fieldMessage(error, field) : undefined;
    setOutcome(
      field !== null && message !== undefined
        ? { kind: "invalid", field, message }
        : { kind: "failed", input: sent.input, code },
    );
  }

  async function cancel() {
    const current = attemptRef.current;
    if (current !== null) {
      if (current.cancelling) return;
      setAttempt({ ...current, cancelling: true });
      try {
        await cancelAction.mutateAsync({
          path: { session_id: view.id },
          body: { version: current.version },
        });
      } catch (error) {
        const now = attemptRef.current;
        if (now?.id !== current.id) return;
        setAttempt({ ...now, cancelling: false });
        if (toApiError(error).kind === "unknown") {
          status.report(UNANSWERED.cancel, () => void latest.current.cancel());
        }
        return;
      }
      // The result came first and is shown: nothing was cancelled.
      if (!waitingFor(current.id)) return;
      focusAfterCancel();
      setAttempt(null);
      setOutcome({ kind: "cancelled", action: current.input.action });
      return;
    }
    const pending = storedPending;
    if (pending === null || cancellingStored === storedKey) return;
    const version = view.version;
    setCancellingStored(storedKey);
    try {
      await cancelAction.mutateAsync({
        path: { session_id: view.id },
        body: { version },
      });
    } catch (error) {
      setCancellingStored(null);
      if (toApiError(error).kind === "unknown") {
        status.report(UNANSWERED.cancel, () => void latest.current.cancel());
      }
      return;
    }
    setCancellingStored(null);
    // The stored result arrived first and is shown: nothing was cancelled.
    if (latestVersion.current !== version) return;
    focusAfterCancel();
    setSettledKey(storedKey);
    const fields = restoredFields(pending.input);
    if (fields.text !== undefined) setText(fields.text);
    if (fields.gap !== undefined) {
      setGap(fields.gap);
      setHintOpen(true);
    }
    setOutcome({ kind: "cancelled", action: pending.action });
    const asked = Date.now();
    await readAgain();
    // The server cancelled before its 204, so a pending submission this read
    // shows is a new one, even at the same version and action: wait for it.
    const read = queryClient.getQueryState(sessionKey);
    if (read?.status === "success" && read.dataUpdatedAt >= asked) {
      setSettledKey(null);
      setStoredRound((round) => round + 1);
    }
  }

  /** [中止] goes away: focus the way on, never the document body. */
  function focusAfterCancel() {
    focusAfterPast.current = autoAction !== null ? "again" : "composer";
  }

  async function endSession() {
    setEndError(null);
    status.resolve(UNANSWERED.end);
    try {
      const next = await end.mutateAsync({
        path: { session_id: view.id },
        body: { action: "end", version: view.version },
      });
      // Ending supersedes the request in flight: its answer is discarded.
      setAttempt(null);
      setOutcome(null);
      await writeView(next);
    } catch (caught) {
      const error = toApiError(caught);
      const code = error.kind === "problem" ? error.code : undefined;
      if (error.kind === "unknown") {
        status.report(UNANSWERED.end, () => void latest.current.endSession());
      } else if (code !== undefined && STALE_CODES.has(code)) {
        await readAgain();
        setOutcome({ kind: "stale" });
      } else if (code === "session_ended") {
        await readAgain();
      } else {
        setEndError(error);
      }
    }
  }

  // What a retry from the layout's banner calls: this render's functions,
  // which send at the version shown then.
  const latest = useRef({ send, cancel, endSession });
  useEffect(() => {
    latest.current = { send, cancel, endSession };
    latestVersion.current = view.version;
  });
  useEffect(
    () => () => {
      for (const key of Object.values(UNANSWERED)) status.resolve(key);
    },
    [status],
  );

  // A stored submission that appears later (a polled one settling failed or
  // interrupted, another tab's) puts its text back too, unless the learner has
  // typed since. A pending one this tab waited for that completes is a result
  // like this tab's own: its text is cleared and the composer takes focus.
  const watched = useRef({
    key: storedKey,
    version: view.version,
    pending: stored,
    afterSeq: view.entries.at(-1)?.seq ?? 0,
  });
  const followStored = useEffectEvent(() => {
    const before = watched.current;
    watched.current = {
      key: storedKey,
      version: view.version,
      pending: stored,
      afterSeq: view.entries.at(-1)?.seq ?? 0,
    };
    if (before.key === storedKey) return;
    const completed =
      before.pending?.state === "pending" &&
      view.last_submission === null &&
      view.version > before.version;
    if (completed && before.pending !== null) {
      const received = receivedAttempt.current;
      const input =
        received !== null &&
        received.version === before.version &&
        hasMatchingSubmission(before.pending, received.input)
          ? received.input
          : toActionInput(before.pending);
      receivedAttempt.current = null;
      if (hasRecordedInput(view, input, before.afterSeq)) {
        if (COMPOSER_ACTIONS.has(input.action) && "text" in input)
          setText((current) => (current === input.text ? "" : current));
        if (input.action === "hint") {
          setGap((current) => (current === input.gap ? "" : current));
          if (gap === input.gap) setHintOpen(false);
        }
      }
      focusOnResult.current = view.version;
      return;
    }
    const fields = restoredFrom(view);
    if (fields.text !== undefined) {
      const restored = fields.text;
      setText((previous) => (previous === "" ? restored : previous));
    }
    if (fields.gap !== undefined) {
      const restored = fields.gap;
      setGap((previous) => (previous === "" ? restored : previous));
    }
  });
  useEffect(() => {
    const before = watched.current;
    if (before.key === storedKey && before.version === view.version) return;
    followStored();
  }, [storedKey, view.version]);

  const waitingAction = attempt?.input.action ?? storedPending?.action;
  const busy = waitingAction !== undefined;
  const waitingPane = waitingAction === undefined ? null : paneFor(waitingAction);
  const waitKey =
    attempt !== null
      ? `sent:${attempt.id}`
      : storedPending !== null
        ? `stored:${storedRound}:${storedKey}`
        : null;
  const lineShown = useDelayedLoading(busy) && busy;
  // Nothing left to cancel: a cancel that got no response needs no 再試行.
  useEffect(() => {
    if (!busy) status.resolve(UNANSWERED.cancel);
  }, [busy, status]);
  const longWait = useAfter(waitKey, LONG_WAIT_MS);
  const cancelling =
    attempt?.cancelling === true ||
    (storedPending !== null && cancellingStored === storedKey);
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
  const nextLine =
    waitingPane === "coach"
      ? null
      : waitingPane === "partner"
        ? "Partner の返事を待っています"
        : (ui?.next ?? null);

  const conversationPane = (
    <>
      <h2 className="text-[13px] font-bold tracking-[0.04em] text-ink-muted">
        会話（Partner が聞いている英語）
      </h2>
      <ConversationTimeline
        entries={view.entries}
        {...(ended ? {} : { onSelectTurn: showPastTurn })}
      />
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
      {endError !== null && <ErrorMessage error={endError} />}
    </>
  );

  const coachPane =
    pastTurn !== null && !ended ? (
      <>
        <h2 className="text-[13px] font-bold tracking-[0.04em] text-ink-muted">
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
        {previous !== null && <p className="text-sm text-ink-muted">{previous}</p>}
        <TurnTimeline
          timeline={view.entries}
          turn={view.turn_index}
          fresh={arrival.ids}
        />
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
      {ui.composer !== null && (
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
      )}
      {showHint && (
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
      {!busy && ui.controls.length > 0 && (
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
            <EndSession ending={end.isPending} onEnd={() => void endSession()} />
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
