/** Phase 8a screens on the exported fixtures: Store Inventory, Recommendations inbox and detail. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { createHttpClient } from "../api/client";
import type { InventoryMovementDTO, RecommendationDTO } from "../api/types";
import { FIXTURES } from "../mocks/fixtures";
import { renderApp } from "../test/render";

const store = (code: string) => FIXTURES.stores.find((s) => s.code === code)!;
const scenarioRec = (n: "1" | "2" | "3" | "4" | "5", type: RecommendationDTO["rec_type"]) =>
  FIXTURES.recommendations.find((r) => FIXTURES.scenarios[n].rec_ids.includes(r.rec_id) && r.rec_type === type)!;

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe("Store Inventory", () => {
  it("asks the super admin to pick a store, then remembers it", async () => {
    const user = userEvent.setup();
    const first = renderApp("/inventory", "admin");
    expect(await screen.findByRole("heading", { name: "Choose a store" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: new RegExp(store("C").name) }));
    expect(await screen.findByRole("region", { name: "Store inventory" })).toBeTruthy();
    first.unmount();

    renderApp("/inventory", "admin"); // last store selected is the default next time
    const select = (await screen.findByLabelText("Inventory for")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe(store("C").store_id));
    expect(screen.queryByRole("heading", { name: "Choose a store" })).toBeNull();
  });

  it("shows a supervisor their own store directly, with shelf and backroom as separate columns", async () => {
    renderApp("/inventory", "sup.a");
    const table = await screen.findByRole("region", { name: "Store inventory" });
    await within(table).findAllByRole("row");
    for (const header of [
      "Shelf",
      "Shelf min",
      "Backroom",
      "Available",
      "Own requirement",
      "Surplus / shortage",
      "Stockout risk",
    ]) {
      expect(within(table).getByRole("columnheader", { name: header })).toBeTruthy();
    }
    expect(screen.queryByLabelText("Inventory for")).toBeNull();
    expect(screen.getByText(store("A").name)).toBeTruthy();
  });

  it("filters by the summary chips", async () => {
    const user = userEvent.setup();
    renderApp("/inventory", "sup.c");
    const chip = await screen.findByRole("button", { name: /^High stockout risk · \d+/ });
    const count = Number(chip.textContent?.split("·")[1]);
    await user.click(chip);
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(screen.getByText(count === 0 ? "No rows" : new RegExp(`of ${count}$`))).toBeTruthy());
  });

  it("switches tabs with the arrow keys and shows the ledger, batches and expiring stock", async () => {
    const user = userEvent.setup();
    renderApp("/inventory", "sup.a");
    const tab = await screen.findByRole("tab", { name: "All products" });
    tab.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Stock moves" }).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("region", { name: "Stock moves (movement ledger)" })).toBeTruthy();
    await user.keyboard("{End}");
    expect(await screen.findByRole("region", { name: "Batches expiring within 14 days" })).toBeTruthy();
    expect(await screen.findByText("30 will not sell in time")).toBeTruthy(); // scenario 5 paneer batch in Store A
    await user.keyboard("{ArrowLeft}");
    expect(await screen.findByRole("region", { name: "Batches (earliest expiry first)" })).toBeTruthy();
  });

  it("pages the stock-move ledger forwards and back by cursor, without a total", async () => {
    const user = userEvent.setup();
    renderApp("/inventory", "sup.a");
    await screen.findByRole("region", { name: "Store inventory" });
    await user.click(screen.getByRole("tab", { name: "Stock moves" }));
    const ledger = await screen.findByRole("region", { name: "Stock moves (movement ledger)" });
    const firstRow = FIXTURES.movements[store("A").store_id]![0]!;
    const row26 = FIXTURES.movements[store("A").store_id]![25]!;
    await waitFor(() => expect(within(ledger).getAllByRole("row")).toHaveLength(26)); // header + 25
    expect(screen.getByText("Showing 1–25")).toBeTruthy();
    expect(screen.getByText("Page 1")).toBeTruthy();
    expect(within(ledger).queryByRole("button", { name: /When/ })).toBeNull(); // fixed order: not sortable

    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Showing 26–50")).toBeTruthy();
    expect(screen.getByText("Page 2")).toBeTruthy();
    expect(within(ledger).getAllByRole("row")[1]!.textContent).toContain(row26.product.name);

    await user.click(screen.getByRole("button", { name: "Previous page" }));
    expect(await screen.findByText("Showing 1–25")).toBeTruthy();
    expect(within(ledger).getAllByRole("row")[1]!.textContent).toContain(firstRow.product.name);
  });

  it("with the real HTTP client, Previous from page 2 returns exactly page 1 (cursor stack in useCursorPaging)", async () => {
    // A fake server behind a stubbed fetch: keyset pages over Store A's ledger; the cursor is opaque to the client.
    const rows = FIXTURES.movements[store("A").store_id]!;
    const requests: URLSearchParams[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const params = new URL(input, "http://test").searchParams;
        requests.push(params);
        const start = params.get("cursor") ? Number(atob(params.get("cursor")!)) : 0;
        const size = Number(params.get("page_size"));
        const items = rows.slice(start, start + size);
        const next = start + size < rows.length ? btoa(String(start + size)) : null;
        return new Response(JSON.stringify({ items, next_cursor: next, page_size: size }), { status: 200 });
      }),
    );
    const http = createHttpClient(() => "token");
    const user = userEvent.setup();
    renderApp("/inventory", "sup.a", { listStoreMovements: http.listStoreMovements });
    await screen.findByRole("region", { name: "Store inventory" });
    await user.click(screen.getByRole("tab", { name: "Stock moves" }));
    const ledger = await screen.findByRole("region", { name: "Stock moves (movement ledger)" });
    const shown = () =>
      within(ledger)
        .getAllByRole("row")
        .slice(1)
        .map((r) => r.textContent);
    const expected = (page: InventoryMovementDTO[]) => page.map((m) => m.product.name);

    await screen.findByText("Showing 1–25");
    const page1 = shown();
    expect(page1.map((t, i) => t?.includes(expected(rows.slice(0, 25))[i]!))).not.toContain(false);
    expect(requests.at(-1)!.has("cursor")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("Showing 26–50");
    expect(requests.at(-1)!.get("cursor")).toBe(btoa("25")); // the next_cursor of page 1, passed back verbatim

    await user.click(screen.getByRole("button", { name: "Previous page" }));
    await screen.findByText("Showing 1–25");
    expect(shown()).toEqual(page1); // exactly page 1: same rows, same order
    const pageOneRequests = requests.filter((p) => !p.has("cursor"));
    expect(pageOneRequests.every((p) => p.get("page_size") === "25")).toBe(true);
  });

  it("opens a read-only product drawer with recommendations, transfers and batches", async () => {
    const user = userEvent.setup();
    renderApp("/inventory", "sup.c");
    const table = await screen.findByRole("region", { name: "Store inventory" });
    await user.type(screen.getByRole("searchbox"), "Biscuits 200");
    const cell = await within(table).findByText("Biscuits 200 g (demo)");
    await user.click(cell);
    const drawer = await screen.findByRole("dialog", { name: "Biscuits 200 g (demo)" });
    expect(await within(drawer).findByRole("link", { name: /Transfer · 24 units/ })).toBeTruthy();
    expect(within(drawer).getByRole("link", { name: /Reorder · 16 units/ })).toBeTruthy();
    expect(await within(drawer).findByText(new RegExp(`From ${store("A").name} · 24 units`))).toBeTruthy();
    expect(within(drawer).queryByRole("button", { name: /approve|reject/i })).toBeNull(); // read-only
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = renderApp("/inventory", "sup.a");
    await screen.findByRole("region", { name: "Store inventory" });
    await screen.findByText(/^Showing 1–25 of/);
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);
});

describe("Recommendations inbox", () => {
  it("filters by type through the URL and opens a recommendation", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/recommendations", "sup.c");
    await screen.findByRole("region", { name: "AI recommendations" });
    await user.selectOptions(screen.getByLabelText("Type"), "TRANSFER");
    await waitFor(() => expect(router.state.location.search).toContain("type=TRANSFER"));
    const table = screen.getByRole("region", { name: "AI recommendations" });
    const row = await within(table).findByText("Biscuits 200 g (demo)");
    await user.click(row);
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(`/recommendations/${scenarioRec("3", "TRANSFER").rec_id}`),
    );
  });

  it("restores filters from the URL and lists high priority first", async () => {
    renderApp("/recommendations?priority=HIGH", "admin");
    const table = await screen.findByRole("region", { name: "AI recommendations" });
    await within(table).findAllByText("High");
    expect(within(table).queryByText("Normal")).toBeNull();
    expect((screen.getByLabelText("Priority") as HTMLSelectElement).value).toBe("HIGH");
  });

  it("hides the store column for a supervisor and has no axe violations", async () => {
    const { container } = renderApp("/recommendations", "sup.b");
    const table = await screen.findByRole("region", { name: "AI recommendations" });
    await screen.findByText(/^Showing 1–/);
    expect(within(table).queryByRole("columnheader", { name: "Store" })).toBeNull();
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);
});

describe("Recommendation detail", () => {
  it("scenario 3 for the destination supervisor: transfer and PO remainder shown separately, donor as name + quantity", async () => {
    const { container } = renderApp(`/recommendations/${scenarioRec("3", "TRANSFER").rec_id}`, "sup.c");
    await screen.findByRole("heading", { name: "Transfer · Biscuits 200 g (demo)" });
    expect(screen.getByText("Transfer now").nextSibling?.textContent).toBe("24 units");
    expect(screen.getByText("Order from supplier").nextSibling?.textContent).toBe("16 units");
    const evidence = screen.getByRole("region", { name: "Decision evidence" });
    expect(within(evidence).getByText(`${store("A").name} · 24 units`)).toBeTruthy();
    expect(within(evidence).getByText("Donor keeps its full requirement")).toBeTruthy();
    expect(within(evidence).queryByText("Donor surplus")).toBeNull();
    expect(screen.queryByRole("button", { name: /approve|reject|edit/i })).toBeNull(); // read-only in 8a
    expect(await axe(container)).toHaveNoViolations();
  }, 20_000);

  it("scenario 3 for the donor supervisor shows its own surplus and protected requirement", async () => {
    renderApp(`/recommendations/${scenarioRec("3", "TRANSFER").rec_id}`, "sup.a");
    const evidence = await screen.findByRole("region", { name: "Decision evidence" });
    expect(within(evidence).getByText("Donor surplus")).toBeTruthy();
    expect(within(evidence).getByText("30 units kept")).toBeTruthy();
  });

  it("scenario 3 reorder explains the partial surplus", async () => {
    renderApp(`/recommendations/${scenarioRec("3", "REORDER").rec_id}`, "sup.c");
    const evidence = await screen.findByRole("region", { name: "Decision evidence" });
    expect(within(evidence).getByText("Other stores could cover only part of the need")).toBeTruthy();
    expect(screen.getByText("Covered by transfer").nextSibling?.textContent).toBe("24 units");
  });

  it("scenario 4 co-replenishment shows the bread rule; scenario 5 shows the expiring batch", async () => {
    const first = renderApp(`/recommendations/${scenarioRec("4", "CO_REPLENISH").rec_id}`, "sup.a");
    const co = await screen.findByRole("region", { name: "Decision evidence" });
    expect(within(co).getByText("Bread 400 g (demo)")).toBeTruthy();
    first.unmount();

    renderApp(`/recommendations/${scenarioRec("5", "TRANSFER").rec_id}`, "sup.c");
    const expiry = await screen.findByRole("region", { name: "Decision evidence" });
    expect(within(expiry).getByText("Why this batch should move")).toBeTruthy();
    expect(within(expiry).getByText(/5 days left/)).toBeTruthy();
  });

  it("tells a supervisor of an uninvolved store that it belongs to another store", async () => {
    renderApp(`/recommendations/${scenarioRec("3", "TRANSFER").rec_id}`, "sup.b");
    expect(await screen.findByText("This recommendation belongs to another store.")).toBeTruthy();
  });
});
