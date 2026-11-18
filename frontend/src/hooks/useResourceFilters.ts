import { useState } from "react";
import { EMPTY_RESOURCE_FILTERS, type ResourceFilters } from "../utils/resourceSearch";

export interface ResourceFilterProps {
  filters?: ResourceFilters;
  onFiltersChange?: (filters: ResourceFilters) => void;
}

export function useResourceFilters(props: ResourceFilterProps, resetPage: () => void) {
  const [local, setLocal] = useState(EMPTY_RESOURCE_FILTERS);
  return [props.filters ?? local, (value: ResourceFilters) => {
    setLocal(value);
    props.onFiltersChange?.(value);
    resetPage();
  }] as const;
}
