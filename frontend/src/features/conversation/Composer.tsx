import { type KeyboardEvent, type Ref, useId } from "react";
import { FOCUS_RING, PRIMARY_BUTTON } from "../../lib/ui";
import { COMPOSER_LIMIT, measure } from "./session";

/** Whether a keydown is part of IME composition (Safari's committing Enter is 229). */
export function isComposing(event: KeyboardEvent): boolean {
  return event.nativeEvent.isComposing || event.keyCode === 229;
}

const MAC =
  typeof navigator !== "undefined" && /Mac|iP(hone|ad)/.test(navigator.userAgent);

/**
 * The one textarea of the Coach pane: ⌘↵ / Ctrl+Enter sends and Enter is a
 * newline; a key during IME composition never sends. Grows to 6 lines, counts
 * from 900 of 1,000 code points, and refuses to send empty or over-long text
 * without cutting what was typed or dictated.
 */
export function Composer({
  label,
  value,
  onChange,
  onSend,
  placeholder,
  lang,
  disabled = false,
  error,
  textareaRef,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  placeholder?: string | undefined;
  lang: "ja" | "en";
  disabled?: boolean;
  /** The server's rejection of this text (a 422), shown under the field. */
  error?: string | undefined;
  textareaRef?: Ref<HTMLTextAreaElement>;
}) {
  const id = useId();
  const counterId = `${id}-counter`;
  const messageId = `${id}-message`;
  const size = measure(value, COMPOSER_LIMIT);
  const canSend = !disabled && !size.blank && !size.over;
  const invalid = size.over || error !== undefined;
  const describedBy = [
    size.showCounter ? counterId : null,
    invalid ? messageId : null,
  ].filter((part) => part !== null);

  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-xs font-bold">
        {label}
      </label>
      <textarea
        ref={textareaRef}
        id={id}
        lang={lang}
        rows={2}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy.length > 0 ? describedBy.join(" ") : undefined}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Enter" || isComposing(event)) return;
          if (!(event.metaKey || event.ctrlKey)) return;
          event.preventDefault();
          if (canSend) onSend();
        }}
        className={`block max-h-[calc(6lh+1.5rem)] min-h-[calc(2lh+1.5rem)] w-full resize-none overflow-y-auto rounded-panel border border-field-edge bg-canvas px-3 py-3 leading-[1.7] field-sizing-content placeholder:text-ink-subtle disabled:cursor-not-allowed disabled:opacity-60 ${lang === "en" ? "font-en text-base" : "text-[15px]"} ${FOCUS_RING}`}
      />
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1 text-sm">
          {size.showCounter && (
            <p
              id={counterId}
              className={`tabular-nums ${size.over ? "text-danger" : "text-ink-muted"}`}
            >
              {size.counter}
            </p>
          )}
          {size.over ? (
            <p id={messageId} className="text-danger">
              {size.overMessage}
            </p>
          ) : (
            error !== undefined && (
              <p id={messageId} role="alert" className="text-danger">
                {error}
              </p>
            )
          )}
        </div>
        <button
          type="button"
          disabled={!canSend}
          onClick={onSend}
          className={`${PRIMARY_BUTTON} ml-auto`}
        >
          送信
          <span aria-hidden="true" className="font-sans text-xs opacity-80">
            {MAC ? "⌘↵" : "Ctrl+Enter"}
          </span>
        </button>
      </div>
    </div>
  );
}
