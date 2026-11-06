"""Locust load test for RetailPilot AI backend performance targets (spec Phase 9).

Targets:
    - Cached reads (Dashboard, Recommendations, Stores): p95 < 200 ms
    - Uncached reads (Inventory movements keyset paging, Agent runs trace): p95 < 500 ms

Usage:
    cd backend && uv run locust -f tests/load/locustfile.py --headless -u 20 -r 5 --run-time 30s --host http://127.0.0.1:8000
"""

from locust import HttpUser, between, task


class RetailPilotUser(HttpUser):
    wait_time = between(0.5, 2.0)
    token: str | None = None
    store_id: str | None = None

    def on_start(self) -> None:
        """Authenticate user and obtain JWT token before issuing requests."""
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "demo"},
        )
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("access_token")
            self.client.headers.update({"Authorization": f"Bearer {self.token}"})

        # Fetch stores list
        stores_resp = self.client.get("/api/v1/stores")
        if stores_resp.status_code == 200:
            stores = stores_resp.json()
            if stores:
                self.store_id = stores[0].get("store_id")

    # -------------------------------------------------------------
    # Cached Reads: Target p95 < 200 ms (SD-11 Redis Cache-Aside)
    # -------------------------------------------------------------

    @task(5)
    def test_cached_dashboard_summary(self) -> None:
        """Reads aggregated KPI dashboard (Redis cached)."""
        with self.client.get("/api/v1/dashboard?period=LAST_28_DAYS", catch_response=True) as resp:
            if resp.status_code == 200:
                if resp.elapsed.total_seconds() > 0.200:
                    resp.failure(f"Cached read SLA exceeded: {resp.elapsed.total_seconds():.3f}s > 0.200s")
                else:
                    resp.success()

    @task(4)
    def test_cached_recommendations(self) -> None:
        """Reads recommendations inbox."""
        with self.client.get("/api/v1/recommendations", catch_response=True) as resp:
            if resp.status_code == 200:
                if resp.elapsed.total_seconds() > 0.200:
                    resp.failure(
                        f"Recommendations read SLA exceeded: {resp.elapsed.total_seconds():.3f}s > 0.200s"
                    )
                else:
                    resp.success()

    @task(3)
    def test_cached_stores(self) -> None:
        """Reads stores network directory."""
        with self.client.get("/api/v1/stores", catch_response=True) as resp:
            if resp.status_code == 200:
                if resp.elapsed.total_seconds() > 0.200:
                    resp.failure(f"Stores read SLA exceeded: {resp.elapsed.total_seconds():.3f}s > 0.200s")
                else:
                    resp.success()

    # -------------------------------------------------------------
    # Uncached Reads: Target p95 < 500 ms (Database Keyset Paging)
    # -------------------------------------------------------------

    @task(2)
    def test_uncached_inventory_movements(self) -> None:
        """Cursor-paged partition movements ledger query."""
        if not self.store_id:
            return
        with self.client.get(
            f"/api/v1/stores/{self.store_id}/inventory/movements?limit=25",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                if resp.elapsed.total_seconds() > 0.500:
                    resp.failure(f"Ledger paging SLA exceeded: {resp.elapsed.total_seconds():.3f}s > 0.500s")
                else:
                    resp.success()

    @task(2)
    def test_uncached_agent_runs(self) -> None:
        """Agent runs observability telemetry list."""
        with self.client.get("/api/v1/agent-runs?page_size=50", catch_response=True) as resp:
            if resp.status_code == 200:
                if resp.elapsed.total_seconds() > 0.500:
                    resp.failure(f"Telemetry SLA exceeded: {resp.elapsed.total_seconds():.3f}s > 0.500s")
                else:
                    resp.success()
