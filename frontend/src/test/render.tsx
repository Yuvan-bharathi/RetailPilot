/** Test helper: render routes with the real providers, the mock API (no delay) and a signed-in user. */
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import type { ApiClient } from "../api/client";
import { AppProviders, appRoutes } from "../app/App";
import { createMockClient } from "../mocks/mockClient";

export function memoryTokens(initial: string | null = null) {
  let token = initial;
  return {
    get: () => token,
    set: (next: string | null) => {
      token = next;
    },
  };
}

/** `overrides` replaces individual client methods, e.g. with the real HTTP client over a stubbed fetch. */
export function renderApp(path: string, username: string | null = "admin", overrides: Partial<ApiClient> = {}) {
  const tokens = memoryTokens(username ? `mock-token:${username}` : null);
  const client: ApiClient = { ...createMockClient(tokens.get, 0), ...overrides };
  const router = createMemoryRouter(appRoutes(true), { initialEntries: [path] });
  const utils = render(
    <AppProviders client={client} tokens={tokens}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { ...utils, router, client, tokens };
}
