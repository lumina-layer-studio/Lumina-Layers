import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { CheckIcon } from "@heroicons/react/20/solid";
import { useI18n } from "../../i18n/context";
import CloseButton from "./CloseButton";
import CalibrationThumbnail, { type CalibrationThumbnailProps } from "./CalibrationThumbnail";
import { LibraryCardIdentity, LibraryCardPalette } from "./LibraryDetails";
import ResourceDetailsPanel from "./ResourceDetailsPanel";
import "./CloudLibraryPreview.css";

export interface CloudPreviewItem {
  key: string;
  name: string;
  originalName?: string;
  subtitle: string;
  metric?: string;
  thumbnail: CalibrationThumbnailProps;
  logo?: string;
  colorDescription?: string;
  activity?: ReactNode;
  state?: string;
  action?: ReactNode;
  detail: ReactNode;
}

export default function CloudLibraryPreview({
  items,
  toolbar,
  notices,
  footer,
  busy,
  resetKey,
  emptyMessage,
  emptyAction,
  loadingMessage,
  onColumnsChange,
}: {
  items: CloudPreviewItem[];
  toolbar: ReactNode;
  notices?: ReactNode;
  footer?: ReactNode;
  busy?: boolean;
  resetKey: string;
  emptyMessage?: string;
  emptyAction?: ReactNode;
  loadingMessage?: string;
  onColumnsChange?: (columns: number, anchorIndex: number) => void;
}) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const layoutRef = useRef({ items, selected, onColumnsChange });
  const trackColumns = onColumnsChange !== undefined;

  useLayoutEffect(() => {
    layoutRef.current = { items, selected, onColumnsChange };
  });

  useLayoutEffect(() => {
    const grid = gridRef.current;
    if (!grid || !trackColumns) return;
    let lastColumns = 0;
    const measure = () => {
      // Read the actual CSS tracks so zoom, root font size and the details
      // sidebar all follow the same geometry as the visible cards.
      const tracks = getComputedStyle(grid).gridTemplateColumns.trim().split(/\s+/);
      if (!tracks.length || !tracks.every((track) => /^\d+(?:\.\d+)?px$/.test(track))) return;
      const columns = tracks.length;
      if (columns === lastColumns) return;
      lastColumns = columns;
      const current = layoutRef.current;
      current.onColumnsChange?.(
        columns,
        Math.max(0, current.items.findIndex((item) => item.key === current.selected)),
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, [trackColumns]);

  const detail = items.find((item) => item.key === selected);
  const close = () => {
    setSelected(null);
    triggerRef.current?.focus();
  };

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    if (sectionRef.current) sectionRef.current.scrollTop = 0;
    setScrolled(false);
    setSelected(null);
  }, [resetKey]);

  useEffect(() => {
    if (selected) {
      closeRef.current?.focus({ preventScroll: window.innerWidth >= 1024 && window.innerHeight > 600 });
    }
  }, [selected]);

  return (
    <section
      ref={sectionRef}
      className="cloud-library-preview flex h-full min-h-0 flex-col overflow-hidden bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100"
    >
      <div
        className={`flex shrink-0 flex-wrap items-center gap-3 border-b px-4 py-3.5 transition-colors duration-200 ${
          scrolled ? "border-slate-200 dark:border-slate-700" : "border-transparent"
        }`}
      >
        {toolbar}
      </div>
      <div
        ref={scrollRef}
        onScroll={(event) => setScrolled(event.currentTarget.scrollTop > 0)}
        className="cloud-library-preview__content min-h-0 flex-1 overflow-y-auto overscroll-y-contain p-4"
      >
        {notices && (
          <div className="mb-4 grid gap-3 empty:hidden" role="status">
            {notices}
          </div>
        )}
        <div className="resource-detail-layout grid items-start gap-5">
          <div className="min-w-0" aria-busy={busy}>
            <div
              ref={gridRef}
              className="grid items-stretch gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,15rem),1fr))]"
            >
              {items.map((item) => (
                <article
                  key={item.key}
                  onClick={(event) => {
                    if (
                      !(event.target instanceof Element) ||
                      event.target.closest("button, a, input, select, textarea, [role=button]")
                    ) {
                      return;
                    }
                    triggerRef.current =
                      event.currentTarget.querySelector<HTMLButtonElement>("[data-library-details]");
                    if (selected === item.key) close();
                    else setSelected(item.key);
                  }}
                  className={`flex min-w-0 cursor-pointer flex-col rounded-[10px] border p-5 transition-colors duration-150 ${
                    selected === item.key
                      ? "border-slate-300 bg-slate-200 dark:border-slate-500 dark:bg-slate-700"
                      : "border-slate-200 bg-slate-100 hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700"
                  }`}
                >
                  <button
                    type="button"
                    data-library-details
                    aria-expanded={selected === item.key}
                    onClick={(event) => {
                      triggerRef.current = event.currentTarget;
                      if (selected === item.key) close();
                      else setSelected(item.key);
                    }}
                    className="flex w-full flex-1 flex-col items-stretch gap-3 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                  >
                    <span className="flex min-w-0 items-start gap-3.5">
                      <CalibrationThumbnail {...item.thumbnail} />
                      <LibraryCardIdentity
                        name={item.name}
                        subtitle={item.subtitle}
                        logo={item.logo}
                        thumbnail={item.thumbnail}
                        showMeta={false}
                      />
                    </span>
                    <LibraryCardPalette thumbnail={item.thumbnail} metric={item.metric} />
                  </button>
                  {(item.activity || item.state || item.action) && (
                    <div className="mt-auto flex flex-col gap-2 pt-3.5">
                      {item.activity}
                      {item.action ? (
                        <>
                          {item.state && (
                            <span className="text-xs text-slate-600 dark:text-slate-300">
                              {item.state}
                            </span>
                          )}
                          <div className="grid [&>button]:w-full">{item.action}</div>
                        </>
                      ) : (
                        item.state && (
                          <span className="inline-flex min-h-8 items-center justify-center gap-1.5 rounded-lg bg-[var(--surface-well)] px-3 text-xs font-medium text-slate-600 dark:text-slate-300">
                            <CheckIcon
                              className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400"
                              aria-hidden="true"
                            />
                            <span>{item.state}</span>
                          </span>
                        )
                      )}
                    </div>
                  )}
                </article>
              ))}
            </div>
            {!items.length && (() => {
              const resolvedEmptyText = busy
                ? loadingMessage ?? t("lut_sync_loading")
                : emptyMessage ?? t("lut_sync_catalog_empty");
              if (!resolvedEmptyText && (busy || !emptyAction)) return null;
              return (
                <div className="grid justify-items-center gap-3 py-12 text-center text-sm text-slate-500 dark:text-slate-400">
                  {resolvedEmptyText && <p>{resolvedEmptyText}</p>}
                  {!busy && emptyAction}
                </div>
              );
            })()}
            {footer && (
              <div className="mt-5 flex flex-wrap items-center justify-between gap-3">{footer}</div>
            )}
          </div>
          {/* Removed entries clear immediately; an explicit close plays the exit. */}
          {(!selected || detail) && (
            <ResourceDetailsPanel
              open={!!detail}
              as="aside"
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.stopPropagation();
                  close();
                }
              }}
              className="cloud-library-preview__detail relative order-first min-w-0 rounded-[10px] border border-slate-200 bg-slate-100 p-5 lg:sticky lg:top-0 lg:order-last lg:max-h-[calc(100vh-16rem)] lg:overflow-y-auto lg:overscroll-y-contain dark:border-slate-700 dark:bg-slate-800"
            >
              <div className="absolute right-4 top-4">
                <CloseButton ref={closeRef} label={t("announcement_close")} onClick={close} />
              </div>
              {detail?.detail}
            </ResourceDetailsPanel>
          )}
        </div>
      </div>
    </section>
  );
}
