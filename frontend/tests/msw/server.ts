import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll } from "vitest";
import { client } from "../../src/api/generated/client.gen";
import type {
  MetaResponse,
  SessionPageResponse,
} from "../../src/api/generated/types.gen";

// jsdom's fetch and Request are Node's: relative Request URLs need an origin.
// Production keeps the generated client's relative base URL.
client.setConfig({ baseUrl: window.location.origin });
export const server = setupServer(
  // The home screen lists sessions on every visit; none are stored by default.
  http.get("/api/sessions", () =>
    HttpResponse.json<SessionPageResponse>({ items: [], next_cursor: null }),
  ),
  // The header asks on every screen; a model key is configured unless a test
  // says otherwise, so no badge shows by default.
  http.get("/api/meta", () =>
    HttpResponse.json<MetaResponse>({ model_mode: "anthropic" }),
  ),
);

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
