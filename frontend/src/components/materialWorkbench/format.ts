/**
 * Display helpers shared by the material gamut and cache views.
 * 耗材色域与缓存视图共用的显示辅助函数。
 */

/** Compact candidate count, e.g. 1048576 -> "1M", 33554432 -> "33.6M". */
export function formatCandidateCount(value: number): string {
  if (value >= 1_000_000) {
    const millions = value / 1_000_000;
    return `${Number.isInteger(Math.round(millions * 10) / 10) ? Math.round(millions) : millions.toFixed(1)}M`;
  }
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`;
  return value.toLocaleString();
}

/** Percent with one decimal, e.g. 23.456 -> "23.5". */
export function formatPercent(value: number): string {
  return value.toFixed(1);
}

/** File size in MB with one decimal. */
export function formatMegabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(1);
}

/** Color difference with one decimal, e.g. 2.345 -> "2.3". */
export function formatDeltaE(value: number): string {
  return value.toFixed(1);
}

/** CIELAB lightness with no decimals, e.g. 52.5 -> "53". */
export function formatLightness(value: number): string {
  return Math.round(value).toString();
}
