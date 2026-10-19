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
import { performSessionActionMutation } from "../../api/generated/@tanstack/react-query.gen";
import type { SessionResponse } from "../../api/generated/types.gen";
import { formatStart, formatTime } from "../../lib/format";
import { HeaderItems } from "../../lib/HeaderItems";
import { toApiError } from "../../lib/problem-details";
import { COACH_ENGLISH, ENTER, FOCUS_RING, SECONDARY_BUTTON } from "../../lib/ui";
import {
  ConversationTimeline,
  type SessionView,
  sessionQueryOptions,
  TurnTimeline,
  useWideLayout,
} from "../conversation";

/** How often a wrap-up another tab or an earlier load started is read again. */
export const WRAP_UP_POLL_MS = 2000;

const REASONS: Readonly<Record<string, string>> = {
  model_timeout: "時間切れ",
  model_rate_limited: "混み合っています",
  model_unavailable: "接続できません",
  model_error: "接続できません",
  model_output_invalid: "返事の形式が正しくありませんでした",
};

/** 「振り返りを作れませんでした（<reason>）。」, without a reason it cannot name. */
export function wrapUpFailureLine(code: string | null | undefined): string {
  const reason = code === null || code === undefined ? undefined : REASONS[code];
  return reason === undefined
    ? "振り返りを作れませんでした。"
    : `振り返りを作れませんでした（${reason}）。`;
}

function codeOf(error: unknown): string | undefined {
  const apiError = toApiError(error);
  return apiError.kind === "problem" ? apiError.code : undefined;
}

/** Any submission still running on the server, which a wrap-up must wait for. */
function submissionPending(view: SessionView | undefined): boolean {
  return view?.last_submission?.state === "pending";
}

interface Turn {
  number: number;
  english: string | null;
}

/** The turns with anything of the learner's or the Coach's, in order. */
function turnsOf(view: SessionView): Turn[] {
  const turns = new Map<number, Turn>();
  for (const item of view.entries) {
    if (item.kind === "partner_line") continue;
    const turn = turns.get(item.turn_index) ?? {
      number: item.turn_index,
      english: null,
    };
    if (item.kind === "turn_done") turn.english = item.payload.english;
    turns.set(item.turn_index, turn);
  }
  return [...turns.values()].sort((a, b) => a.number - b.number);
}

type Tab = "conversation" | "coach";

const PANE_HEADING = "text-[13px] font-bold tracking-[0.04em] text-ink-muted";

/**
 * S3, an ended session read-only: the English conversation straight through
 * on the left; the wrap-up, then every turn collapsed, on the right. While a
 * wrap-up is due the screen asks for it once per version, and shows the
 * waiting line or the failure with [もう一度] in its place.
 */
export function TranscriptScreen({
  view,
  backLink,
}: {
  view: SessionView;
  /** The header's 「← 会話一覧」, which the route supplies as a router link. */
  backLink?: ReactNode;
}) {
  const queryClient = useQueryClient();
  const sessionKey = sessionQueryOptions(view.id).queryKey;
  const wide = useWideLayout();
  const ids = useId();
  const [tab, setTab] = useState<Tab>("coach");
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());
  const rowRefs = useRef(new Map<number, HTMLButtonElement>());
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({
    conversation: null,
    coach: null,
  });
  const focusTurn = useRef<number | null>(null);
  const inFlight = useRef(false);
  const autoSent = useRef<number | null>(null);

  // A wrap-up running elsewhere settles on the server: read it until it does.
  useQuery({
    ...sessionQueryOptions(view.id),
    refetchInterval: (query) =>
      submissionPending(query.state.data) ? WRAP_UP_POLL_MS : false,
  });

  const wrapUp = useMutation({
    ...performSessionActionMutation(),
    onMutate: () => queryClient.cancelQueries({ queryKey: sessionKey }),
    onSuccess: async (next) => {
      queryClient.setQueryData<SessionResponse>(sessionKey, (old) =>
        old === undefined || next.version >= old.version ? next : old,
      );
      await queryClient.invalidateQueries({ queryKey: [{ _id: "listSessions" }] });
    },
    // The server records the failure on the session: read it back.
    onError: () => queryClient.invalidateQueries({ queryKey: sessionKey }),
    onSettled: () => {
      inFlight.current = false;
    },
  });

  function sendWrapUp() {
    if (inFlight.current) return;
    inFlight.current = true;
    wrapUp.mutate({
      path: { session_id: view.id },
      body: { action: "wrap_up", version: view.version },
    });
  }

  const due = view.wrap_up === null;
  const autoSend = useEffectEvent(() => sendWrapUp());
  useEffect(() => {
    if (!due || !view.allowed_actions.includes("wrap_up")) return;
    // Never while a submission runs, never over a wrap-up that failed (the
    // learner retries that), and once per version. Another action's settled
    // failure from before the end does not hold the wrap-up back.
    const last = view.last_submission;
    if (last !== null && (last.state === "pending" || last.action === "wrap_up"))
      return;
    if (autoSent.current === view.version) return;
    autoSent.current = view.version;
    autoSend();
  }, [due, view.allowed_actions, view.last_submission, view.version]);

  useEffect(() => {
    const turn = focusTurn.current;
    if (turn === null) return;
    focusTurn.current = null;
    rowRefs.current.get(turn)?.focus();
  });

  const stored = view.last_submission;
  const failure: string | null = !due
    ? null
    : wrapUp.isPending
      ? null
      : wrapUp.isError
        ? wrapUpFailureLine(codeOf(wrapUp.error))
        : stored !== null && stored.action === "wrap_up" && stored.state !== "pending"
          ? wrapUpFailureLine(stored.failure_code)
          : null;
  const waiting = due && failure === null;

  function toggle(turn: number) {
    setOpen((previous) => {
      const next = new Set(previous);
      if (next.has(turn)) next.delete(turn);
      else next.add(turn);
      return next;
    });
  }

  function selectTurn(turn: number) {
    setOpen((previous) => new Set(previous).add(turn));
    setTab("coach");
    focusTurn.current = turn;
  }

  const turns = turnsOf(view);
  const startLabel = formatStart(view.started_at);
  const endLabel = view.ended_at === null ? "" : `– ${formatTime(view.ended_at)} `;

  const conversationPane = (
    <>
      <h2 className={PANE_HEADING}>会話（英文だけの通し）</h2>
      <ConversationTimeline entries={view.entries} onSelectTurn={selectTurn} />
    </>
  );

  const coachPane = (
    <>
      {(view.wrap_up === null || view.wrap_up.items.length > 0) && (
        <section aria-labelledby={`${ids}-wrap-up`} className="space-y-2">
          <h2 id={`${ids}-wrap-up`} className={PANE_HEADING}>
            この会話で出てきた表現
          </h2>
          <div role="status">
            {waiting && (
              <p className="text-ink-muted">コーチが振り返りを作っています…</p>
            )}
          </div>
          {failure !== null && (
            <div role="alert" className="space-y-2">
              <p className="text-danger">{failure}</p>
              <button type="button" onClick={sendWrapUp} className={SECONDARY_BUTTON}>
                もう一度
              </button>
            </div>
          )}
          {view.wrap_up !== null && (
            <ul className="space-y-2">
              {view.wrap_up.items.map((item) => (
                <li key={`${item.phrase}-${item.note}`} className={ENTER}>
                  <span lang="en" className={`${COACH_ENGLISH} font-bold`}>
                    {item.phrase}
                  </span>
                  <span className="text-sm">（{item.note}）</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      <section
        aria-labelledby={`${ids}-turns`}
        className="space-y-2 border-t border-line pt-3 first:border-t-0 first:pt-0"
      >
        <h2 id={`${ids}-turns`} className={PANE_HEADING}>
          ターンごとのやりとり
        </h2>
        <ul className="space-y-1">
          {turns.map((turn) => {
            const expanded = open.has(turn.number);
            const panel = `${ids}-turn-${turn.number}`;
            return (
              <li key={turn.number}>
                <h3>
                  <button
                    ref={(element) => {
                      if (element === null) rowRefs.current.delete(turn.number);
                      else rowRefs.current.set(turn.number, element);
                    }}
                    type="button"
                    aria-expanded={expanded}
                    aria-controls={panel}
                    onClick={() => toggle(turn.number)}
                    className={`flex min-h-11 w-full items-baseline gap-2 rounded-sm text-left ${FOCUS_RING}`}
                  >
                    <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
                    <span className="shrink-0 font-bold">ターン {turn.number}</span>
                    {turn.english !== null && (
                      <span lang="en" className="min-w-0 truncate font-en">
                        {turn.english}
                      </span>
                    )}
                  </button>
                </h3>
                {expanded && (
                  <div
                    id={panel}
                    className="py-2 pl-5 transition-opacity duration-200 starting:opacity-0 motion-reduce:transition-none"
                  >
                    <TurnTimeline timeline={view.entries} turn={turn.number} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    </>
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
    setTab(target);
    tabRefs.current[target]?.focus();
  }

  const leftScroll = (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 lg:p-5">
      {conversationPane}
    </div>
  );
  const rightScroll = (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 lg:p-5">
      {coachPane}
    </div>
  );

  return (
    <>
      <HeaderItems>
        {backLink}
        <span className="min-w-0 truncate text-[13px] text-ink-muted tabular-nums">
          <span className="max-lg:hidden">{`${startLabel} ${endLabel}· `}</span>
          {`${view.finished_replies}往復 · 終了`}
        </span>
      </HeaderItems>
      <h1 className="sr-only">{`${startLabel} からの会話（終了）`}</h1>
      {wide ? (
        <div className="grid h-[calc(100dvh-3rem)] grid-cols-[minmax(360px,42fr)_minmax(480px,58fr)]">
          <section
            aria-label="会話"
            className="flex min-h-0 flex-col border-r border-line bg-canvas"
          >
            {leftScroll}
          </section>
          <section aria-label="コーチ" className="flex min-h-0 flex-col bg-surface">
            {rightScroll}
          </section>
        </div>
      ) : (
        <div className="flex h-[calc(100dvh-3rem)] flex-col">
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
                onClick={() => setTab(name)}
                onKeyDown={onTabKey}
                className={`inline-flex min-h-11 items-center border-b-2 px-4 font-bold ${tab === name ? "border-ink text-ink" : "border-transparent text-ink-muted"} ${FOCUS_RING}`}
              >
                {name === "conversation" ? "会話" : "コーチ"}
              </button>
            ))}
          </div>
          <section
            role="tabpanel"
            id={`${ids}-panel-conversation`}
            aria-labelledby={`${ids}-tab-conversation`}
            hidden={tab !== "conversation"}
            className="flex min-h-0 flex-1 flex-col bg-canvas"
          >
            {leftScroll}
          </section>
          <section
            role="tabpanel"
            id={`${ids}-panel-coach`}
            aria-labelledby={`${ids}-tab-coach`}
            hidden={tab !== "coach"}
            className="flex min-h-0 flex-1 flex-col bg-surface"
          >
            {rightScroll}
          </section>
        </div>
      )}
    </>
  );
}
