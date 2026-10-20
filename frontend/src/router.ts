import type { QueryClient } from "@tanstack/react-query";
import { createRouter, type RouterHistory } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

export interface AppRouterOptions {
  /** Defaults to the browser's history; tests pass createMemoryHistory(). */
  history?: RouterHistory;
}

/**
 * The app's router over the generated route tree. The caller owns the query
 * client, so the one QueryClientProvider serves and the router's context hold
 * the same instance. Scroll restoration returns S1 to where the learner left
 * it when they come back from a session (ux-guidelines § Navigation).
 */
export function createAppRouter(queryClient: QueryClient, options?: AppRouterOptions) {
  return createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    // Return links create a new history entry; S1 retains one shared position.
    getScrollRestorationKey: (location) =>
      location.pathname === "/" ? "/" : location.state.__TSR_key || location.href,
    ...options,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
