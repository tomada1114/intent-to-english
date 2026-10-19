import { SECONDARY_BUTTON } from "./ui";

export interface BannerAction {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

/**
 * An inline failure banner (design-direction § Components): the danger tint,
 * an alert icon and the text, and the one action that recovers, if any.
 * Announced assertively, since it reports something that went wrong.
 */
export function Banner({
  message,
  action,
  className = "",
}: {
  message: string;
  action?: BannerAction | undefined;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={`flex flex-wrap items-center gap-3 rounded-panel border border-danger-edge bg-danger-tint p-4 text-danger ${className}`}
    >
      <p className="flex min-w-0 items-center gap-2">
        <span aria-hidden="true">⚠</span>
        <span className="min-w-0">{message}</span>
      </p>
      {action !== undefined && (
        <button
          type="button"
          disabled={action.disabled}
          onClick={action.onClick}
          className={SECONDARY_BUTTON}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
