import { type QueryClient, useQuery } from "@tanstack/react-query";
import { createRootRouteWithContext, Link, Outlet } from "@tanstack/react-router";
import { useId, useRef, useState } from "react";
import { getMetaOptions } from "../api/generated/@tanstack/react-query.gen";
import { HeaderSlot, HeaderSlotProvider } from "../lib/HeaderItems";
import { ServerStatusProvider, ServerUnreachableBanner } from "../lib/ServerStatus";
import { NotFound } from "./-NotFound";

/** What every route's loader and beforeLoad receive as `context`. */
export interface RouterContext {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
  notFoundComponent: NotFound,
});

const FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function RootLayout() {
  const main = useRef<HTMLElement>(null);
  return (
    <ServerStatusProvider>
      <HeaderSlotProvider>
        {/* A session screen fills the height the header and any banner leave,
            its panes scrolling inside; any other screen scrolls the page. */}
        <div className="flex min-h-dvh flex-col bg-canvas font-sans text-ink has-[[data-fill-viewport]]:h-dvh">
          <header className="group/header sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 border-b border-line bg-canvas px-4 lg:gap-4">
            {/* Below 1024 px a page's own items take the room; its back link leads home. */}
            <Link
              to="/"
              className={`shrink-0 rounded-sm font-bold max-lg:group-has-[[data-header-slot]:not(:empty)]/header:hidden ${FOCUS_RING}`}
            >
              Intent to English
            </Link>
            <HeaderSlot className="flex min-w-0 flex-1 items-center gap-2 lg:gap-4" />
            <FixedModeBadge />
          </header>
          {/* A request with no response, on any screen: directly under the header. */}
          <ServerUnreachableBanner
            onRetry={() => main.current?.focus({ preventScroll: true })}
          />
          <main
            ref={main}
            tabIndex={-1}
            className={`flex min-h-0 flex-1 flex-col ${FOCUS_RING}`}
          >
            <Outlet />
          </main>
        </div>
      </HeaderSlotProvider>
    </ServerStatusProvider>
  );
}

const TOOLTIP =
  "Anthropic の API キーが未設定のため、決まった応答で動いています。品質の確認には使えません。";

/**
 * 「固定応答モード」 while the API answers with fixed responses. A failed meta
 * request shows nothing: the badge is a notice, not a gate.
 */
function FixedModeBadge() {
  const meta = useQuery(getMetaOptions());
  const tooltipId = useId();
  const [open, setOpen] = useState(false);
  if (meta.data?.model_mode !== "fixed") return null;
  return (
    <span className="relative ml-auto shrink-0">
      <button
        type="button"
        aria-describedby={tooltipId}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        className={`rounded-full bg-badge px-2 py-0.5 text-xs font-bold text-badge-ink ${FOCUS_RING}`}
      >
        固定応答モード
      </button>
      <span
        role="tooltip"
        id={tooltipId}
        hidden={!open}
        className="absolute top-full right-0 z-20 mt-2 w-72 rounded-panel border border-line bg-canvas p-3 text-sm text-ink"
      >
        {TOOLTIP}
      </span>
    </span>
  );
}
