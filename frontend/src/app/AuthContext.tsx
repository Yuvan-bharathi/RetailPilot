import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import type { MeDTO } from "../api/types";
import { useApi } from "./ApiContext";

interface TokenStore {
  get(): string | null;
  set(token: string | null): void;
}

interface AuthState {
  user: MeDTO | null;
  isLoading: boolean;
  signIn(username: string, password: string): Promise<void>;
  signOut(): void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ tokens, children }: { tokens: TokenStore; children: ReactNode }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [token, setToken] = useState<string | null>(() => tokens.get());

  const me = useQuery({ queryKey: ["me", token], queryFn: () => api.getMe(), enabled: token !== null, retry: false });

  const signIn = useCallback(
    async (username: string, password: string) => {
      const response = await api.login({ username, password });
      tokens.set(response.access_token);
      queryClient.clear();
      setToken(response.access_token);
    },
    [api, queryClient, tokens],
  );

  const signOut = useCallback(() => {
    tokens.set(null);
    queryClient.clear();
    setToken(null);
  }, [queryClient, tokens]);

  const value = useMemo<AuthState>(
    () => ({
      user: token !== null && me.data ? me.data : null,
      isLoading: token !== null && me.isPending,
      signIn,
      signOut,
    }),
    [token, me.data, me.isPending, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth must be used inside <AuthProvider>");
  return state;
}
