import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useSlicerStore } from "../../stores/slicerStore";
import { useConverterStore } from "../../stores/converterStore";
import { useI18n } from "../../i18n/context";

/** Brand color style for a slicer button. 切片软件品牌配色样式。 */
export interface SlicerBrandStyle {
  bg: string;
  hover: string;
  text: string;
}

/** Default gray style for unknown slicers. 未知切片软件的默认灰色样式。 */
const DEFAULT_BRAND_STYLE: SlicerBrandStyle = {
  bg: "bg-gray-600",
  hover: "hover:bg-gray-700",
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
 * @param threemfDiskPath - The 3MF file disk path, or null. (3MF 文件磁盘路径，或 null)
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

interface SlicerSelectorProps {
  threemfDiskPath: string | null;
  downloadUrl: string | null;
  canSubmit: boolean;
  onAutoGenerate: () => Promise<string | null>;
  largeFormat?: boolean;
}

export default function SlicerSelector({
  threemfDiskPath,
  downloadUrl,
  canSubmit,
  onAutoGenerate,
  largeFormat,
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

  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isAutoGenerating, setIsAutoGenerating] = useState(false);
  const triggerRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
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
  const selectedSlicer = slicers.find((s) => s.id === selectedSlicerId);
  const brandStyle = selectedSlicerId
    ? getSlicerBrandStyle(selectedSlicerId)
    : DEFAULT_BRAND_STYLE;

  /**
   * Helper to trigger a browser download from a URL.
   * 辅助函数：通过 URL 触发浏览器下载。
   */
  const triggerDownload = (url: string) => {
    const link = document.createElement("a");
    link.href = url;
    link.download = "";
    link.click();
  };

  const handleDownloadOrGenerate = async () => {
    if (downloadUrl) {
      triggerDownload(downloadUrl);
    } else {
      setIsAutoGenerating(true);
      try {
        await onAutoGenerate();
        const latestDownloadUrl = useConverterStore.getState().downloadUrl;
        if (latestDownloadUrl) {
          triggerDownload(latestDownloadUrl);
        }
      } catch {
        // Error state is set by submitGenerate in ConverterStore
      } finally {
        setIsAutoGenerating(false);
      }
    }
  };

  const handleMainClick = async () => {
    if (largeFormat || !hasSlicers) {
      await handleDownloadOrGenerate();
      return;
    }

    // Has slicers (normal mode)
    if (threemfDiskPath) {
      void launchSlicer(threemfDiskPath);
    } else {
      setIsAutoGenerating(true);
      try {
        await onAutoGenerate();
        const latestPath = useConverterStore.getState().threemfDiskPath;
        if (latestPath) {
          void launchSlicer(latestPath);
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

  const handleDownloadFromMenu = () => {
    if (downloadUrl) {
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = "";
      link.click();
    }
    setIsDropdownOpen(false);
  };

  const isDisabled = !canSubmit || isDetecting || isLaunching || isAutoGenerating;

  const mainButtonLabel = getButtonLabel(
    hasSlicers,
    threemfDiskPath,
    selectedSlicer?.display_name ?? null,
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
            <button
              type="button"
              onClick={() => void handleMainClick()}
              disabled={isDisabled}
              className={`flex flex-1 items-center justify-center gap-2 rounded-l-md px-4 py-2 text-sm font-medium transition-colors ${brandStyle.bg} ${brandStyle.hover} ${brandStyle.text} disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              {(isLaunching || isAutoGenerating) && (
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              {mainButtonLabel}
            </button>

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
              className="z-[9999] rounded-md border border-gray-200 bg-white dark:border-gray-600 dark:bg-gray-800 py-1 shadow-lg"
              role="listbox"
            >
              {slicers.map((slicer) => {
                const style = getSlicerBrandStyle(slicer.id);
                const isSelected = slicer.id === selectedSlicerId;
                return (
                  <button
                    key={slicer.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => handleSelectSlicer(slicer.id)}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 ${isSelected ? "bg-gray-100 dark:bg-gray-700" : ""}`}
                  >
                    <span className={`inline-block h-2.5 w-2.5 rounded-full ${style.bg}`} />
                    <span className="text-gray-700 dark:text-gray-200">{slicer.display_name}</span>
                    {isSelected && <span className="ml-auto text-xs text-gray-500 dark:text-gray-400">✓</span>}
                  </button>
                );
              })}

              {/* Divider + Download 3MF option */}
              <div className="my-1 border-t border-gray-200 dark:border-gray-600" />
              <button
                type="button"
                onClick={handleDownloadFromMenu}
                disabled={!downloadUrl}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-700 dark:text-gray-200 transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <svg className="h-4 w-4 text-gray-500 dark:text-gray-400" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z" />
                  <path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
                </svg>
                {largeFormat ? t("slicer_download_zip") : t("slicer_download_3mf")}
              </button>
            </div>,
            document.body,
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2">
          {isDetecting ? (
            <p className="text-xs text-gray-400">{t("slicer_detecting")}</p>
          ) : (
            <>
              <p className="text-xs text-gray-400">{t("slicer_not_detected")}</p>
              <button
                type="button"
                onClick={() => void handleMainClick()}
                disabled={isDisabled}
                className="flex items-center gap-2 rounded-md bg-gray-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isAutoGenerating && (
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                )}
                {getButtonLabel(false, threemfDiskPath, null, t, largeFormat)}
              </button>
            </>
          )}
        </div>
      )}

      {launchMessage && (
        <p className="text-xs text-green-400">{launchMessage}</p>
      )}
      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}
    </div>
  );
}
