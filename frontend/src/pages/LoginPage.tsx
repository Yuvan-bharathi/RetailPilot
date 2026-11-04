import { ShoppingBasket } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Navigate } from "react-router";

import { ApiError } from "../api/client";
import { useAuth } from "../app/AuthContext";
import { Button } from "../components/Button";

export function LoginPage({ showDemoUsers }: { showDemoUsers: boolean }) {
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
        {showDemoUsers ? (
          <p className="mt-6 text-xs text-ink-secondary">
            Demo (mock data): <strong>admin</strong>, <strong>sup.a</strong>, <strong>sup.b</strong> or{" "}
            <strong>sup.c</strong> with password <strong>demo</strong>.
          </p>
        ) : null}
      </div>
    </main>
  );
}
