import { type Ref, useId } from "react";
import { isComposing } from "./Composer";
import { GAP_LIMIT, measure } from "./session";
import { FOCUS_RING, SECONDARY_BUTTON } from "./ui";

/**
 * The inline hint request under the composer: what the learner cannot say
 * (1–200 characters), sent with [ヒントをもらう] or Enter; [やめる] or Esc
 * closes it. The composer keeps its partial English meanwhile.
 */
export function HintRequest({
  value,
  onChange,
  onSubmit,
  onCancel,
  disabled,
  error,
  inputRef,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  disabled: boolean;
  error: string | undefined;
  inputRef: Ref<HTMLInputElement>;
}) {
  const id = useId();
  const counterId = `${id}-counter`;
  const messageId = `${id}-message`;
  const size = measure(value, GAP_LIMIT);
  const canSend = !disabled && !size.blank && !size.over;
  const invalid = size.over || error !== undefined;
  const describedBy = [size.showCounter ? counterId : null, invalid ? messageId : null]
    .filter((part) => part !== null)
    .join(" ");

  return (
    <form
      aria-label="ヒントのお願い"
      className="space-y-2 rounded-panel border border-line bg-canvas p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSend) onSubmit();
      }}
    >
      <label htmlFor={id} className="block text-xs font-bold">
        分からないところ
      </label>
      <input
        ref={inputRef}
        id={id}
        type="text"
        autoComplete="off"
        value={value}
        disabled={disabled}
        placeholder="分からないところ（例: 「久しぶり」が分からない）"
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy === "" ? undefined : describedBy}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          } else if (event.key === "Enter" && isComposing(event)) {
            event.preventDefault();
          }
        }}
        className={`block w-full rounded-panel border border-field-edge bg-canvas px-3 py-2 text-[15px] placeholder:text-ink-subtle disabled:opacity-60 ${FOCUS_RING}`}
      />
      {size.showCounter && (
        <p
          id={counterId}
          className={`text-sm tabular-nums ${size.over ? "text-danger" : "text-ink-muted"}`}
        >
          {size.counter}
        </p>
      )}
      {size.over ? (
        <p id={messageId} className="text-sm text-danger">
          {size.overMessage}
        </p>
      ) : (
        error !== undefined && (
          <p id={messageId} role="alert" className="text-sm text-danger">
            {error}
          </p>
        )
      )}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={!canSend} className={SECONDARY_BUTTON}>
          ヒントをもらう
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onCancel}
          className={SECONDARY_BUTTON}
        >
          やめる
        </button>
      </div>
    </form>
  );
}
