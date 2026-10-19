import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ConversationLoadError,
  ConversationScreen,
  ConversationSkeleton,
  sessionQueryOptions,
} from "../features/conversation";
import { toApiError } from "../lib/problem-details";

export const Route = createFileRoute("/sessions/$sessionId")({
  component: SessionRoute,
});

const BACK_LINK =
  "shrink-0 rounded-sm text-sm text-ink-muted hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function SessionRoute() {
  const { sessionId } = Route.useParams();
  const query = useQuery(sessionQueryOptions(sessionId));
  if (query.data !== undefined) {
    return (
      <ConversationScreen
        key={sessionId}
        view={query.data}
        backLink={
          <Link to="/" className={BACK_LINK}>
            ← 会話一覧
          </Link>
        }
      />
    );
  }
  if (query.isError) return <ConversationLoadError error={toApiError(query.error)} />;
  return <ConversationSkeleton />;
}
