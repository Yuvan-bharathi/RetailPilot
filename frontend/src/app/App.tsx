import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { createBrowserRouter, Navigate, Outlet, RouterProvider, useLocation, type RouteObject } from "react-router";

import { api, tokenStore, USE_MOCKS } from "../api";
import type { ApiClient } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ComponentsPage } from "../pages/ComponentsPage";
import { LoginPage } from "../pages/LoginPage";
import { ForbiddenPage, NotFoundPage, PlaceholderPage } from "../pages/SimplePages";
import { ApiProvider } from "./ApiContext";
import { AuthProvider, useAuth } from "./AuthContext";
import { canAccess, NAV_ITEMS } from "./nav";
import { ShellProvider } from "./ShellContext";

interface TokenStore {
  get(): string | null;
  set(token: string | null): void;
}

function ProtectedLayout() {
  const { user, isLoading, signOut } = useAuth();
  const location = useLocation();
  if (isLoading) return <p className="p-6 text-sm text-ink-secondary">Loading…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return (
    <ShellProvider>
      <AppShell user={user} onSignOut={signOut}>
        {canAccess(user.role, location.pathname) || !NAV_ITEMS.some((i) => i.path === location.pathname) ? (
          <Outlet />
        ) : (
          <ForbiddenPage />
        )}
      </AppShell>
    </ShellProvider>
  );
}

function Placeholder() {
  const { user } = useAuth();
  const location = useLocation();
  const item = NAV_ITEMS.find((i) => i.path === location.pathname);
  return <PlaceholderPage title={(user && item?.label[user.role]) ?? "Coming soon"} />;
}

// eslint-disable-next-line react-refresh/only-export-components
export function appRoutes(showDemoUsers: boolean): RouteObject[] {
  return [
    { path: "/login", element: <LoginPage showDemoUsers={showDemoUsers} /> },
    {
      element: <ProtectedLayout />,
      children: [
        ...NAV_ITEMS.map((item) => ({ path: item.path, element: <Placeholder /> })),
        { path: "/components", element: <ComponentsPage /> },
        { path: "*", element: <NotFoundPage /> },
      ],
    },
  ];
}

export function AppProviders({ client, tokens, children }: { client: ApiClient; tokens: TokenStore; children: ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false } } }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>
        <AuthProvider tokens={tokens}>{children}</AuthProvider>
      </ApiProvider>
    </QueryClientProvider>
  );
}

const router = createBrowserRouter(appRoutes(USE_MOCKS));

export function App() {
  return (
    <AppProviders client={api} tokens={tokenStore}>
      <RouterProvider router={router} />
    </AppProviders>
  );
}
