import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { DataTable, type Column, type TableQuery } from "./DataTable";
import { deadlineState, DeadlineCountdown } from "./DeadlineCountdown";
import { ConfirmDialog, Modal } from "./Modal";
import { StatusBadge, statusDisplay } from "./StatusBadge";

interface Row {
  id: string;
  name: string;
  qty: number;
}
const ROWS: Row[] = Array.from({ length: 23 }, (_, i) => ({ id: `r${i}`, name: `Item ${i}`, qty: i * 2 }));
const COLUMNS: Column<Row>[] = [
  { id: "name", header: "Product", sortable: true, cell: (r) => r.name },
  { id: "qty", header: "Qty", sortable: true, align: "right", cell: (r) => r.qty },
  { id: "note", header: "Note", cell: () => "—" },
];

function ServerTable({ onQuery }: { onQuery?: (q: TableQuery) => void }) {
  const [query, setQuery] = useState<TableQuery>({ page: 1, pageSize: 10 });
  const sorted = [...ROWS].sort((a, b) => (query.sort === "-qty" ? b.qty - a.qty : a.qty - b.qty));
  const items = sorted.slice((query.page - 1) * query.pageSize, query.page * query.pageSize);
  return (
    <DataTable
      caption="Test table"
      columns={COLUMNS}
      page={{ items, total: ROWS.length, page: query.page, page_size: query.pageSize }}
      query={query}
      onQueryChange={(q) => {
        setQuery(q);
        onQuery?.(q);
      }}
      getRowId={(r) => r.id}
    />
  );
}

describe("StatusBadge", () => {
  it("always shows a text label next to an icon", () => {
    const { container } = render(<StatusBadge tone="danger" label="Rejected" />);
    expect(screen.getByText("Rejected")).toBeTruthy();
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("maps statuses to readable labels", () => {
    expect(statusDisplay("PENDING_L2")).toEqual({ tone: "info", label: "Pending L2" });
    expect(statusDisplay("SOMETHING_NEW").label).toBe("something new");
  });
});

describe("DataTable", () => {
  it("shows loading, empty and error states", async () => {
    const onRetry = vi.fn();
    const common = {
      caption: "T",
      columns: COLUMNS,
      query: { page: 1, pageSize: 10 },
      onQueryChange: () => {},
      getRowId: (r: Row) => r.id,
    };
    const { rerender } = render(<DataTable {...common} page={undefined} isLoading />);
    expect(screen.getByRole("region", { name: "T" }).getAttribute("aria-busy")).toBe("true");

    rerender(
      <DataTable {...common} page={{ items: [], total: 0, page: 1, page_size: 10 }} emptyTitle="Nothing here" />,
    );
    expect(screen.getByText("Nothing here")).toBeTruthy();

    rerender(<DataTable {...common} page={undefined} error="Server down" onRetry={onRetry} />);
    expect(screen.getByRole("alert").textContent).toContain("Server down");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("asks the server to sort and page", async () => {
    const onQuery = vi.fn();
    render(<ServerTable onQuery={onQuery} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Qty" }));
    expect(onQuery).toHaveBeenLastCalledWith({ page: 1, pageSize: 10, sort: "qty" });
    await user.click(screen.getByRole("button", { name: "Qty" }));
    expect(onQuery).toHaveBeenLastCalledWith({ page: 1, pageSize: 10, sort: "-qty" });
    expect(screen.getByRole("columnheader", { name: /Qty/ }).getAttribute("aria-sort")).toBe("descending");

    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(onQuery).toHaveBeenLastCalledWith({ page: 2, pageSize: 10, sort: "-qty" });
    expect(screen.getByText("Showing 11–20 of 23")).toBeTruthy();
  });

  it("is keyboard operable: tab to a sort header and press Enter", async () => {
    const onQuery = vi.fn();
    render(<ServerTable onQuery={onQuery} />);
    const user = userEvent.setup();

    await user.tab(); // Columns button
    await user.tab(); // scrollable table region (focusable so keyboard users can scroll it)
    expect(document.activeElement?.getAttribute("role")).toBe("region");
    await user.tab(); // first sortable header
    expect(document.activeElement?.textContent).toBe("Product");
    await user.keyboard("{Enter}");
    expect(onQuery).toHaveBeenLastCalledWith({ page: 1, pageSize: 10, sort: "name" });
  });

  it("hides a column from the column chooser and closes it with Escape", async () => {
    render(<ServerTable />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Columns" }));
    await user.click(screen.getByRole("checkbox", { name: "Note" }));
    expect(screen.queryByRole("columnheader", { name: "Note" })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Product" })).toBeNull(); // first column cannot be hidden
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: "Visible columns" })).toBeNull();
    expect(document.activeElement?.textContent).toContain("Columns");
  });

  it("pins the first column for horizontal scrolling", () => {
    render(<ServerTable />);
    const firstCell = screen.getAllByRole("row")[1]!.querySelector("td");
    expect(firstCell?.className).toContain("sticky");
  });

  it("has no axe violations", async () => {
    const { container } = render(<ServerTable />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("Modal and ConfirmDialog", () => {
  function Opener() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>Open</button>
        <Modal open={open} title="Edit quantity" onClose={() => setOpen(false)} footer={<button>Save</button>}>
          <input aria-label="Quantity" />
        </Modal>
      </>
    );
  }

  it("moves focus in, traps Tab, closes on Escape and returns focus", async () => {
    render(<Opener />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    const dialog = screen.getByRole("dialog", { name: "Edit quantity" });
    expect(dialog.contains(document.activeElement)).toBe(true);

    for (let i = 0; i < 5; i += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement?.textContent).toBe("Open");
  });

  it("requires a written reason before confirming", async () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Reject line?"
        reason="Not needed"
        consequences={["Line closed"]}
        approver="You (L1)"
        confirmLabel="Reject"
        destructive
        requireReason
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );
    const user = userEvent.setup();
    const dialog = screen.getByRole("dialog", { name: "Reject line?" });
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText("Enter a reason before confirming.")).toBeTruthy();

    await user.type(screen.getByRole("textbox", { name: /Your reason/ }), "Enough stock");
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));
    expect(onConfirm).toHaveBeenCalledWith("Enough stock");
    expect(await axe(dialog)).toHaveNoViolations();
  });
});

describe("DeadlineCountdown", () => {
  const now = Date.parse("2026-11-03T06:00:00Z");
  const at = (hours: number) => new Date(now + hours * 3_600_000).toISOString();

  it("classifies on time, due soon, overdue and escalated", () => {
    expect(deadlineState(at(5), now, false)).toBe("on-time");
    expect(deadlineState(at(1.5), now, false)).toBe("due-soon");
    expect(deadlineState(at(-1), now, false)).toBe("overdue");
    expect(deadlineState(at(-1), now, true)).toBe("escalated");
  });

  it("renders readable labels", () => {
    render(
      <>
        <DeadlineCountdown deadline={at(5.5)} now={now} />
        <DeadlineCountdown deadline={at(-2.25)} now={now} />
        <DeadlineCountdown deadline={at(30)} now={now} />
        <DeadlineCountdown deadline={at(-1)} now={now} escalated />
      </>,
    );
    expect(screen.getByText("Due in 5h 30m")).toBeTruthy();
    expect(screen.getByText("Overdue by 2h 15m")).toBeTruthy();
    expect(screen.getByText("Due in 1d 6h")).toBeTruthy();
    expect(screen.getByText("Escalated to Super Admin")).toBeTruthy();
  });
});
