import { createHttpClient, type ApiClient } from "./client";

const TOKEN_KEY = "retailpilot.token";

/** Session token (sessionStorage; tolerant of blocked storage). */
export const tokenStore = {
  get(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string | null): void {
    try {
      if (token) sessionStorage.setItem(TOKEN_KEY, token);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable: the session lasts until reload */
    }
  },
};

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";

/**
 * Mock client loaded on first use, so the mock module and its ~1 MB fixture are a separate chunk that is never
 * downloaded when the real API is used.
 */
function lazyMockClient(getToken: () => string | null): ApiClient {
  let client: Promise<ApiClient> | null = null;
  const load = () => (client ??= import("../mocks/mockClient").then((m) => m.createMockClient(getToken)));
  return new Proxy({} as ApiClient, {
    get: (_target, method: string) =>
      async (...args: unknown[]) => {
        const target = (await load()) as unknown as Record<string, (...a: unknown[]) => Promise<unknown>>;
        const fn = target[method];
        if (!fn) throw new Error(`Unknown API method: ${method}`);
        return fn(...args);
      },
  });
}

export const api: ApiClient = USE_MOCKS ? lazyMockClient(() => tokenStore.get()) : createHttpClient(() => tokenStore.get());

export { ApiError } from "./client";
export type { ApiClient } from "./client";
