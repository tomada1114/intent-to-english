import type { SessionResponse } from "../api/generated/types.gen";

/**
 * How often a screen reads the session again while a submission it did not
 * send (another tab's, or one still running after a reload) is pending.
 */
export const SUBMISSION_POLL_MS = 2000;

/** Any submission still running on the server, which the screen waits for. */
export function submissionPending(view: SessionResponse | undefined): boolean {
  return view?.last_submission?.state === "pending";
}

const REASONS: Readonly<Record<string, string>> = {
  model_timeout: "時間切れ",
  model_rate_limited: "混み合っています",
  model_unavailable: "接続できません",
  model_error: "接続できません",
  model_output_invalid: "返事の形式が正しくありませんでした",
};

/**
 * The reason a failed model call names in its banner (ux-guidelines § States),
 * chosen by the Problem Details `code`, never the status: two codes share 502.
 * Undefined for a code that is not a model failure.
 */
export function modelFailureReason(
  code: string | null | undefined,
): string | undefined {
  return code === null || code === undefined ? undefined : REASONS[code];
}
