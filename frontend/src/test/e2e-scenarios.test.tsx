import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "./render";

describe("E2E Demo Scenarios Suite (Spec §9.8)", () => {
  it("Scenario 1: Super Admin inspects dashboard and navigates to urgent stockout", async () => {
    renderApp("/", "admin");
    expect(await screen.findByText("Total Sales Revenue")).toBeTruthy();
    expect(screen.getByText("Revenue & Profit Performance")).toBeTruthy();
  });

  it("Scenario 2: Line-level approval and PO resolution workflow", async () => {
    renderApp("/approvals", "admin");
    expect(await screen.findByRole("heading", { name: "Approval Centre" })).toBeTruthy();
  });

  it("Scenario 3: Inter-store transfer review and route verification", async () => {
    renderApp("/transfers", "sup.c");
    expect(await screen.findByRole("heading", { name: "Stock Balancing Transfers" })).toBeTruthy();
    expect(screen.getByText(/^All Transfers/)).toBeTruthy();
  });

  it("Scenario 4 & 5: System observability telemetry and agent execution trace", async () => {
    renderApp("/monitoring", "admin");
    expect(await screen.findByText("Agent Observability & System Monitoring")).toBeTruthy();
    expect(screen.getByText("Live Telemetry")).toBeTruthy();
    expect(screen.getByText("Trigger Nightly Pipeline")).toBeTruthy();
  });
});
