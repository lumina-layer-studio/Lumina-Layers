import ButtonContent from "../ui/ButtonContent";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useSlicerStore } from "../../stores/slicerStore";
import { useConverterStore } from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import { useI18n } from "../../i18n/context";
import {
  apiErrorToVisibleMessage,
  assertResourceDownloadAvailable,
} from "../../api/client";
import {
  getDetectedSlicerIdForSoftware,
  getSlicerSoftwareDisplayName,
} from "../../utils/settingsOptionIds";
import type { SlicerInfo } from "../../api/types";
import { WIKI_DOCS } from "../../utils/wikiDocs";
import SlicerLogo from "../slicer/SlicerLogo";
import { useApplicationMenuCommand } from "../../integrations/applicationMenu";
import WikiTooltip from "../ui/WikiTooltip";

/** Brand color style for a slicer button. 切片软件品牌配色样式。 */
export interface SlicerBrandStyle {
  bg: string;
  hover: string;
  text: string;
}

/** Default gray style for unknown slicers. 未知切片软件的默认灰色样式。 */
const DEFAULT_BRAND_STYLE: SlicerBrandStyle = {
  bg: "bg-slate-600",
  hover: "hover:bg-slate-700",
  text: "text-white",
};

/**
 * Brand color mapping for known slicer software.
 * 已知切片软件的品牌配色映射。
 */
export const SLICER_BRAND_COLORS: Record<string, SlicerBrandStyle> = {
  bambu_studio:  { bg: "bg-green-600",  hover: "hover:bg-green-700",  text: "text-white" },
  orca_slicer:   { bg: "bg-blue-600",   hover: "hover:bg-blue-700",   text: "text-white" },
  elegoo_slicer: { bg: "bg-sky-500",    hover: "hover:bg-sky-600",    text: "text-white" },
  anycubic_slicer_next: { bg: "bg-red-600", hover: "hover:bg-red-700", text: "text-white" },
  flash_studio: { bg: "bg-indigo-600", hover: "hover:bg-indigo-700", text: "text-white" },
  qidi_studio: { bg: "bg-violet-600", hover: "hover:bg-violet-700", text: "text-white" },
  prusa_slicer:  { bg: "bg-orange-500", hover: "hover:bg-orange-600", text: "text-white" },
  cura:          { bg: "bg-blue-400",   hover: "hover:bg-blue-500",   text: "text-white" },
};

/**
 * Get brand style for a slicer by ID, falling back to default gray.
 * 根据切片软件 ID 获取品牌样式，未知 ID 返回默认灰色。
 *
 * @param slicerId - The slicer identifier. (切片软件标识符)
 * @returns The brand style object. (品牌样式对象)
 */
export function getSlicerBrandStyle(slicerId: string): SlicerBrandStyle {
  return Object.hasOwn(SLICER_BRAND_COLORS, slicerId)
    ? SLICER_BRAND_COLORS[slicerId]
    : DEFAULT_BRAND_STYLE;
}

/**
 * Determine the main button label based on slicer availability and 3MF state.
 * 根据切片软件可用性和 3MF 状态决定主按钮文案。
 *
 * @param hasSlicers - Whether any slicer is detected. (是否检测到切片软件)
 * @param threemfDiskPath - Legacy 3MF disk path or public artifact URL, or null.
 *   (旧版 3MF 磁盘路径或公开产物 URL，或 null)
 * @param slicerName - The display name of the selected slicer. (选中切片软件的显示名称)
 * @returns The button label string. (按钮文案字符串)
 */
export function getButtonLabel(
  hasSlicers: boolean,
  threemfDiskPath: string | null,
  slicerName: string | null,
  t: (key: string) => string,
  largeFormat?: boolean,
): string {
  if (largeFormat) {
    return threemfDiskPath || hasSlicers
      ? t("slicer_download_zip")
      : t("slicer_generate_download_zip");
  }
  if (hasSlicers) {
    return threemfDiskPath
      ? t("slicer_open_in").replace("{name}", slicerName ?? "")
      : t("slicer_generate_open_in").replace("{name}", slicerName ?? "");
  }
  return threemfDiskPath ? t("slicer_download_3mf") : t("slicer_generate_download");
}

/**
 * Label for the dropdown download entry: generate first when no artifact exists.
 * 下拉菜单下载项文案：没有可用产物时先生成再下载。
 *
 * @param hasArtifact - Whether a current downloadable artifact exists. (是否已有可下载产物)
 * @param t - Translation function. (翻译函数)
 * @param largeFormat - Whether large-format ZIP output is active. (是否为大画幅 ZIP 输出)
 * @returns The menu entry label. (菜单项文案)
 */
function getMenuDownloadLabel(
  hasArtifact: boolean,
  t: (key: string) => string,
  largeFormat?: boolean,
): string {
  if (largeFormat) {
    return hasArtifact ? t("slicer_download_zip") : t("slicer_generate_download_zip");
  }
  return hasArtifact ? t("slicer_download_3mf") : t("slicer_generate_download_3mf");
}

export function getSlicerLinkHint(
  preferredSlicerId: string | null,
  preferredSlicerName: string,
  preferredInstalled: boolean,
  selectedSlicerId: string | null,
  selectedSlicerName: string | null,
  t: (key: string) => string,
): string | null {
  if (!preferredSlicerId) {
    return null;
  }

  if (!preferredInstalled) {
    return t("slicer_preferred_missing").replace("{name}", preferredSlicerName);
  }

  if (
    selectedSlicerId &&
    selectedSlicerId !== preferredSlicerId &&
    selectedSlicerName
  ) {
    return t("slicer_preferred_mismatch")
      .replace("{expected}", preferredSlicerName)
      .replace("{actual}", selectedSlicerName);
  }

  return null;
}

function resolveActiveSlicer(
  slicers: SlicerInfo[],
  selectedSlicerId: string | null,
  preferredDetectedSlicerId: string | null,
): SlicerInfo | null {
  const preferredInstalledSlicer = preferredDetectedSlicerId
    ? slicers.find((slicer) => slicer.id === preferredDetectedSlicerId) ?? null
    : null;
  if (preferredDetectedSlicerId) {
    return preferredInstalledSlicer;
  }

  const selectedSlicer = selectedSlicerId
    ? slicers.find((slicer) => slicer.id === selectedSlicerId) ?? null
    : null;
  return selectedSlicer;
}

function toVisibleErrorMessage(error: unknown, fallback: string): string {
  return apiErrorToVisibleMessage(error, fallback);
}

interface SlicerSelectorProps {
  threemfDiskPath: string | null;
  downloadUrl: string | null;
  canSubmit: boolean;
  generationPending?: boolean;
  onAutoGenerate: () => Promise<string | null>;
  largeFormat?: boolean;
  getLatestDownloadUrl?: () => string | null;
  getLatestThreemfDiskPath?: () => string | null;
  onArtifactAction?: () => void;
}

export default function SlicerSelector({
  threemfDiskPath,
  downloadUrl,
  canSubmit,
  generationPending = false,
  onAutoGenerate,
  largeFormat,
  getLatestDownloadUrl,
  getLatestThreemfDiskPath,
  onArtifactAction,
}: SlicerSelectorProps) {
  const slicers = useSlicerStore((s) => s.slicers);
  const selectedSlicerId = useSlicerStore((s) => s.selectedSlicerId);
  const isDetecting = useSlicerStore((s) => s.isDetecting);
  const isLaunching = useSlicerStore((s) => s.isLaunching);
  const launchMessage = useSlicerStore((s) => s.launchMessage);
  const error = useSlicerStore((s) => s.error);
  const detectSlicers = useSlicerStore((s) => s.detectSlicers);
  const setSelectedSlicerId = useSlicerStore((s) => s.setSelectedSlicerId);
  const launchSlicer = useSlicerStore((s) => s.launchSlicer);
  const clearMessage = useSlicerStore((s) => s.clearMessage);
  const slicerSoftware = useSettingsStore((s) => s.slicerSoftware);

  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isAutoGenerating, setIsAutoGenerating] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const syncedSlicerSoftwareRef = useRef<string | null>(null);
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const { t } = useI18n();

  /**
   * Compute dropdown position above the trigger button via getBoundingClientRect.
   * 通过 getBoundingClientRect 计算下拉菜单在触发按钮上方的位置。
   */
  const updateDropdownPos = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    setDropdownPos({ top: rect.top, left: rect.left, width: rect.width });
  }, []);

  // Auto-detect slicers on mount
  useEffect(() => {
    void detectSlicers();
  }, [detectSlicers]);

  // Auto-clear messages after 5 seconds
  useEffect(() => {
    if (!launchMessage && !error) return;
    const timer = setTimeout(clearMessage, 5000);
    return () => clearTimeout(timer);
  }, [launchMessage, error, clearMessage]);

  // Close dropdown when clicking outside (check both trigger and portal)
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        dropdownRef.current && !dropdownRef.current.contains(target)
      ) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Recalculate position on scroll/resize while open
  useEffect(() => {
    if (!isDropdownOpen) return;
    updateDropdownPos();
    window.addEventListener("scroll", updateDropdownPos, true);
    window.addEventListener("resize", updateDropdownPos);
    return () => {
      window.removeEventListener("scroll", updateDropdownPos, true);
      window.removeEventListener("resize", updateDropdownPos);
    };
  }, [isDropdownOpen, updateDropdownPos]);

  const hasSlicers = slicers.length > 0;
  const preferredDetectedSlicerId = getDetectedSlicerIdForSoftware(slicerSoftware);
  const preferredInstalledSlicer = preferredDetectedSlicerId
    ? slicers.find((slicer) => slicer.id === preferredDetectedSlicerId) ?? null
    : null;
  const orderedSlicers = preferredDetectedSlicerId
    ? [...slicers].sort((left, right) => {
        const leftPriority = left.id === preferredDetectedSlicerId ? 0 : 1;
        const rightPriority = right.id === preferredDetectedSlicerId ? 0 : 1;
        if (leftPriority !== rightPriority) {
          return leftPriority - rightPriority;
        }
        return left.display_name.localeCompare(right.display_name);
      })
    : slicers;
  const activeSlicer = resolveActiveSlicer(
    slicers,
    selectedSlicerId,
    preferredDetectedSlicerId,
  );
  const activeSlicerId = activeSlicer?.id ?? null;
  const canOpenInSlicer = activeSlicer !== null;
  const brandSlicerId = activeSlicerId;
  const brandStyle = brandSlicerId
    ? getSlicerBrandStyle(brandSlicerId)
    : DEFAULT_BRAND_STYLE;
  const preferredSlicerName =
    preferredInstalledSlicer?.display_name ??
    getSlicerSoftwareDisplayName(slicerSoftware);
  const slicerLinkHint = getSlicerLinkHint(
    preferredDetectedSlicerId,
    preferredSlicerName,
    preferredInstalledSlicer !== null,
    activeSlicerId ?? null,
    activeSlicer?.display_name ?? null,
    t,
  );
  const outputHint = !isDetecting && !largeFormat
    ? slicerLinkHint ?? (!hasSlicers ? t("slicer_not_detected") : null)
    : null;
  const resolveLatestDownloadUrl =
    getLatestDownloadUrl ?? (() => useConverterStore.getState().downloadUrl);
  const resolveLatestThreemfDiskPath =
    getLatestThreemfDiskPath ?? (() => useConverterStore.getState().threemfDiskPath);
  const handleArtifactAction =
    onArtifactAction ?? (() => useConverterStore.getState().cleanupAfterDownload());
  const launchArtifactSource = downloadUrl ?? threemfDiskPath;

  useEffect(() => {
    if (!preferredInstalledSlicer) {
      if (syncedSlicerSoftwareRef.current === slicerSoftware) {
        syncedSlicerSoftwareRef.current = null;
      }
      return;
    }
    if (syncedSlicerSoftwareRef.current === slicerSoftware) {
      return;
    }
    syncedSlicerSoftwareRef.current = slicerSoftware;
    if (selectedSlicerId !== preferredInstalledSlicer.id) {
      setSelectedSlicerId(preferredInstalledSlicer.id);
    }
  }, [
    preferredInstalledSlicer,
    selectedSlicerId,
    setSelectedSlicerId,
    slicerSoftware,
  ]);

  useEffect(() => {
    setDownloadError(null);
  }, [downloadUrl]);

  /**
   * Helper to trigger a browser download from a URL.
   * 辅助函数：通过 URL 触发浏览器下载。
   */
  const triggerDownload = async (url: string) => {
    setIsDownloading(true);
    setDownloadError(null);
    try {
      await assertResourceDownloadAvailable(url);
      const link = document.createElement("a");
      link.href = url;
      link.download = "";
      link.click();
      handleArtifactAction();
    } catch (err) {
      setDownloadError(toVisibleErrorMessage(err, t("slicer_download_failed")));
    } finally {
      setIsDownloading(false);
    }
  };

  const handleDownloadOrGenerate = async () => {
    if (downloadUrl) {
      await triggerDownload(downloadUrl);
    } else {
      setIsAutoGenerating(true);
      try {
        await onAutoGenerate();
        const latestDownloadUrl = resolveLatestDownloadUrl();
        if (latestDownloadUrl) {
          await triggerDownload(latestDownloadUrl);
        }
      } catch {
        // Error state is set by submitGenerate in ConverterStore
      } finally {
        setIsAutoGenerating(false);
      }
    }
  };

  const handleMainClick = async () => {
    if (largeFormat || !canOpenInSlicer) {
      await handleDownloadOrGenerate();
      return;
    }

    // Has slicers (normal mode)
    if (launchArtifactSource) {
      void launchSlicer(launchArtifactSource, activeSlicerId);
      handleArtifactAction();
    } else {
      setIsAutoGenerating(true);
      try {
        await onAutoGenerate();
        const latestArtifactSource =
          resolveLatestDownloadUrl() ?? resolveLatestThreemfDiskPath();
        if (latestArtifactSource) {
          void launchSlicer(latestArtifactSource, activeSlicerId);
          handleArtifactAction();
        }
      } catch {
        // Error state is set by submitGenerate in ConverterStore
      } finally {
        setIsAutoGenerating(false);
      }
    }
  };

  const handleSelectSlicer = (id: string) => {
    setSelectedSlicerId(id);
    setIsDropdownOpen(false);
  };

  const handleDownloadFromMenu = async () => {
    setIsDropdownOpen(false);
    await handleDownloadOrGenerate();
  };

  const actionBusy = isLaunching || generationPending || isAutoGenerating || isDownloading;
  const isDisabled = !canSubmit || isDetecting || actionBusy;
  useApplicationMenuCommand('export', () => { void handleDownloadFromMenu(); }, Boolean(downloadUrl) && !isDisabled);
  const showActiveSlicerLogo = !largeFormat && activeSlicerId !== null;

  const mainButtonLabel = getButtonLabel(
    largeFormat ? hasSlicers : canOpenInSlicer,
    launchArtifactSource,
    activeSlicer?.display_name ?? preferredSlicerName,
    t,
    largeFormat,
  );

  return (
    <div className="flex flex-col gap-2">
      {hasSlicers ? (
        <div className="relative" ref={triggerRef}>
          {/* Split Button */}
          <div className="flex">
            {/* Main button with brand color */}
            <WikiTooltip
              title={mainButtonLabel}
              description={t("slicer_output_hint")}
              wikiPath={WIKI_DOCS.slicerOutput}
              placement="top"
              asChild
            >
              <button
                type="button"
                onClick={() => void handleMainClick()}
                disabled={isDisabled}
                aria-label={mainButtonLabel}
                aria-busy={actionBusy || undefined}
                className={`relative flex min-h-10 flex-1 items-center justify-center gap-2 rounded-l-md px-4 py-1.5 text-sm font-medium transition-colors ${brandStyle.bg} ${brandStyle.hover} ${brandStyle.text} disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                <ButtonContent loading={actionBusy}>
                  {showActiveSlicerLogo && <SlicerLogo slicerId={activeSlicerId} variant="onBrand" />}
                  {mainButtonLabel}
                </ButtonContent>
              </button>
            </WikiTooltip>

            {/* Dropdown arrow button */}
            <button
              type="button"
              onClick={() => setIsDropdownOpen((prev) => !prev)}
              disabled={isDisabled}
              className={`flex items-center justify-center rounded-r-md border-l border-white/20 px-2 py-2 text-sm transition-colors ${brandStyle.bg} ${brandStyle.hover} ${brandStyle.text} disabled:opacity-40 disabled:cursor-not-allowed`}
              aria-label={t("slicer_toggle_list")}
              aria-expanded={isDropdownOpen}
              aria-haspopup="listbox"
            >
              <svg className={`h-4 w-4 transition-transform ${isDropdownOpen ? "rotate-180" : ""}`} viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
              </svg>
            </button>
          </div>

          {/* Dropdown menu — rendered via Portal to escape overflow clipping */}
          {isDropdownOpen && dropdownPos && createPortal(
            <div
              ref={dropdownRef}
              style={{
                position: "fixed",
                bottom: `${window.innerHeight - dropdownPos.top + 4}px`,
                left: `${dropdownPos.left}px`,
                width: `${Math.max(dropdownPos.width, 200)}px`,
              }}
              className="z-[9999] rounded-md border border-slate-200 bg-slate-100 dark:border-slate-600 dark:bg-slate-800 py-1 shadow-lg"
              role="listbox"
            >
              {orderedSlicers.map((slicer) => {
                const isSelected = slicer.id === activeSlicerId;
                return (
                  <button
                    key={slicer.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => handleSelectSlicer(slicer.id)}
                    className={`flex min-h-11 w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors hover:bg-slate-100 dark:hover:bg-slate-700 ${isSelected ? "bg-slate-100 dark:bg-slate-700" : ""}`}
                  >
                    <SlicerLogo slicerId={slicer.id} />
                    <span className="text-slate-700 dark:text-slate-200">{slicer.display_name}</span>
                    {isSelected && <span className="ml-auto text-xs text-slate-500 dark:text-slate-400">✓</span>}
                  </button>
                );
              })}

              {/* Divider + Download 3MF option */}
              <div className="my-1 border-t border-slate-200 dark:border-slate-600" />
              <button
                type="button"
                onClick={() => void handleDownloadFromMenu()}
                disabled={isDisabled}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 dark:text-slate-200 transition-colors hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <svg className="h-4 w-4 text-slate-500 dark:text-slate-400" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z" />
                  <path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
                </svg>
                {getMenuDownloadLabel(Boolean(downloadUrl), t, largeFormat)}
              </button>
            </div>,
            document.body,
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2">
          {isDetecting ? (
            <p className="text-xs text-slate-400">{t("slicer_detecting")}</p>
          ) : (
            <>
              <WikiTooltip
                title={mainButtonLabel}
                description={t("slicer_output_hint")}
                wikiPath={WIKI_DOCS.slicerOutput}
                placement="top"
                asChild
              >
                <button
                  type="button"
                  onClick={() => void handleMainClick()}
                  disabled={isDisabled}
                  aria-label={getButtonLabel(false, launchArtifactSource, null, t, largeFormat)}
                  aria-busy={actionBusy || undefined}
                  className={`relative flex w-full items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${brandStyle.bg} ${brandStyle.hover} ${brandStyle.text} disabled:opacity-40 disabled:cursor-not-allowed`}
                >
                  <ButtonContent loading={actionBusy}>
                    {getButtonLabel(false, launchArtifactSource, null, t, largeFormat)}
                  </ButtonContent>
                </button>
              </WikiTooltip>
            </>
          )}
        </div>
      )}

      {launchMessage && (
        <p className="text-xs text-green-400">{launchMessage}</p>
      )}
      {outputHint && (
        <p role="status" className="text-xs text-slate-500 dark:text-slate-400">{outputHint}</p>
      )}
      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}
      {downloadError && (
        <p role="alert" className="text-xs text-red-400">{downloadError}</p>
      )}
    </div>
  );
}
