import type { ReactNode } from "react";
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
import { COACH_ENGLISH, ENTER, LABEL } from "./ui";

/**
 * The left pane's timeline: only what the Partner hears — its lines, each
 * restatement labelled under its line, and each turn's final English.
 */
export function ConversationTimeline({ entries }: { entries: readonly Entry[] }) {
  return (
    <ol aria-label="会話の流れ" className="space-y-4">
      {entries.map((item) => (
        <ConversationEntry key={item.id} entry={item} />
      ))}
    </ol>
  );
}

/** One left-pane line, or nothing for an entry the Partner does not hear. */
export function ConversationEntry({ entry }: { entry: Entry }) {
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
        <p
          lang="en"
          className="max-w-[36em] rounded-panel rounded-tr-[4px] border border-line bg-canvas px-4 py-3 font-en text-[17px] leading-[1.55] whitespace-pre-wrap"
        >
          {entry.payload.english}
        </p>
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
}: {
  timeline: readonly Entry[];
  turn: number;
  fresh?: ReadonlySet<string>;
}) {
  const entries = timeline.filter(
    (item) => item.turn_index === turn && item.kind !== "partner_line",
  );
  return (
    <ol aria-label={`ターン ${turn}`} className="space-y-3">
      {entries.map((item, index) => (
        <CoachEntry
          key={item.id}
          entry={item}
          timeline={timeline}
          celebrate={
            item.kind === "feedback" &&
            entries
              .slice(index + 1)
              .some(
                (later) =>
                  later.kind === "retry_result" &&
                  fresh.has(later.id) &&
                  isAccepted(later.payload.result),
              )
          }
        />
      ))}
    </ol>
  );
}

function Learner({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li className={`space-y-1 border-l-2 border-line-strong pl-3 ${ENTER}`}>
      <p className={LABEL}>{label}</p>
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
}: {
  entry: Entry;
  timeline: readonly Entry[];
  celebrate?: boolean;
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
        <Learner label="あなたの日本語">
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
