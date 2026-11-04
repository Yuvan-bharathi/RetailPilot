import { Construction, Lock } from "lucide-react";
import { Link } from "react-router";

export function PlaceholderPage({ title }: { title: string }) {
  return (
    <section className="rounded-card border border-border bg-surface p-8 text-center shadow-card">
      <Construction aria-hidden="true" className="mx-auto text-ink-secondary" size={32} />
      <h2 className="mt-3 text-lg font-semibold text-ink">{title}</h2>
      <p className="mt-1 text-sm text-ink-secondary">
        This screen is built in Phase 8. The design system is on the{" "}
        <Link className="text-brand underline" to="/components">
          components page
        </Link>
        .
      </p>
    </section>
  );
}

export function ForbiddenPage() {
  return (
    <section role="alert" className="rounded-card border border-border bg-surface p-8 text-center shadow-card">
      <Lock aria-hidden="true" className="mx-auto text-danger" size={32} />
      <h2 className="mt-3 text-lg font-semibold text-ink">You do not have access to this page</h2>
      <p className="mt-1 text-sm text-ink-secondary">
        <Link className="text-brand underline" to="/">
          Go to your overview
        </Link>
      </p>
    </section>
  );
}

export function NotFoundPage() {
  return (
    <section className="rounded-card border border-border bg-surface p-8 text-center shadow-card">
      <h2 className="text-lg font-semibold text-ink">Page not found</h2>
      <p className="mt-1 text-sm text-ink-secondary">
        <Link className="text-brand underline" to="/">
          Go to your overview
        </Link>
      </p>
    </section>
  );
}
