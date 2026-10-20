import { type FormEvent, useEffect, useId, useRef } from "react";
import { FOCUS_RING, PRIMARY_BUTTON, QUIET_BUTTON } from "../../lib/ui";
import { isComposing } from "./Composer";
import { measure } from "./session";

/** A side question's parent owns its draft across pane and past-turn changes. */
export function CoachQuestion({
  disabled,
  error,
  onSend,
  open,
  onOpenChange,
  text,
  onTextChange,
}: {
  disabled: boolean;
  error: string | undefined;
  onSend: (text: string) => Promise<boolean>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  text: string;
  onTextChange: (text: string) => void;
}) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const size = measure(text, 500);
  const invalid = size.over || error !== undefined;
  const canSend = !disabled && !size.blank && !size.over;
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  useEffect(() => {
    if (error !== undefined && !disabled) input.current?.focus();
  }, [error, disabled]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canSend) void onSend(text);
  }

  return (
    <div className="space-y-2">
      <button
        ref={button}
        type="button"
        className={QUIET_BUTTON}
        aria-expanded={open}
        aria-controls={`${id}-box`}
        disabled={disabled}
        onClick={() => onOpenChange(!open)}
      >
        <span aria-hidden="true">{open ? "▾ " : "▸ "}</span>
        コーチに質問（会話は進みません）
      </button>
      {open && (
        <form
          id={`${id}-box`}
          aria-label="コーチへの質問"
          onSubmit={submit}
          className="space-y-2 transition-opacity duration-200 starting:opacity-0 motion-reduce:transition-none"
        >
          <label htmlFor={`${id}-input`} className="block text-xs font-bold">
            質問
          </label>
          <input
            ref={input}
            id={`${id}-input`}
            type="text"
            lang="ja"
            value={text}
            disabled={disabled}
            aria-invalid={invalid || undefined}
            aria-describedby={
              invalid ? `${id}-error` : size.showCounter ? `${id}-count` : undefined
            }
            onChange={(event) => onTextChange(event.target.value)}
            onKeyDown={(event) => {
              if (isComposing(event)) {
                if (event.key === "Enter") event.preventDefault();
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                onOpenChange(false);
                button.current?.focus();
              }
            }}
            className={`w-full rounded-panel border border-field-edge bg-canvas px-3 py-2 ${FOCUS_RING}`}
          />
          {size.showCounter && (
            <p id={`${id}-count`} className="text-xs tabular-nums">
              {size.counter}
            </p>
          )}
          {invalid && (
            <p
              id={`${id}-error`}
              role={error ? "alert" : undefined}
              className="text-sm text-danger"
            >
              {size.over ? size.overMessage : error}
            </p>
          )}
          <button type="submit" disabled={!canSend} className={PRIMARY_BUTTON}>
            質問する
          </button>
        </form>
      )}
    </div>
  );
}
