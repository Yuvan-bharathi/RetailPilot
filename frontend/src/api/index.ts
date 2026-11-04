import { createMockClient } from "../mocks/mockClient";
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

export const api: ApiClient = USE_MOCKS
  ? createMockClient(() => tokenStore.get())
  : createHttpClient(() => tokenStore.get());

export { ApiError } from "./client";
export type { ApiClient } from "./client";
