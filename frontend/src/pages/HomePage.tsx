import { useHealth } from "../api/health.ts";

// Phase 1 placeholder. The design system (tokens, AppShell, components) arrives in Phase 7.
export function HomePage() {
  const { data, isPending, isError } = useHealth();

  let apiStatus = "checking…";
  if (isError) apiStatus = "unreachable";
  else if (!isPending) apiStatus = `${data.status} (database: ${data.checks.database}, redis: ${data.checks.redis})`;

  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="text-[28px] font-semibold">RetailPilot AI</h1>
      <p className="mt-2 text-sm">AI replenishment for multi-store FMCG retail.</p>
      <p className="mt-6 text-sm">
        API status: <span className="font-medium">{apiStatus}</span>
      </p>
    </main>
  );
}
