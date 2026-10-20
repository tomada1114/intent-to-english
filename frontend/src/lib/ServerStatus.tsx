import { isCancelledError, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Banner } from "./Banner";
import { toApiError } from "./problem-details";

type Retry = () => void;

export interface ServerStatus {
  /** A request under `key` got no response; `retry` sends it again. */
  report: (key: string, retry: Retry) => void;
  /** The request under `key` got through, or no longer needs to. */
  resolve: (key: string) => void;
}

const IGNORED: ServerStatus = { report: () => {}, resolve: () => {} };

const StatusContext = createContext<ServerStatus | undefined>(undefined);
const RetriesContext = createContext<ReadonlyMap<string, Retry>>(new Map());

export const UNREACHABLE_MESSAGE =
  "アプリのサーバーに接続できません。起動しているか確認してください。";

/**
 * Tracks the requests that got no response from the app's own API, on every
 * screen: each query is watched through the query cache, and a screen reports
 * a failed mutation itself with `useServerStatus`, giving the retry.
 */
export function ServerStatusProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [retries, setRetries] = useState<ReadonlyMap<string, Retry>>(new Map());
  const status = useMemo<ServerStatus>(
    () => ({
      report: (key, retry) =>
        setRetries((previous) => new Map(previous).set(key, retry)),
      resolve: (key) =>
        setRetries((previous) => {
          if (!previous.has(key)) return previous;
          const next = new Map(previous);
          next.delete(key);
          return next;
        }),
    }),
    [],
  );

  useEffect(
    () =>
      queryClient.getQueryCache().subscribe((event) => {
        const key = `query:${event.query.queryHash}`;
        // A query no screen reads any more (the learner left it), or one gone
        // from the cache, no longer holds the banner up.
        if (
          event.type === "removed" ||
          (event.type === "observerRemoved" && event.query.getObserversCount() === 0)
        ) {
          status.resolve(key);
          return;
        }
        if (event.type !== "updated") return;
        const { query, action } = event;
        if (action.type === "success") {
          status.resolve(key);
        } else if (action.type === "error" && !isCancelledError(action.error)) {
          if (toApiError(action.error).kind === "unknown") {
            status.report(key, () => {
              void queryClient.refetchQueries({
                queryKey: query.queryKey,
                exact: true,
              });
            });
          } else {
            // Problem Details: the server answered, whatever it said.
            status.resolve(key);
          }
        }
      }),
    [queryClient, status],
  );

  return (
    <StatusContext.Provider value={status}>
      <RetriesContext.Provider value={retries}>{children}</RetriesContext.Provider>
    </StatusContext.Provider>
  );
}

/** Report or resolve a request with no response; a no-op without the provider. */
export function useServerStatus(): ServerStatus {
  return useContext(StatusContext) ?? IGNORED;
}

/**
 * 「アプリのサーバーに接続できません。…」 with [再試行], directly under the
 * header while any request is unanswered; [再試行] sends each one again.
 */
export function ServerUnreachableBanner() {
  const retries = useContext(RetriesContext);
  const status = useServerStatus();
  if (retries.size === 0) return null;
  return (
    <Banner
      className="mx-4 mt-1 shrink-0 max-sm:gap-2 max-sm:p-2 sm:mt-2"
      message={UNREACHABLE_MESSAGE}
      action={{
        label: "再試行",
        onClick: () => {
          for (const [key, retry] of retries) {
            status.resolve(key);
            retry();
          }
        },
      }}
    />
  );
}
