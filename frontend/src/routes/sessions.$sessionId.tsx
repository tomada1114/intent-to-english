import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ConversationLoadError,
  ConversationScreen,
  ConversationSkeleton,
  sessionQueryOptions,
} from "../features/conversation";
import { TranscriptScreen } from "../features/transcript";
import { useDelayedLoading } from "../lib/delayed-loading";
import { toApiError } from "../lib/problem-details";
import { NotFound } from "./-NotFound";

export const Route = createFileRoute("/sessions/$sessionId")({
  component: SessionRoute,
});

const BACK_LINK =
  "shrink-0 rounded-sm text-sm text-ink-muted hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function SessionRoute() {
  const { sessionId } = Route.useParams();
  const query = useQuery(sessionQueryOptions(sessionId));
  const backLink = (
    <Link to="/" className={BACK_LINK}>
      ← <span className="max-lg:hidden">会話</span>一覧
    </Link>
  );
  // The skeleton follows the delayed indicator: never under 300 ms, and the
  // session renders once a shown skeleton's 500 ms minimum ends.
  const skeleton = useDelayedLoading(query.data === undefined && query.isFetching);
  if (skeleton) return <ConversationSkeleton />;
  const error = query.isError ? toApiError(query.error) : null;
  // No response at all is the layout's server-unreachable banner instead.
  const loadFailed =
    error?.kind === "problem" ? (
      <ConversationLoadError
        retrying={query.isFetching}
        onRetry={() => void query.refetch()}
      />
    ) : null;
  if (query.data !== undefined) {
    // An ended session is S3 on the same URL; ending on S2 switches in place.
    return query.data.status === "ended" ? (
      <TranscriptScreen key={sessionId} view={query.data} backLink={backLink} />
    ) : (
      <ConversationScreen
        key={sessionId}
        view={query.data}
        backLink={backLink}
        notice={loadFailed}
      />
    );
  }
  if (error?.kind === "problem" && error.code === "session_not_found") {
    return <NotFound />;
  }
  return loadFailed;
}
