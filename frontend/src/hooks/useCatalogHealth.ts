import { useEffect } from "react";
import type { ResourceKind } from "../api/resources";
import { useResourceStore } from "../stores/resourceStore";

export function useCatalogHealth(kind: ResourceKind, ready: boolean, cached: boolean | undefined, fetchedAt: string | null | undefined, error: string | null) {
  const sourceUrl = useResourceStore(state => state.status?.source_settings?.urls[kind]);
  useEffect(() => {
    if (!sourceUrl || (!ready && !error)) return;
    useResourceStore.getState().observeCatalog(kind, {
      sourceUrl, state: error ? "error" : cached ? "cached" : "ready", fetchedAt,
    });
  }, [kind, sourceUrl, ready, cached, fetchedAt, error]);
}

export function catalogCheckedTime(value: string | null | undefined, lang: string): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString(lang === "zh" ? "zh-CN" : "en-US") : "";
}
