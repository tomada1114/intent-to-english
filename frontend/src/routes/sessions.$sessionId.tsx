import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ConversationLoadError,
  ConversationScreen,
  ConversationSkeleton,
  sessionQueryOptions,
} from "../features/conversation";
import { TranscriptScreen } from "../features/transcript";
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
  if (query.data !== undefined) {
    // An ended session is S3 on the same URL; ending on S2 switches in place.
    return query.data.status === "ended" ? (
      <TranscriptScreen key={sessionId} view={query.data} backLink={backLink} />
    ) : (
      <ConversationScreen key={sessionId} view={query.data} backLink={backLink} />
    );
  }
  if (query.isError) {
    const error = toApiError(query.error);
    if (error.kind === "problem" && error.code === "session_not_found") {
      return <NotFound />;
    }
    return <ConversationLoadError error={error} />;
  }
  return <ConversationSkeleton />;
}
