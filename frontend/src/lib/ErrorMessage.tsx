import type { ApiError } from "./problem-details";

export function ErrorMessage({ error }: { error: ApiError }) {
  const message =
    error.kind === "unknown"
      ? "Could not reach the server. Check your connection and try again."
      : error.status >= 500
        ? "Something went wrong on our side. Try again."
        : (error.detail ?? error.title);

  return (
    // The template's messages are English on a Japanese page.
    <div role="alert" lang="en" className="space-y-1 text-danger">
      <p>{message}</p>
      {error.kind === "problem" &&
        error.status >= 500 &&
        error.requestId !== undefined && (
          <p className="break-words text-sm">Request ID: {error.requestId}</p>
        )}
    </div>
  );
}
