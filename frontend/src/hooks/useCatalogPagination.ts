import { useCallback, useRef, useState } from "react";

export const DEFAULT_CATALOG_PAGE_SIZE = 24;

/** Keep roughly 24 cards per page and preserve an inspected card across reflow. */
export function useCatalogPagination() {
  const [pagination, setPagination] = useState({ page: 1, pageSize: DEFAULT_CATALOG_PAGE_SIZE, navigationKey: 0 });
  const paginationRef = useRef(pagination);
  const updatePage = useCallback((page: number) => {
    const next = { ...paginationRef.current, page };
    paginationRef.current = next;
    setPagination(next);
  }, []);
  const setPage = useCallback((page: number) => {
    const next = { ...paginationRef.current, page, navigationKey: paginationRef.current.navigationKey + 1 };
    paginationRef.current = next;
    setPagination(next);
  }, []);
  const resizePage = useCallback((columns: number, anchorIndex: number, currentPage = paginationRef.current.page, currentSize = paginationRef.current.pageSize) => {
    if (!Number.isInteger(columns) || columns < 1) return;
    const previous = paginationRef.current;
    const pageSize = Math.ceil(DEFAULT_CATALOG_PAGE_SIZE / columns) * columns;
    if (pageSize === previous.pageSize) return;
    const anchor = (currentPage - 1) * currentSize + Math.max(0, anchorIndex);
    const next = { ...previous, pageSize, page: Math.floor(anchor / pageSize) + 1 };
    paginationRef.current = next;
    setPagination(next);
  }, []);
  return { ...pagination, paginationRef, setPage, updatePage, resizePage };
}
