import { useMutation, useQueryClient } from "@tanstack/react-query";
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
import type { Action, SessionResponse } from "../../api/generated/types.gen";
import { ErrorMessage } from "../../lib/ErrorMessage";
import { formatStart } from "../../lib/format";
import { HeaderItems } from "../../lib/HeaderItems";
import { type ApiError, toApiError } from "../../lib/problem-details";
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
import { type Arrival, useArrivals, useFollowBottom, useWideLayout } from "./hooks";
import {
  type ActionInput,
  type Control,
  lineBeingAnswered,
  paneFor,
  previousTurnLine,
  type SessionView,
  sessionQueryOptions,
  stageUi,
} from "./session";

/** Actions whose text is the composer's: a success clears it, nothing else does. */
const COMPOSER_ACTIONS: ReadonlySet<Action> = new Set([
  "intent",
  "english_direct",
  "english",
  "retry",
  "typed_copy",
]);

const HOW_TO = [
  "1. 返したいことを、まず日本語で送ってください",
  "2. それを自分で英語にしてみてください（途中まででOK。詰まったら「ヒント」）",
  "3. 最初から英語で返すときは「英語で直接返す」",
  "4. 「答えを見せて」「スキップ」「会話を終える」はいつでも使えます",
];

type Tab = "conversation" | "coach";

/** The template's error display for a submission the server reports as failed. */
const STORED_FAILURE: ApiError = {
  kind: "problem",
  status: 500,
  title: "The last submission did not finish",
  fieldErrors: {},
};

/**
 * S2, the conversation in progress (and, read-only, an ended one): the
 * Partner's pane and the Coach's, side by side from 1024 px and tabs below.
 * Every stage, control, and 👉 次 line comes from the view; the screen sends
 * `open` and `partner_reply` by itself, and writes each result into the
 * session query, so the route re-renders with the server's next stage.
 */
export function ConversationScreen({
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
  const [unread, setUnread] = useState(false);
  const [text, setText] = useState("");
  const [gap, setGap] = useState("");
  const [directTurn, setDirectTurn] = useState<number | null>(null);
  const [hintOpen, setHintOpen] = useState(false);
  const [howToOpen, setHowToOpen] = useState(true);
  /** A past turn the learner selected on the left, shown read-only on the right. */
  const [pastTurn, setPastTurn] = useState<number | null>(null);
  const backToTurnRef = useRef<HTMLButtonElement>(null);
  const focusAfterPast = useRef<"back" | "composer" | null>(null);
  const coachHeadingRef = useRef<HTMLHeadingElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const gapRef = useRef<HTMLInputElement>(null);
  const controlsRef = useRef<HTMLFieldSetElement>(null);
  const hintButtonRef = useRef<HTMLButtonElement>(null);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({
    conversation: null,
    coach: null,
  });
  // A second send can arrive before React renders the disabled state.
  const inFlight = useRef(false);
  const autoSent = useRef<number | null>(null);
  /** The version of a result that should take focus once it is shown. */
  const focusOnResult = useRef<number | null>(null);
  const focusHintButton = useRef(false);

  async function writeView(next: SessionResponse) {
    // A result for an older version (an action an `end` superseded) never
    // replaces a newer view.
    queryClient.setQueryData<SessionResponse>(sessionKey, (old) =>
      old === undefined || next.version >= old.version ? next : old,
    );
    await queryClient.invalidateQueries({ queryKey: [{ _id: "listSessions" }] });
  }

  const action = useMutation({
    ...performSessionActionMutation(),
    // A read that started before the action must not overwrite its result.
    onMutate: () => queryClient.cancelQueries({ queryKey: sessionKey }),
    onSuccess: (next, variables) => {
      const sent = variables.body.action;
      if (COMPOSER_ACTIONS.has(sent)) setText("");
      if (sent === "hint") {
        setGap("");
        setHintOpen(false);
      }
      focusOnResult.current = next.version;
      return writeView(next);
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });
  const end = useMutation({
    ...performSessionActionMutation(),
    onMutate: () => queryClient.cancelQueries({ queryKey: sessionKey }),
    onSuccess: (next) => writeView(next),
  });

  function send(input: ActionInput) {
    if (inFlight.current) return;
    inFlight.current = true;
    action.mutate({
      path: { session_id: view.id },
      body: { ...input, version: view.version },
    });
  }

  const sending = action.isPending ? action.variables?.body.action : undefined;
  const pending =
    sending ??
    (view.last_submission?.state === "pending"
      ? view.last_submission.action
      : undefined);
  const busy = pending !== undefined;
  const waitingPane = pending === undefined ? null : paneFor(pending);
  const ended = view.status === "ended";

  const autoSend = useEffectEvent((auto: "open" | "partner_reply") => {
    send({ action: auto });
  });
  useEffect(() => {
    const auto =
      view.stage === "opening"
        ? "open"
        : view.stage === "partner_turn"
          ? "partner_reply"
          : null;
    // Never for a submission the server still holds, and once per version:
    // a failed auto-send stays failed (StrictMode re-runs this effect too).
    if (auto === null || view.last_submission !== null) return;
    if (autoSent.current === view.version) return;
    autoSent.current = view.version;
    autoSend(auto);
  }, [view.stage, view.version, view.last_submission]);

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

  const failure =
    action.isError && !ended && action.variables !== undefined
      ? { error: toApiError(action.error), action: action.variables.body.action }
      : view.last_submission !== null &&
          view.last_submission.state !== "pending" &&
          action.isIdle &&
          !ended
        ? { error: STORED_FAILURE, action: view.last_submission.action }
        : null;
  const fieldMessage = (field: string) => {
    if (failure?.error.kind !== "problem" || failure.error.status !== 422) return;
    const messages = failure.error.fieldErrors[field];
    if (messages !== undefined) return messages.join(" ");
    return failure.error.code === "invalid_input"
      ? (failure.error.detail ?? failure.error.title)
      : undefined;
  };
  const composerError =
    failure !== null && COMPOSER_ACTIONS.has(failure.action)
      ? fieldMessage("text")
      : undefined;
  const gapError = failure?.action === "hint" ? fieldMessage("gap") : undefined;
  const bannerFor = (side: "partner" | "coach") =>
    failure !== null &&
    composerError === undefined &&
    gapError === undefined &&
    paneFor(failure.action) === side ? (
      <ErrorMessage error={failure.error} />
    ) : null;

  const left = useFollowBottom(`${view.entries.length}:${pending ?? ""}`);
  const right = useFollowBottom(`${view.entries.length}:${pending ?? ""}:${showHint}`);

  function runControl(control: Control) {
    if (control.input === "toggle_direct") {
      setDirectTurn(direct ? null : view.turn_index);
    } else if (control.input === "open_hint") {
      setHintOpen(true);
    } else {
      send(control.input);
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
        {waitingPane === "partner" && (
          <p className={ENTER}>Partner が返事を考えています…</p>
        )}
      </div>
      {bannerFor("partner")}
    </>
  );

  // Shown under whichever turn the Coach pane holds, the current or a past one.
  const coachErrors = (
    <>
      {bannerFor("coach")}
      {end.isError && <ErrorMessage error={toApiError(end.error)} />}
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
      <div role="status">
        {waitingPane === "coach" ? (
          <p className="text-ink-muted">コーチが確認しています…</p>
        ) : (
          nextLine !== null && <p className="font-bold">{`👉 次: ${nextLine}`}</p>
        )}
      </div>
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
            if (composer !== null) send({ action: composer.action, text });
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
          onSubmit={() => send({ action: "hint", gap, partial_english: text })}
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
            <EndSession
              ending={end.isPending}
              onEnd={() =>
                end.mutate({
                  path: { session_id: view.id },
                  body: { action: "end", version: view.version },
                })
              }
            />
          </span>
        )}
      </HeaderItems>
      <h1 className="sr-only">{`${startLabel} からの会話`}</h1>
      <div role="status" aria-label="お知らせ" aria-atomic="true" className="sr-only">
        {arrival.message !== "" && <span key={arrival.key}>{arrival.message}</span>}
      </div>
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
            {footer}
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
        </div>
      )}
    </>
  );
}

/** Loading the session: three skeleton blocks in each pane's place. */
export function ConversationSkeleton() {
  return (
    <div className="grid h-[calc(100dvh-3rem)] lg:grid-cols-[minmax(360px,42fr)_minmax(480px,58fr)]">
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

/** The session failed to load: the template's error display, in the page. */
export function ConversationLoadError({ error }: { error: ApiError }) {
  return (
    <div className="p-4">
      <ErrorMessage error={error} />
    </div>
  );
}
