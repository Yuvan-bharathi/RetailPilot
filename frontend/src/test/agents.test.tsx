/** Agent console (docs/09 §7) and Ask RetailPilot — on the mock API. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { renderApp } from "./render";

describe("agent console — access", () => {
  it("hides the Agents section from store supervisors and blocks its routes", async () => {
    renderApp("/agents/stock_balancing", "sup.a");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).queryByText("Agents")).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Overview" })).toBeNull();
    expect(within(nav).getByRole("link", { name: "Ask RetailPilot" })).toBeTruthy();
    expect(await screen.findByText("You do not have access to this page")).toBeTruthy();
  });

  it("redirects the old System monitoring route to the agent logs", async () => {
    const { router } = renderApp("/monitoring", "admin");
    await waitFor(() => expect(router.state.location.pathname).toBe("/agents/logs"));
  });
});

describe("agent console — overview", () => {
  it("lists every registered agent in two groups with no axe violations", async () => {
    const { container } = renderApp("/agents", "admin");
    expect(await screen.findByRole("heading", { name: /Nightly pipeline/ })).toBeTruthy();
    for (const name of [
      "Stock Balancing",
      "Purchase Orders",
      "Ask RetailPilot",
      "Run Coordinator",
      "Recommendation Reviewer",
    ]) {
      expect(screen.getByRole("article", { name })).toBeTruthy();
    }
    expect(screen.getByText("All LLM agents")).toBeTruthy();
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);

  it("requires a reason and a second confirmation to turn off a critical agent, then shows the pause banner", async () => {
    renderApp("/agents", "admin");
    const user = userEvent.setup();
    const card = await screen.findByRole("article", { name: "Stock Balancing" });
    await user.click(within(card).getByRole("button", { name: "Turn off Stock Balancing" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Turn off" }));
    expect(within(dialog).getByText("Enter a reason (5+ characters).")).toBeTruthy();
    expect(within(dialog).getByText("Second confirmation required.")).toBeTruthy();
    await user.type(within(dialog).getByLabelText(/Reason/), "Supplier master data migration tonight");
    await user.click(within(dialog).getByLabelText("I confirm that nightly replenishment will be paused."));
    await user.click(within(dialog).getByRole("button", { name: "Turn off" }));
    expect(await screen.findByText(/Replenishment paused by .*Supplier master data migration tonight/)).toBeTruthy();
  });
});

describe("agent console — run now", () => {
  it("starts a dry run by default and asks for reason + confirmation before a live run", async () => {
    renderApp("/agents/stock_balancing", "admin");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Run now" }));
    expect(await screen.findByText(/preview set only/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Start dry run" }));
    expect(await screen.findByText(/DRY_RUN run finished/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "open trace" })).toBeTruthy();

    await user.click(screen.getByLabelText(/Live \(publishes\)/));
    await user.click(await screen.findByRole("button", { name: "Run live…" }));
    const dialog = await screen.findByRole("dialog", { name: "Run Stock Balancing live?" });
    await user.click(within(dialog).getByRole("button", { name: "Run live" }));
    expect(within(dialog).getByText("Enter a reason (5+ characters).")).toBeTruthy();
    expect(within(dialog).getByText("Confirm the consequences first.")).toBeTruthy();
    await user.type(within(dialog).getByLabelText(/Reason/), "Late supplier file re-imported");
    await user.click(within(dialog).getByLabelText("I understand these consequences."));
    await user.click(within(dialog).getByRole("button", { name: "Run live" }));
    expect(await screen.findByText(/LIVE run finished/)).toBeTruthy();
  });

  it("explains that Ask RetailPilot is triggered by questions", async () => {
    renderApp("/agents/ask_retailpilot", "admin");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Run now" }));
    expect(screen.getByText(/This agent is triggered by questions/)).toBeTruthy();
  });
});

describe("agent console — pipeline, flow, logs, decisions", () => {
  it("shows a skipped (disabled) stage and a failed stage when runs are expanded", async () => {
    renderApp("/agents/pipeline", "admin");
    const user = userEvent.setup();
    const expanders = await screen.findAllByRole("button", { name: /Expand stages/ });
    for (const b of expanders) await user.click(b);
    expect(screen.getAllByText("Skipped — disabled").length).toBeGreaterThan(0);
    expect(screen.getByText(/statement timeout/)).toBeTruthy();
    expect(screen.getAllByText(/1 retry/).length).toBeGreaterThan(0);
  });

  it("draws the visual flow with labelled nodes and a human approval gate", async () => {
    const { container } = renderApp("/agents/flow", "admin");
    const user = userEvent.setup();
    const node = await screen.findByRole("button", { name: /^Stock Balancing: Success/ });
    expect(screen.getByRole("button", { name: /^Human approval:/ })).toBeTruthy();
    await user.click(node);
    expect(await screen.findByRole("link", { name: "Open run trace" })).toBeTruthy();
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);

  it("opens a run trace from the logs", async () => {
    renderApp("/agents/logs", "admin");
    const user = userEvent.setup();
    const table = await screen.findByRole("table", { name: /Agent runs/ });
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBeGreaterThan(2));
    await user.click(within(table).getAllByText("Nightly pipeline")[0]!);
    expect(await screen.findByRole("list", { name: "Run timeline" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Export JSON" })).toBeTruthy();
  });

  it("lists decisions with the human outcome and the acceptance table", async () => {
    renderApp("/agents/decisions", "admin");
    expect(await screen.findByRole("table", { name: "Acceptance rate per agent and decision type" })).toBeTruthy();
    const table = await screen.findByRole("table", { name: /Agent decisions/ });
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBeGreaterThan(2));
    expect(within(table).getAllByText("Run Coordinator").length).toBeGreaterThan(0);
  });
});

describe("Ask RetailPilot", () => {
  it("answers with sources and refuses actions", async () => {
    const { container } = renderApp("/ask", "sup.c");
    const user = userEvent.setup();
    const input = await screen.findByLabelText(/Ask a question/);
    await user.type(input, "Please approve the butter order");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Not allowed — read-only assistant")).toBeTruthy();
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);
});
