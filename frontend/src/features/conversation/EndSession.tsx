import { useEffect, useId, useRef, useState } from "react";
import { HEADER_BUTTON } from "./ui";

/** How long the confirmation waits untouched before it reverts (ux-guidelines). */
export const CONFIRM_TIMEOUT_MS = 5000;

/**
 * 「会話を終える」, which becomes in place 「終えて振り返りを作りますか？ [終える]
 * [戻る]」 and reverts by itself after 5 s untouched. Never blocked by another
 * request: ending supersedes it.
 */
export function EndSession({ onEnd, ending }: { onEnd: () => void; ending: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const questionId = useId();
  const start = useRef<HTMLButtonElement>(null);
  const back = useRef<HTMLButtonElement>(null);
  const group = useRef<HTMLFieldSetElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const focusStart = useRef(false);
  const endingNow = useRef(ending);

  useEffect(() => {
    endingNow.current = ending;
  }, [ending]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  useEffect(() => {
    if (confirming) {
      back.current?.focus();
    } else if (focusStart.current) {
      focusStart.current = false;
      start.current?.focus();
    }
  }, [confirming]);

  function revert() {
    window.clearTimeout(timer.current);
    focusStart.current = group.current?.contains(document.activeElement) === true;
    setConfirming(false);
  }

  /** (Re)start the 5 s wait; a wait that ends while the end is sent is renewed. */
  function arm() {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      if (endingNow.current) arm();
      else revert();
    }, CONFIRM_TIMEOUT_MS);
  }

  if (!confirming) {
    return (
      <button
        ref={start}
        type="button"
        onClick={() => {
          setConfirming(true);
          arm();
        }}
        className={HEADER_BUTTON}
      >
        会話を終える
      </button>
    );
  }
  return (
    <fieldset
      ref={group}
      aria-labelledby={questionId}
      className="flex min-w-0 shrink-0 items-center gap-2"
      onKeyDown={arm}
      onPointerDown={arm}
    >
      <span id={questionId} className="text-sm">
        終えて振り返りを作りますか？
      </span>
      <button type="button" disabled={ending} onClick={onEnd} className={HEADER_BUTTON}>
        終える
      </button>
      <button
        ref={back}
        type="button"
        disabled={ending}
        onClick={revert}
        className={HEADER_BUTTON}
      >
        戻る
      </button>
    </fieldset>
  );
}
