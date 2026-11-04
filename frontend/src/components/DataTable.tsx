/**
 * DataTable — TanStack Table v9 with SERVER-side paging and sorting (Page[T] / PageParams, D-32).
 * Sticky header, pinned first column with horizontal scroll, search, filter slot, sort, pagination, row selection,
 * column chooser, loading / empty / error states, keyboard reachable (design doc §3).
 */
import {
  columnVisibilityFeature,
  FlexRender,
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  tableFeatures,
  useTable,
  type ColumnDef,
  type PaginationState,
  type RowSelectionState,
  type SortingState,
  type ColumnVisibilityState,
  type RowData,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Columns3, Search } from "lucide-react";
import { useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import type { Page } from "../api/types";
import { formatNumber } from "../lib/format";
import { Button } from "./Button";
import { EmptyState, ErrorState, SkeletonLine } from "./StateViews";

const features = tableFeatures({ rowSortingFeature, rowPaginationFeature, columnVisibilityFeature, rowSelectionFeature });
type Features = typeof features;

export interface Column<T> {
  id: string; // also the server sort field
  header: string;
  cell: (row: T) => ReactNode;
  sortable?: boolean;
  align?: "left" | "right";
  hideable?: boolean; // default true (the first column is never hideable)
}

export interface TableQuery {
  page: number;
  pageSize: number;
  sort?: string; // "field" or "-field"
}

export interface DataTableProps<T extends RowData> {
  caption: string;
  columns: Column<T>[];
  page: Page<T> | undefined;
  query: TableQuery;
  onQueryChange: (next: TableQuery) => void;
  getRowId: (row: T) => string;
  isLoading?: boolean;
  isFetching?: boolean;
  error?: string | null;
  onRetry?: () => void;
  search?: { value: string; onChange: (value: string) => void; placeholder?: string };
  filters?: ReactNode;
  selection?: { value: RowSelectionState; onChange: (value: RowSelectionState) => void };
  onRowClick?: (row: T) => void;
  emptyTitle?: string;
  emptyDescription?: string;
  pageSizes?: number[];
}

function toSorting(sort: string | undefined): SortingState {
  if (!sort) return [];
  return sort.startsWith("-") ? [{ id: sort.slice(1), desc: true }] : [{ id: sort, desc: false }];
}

function fromSorting(sorting: SortingState): string | undefined {
  const first = sorting[0];
  if (!first) return undefined;
  return first.desc ? `-${first.id}` : first.id;
}

export function DataTable<T extends RowData>({
  caption,
  columns,
  page,
  query,
  onQueryChange,
  getRowId,
  isLoading = false,
  isFetching = false,
  error = null,
  onRetry,
  search,
  filters,
  selection,
  onRowClick,
  emptyTitle = "Nothing to show",
  emptyDescription,
  pageSizes = [10, 25, 50, 100],
}: DataTableProps<T>) {
  const [columnVisibility, setColumnVisibility] = useState<ColumnVisibilityState>({});
  const [chooserOpen, setChooserOpen] = useState(false);
  const chooserId = useId();
  const chooserButton = useRef<HTMLButtonElement>(null);

  const tableColumns = useMemo<ColumnDef<Features, T>[]>(() => {
    const defs: ColumnDef<Features, T>[] = columns.map((col, index) => ({
      id: col.id,
      accessorFn: () => null,
      header: col.header,
      cell: ({ row }) => col.cell(row.original),
      enableSorting: col.sortable === true,
      enableHiding: index > 0 && col.hideable !== false,
    }));
    if (selection) {
      defs.unshift({
        id: "__select",
        accessorFn: () => null,
        enableSorting: false,
        enableHiding: false,
        header: ({ table }) => (
          <input
            type="checkbox"
            aria-label="Select all rows on this page"
            checked={table.getIsAllPageRowsSelected()}
            onChange={() => table.toggleAllPageRowsSelected()}
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            aria-label={`Select row ${row.index + 1}`}
            checked={row.getIsSelected()}
            onChange={() => row.toggleSelected()}
            onClick={(e) => e.stopPropagation()}
          />
        ),
      });
    }
    return defs;
  }, [columns, selection]);

  const sorting = toSorting(query.sort);
  const pagination: PaginationState = { pageIndex: query.page - 1, pageSize: query.pageSize };

  const table = useTable({
    features,
    columns: tableColumns,
    data: page?.items ?? [],
    getRowId: (row) => getRowId(row),
    manualSorting: true,
    manualPagination: true,
    rowCount: page?.total ?? 0,
    state: { sorting, pagination, columnVisibility, rowSelection: selection?.value ?? {} },
    onSortingChange: (updater) => {
      const next = typeof updater === "function" ? updater(sorting) : updater;
      onQueryChange({ ...query, sort: fromSorting(next), page: 1 });
    },
    onPaginationChange: (updater) => {
      const next = typeof updater === "function" ? updater(pagination) : updater;
      onQueryChange({ ...query, page: next.pageIndex + 1, pageSize: next.pageSize });
    },
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: (updater) => {
      if (!selection) return;
      selection.onChange(typeof updater === "function" ? updater(selection.value) : updater);
    },
  });

  const total = page?.total ?? 0;
  const first = total === 0 ? 0 : (query.page - 1) * query.pageSize + 1;
  const last = Math.min(query.page * query.pageSize, total);
  const pageCount = Math.max(1, Math.ceil(total / query.pageSize));
  const visibleColumns = table.getVisibleLeafColumns().length;
  const pinnedIndex = selection ? 1 : 0; // the first data column stays visible while scrolling sideways

  const onRowKey = (event: KeyboardEvent<HTMLTableRowElement>, row: T) => {
    if (onRowClick && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      onRowClick(row);
    }
  };

  let body: ReactNode;
  if (error) {
    body = (
      <tr>
        <td colSpan={visibleColumns}>
          <ErrorState message={error} onRetry={onRetry} />
        </td>
      </tr>
    );
  } else if (isLoading && !page) {
    body = Array.from({ length: 5 }, (_, r) => (
      <tr key={`skeleton-${r}`} className="h-11 border-b border-divider">
        {table.getVisibleLeafColumns().map((c) => (
          <td key={c.id} className="px-3">
            <SkeletonLine width={c.id === "__select" ? "16px" : "70%"} />
          </td>
        ))}
      </tr>
    ));
  } else if (!page || page.items.length === 0) {
    body = (
      <tr>
        <td colSpan={visibleColumns}>
          <EmptyState title={emptyTitle} description={emptyDescription} />
        </td>
      </tr>
    );
  } else {
    body = table.getRowModel().rows.map((row) => (
      <tr
        key={row.id}
        className={`group h-11 border-b border-divider ${onRowClick ? "cursor-pointer hover:bg-elevated focus-visible:bg-brand-soft" : ""} ${row.getIsSelected() ? "bg-brand-soft" : ""}`}
        tabIndex={onRowClick ? 0 : undefined}
        onClick={onRowClick ? () => onRowClick(row.original) : undefined}
        onKeyDown={onRowClick ? (e) => onRowKey(e, row.original) : undefined}
      >
        {row.getVisibleCells().map((cell, i) => {
          const col = columns.find((c) => c.id === cell.column.id);
          const pinned = i === pinnedIndex;
          return (
            <td
              key={cell.id}
              className={`px-3 whitespace-nowrap ${col?.align === "right" ? "tabular text-right" : ""} ${pinned ? "sticky left-0 z-10 bg-surface group-hover:bg-elevated" : ""}`}
            >
              <FlexRender cell={cell} />
            </td>
          );
        })}
      </tr>
    ));
  }

  return (
    <div className="rounded-card border border-border bg-surface shadow-card">
      <div className="flex flex-wrap items-center gap-3 border-b border-divider p-3">
        {search ? (
          <label className="relative flex min-w-[220px] flex-1 items-center">
            <span className="sr-only">Search {caption}</span>
            <Search aria-hidden="true" size={16} className="pointer-events-none absolute left-3 text-ink-secondary" />
            <input
              type="search"
              value={search.value}
              onChange={(e) => search.onChange(e.target.value)}
              placeholder={search.placeholder ?? "Search"}
              className="h-10 w-full rounded-input border border-border bg-surface pr-3 pl-9 text-sm placeholder:text-ink-secondary"
            />
          </label>
        ) : null}
        {filters}
        <div className="relative ml-auto">
          <Button
            ref={chooserButton}
            variant="secondary"
            size="sm"
            icon={<Columns3 size={14} />}
            aria-expanded={chooserOpen}
            aria-controls={chooserId}
            onClick={() => setChooserOpen((open) => !open)}
          >
            Columns
          </Button>
          {chooserOpen ? (
            <fieldset
              id={chooserId}
              className="absolute right-0 z-30 mt-1 w-56 rounded-input border border-border bg-surface p-2 shadow-dropdown"
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setChooserOpen(false);
                  chooserButton.current?.focus();
                }
              }}
            >
              <legend className="sr-only">Visible columns</legend>
              {table
                .getAllLeafColumns()
                .filter((c) => c.getCanHide())
                .map((c) => (
                  <label key={c.id} className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-elevated">
                    <input type="checkbox" checked={c.getIsVisible()} onChange={() => c.toggleVisibility()} />
                    {columns.find((col) => col.id === c.id)?.header ?? c.id}
                  </label>
                ))}
            </fieldset>
          ) : null}
        </div>
      </div>

      {/* `relative` keeps absolutely positioned children (e.g. sr-only labels) inside the scroll area; without it
          they are positioned against the page and widen the whole document. */}
      <div
        className="relative max-h-[560px] overflow-auto"
        role="region"
        aria-label={caption}
        aria-busy={isLoading || isFetching}
        tabIndex={0}
      >
        <table className="w-full min-w-max border-collapse text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 z-20 bg-surface">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} className="border-b border-border">
                {group.headers.map((header, i) => {
                  const col = columns.find((c) => c.id === header.column.id);
                  const sorted = header.column.getIsSorted();
                  const pinned = i === pinnedIndex;
                  const SortIcon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown;
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                      className={`h-11 px-3 text-xs font-medium whitespace-nowrap text-ink-secondary ${col?.align === "right" ? "text-right" : "text-left"} ${pinned ? "sticky left-0 z-30 bg-surface" : ""}`}
                    >
                      {header.column.getCanSort() ? (
                        <button
                          type="button"
                          className={`inline-flex items-center gap-1 rounded hover:text-ink ${col?.align === "right" ? "flex-row-reverse" : ""}`}
                          onClick={() => header.column.toggleSorting(sorted === "asc")}
                        >
                          {col?.header}
                          <SortIcon aria-hidden="true" size={12} />
                        </button>
                      ) : (
                        <FlexRender header={header} />
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-divider px-3 py-2 text-sm text-ink-secondary">
        <span className="tabular" aria-live="polite">
          {total === 0 ? "No rows" : `Showing ${formatNumber(first)}–${formatNumber(last)} of ${formatNumber(total)}`}
        </span>
        <label className="ml-auto flex items-center gap-2">
          Rows per page
          <select
            className="h-8 rounded-input border border-border bg-surface px-2 text-ink"
            value={query.pageSize}
            onChange={(e) => onQueryChange({ ...query, pageSize: Number(e.target.value), page: 1 })}
          >
            {pageSizes.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <span className="tabular">
          Page {query.page} of {pageCount}
        </span>
        <Button
          variant="secondary"
          size="sm"
          aria-label="Previous page"
          disabled={query.page <= 1}
          onClick={() => table.previousPage()}
        >
          <ChevronLeft aria-hidden="true" size={16} />
        </Button>
        <Button
          variant="secondary"
          size="sm"
          aria-label="Next page"
          disabled={query.page >= pageCount}
          onClick={() => table.nextPage()}
        >
          <ChevronRight aria-hidden="true" size={16} />
        </Button>
      </div>
    </div>
  );
}
