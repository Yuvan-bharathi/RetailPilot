/**
 * Cursor paging state for a DataTable in `paging="cursor"` mode (D-37).
 *
 * A cursor-paged API only knows "the page after this key", so going back needs the cursors already seen:
 * `cursors[i]` is the cursor that fetches page i + 1 (page 1 has none). Next pushes the current page's
 * `next_cursor`; Previous pops; any other change (page size, filters via `reset`) starts again at page 1.
 */
import { useCallback, useState } from "react";

import type { TableQuery } from "../components/DataTable";

export function useCursorPaging(pageSize = 25) {
  const [query, setQuery] = useState<TableQuery>({ page: 1, pageSize });
  const [cursors, setCursors] = useState<(string | null)[]>([null]);

  const reset = useCallback(() => {
    setCursors([null]);
    setQuery((q) => ({ ...q, page: 1 }));
  }, []);

  /** Pass the current page's `next_cursor` so Next can remember where page + 1 starts. */
  const onQueryChange = (next: TableQuery, nextCursor: string | null | undefined) => {
    if (next.pageSize === query.pageSize && next.page === query.page + 1 && nextCursor) {
      setCursors((c) => [...c.slice(0, query.page), nextCursor]);
      setQuery(next);
    } else if (next.pageSize === query.pageSize && next.page === query.page - 1 && next.page >= 1) {
      setQuery(next);
    } else {
      setCursors([null]);
      setQuery({ ...next, page: 1 });
    }
  };

  return { query, cursor: cursors[query.page - 1] ?? undefined, onQueryChange, reset };
}
