import type { ReactNode } from "react";
import { COACH_ENGLISH, ENTER, FOCUS_RING, LABEL } from "../../lib/ui";
import { FeedbackCard } from "./FeedbackCard";
import {
  checkInCount,
  checkInLine,
  circled,
  type Entry,
  type EntryOf,
  isAccepted,
  isPieceGiven,
  readingQuestionLine,
  retryResultLine,
} from "./session";

/**
 * The left pane's timeline: only what the Partner hears — its lines, each
 * restatement labelled under its line, and each turn's final English. With
 * `onSelectTurn`, each learner line is a button that selects its turn.
 */
export function ConversationTimeline({
  entries,
  onSelectTurn,
}: {
  entries: readonly Entry[];
  onSelectTurn?: (turn: number) => void;
}) {
  return (
    <ol aria-label="会話の流れ" className="space-y-4">
      {entries.map((item) => (
        <ConversationEntry
          key={item.id}
          entry={item}
          {...(onSelectTurn === undefined ? {} : { onSelectTurn })}
        />
      ))}
    </ol>
  );
}

const LEARNER_BUBBLE =
  "max-w-[36em] rounded-panel rounded-tr-[4px] border border-line bg-canvas px-4 py-3 font-en text-[17px] leading-[1.55] whitespace-pre-wrap";

/** One left-pane line, or nothing for an entry the Partner does not hear. */
export function ConversationEntry({
  entry,
  onSelectTurn,
}: {
  entry: Entry;
  onSelectTurn?: (turn: number) => void;
}) {
  if (entry.kind === "partner_line") {
    const restated = entry.payload.line_kind === "restatement";
    return (
      <li className={`flex items-start gap-2 ${restated ? "ml-9" : ""} ${ENTER}`}>
        {!restated && <PartnerAvatar />}
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-bold text-partner-ink">
            {restated
              ? entry.payload.restate_mode === "shorter"
                ? "言い換え（短く）"
                : "言い換え（簡単に）"
              : "Partner"}
          </p>
          <p
            lang="en"
            className="max-w-[36em] rounded-panel rounded-tl-[4px] border border-partner-edge bg-partner px-4 py-3 font-en text-[17px] leading-[1.55]"
          >
            {entry.payload.text}
          </p>
        </div>
      </li>
    );
  }
  if (entry.kind === "turn_done") {
    return (
      <li className={`flex flex-col items-end gap-1 ${ENTER}`}>
        <p className="text-xs font-bold text-ink-muted">You</p>
        {onSelectTurn === undefined ? (
          <p lang="en" className={LEARNER_BUBBLE}>
            {entry.payload.english}
          </p>
        ) : (
          <button
            type="button"
            lang="en"
            onClick={() => onSelectTurn(entry.turn_index)}
            className={`${LEARNER_BUBBLE} text-left hover:border-line-strong ${FOCUS_RING}`}
          >
            {entry.payload.english}
          </button>
        )}
      </li>
    );
  }
  return null;
}

function PartnerAvatar() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 28 28"
      className="mt-5 size-7 shrink-0 text-partner-ink"
    >
      <rect width="28" height="28" rx="8" className="fill-partner-edge" />
      <circle cx="10" cy="12" r="1.75" fill="currentColor" />
      <circle cx="18" cy="12" r="1.75" fill="currentColor" />
      <path
        d="M10 17.5c2.2 2 5.8 2 8 0"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * One turn's Coach timeline, read-only: every entry of `turn` in `timeline`
 * except the Partner's lines, with no composer or controls. `fresh` names
 * entries that just arrived, so an accepted retry flashes its card's edge.
 */
export function TurnTimeline({
  timeline,
  turn,
  fresh = new Set<string>(),
  intentControl,
}: {
  timeline: readonly Entry[];
  turn: number;
  fresh?: ReadonlySet<string>;
  intentControl?: ReactNode;
}) {
  const entries = timeline.filter(
    (item) => item.turn_index === turn && item.kind !== "partner_line",
  );
  const latestIntent = entries.findLast((item) => item.kind === "intent");
  const groups: Entry[][] = [[]];
  for (const item of entries) {
    if (item.kind === "intent" && item.payload.is_replacement && groups.at(-1)?.length)
      groups.push([]);
    groups.at(-1)?.push(item);
  }
  const renderEntry = (item: Entry) => (
    <CoachEntry
      key={item.id}
      entry={item}
      timeline={timeline}
      intentControl={item.id === latestIntent?.id ? intentControl : undefined}
      celebrate={
        item.kind === "feedback" &&
        entries
          .slice(entries.indexOf(item) + 1)
          .some(
            (later) =>
              later.kind === "retry_result" &&
              fresh.has(later.id) &&
              isAccepted(later.payload.result),
          )
      }
    />
  );
  return (
    <ol aria-label={`ターン ${turn}`} className="space-y-3">
      {groups.map((group, index) =>
        index === groups.length - 1 ? (
          group.map(renderEntry)
        ) : (
          <li key={group[0]?.id}>
            <details className="space-y-2">
              <summary
                className={`cursor-pointer text-sm text-ink-muted ${FOCUS_RING}`}
              >
                書き直す前のやりとり
              </summary>
              <ol className="space-y-3 transition-opacity duration-200 starting:opacity-0 motion-reduce:transition-none">
                {group.map(renderEntry)}
              </ol>
            </details>
          </li>
        ),
      )}
    </ol>
  );
}

function Learner({
  label,
  children,
  action,
}: {
  label: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <li className={`space-y-1 border-l-2 border-line-strong pl-3 ${ENTER}`}>
      <div className="flex flex-wrap items-center gap-2">
        <p className={LABEL}>{label}</p>
        {action}
      </div>
      {children}
    </li>
  );
}

function English({ children }: { children: string }) {
  return (
    <p lang="en" className={`${COACH_ENGLISH} whitespace-pre-wrap`}>
      {children}
    </p>
  );
}

function Coach({ line, children }: { line: string; children?: ReactNode }) {
  return (
    <li className={`max-w-[40em] space-y-1 ${ENTER}`}>
      <p className="text-pretty">💡 {line}</p>
      {children}
    </li>
  );
}

function Success({ line }: { line: string }) {
  return (
    <li className={`text-success ${ENTER}`}>
      <p>
        <span aria-hidden="true">✓ </span>
        {line}
      </p>
    </li>
  );
}

function RetryResult({
  entry,
}: {
  entry: EntryOf<"retry_result" | "practice_result">;
}) {
  const { result } = entry.payload;
  if (isAccepted(result)) return <Success line={result.line} />;
  return (
    <Coach line={retryResultLine(result)}>
      {isPieceGiven(result) && (
        <ul>
          {result.pieces.map((piece) => (
            <li key={piece.number} className="flex gap-2">
              <span>{circled(piece.number)}</span>{" "}
              <span lang="en" className={`${COACH_ENGLISH} font-bold`}>
                {piece.text}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Coach>
  );
}

/**
 * One right-pane block of a turn: the learner's entries as ruled rows, the
 * Coach's as plain lines, the feedback as its card. `timeline` is the whole
 * session, which a check-in's reply count reads.
 */
export function CoachEntry({
  entry,
  timeline,
  celebrate = false,
  intentControl,
}: {
  entry: Entry;
  timeline: readonly Entry[];
  celebrate?: boolean;
  intentControl?: ReactNode;
}) {
  switch (entry.kind) {
    case "partner_line":
      return (
        <li className={ENTER}>
          <p className="text-xs font-bold text-partner-ink">🗣 Partner</p>
          <English>{entry.payload.text}</English>
        </li>
      );
    case "intent":
      return (
        <Learner label="あなたの日本語" action={intentControl}>
          <p className="whitespace-pre-wrap">{entry.payload.text}</p>
        </Learner>
      );
    case "acknowledgment":
      return (
        <Coach line={entry.payload.line}>
          {entry.payload.build_hint !== null && (
            <p className="text-pretty">組み立てのヒント: {entry.payload.build_hint}</p>
          )}
        </Coach>
      );
    case "english":
      return (
        <Learner label="あなたの英語">
          <English>{entry.payload.text}</English>
        </Learner>
      );
    case "hint_request":
      return (
        <Learner label="分からないところ">
          <p className="whitespace-pre-wrap">{entry.payload.gap}</p>
          {entry.payload.partial_english.trim() !== "" && (
            <>
              <p className={LABEL}>途中までの英語</p>
              <English>{entry.payload.partial_english}</English>
            </>
          )}
        </Learner>
      );
    case "gap_hint":
      return <Coach line={entry.payload.hint} />;
    case "reading_question":
      return <Coach line={readingQuestionLine(entry)} />;
    case "reading_choice":
      return (
        <li className={`border-l-2 border-line-strong pl-3 ${ENTER}`}>
          <p>
            <span lang="en" className="font-en">
              {entry.payload.chosen}
            </span>{" "}
            のつもり
          </p>
        </li>
      );
    case "feedback":
      return (
        <li>
          <FeedbackCard feedback={entry.payload.feedback} celebrate={celebrate} />
        </li>
      );
    case "retry":
      return (
        <Learner label="言い直し">
          <English>{entry.payload.sentence}</English>
        </Learner>
      );
    case "retry_result":
    case "practice_result":
      return <RetryResult entry={entry} />;
    case "answer":
      return (
        <li className={`max-w-[40em] space-y-1 ${ENTER}`}>
          <p className={LABEL}>完成例</p>
          <English>{entry.payload.example}</English>
        </li>
      );
    case "typed_copy":
      return (
        <Learner label="あなたの英語">
          <English>{entry.payload.text}</English>
        </Learner>
      );
    case "skip":
      return (
        <li className={`text-ink-muted ${ENTER}`}>
          <p>スキップして会話に戻ります</p>
        </li>
      );
    case "turn_done":
      return entry.payload.end === "accepted" ? (
        <Success line="言い直しできました" />
      ) : null;
    case "question":
      return (
        <li className={`space-y-1 text-sm text-ink-muted ${ENTER}`}>
          <p className="text-xs font-bold">質問</p>
          <p className="whitespace-pre-wrap">{entry.payload.text}</p>
        </li>
      );
    case "coach_answer":
      return (
        <li className={`max-w-[40em] space-y-1 text-sm text-ink-muted ${ENTER}`}>
          <p className="text-xs font-bold">💡 コーチ</p>
          <p className="text-pretty">{entry.payload.text}</p>
        </li>
      );
    case "check_in":
      return <Coach line={checkInLine(checkInCount(timeline, entry))} />;
    case "check_in_answer":
      return (
        <li className={`border-l-2 border-line-strong pl-3 ${ENTER}`}>
          <p>{entry.payload.answer === "continue" ? "続ける" : "終わる"}</p>
        </li>
      );
    case "practice":
      return (
        <Learner label="もう一度練習">
          <English>{entry.payload.sentence}</English>
        </Learner>
      );
  }
}
