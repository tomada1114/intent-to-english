import { Fragment, type ReactNode, useId } from "react";
import type { FeedbackResponse, FixResponse } from "../../api/generated/types.gen";
import { COACH_ENGLISH, ENTER, LABEL } from "../../lib/ui";
import { circled } from "./session";

const BLANK = /\(([①-⑳])\) ____/g;

/**
 * The Coach's feedback: the intent line, then 直し方 (the fixes in number
 * order), あなたの文 (the learner's sentence verbatim, each fixed 元 marked), and
 * 穴埋め (the template, each blank a numbered slot), then the request line.
 */
export function FeedbackCard({
  feedback,
  celebrate = false,
}: {
  feedback: FeedbackResponse;
  celebrate?: boolean;
}) {
  const fixesId = useId();
  const fixes = [...feedback.fixes].sort((a, b) => a.number - b.number);

  return (
    <article
      aria-label="コーチの添削"
      className={`relative max-w-[40em] space-y-3 rounded-panel border border-coach-edge bg-coach p-4 ${ENTER}`}
    >
      {celebrate && (
        <span
          data-testid="success-edge"
          aria-hidden="true"
          className="pointer-events-none absolute -inset-px rounded-panel border-2 border-success opacity-0 transition-opacity duration-600 starting:opacity-100 motion-reduce:hidden"
        />
      )}
      <p className="text-pretty">{feedback.first_line}</p>
      {fixes.length > 0 && (
        <div className="space-y-2">
          <h3 id={fixesId} className={LABEL}>
            直し方
          </h3>
          <ol aria-labelledby={fixesId} className="space-y-2">
            {fixes.map((fix) => (
              <FixRow key={fix.number} fix={fix} />
            ))}
          </ol>
        </div>
      )}
      {feedback.sentence !== null && (
        <div className="space-y-2">
          <h3 className={LABEL}>あなたの文</h3>
          <p lang="en" className={`${COACH_ENGLISH} whitespace-pre-wrap`}>
            {markOriginals(feedback.sentence, fixes)}
          </p>
        </div>
      )}
      {feedback.template !== null && (
        <div className="space-y-2">
          <h3 className={LABEL}>穴埋め</h3>
          <p lang="en" className={`${COACH_ENGLISH} whitespace-pre-wrap`}>
            {slots(feedback.template)}
          </p>
        </div>
      )}
      {feedback.request_line !== null && (
        <p className="text-pretty">{feedback.request_line}</p>
      )}
      {feedback.readings_noted.length > 0 && (
        <ul className="space-y-1 text-sm text-ink-muted">
          {feedback.readings_noted.map((note) => (
            <li key={`${note.written}-${note.read_as}`}>
              <span lang="en" className="font-en">
                {note.written}
              </span>{" "}
              は{" "}
              <span lang="en" className="font-en">
                {note.read_as}
              </span>{" "}
              として読みました
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function FixRow({ fix }: { fix: FixResponse }) {
  return (
    <li className="space-y-1">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-ink text-xs text-on-ink">
          {circled(fix.number)}
        </span>
        <span className="text-ink-muted">
          元{" "}
          {fix.original === null ? (
            "（なし）"
          ) : (
            <span lang="en" className={COACH_ENGLISH}>
              {fix.original}
            </span>
          )}
        </span>
        <span aria-hidden="true">→</span>
        <span>
          直す{" "}
          <span lang="en" className={`${COACH_ENGLISH} font-bold`}>
            {fix.replacement}
          </span>
        </span>
        <span
          className={
            fix.tag === "miss"
              ? "rounded-full bg-miss-tint px-2 py-0.5 text-xs font-bold text-miss"
              : "rounded-full bg-improve-tint px-2 py-0.5 text-xs font-bold text-improve"
          }
        >
          {fix.tag === "miss" ? "ミス" : "改善"}
        </span>
      </p>
      <p className="text-sm text-pretty text-ink-muted">なぜ: {fix.reason}</p>
    </li>
  );
}

interface Span {
  start: number;
  end: number;
  number: number;
}

/**
 * Each fix's 元 (each part of one split at 「…」), marked where it first occurs
 * in the sentence without overlapping an earlier mark, followed by its number.
 * A 元 the sentence does not contain is left unmarked.
 */
function markOriginals(sentence: string, fixes: readonly FixResponse[]): ReactNode {
  const spans: Span[] = [];
  for (const fix of fixes) {
    for (const part of (fix.original ?? "").split("…")) {
      const words = part.trim().replace(/^,\s*/, "");
      if (words === "") continue;
      let from = sentence.indexOf(words);
      while (from !== -1 && !fits(sentence, words, from, spans)) {
        from = sentence.indexOf(words, from + 1);
      }
      if (from !== -1) {
        spans.push({ start: from, end: from + words.length, number: fix.number });
      }
    }
  }
  spans.sort((a, b) => a.start - b.start);
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const span of spans) {
    parts.push(sentence.slice(cursor, span.start));
    parts.push(
      <mark key={span.start} className="rounded-[4px] bg-marker px-0.5 text-ink">
        {sentence.slice(span.start, span.end)}
        <span className="text-xs">{circled(span.number)}</span>
      </mark>,
    );
    cursor = span.end;
  }
  parts.push(sentence.slice(cursor));
  return parts;
}

const WORD = /[\p{L}\p{N}']/u;

/** Whether `words` at `from` stands as whole words and overlaps no earlier mark. */
function fits(sentence: string, words: string, from: number, spans: readonly Span[]) {
  const end = from + words.length;
  const before = sentence[from - 1] ?? " ";
  const after = sentence[end] ?? " ";
  const wholeStart = !WORD.test(words[0] ?? "") || !WORD.test(before);
  const wholeEnd = !WORD.test(words.at(-1) ?? "") || !WORD.test(after);
  return (
    wholeStart &&
    wholeEnd &&
    spans.every((span) => end <= span.start || from >= span.end)
  );
}

/** The template with each `(①) ____` drawn as a number chip and an underlined gap. */
function slots(template: string): ReactNode {
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const match of template.matchAll(BLANK)) {
    parts.push(template.slice(cursor, match.index));
    parts.push(
      <Fragment key={match.index}>
        <span className="sr-only">(</span>
        <span className="inline-flex min-w-5 items-center justify-center rounded-slot bg-ink px-1 text-xs text-on-ink">
          {match[1]}
        </span>
        <span className="sr-only">)</span>{" "}
        <span className="inline-block w-[4em] border-b-2 border-ink align-baseline">
          <span className="sr-only">____</span>
        </span>
      </Fragment>,
    );
    cursor = match.index + match[0].length;
  }
  parts.push(template.slice(cursor));
  return parts;
}
