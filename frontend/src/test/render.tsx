/** Test helper: render routes with the real providers, the mock API (no delay) and a signed-in user. */
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

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

export function renderApp(path: string, username: string | null = "admin") {
  const tokens = memoryTokens(username ? `mock-token:${username}` : null);
  const client = createMockClient(tokens.get, 0);
  const router = createMemoryRouter(appRoutes(true), { initialEntries: [path] });
  const utils = render(
    <AppProviders client={client} tokens={tokens}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { ...utils, router, client, tokens };
}
