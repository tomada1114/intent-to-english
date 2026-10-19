import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useId, useRef } from "react";
import {
  createSessionMutation,
  listSessionsInfiniteOptions,
} from "../../api/generated/@tanstack/react-query.gen";
import type { SessionSummaryResponse } from "../../api/generated/types.gen";
import { ErrorMessage } from "../../lib/ErrorMessage";
import { formatCount, formatStart } from "../../lib/format";
import { toApiError } from "../../lib/problem-details";
import { FOCUS_RING, PRIMARY_BUTTON, SECONDARY_BUTTON } from "../../lib/ui";
import { useDelayedLoading } from "./hooks";

/** One page of the list, as requirements §3.9 sets it. */
export const SESSION_PAGE_SIZE = 20;
/** How many characters of the opener a row shows before 「…」. */
export const OPENER_LIMIT = 60;

const TAGLINE = "英語で話す前に、日本語で言いたいことを決める練習";
const SKELETON_ROWS = [0, 1, 2];

/** The opener cut to 60 characters (code points), with 「…」 when it was longer. */
export function shortOpener(opener: string): string {
  const characters = Array.from(opener);
  return characters.length <= OPENER_LIMIT
    ? opener
    : `${characters.slice(0, OPENER_LIMIT).join("")}…`;
}

function repliesLabel(count: number): string {
  return `${formatCount(count)}往復`;
}

/**
 * S1, the home screen: the tagline, the start button, the resume card for the
 * newest in-progress session, and the newest-first list of past sessions.
 */
export function HomeScreen() {
  return (
    <div className="mx-auto max-w-[880px] space-y-8 px-4 py-8">
      <div className="space-y-6">
        <h1 className="text-2xl leading-[1.35] font-bold">{TAGLINE}</h1>
        <StartSession />
      </div>
      <SessionList />
    </div>
  );
}

/** 「新しい会話を始める」: focused on load, usable at once, and opens S2 on success. */
function StartSession() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const button = useRef<HTMLButtonElement>(null);
  const start = useMutation({
    ...createSessionMutation(),
    onSuccess: async (view) => {
      void queryClient.invalidateQueries({ queryKey: [{ _id: "listSessions" }] });
      await navigate({ to: "/sessions/$sessionId", params: { sessionId: view.id } });
    },
  });
  useEffect(() => {
    // No scroll: coming back from a session, the router has already restored
    // where the learner was in the list.
    button.current?.focus({ preventScroll: true });
  }, []);
  return (
    <div className="space-y-3">
      <button
        ref={button}
        type="button"
        disabled={start.isPending}
        onClick={() => start.mutate({})}
        className={PRIMARY_BUTTON}
      >
        新しい会話を始める
      </button>
      {start.isError && <ErrorMessage error={toApiError(start.error)} />}
    </div>
  );
}

function SessionList() {
  const headingId = useId();
  const query = useInfiniteQuery({
    ...listSessionsInfiniteOptions({ query: { limit: SESSION_PAGE_SIZE } }),
    initialPageParam: {},
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    // The list sits unread for the whole of a session on S2, which outlasts
    // the default five minutes; coming back must find every page it loaded.
    gcTime: Number.POSITIVE_INFINITY,
  });
  const skeleton = useDelayedLoading(query.isPending);
  const heading = (
    <h2 id={headingId} className="text-xl font-bold">
      これまでの会話
    </h2>
  );

  if (skeleton) {
    return (
      <section aria-labelledby={headingId} className="space-y-3">
        {heading}
        <ListSkeleton />
      </section>
    );
  }
  if (query.isPending) return null;
  if (query.isError && query.data === undefined) {
    return (
      <section aria-labelledby={headingId} className="space-y-3">
        {heading}
        <LoadFailed retrying={query.isFetching} onRetry={() => void query.refetch()} />
      </section>
    );
  }

  const sessions = query.data.pages.flatMap((page) => page.items);
  if (sessions.length === 0) {
    return (
      <p className="text-ink-muted">まだ会話はありません。最初の会話を始めましょう。</p>
    );
  }
  const resume = query.data.pages[0]?.items.find(
    (session) => session.status === "in_progress",
  );
  return (
    <div className="space-y-8">
      {resume !== undefined && <ResumeCard session={resume} />}
      <section aria-labelledby={headingId} className="space-y-3">
        {heading}
        <ul
          aria-labelledby={headingId}
          className="divide-y divide-line border-y border-line"
        >
          {sessions.map((session) => (
            <li key={session.id}>
              <SessionRow session={session} />
            </li>
          ))}
        </ul>
        {query.hasNextPage && !query.isFetchNextPageError && (
          <button
            type="button"
            disabled={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
            className={SECONDARY_BUTTON}
          >
            さらに表示
          </button>
        )}
        {query.isError && (
          <LoadFailed
            retrying={query.isFetching}
            onRetry={() =>
              void (query.isFetchNextPageError
                ? query.fetchNextPage()
                : query.refetch())
            }
          />
        )}
      </section>
    </div>
  );
}

/** A row: start time · status · 「N往復」 · the opener; the whole row is the link. */
function SessionRow({ session }: { session: SessionSummaryResponse }) {
  return (
    <Link
      to="/sessions/$sessionId"
      params={{ sessionId: session.id }}
      className={`grid grid-cols-[auto_auto_auto] items-baseline gap-x-4 gap-y-1 rounded-sm px-2 py-3 hover:bg-surface sm:grid-cols-[auto_auto_auto_minmax(0,1fr)] ${FOCUS_RING}`}
    >
      <span className="text-[13px] text-ink-muted tabular-nums">
        {formatStart(session.started_at)}
      </span>{" "}
      <span className="text-[13px]">
        {session.status === "in_progress" ? "進行中" : "終了"}
      </span>{" "}
      <span className="text-[13px] tabular-nums">
        {repliesLabel(session.finished_replies)}
      </span>
      {session.opener !== null && (
        <>
          {" "}
          <span
            lang="en"
            className="col-span-3 min-w-0 font-en break-words sm:col-span-1"
          >
            {shortOpener(session.opener)}
          </span>
        </>
      )}
    </Link>
  );
}

/** 「続きから」: the newest in-progress session on the first page, and [続ける]. */
function ResumeCard({ session }: { session: SessionSummaryResponse }) {
  const titleId = useId();
  return (
    <section
      aria-labelledby={titleId}
      className="space-y-2 rounded-panel border border-line bg-surface p-4"
    >
      <h2 id={titleId} className="text-xs font-bold text-ink">
        続きから
      </h2>
      {session.opener !== null && (
        <p className="break-words">
          <span aria-hidden="true">🗣 </span>
          <span lang="en" className="font-en">
            {shortOpener(session.opener)}
          </span>
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-ink-muted tabular-nums">
          {`${formatStart(session.started_at)} から · ${repliesLabel(session.finished_replies)}`}
        </p>
        <Link
          to="/sessions/$sessionId"
          params={{ sessionId: session.id }}
          className={SECONDARY_BUTTON}
        >
          続ける
        </Link>
      </div>
    </section>
  );
}

/** Three rows in the list's final layout while it loads. */
function ListSkeleton() {
  return (
    <div>
      <p role="status" className="sr-only">
        読み込んでいます…
      </p>
      <div aria-hidden="true" className="divide-y divide-line border-y border-line">
        {SKELETON_ROWS.map((row) => (
          <div key={row} data-skeleton-row="" className="px-2 py-3">
            <div className="h-5 rounded-sm bg-line motion-safe:animate-pulse" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** 「会話の一覧を読み込めませんでした。」 [再読み込み], in place of the list. */
function LoadFailed({ retrying, onRetry }: { retrying: boolean; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-panel border border-danger-edge bg-danger-tint p-4 text-danger"
    >
      <p className="flex items-center gap-2">
        <span aria-hidden="true">⚠</span>
        会話の一覧を読み込めませんでした。
      </p>
      <button
        type="button"
        disabled={retrying}
        onClick={onRetry}
        className={SECONDARY_BUTTON}
      >
        再読み込み
      </button>
    </div>
  );
}
