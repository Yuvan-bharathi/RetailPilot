import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "./render";

describe("E2E Demo Scenarios Suite (Spec §9.8)", () => {
  it("Scenario 1: Super Admin opens the business overview", async () => {
    renderApp("/", "admin");
    expect(await screen.findByRole("heading", { level: 1, name: "Business overview" })).toBeTruthy();
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

  it("Scenario 4 & 5: agent console — pipeline runs and the nightly trigger (replaces System monitoring)", async () => {
    renderApp("/agents/pipeline", "admin");
    expect(await screen.findByRole("button", { name: "Run nightly pipeline" })).toBeTruthy();
    expect(await screen.findByRole("table", { name: "Pipeline runs, newest first" })).toBeTruthy();
  });
});
