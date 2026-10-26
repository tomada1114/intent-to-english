import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  cancelSessionActionMutation,
  performSessionActionMutation,
} from "../../api/generated/@tanstack/react-query.gen";
import type { Action, SessionResponse } from "../../api/generated/types.gen";
import { settleAfterMinimum } from "../../lib/delayed-loading";
import { type ApiError, toApiError } from "../../lib/problem-details";
import { useServerStatus } from "../../lib/ServerStatus";
import { SUBMISSION_POLL_MS, submissionPending } from "../../lib/submission";
import {
  type ActionInput,
  hasRecordedInput,
  type SessionView,
  sessionQueryOptions,
  toActionInput,
} from "./session";

/** Transport events leave editor settlement, field errors and focus to the screen. */
export type SessionActionEvent =
  | { kind: "started" }
  | { kind: "consumed"; input: ActionInput; version: number }
  | { kind: "result"; version: number }
  | { kind: "restore"; input: ActionInput; mode: "empty" | "cancelled" }
  | { kind: "failed"; input: ActionInput; error: ApiError }
  | { kind: "cancelled"; action: Action }
  | { kind: "stale"; restoreFocus: boolean }
  | { kind: "ending"; retry: boolean };

/** One request this tab is waiting for. */
interface Attempt {
  id: number;
  attemptId: string;
  input: ActionInput;
  /** The conversation version shared by action admission and exact cancellation. */
  version: number;
  /** Last timeline entry before this send, excluding older identical input. */
  afterSeq: number;
  /** The stored record before this send cannot prove this request arrived. */
  storedKey: string | null;
  /** [中止] was pressed and its 204 has not arrived yet. */
  cancelling: boolean;
}

/** Conflicts that mean the shown view is out of date: read it again, then say so. */
const STALE_CODES: ReadonlySet<string> = new Set([
  "stale_session",
  "action_in_progress",
  "action_not_allowed",
  "attempt_already_used",
]);

/** The keys this screen reports a request with no response under. */
const UNANSWERED = {
  action: "session-action",
  cancel: "session-cancel",
  end: "session-end",
};

/** Own request identity and recovery while publishing results to the server-view cache. */
export function useSessionActions(
  view: SessionView,
  onEvent: (event: SessionActionEvent) => void,
) {
  const queryClient = useQueryClient();
  const sessionKey = sessionQueryOptions(view.id).queryKey;
  const status = useServerStatus();
  // Async completions observe the latest committed editor policy, including edits
  // made after a failed request. Never publish callbacks from an abandoned render.
  const events = useRef(onEvent);
  useLayoutEffect(() => {
    events.current = onEvent;
  });
  const emit = useCallback((event: SessionActionEvent) => events.current(event), []);
  const [attempt, setAttemptState] = useState<Attempt | null>(null);
  const [endError, setEndError] = useState<ApiError | null>(null);
  const [settledKey, setSettledKey] = useState<string | null>(null);
  const [storedRound, setStoredRound] = useState(0);
  const [cancellingStored, setCancellingStored] = useState<string | null>(null);
  const [unanswered, setUnanswered] = useState<Attempt | null>(null);
  const attemptRef = useRef<Attempt | null>(null);
  const receivedAttempt = useRef<Attempt | null>(null);
  const attempts = useRef(0);
  const ending = useRef(false);
  const endAttempt = useRef<{ id: string; version: number } | null>(null);
  const latestVersion = useRef(view.version);
  const stored = view.last_submission;
  const storedKey = stored === null ? null : `${stored.attempt_id}:${stored.state}`;
  // A later read can prove that a request whose response was lost did land.
  // Drop its retry before it can resend old input at the newer stage.
  useEffect(() => {
    if (unanswered === null) return;
    const advanced = view.version > unanswered.version;
    if (
      !advanced &&
      (storedKey === unanswered.storedKey ||
        view.last_submission?.attempt_id !== unanswered.attemptId)
    )
      return;
    const input = unanswered.input;
    if (!advanced && view.last_submission?.state === "pending")
      receivedAttempt.current = unanswered;
    setUnanswered(null);
    status.resolve(UNANSWERED.action);
    const consumed = hasRecordedInput(view, input, unanswered.afterSeq);
    if (consumed) emit({ kind: "consumed", input, version: view.version });
    emit({ kind: "result", version: view.version });
  }, [unanswered, view, status, storedKey, emit]);

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
  // one has its own correlation ID even with identical version, input and state.
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

  async function send(input: ActionInput, retry?: Attempt) {
    if (retry !== undefined && retry.version !== view.version) {
      await readAgain();
      return false;
    }
    if (attemptRef.current !== null) return false;
    receivedAttempt.current = unanswered;
    attempts.current += 1;
    const sent: Attempt = {
      id: attempts.current,
      attemptId: retry?.attemptId ?? crypto.randomUUID(),
      input,
      version: view.version,
      afterSeq: view.entries.at(-1)?.seq ?? 0,
      storedKey,
      cancelling: false,
    };
    setAttempt(sent);
    emit({ kind: "started" });
    setSettledKey(storedKey);
    setUnanswered(null);
    status.resolve(UNANSWERED.action);
    let next: SessionResponse;
    try {
      // A slow answer waits out the waiting line's 500 ms minimum.
      next = await settleAfterMinimum(() =>
        action.mutateAsync({
          path: { session_id: view.id },
          body: { ...input, version: sent.version, attempt_id: sent.attemptId },
        }),
      );
    } catch (error) {
      if (waitingFor(sent.id)) await fail(sent, toApiError(error));
      return false;
    }
    // Cancelled, or superseded by `end`: the answer is discarded.
    if (!waitingFor(sent.id)) return false;
    setAttempt(null);
    emit({ kind: "consumed", input, version: next.version });
    await writeView(next);
    return true;
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
      status.report(
        UNANSWERED.action,
        () => void latest.current.send(sent.input, sent),
      );
      return;
    }
    if (code !== undefined && STALE_CODES.has(code)) {
      await readAgain();
      emit({ kind: "stale", restoreFocus: true });
      return;
    }
    if (code === "session_ended") {
      await readAgain();
      return;
    }
    emit({ kind: "failed", input: sent.input, error });
  }

  async function cancel(target?: { version: number; attemptId: string }) {
    const current = attemptRef.current;
    // A retry belongs to its original target even if another tab replaced it.
    if (
      target !== undefined &&
      target.attemptId !== (current?.attemptId ?? storedPending?.attempt_id)
    ) {
      try {
        await cancelAction.mutateAsync({
          path: { session_id: view.id },
          body: { version: target.version, attempt_id: target.attemptId },
        });
        status.resolve(UNANSWERED.cancel);
        await readAgain();
      } catch (error) {
        if (toApiError(error).kind === "unknown")
          status.report(UNANSWERED.cancel, () => void latest.current.cancel(target));
      }
      return;
    }
    if (current !== null) {
      if (current.cancelling) return;
      setAttempt({ ...current, cancelling: true });
      try {
        await cancelAction.mutateAsync({
          path: { session_id: view.id },
          body: { version: current.version, attempt_id: current.attemptId },
        });
      } catch (error) {
        const now = attemptRef.current;
        if (now?.id !== current.id) return;
        setAttempt({ ...now, cancelling: false });
        if (toApiError(error).kind === "unknown") {
          status.report(
            UNANSWERED.cancel,
            () =>
              void latest.current.cancel({
                version: current.version,
                attemptId: current.attemptId,
              }),
          );
        }
        return;
      }
      // The result came first and is shown: nothing was cancelled.
      if (!waitingFor(current.id)) return;
      setAttempt(null);
      emit({ kind: "cancelled", action: current.input.action });
      await readAgain();
      return;
    }
    const pending = storedPending;
    if (pending === null || cancellingStored === storedKey) return;
    const version = view.version;
    setCancellingStored(storedKey);
    try {
      await cancelAction.mutateAsync({
        path: { session_id: view.id },
        body: { version, attempt_id: pending.attempt_id },
      });
    } catch (error) {
      setCancellingStored(null);
      if (toApiError(error).kind === "unknown") {
        status.report(
          UNANSWERED.cancel,
          () => void latest.current.cancel({ version, attemptId: pending.attempt_id }),
        );
      }
      return;
    }
    setCancellingStored(null);
    // The stored result arrived first and is shown: nothing was cancelled.
    if (latestVersion.current !== version) return;
    setSettledKey(storedKey);
    emit({ kind: "restore", input: toActionInput(pending), mode: "cancelled" });
    emit({ kind: "cancelled", action: pending.action });
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

  async function endSession() {
    if (ending.current) return;
    ending.current = true;
    emit({ kind: "ending", retry: endError !== null });
    setEndError(null);
    status.resolve(UNANSWERED.end);
    if (endAttempt.current?.version !== view.version)
      endAttempt.current = { id: crypto.randomUUID(), version: view.version };
    try {
      const next = await end.mutateAsync({
        path: { session_id: view.id },
        body: {
          action: "end",
          version: view.version,
          attempt_id: endAttempt.current.id,
        },
      });
      endAttempt.current = null;
      // Ending supersedes the request in flight: its answer is discarded.
      setAttempt(null);
      emit({ kind: "started" });
      await writeView(next);
    } catch (caught) {
      const error = toApiError(caught);
      const code = error.kind === "problem" ? error.code : undefined;
      if (error.kind !== "unknown") endAttempt.current = null;
      if (error.kind === "unknown") {
        status.report(UNANSWERED.end, () => void latest.current.endSession());
      } else if (code !== undefined && STALE_CODES.has(code)) {
        await readAgain();
        emit({ kind: "stale", restoreFocus: false });
      } else if (code === "session_ended") {
        await readAgain();
      } else {
        setEndError(error);
      }
    } finally {
      ending.current = false;
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
    const received = receivedAttempt.current;
    if (received !== null && view.version > received.version) {
      receivedAttempt.current = null;
      const input = received.input;
      if (hasRecordedInput(view, input, received.afterSeq)) {
        emit({ kind: "consumed", input, version: view.version });
      }
    }
    if (before.key === storedKey) return;
    const completed =
      before.pending?.state === "pending" &&
      view.last_submission === null &&
      view.version > before.version;
    if (completed && before.pending !== null) {
      const input =
        received !== null &&
        received.version === before.version &&
        before.pending.attempt_id === received.attemptId
          ? received.input
          : toActionInput(before.pending);
      receivedAttempt.current = null;
      if (hasRecordedInput(view, input, before.afterSeq)) {
        emit({ kind: "consumed", input, version: view.version });
      }
      emit({ kind: "result", version: view.version });
      return;
    }
    if (storedLive !== null)
      emit({ kind: "restore", input: toActionInput(storedLive), mode: "empty" });
  });
  useEffect(() => {
    const before = watched.current;
    if (before.key === storedKey && before.version === view.version) return;
    followStored();
  }, [storedKey, view.version]);

  const waitingAction = attempt?.input.action ?? storedPending?.action;
  const busy = waitingAction !== undefined;
  const waitKey =
    attempt !== null
      ? `sent:${attempt.id}`
      : storedPending !== null
        ? `stored:${storedRound}:${storedKey}`
        : null;
  const cancelling =
    attempt?.cancelling === true ||
    (storedPending !== null && cancellingStored === storedKey);
  useEffect(() => {
    if (!busy) status.resolve(UNANSWERED.cancel);
  }, [busy, status]);

  return {
    send,
    cancel,
    endSession,
    endError,
    endPending: end.isPending,
    storedLive,
    unanswered: unanswered !== null,
    waitingAction,
    busy,
    waitKey,
    cancelling,
  };
}
