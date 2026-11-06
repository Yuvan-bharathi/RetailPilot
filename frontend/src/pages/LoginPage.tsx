import { ShoppingBasket } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Navigate } from "react-router";

import { ApiError } from "../api/client";
import { useAuth } from "../app/AuthContext";
import { Button } from "../components/Button";

// demo-login buttons are always shown since ba0528b; the prop is kept for the route signature
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function LoginPage(_props: { showDemoUsers: boolean }) {
  const { user, signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const errorId = useId();

  if (user) return <Navigate to="/" replace />;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401 ? "Wrong username or password." : "Sign-in failed. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-app p-4">
      <div className="w-full max-w-sm rounded-card border border-border bg-surface p-6 shadow-card">
        <div className="mb-6 flex items-center gap-2">
          <ShoppingBasket aria-hidden="true" className="text-brand" size={28} />
          <h1 className="text-[22px] font-semibold text-ink">RetailPilot AI</h1>
        </div>
        <form onSubmit={onSubmit} noValidate aria-describedby={error ? errorId : undefined} className="space-y-4">
          <div>
            <label htmlFor="username" className="text-sm font-medium">
              Username
            </label>
            <input
              id="username"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-1 h-10 w-full rounded-input border border-border px-3"
            />
          </div>
          <div>
            <label htmlFor="password" className="text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 h-10 w-full rounded-input border border-border px-3"
            />
          </div>
          {error ? (
            <p id={errorId} role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <Button type="submit" className="w-full" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        {/* Demo Fast-Login Helpers */}
        <div className="mt-6 border-t border-divider pt-4">
          <p className="text-xs font-medium text-ink-secondary">Quick Demo Sign-In (password: demo):</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                setUsername("admin");
                setPassword("demo");
              }}
              className="rounded-button border border-border bg-app px-2.5 py-1 text-xs font-medium text-ink transition hover:border-brand hover:bg-brand-soft/40"
            >
              Super Admin (admin)
            </button>
            <button
              type="button"
              onClick={() => {
                setUsername("sup.c");
                setPassword("demo");
              }}
              className="rounded-button border border-border bg-app px-2.5 py-1 text-xs font-medium text-ink transition hover:border-brand hover:bg-brand-soft/40"
            >
              Supervisor (sup.c)
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
