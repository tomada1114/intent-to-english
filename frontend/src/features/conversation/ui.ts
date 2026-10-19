/** Class lists the conversation's controls share (design-direction § Components). */

export const FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

const TACTILE =
  "inline-flex items-center justify-center gap-2 rounded-panel font-bold transition-[translate,border-width] duration-100 active:translate-y-0.5 motion-reduce:transition-none motion-reduce:active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50";

/** Primary: ink, 44 px tall, a 3 px bottom edge that collapses when pressed. */
export const PRIMARY_BUTTON = `${TACTILE} h-11 border-b-3 border-ink-edge bg-ink px-5 text-[15px] text-on-ink active:border-b ${FOCUS_RING}`;

/** Secondary: canvas fill, 1 px strong line with a 3 px bottom edge. */
export const SECONDARY_BUTTON = `${TACTILE} min-h-11 border border-b-3 border-line-strong bg-canvas px-4 text-[15px] text-ink active:border-b aria-pressed:bg-surface ${FOCUS_RING}`;

/** Quiet: text only, ink-muted, underlined on hover; 32 px tall. */
export const QUIET_BUTTON = `inline-flex min-h-8 items-center rounded-sm text-sm text-ink-muted hover:underline ${FOCUS_RING}`;

/** A new line or block: a 150 ms fade with a 4 px rise; opacity only when reduced. */
export const ENTER =
  "transition-[opacity,translate] duration-150 ease-out starting:opacity-0 motion-safe:starting:translate-y-1";

/** Labels above blocks: 12 px bold. */
export const LABEL = "text-xs font-bold text-ink";

/** English in the Coach pane: the rounded English face at 16 px. */
export const COACH_ENGLISH = "font-en text-base leading-[1.6]";

/** A secondary button sized for the 48 px header: 32 px tall. */
export const HEADER_BUTTON = `${TACTILE} min-h-8 border border-b-2 border-line-strong bg-canvas px-2 text-sm sm:px-3 text-ink active:border-b ${FOCUS_RING}`;
