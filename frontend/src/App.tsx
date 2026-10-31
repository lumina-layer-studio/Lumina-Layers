import { useState, useEffect, useCallback, useRef, Suspense, Component, lazy } from "react";
import type { ReactNode } from "react";
import apiClient from "./api/client";
import { useApplicationMenuCommand, useApplicationMenuLanguage } from "./integrations/applicationMenu";
import type { HealthResponse } from "./api/types";
import { trackLuminaEvent } from "./analytics/umami";
import { useAutoPreview } from "./hooks/useAutoPreview";
import { useVectorPreviewRenderer } from "./hooks/useVectorPreviewRenderer";
import { useAnnouncement } from "./hooks/useAnnouncement";
import { usePuzzleLayoutPreview } from "./hooks/usePuzzleLayoutPreview";
import { useSessionLease } from "./hooks/useSessionLease";
import { useColorcheckerArtifactLease } from "./hooks/useColorcheckerArtifactLease";
import { useActionHistoryBootstrap } from "./hooks/useActionHistoryBootstrap";
import { useReproMode } from "./hooks/useReproMode";
import { useWorkspaceMode } from "./hooks/useWorkspaceMode";
import { useHeaderNavFit } from "./hooks/useHeaderNavFit";
import { useDocumentThemeClass } from "./hooks/useDocumentThemeClass";
import { useOutsideInteraction } from "./hooks/useOutsideInteraction";
import { useSharedSettingsPersistence } from "./hooks/useSharedSettingsPersistence";
import { useConversionPreferences } from "./hooks/useConversionPreferences";
import Scene3D from "./components/Scene3D";
import ExtractorCanvas from "./components/ExtractorCanvas";
import LoadingSpinner from "./components/LoadingSpinner";
import AnnouncementDialog from "./components/ui/AnnouncementDialog";
import NativeMaterialSelectionDialog from "./components/ui/NativeMaterialSelectionDialog";
import { I18nProvider, useI18n } from "./i18n/context";
import { BugReportModal } from "./components/BugReportModal";
import { ErrorTicketPrompt } from "./components/ErrorTicketPrompt";
import { buildErrorTicketDescription } from "./utils/errorTicketDescription";
import { useErrorTicketPromptCapture } from "./hooks/useErrorTicketPromptCapture";
import { useErrorTicketPromptStore } from "./stores/errorTicketPromptStore";
import { HeaderMenu } from "./components/HeaderMenu";
import { LanguageToggle } from "./components/LanguageToggle";
import { ThemeToggle } from "./components/ThemeToggle";
import { TutorialHost } from "./components/tutorial/TutorialHost";
import { WidgetWorkspace } from "./components/widget/WidgetWorkspace";
import { useWidgetStore, WIDGET_REGISTRY, TAB_WIDGET_MAP, CONVERTER_SUB_TAB_WIDGET_MAP } from "./stores/widgetStore";
import TabNavBar, { hasSubTabs } from "./components/widget/TabNavBar";
import SubTabBar from "./components/widget/SubTabBar";
import AlignedNavStrip from "./components/widget/AlignedNavStrip";
import {
  HEADER_NAV_GRID_CLASS,
  primaryTabsCellClass,
  primaryTabsCellShift,
  subTabRowJustifyClass,
  subTabsCenterShift,
} from "./components/widget/headerNavLayout";
import { useSettingsStore } from "./stores/settingsStore";
import CalibrationPanel from "./components/CalibrationPanel";
import ExtractorPanel from "./components/ExtractorPanel";
import ColorcheckerConfirmDialogExtractor from "./components/ColorcheckerConfirmDialog";
import GradientCardGeneratePanel from "./components/GradientCardGeneratePanel";
import GradientCardExtractPanel from "./components/GradientCardExtractPanel";
import MaterialCloudSyncPanel from "./components/MaterialCloudSyncPanel";
import MaterialLibraryPanel from "./components/MaterialLibraryPanel";
import MaterialRecipeQueryPanel from "./components/MaterialRecipeQueryPanel";
import LutCloudSyncPanel from "./components/LutCloudSyncPanel";
import LutLibraryPanel from "./components/LutLibraryPanel";
import LutComparePanel from "./components/LutComparePanel";
import LutManagerPanel from "./components/LutManagerPanel";
import FiveColorQueryPanel from "./components/FiveColorQueryPanel";
import SettingsPanel from "./components/SettingsPanel";
import VectorizerPanel from "./components/VectorizerPanel";
import WorkshopPanel from "./workshop/WorkshopPanel";
import { useSingleStageStore } from "./stores/singleStageStore";
import { useExtractorStore } from "./stores/extractorStore";
import { collectConverterKeepFileIds, useConverterStore } from "./stores/converter";
import { useShallow } from "zustand/react/shallow";
import {
  electronAPI,
  useElectronGeneratedFileDirectorySync,
  useElectronLanguageSync,
} from "./integrations/electron";
import {
  HEADER_MENU_PANEL_CLASS,
} from "./components/ui/headerControls";

import LutDetailsPanel from "./components/LutDetailsPanel";

const HEALTH_RECHECK_MS = 5_000;
const AboutDialog = lazy(() => import("./credits/AboutDialog"));

/* ---------- Error Boundary ---------- */

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class SceneErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

/* ---------- Widget Toggle Buttons ---------- */

import { AnimatePresence, motion } from "framer-motion";

function WidgetToggles() {
  const { t } = useI18n();
  const toggleVisible = useWidgetStore((s) => s.toggleVisible);
  const resetLayout = useWidgetStore((s) => s.resetLayout);
  const activeTab = useWidgetStore((s) => s.activeTab);
  const activeConverterSubTab = useWidgetStore((s) => s.activeConverterSubTab);
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const closeDropdown = useCallback(() => setIsOpen(false), []);

  useOutsideInteraction(dropdownRef, closeDropdown, isOpen);

  // Filter to only show widgets belonging to the current TAB page.
  // For the converter, narrow further by the active sub-tab so users cannot
  // toggle on a widget that the current sub-tab will not render — that was
  // confusing ("why doesn't this panel appear after I enabled it?").
  // 对于「图像转换」主 tab，再按当前二级 sub-tab 收窄；否则用户能开启一个
  // 实际不会渲染的 widget，造成「我开了为什么看不到」的困惑。
  const activeWidgetIds =
    activeTab === "converter"
      ? (CONVERTER_SUB_TAB_WIDGET_MAP[activeConverterSubTab] as readonly import("./types/widget").WidgetId[])
      : (TAB_WIDGET_MAP[activeTab] ?? []);
  const visibleWidgetIds = useWidgetStore(
    useShallow((s) => activeWidgetIds.filter((id) => s.widgets[id]?.visible))
  );
  const filteredRegistry = WIDGET_REGISTRY.filter((c) => activeWidgetIds.includes(c.id));

  const hasWidgets = filteredRegistry.length > 0;

  return (
    <div className={`relative${hasWidgets ? '' : ' invisible pointer-events-none'}`} ref={dropdownRef}>
      <button
        data-testid="panel-controls-toggle"
        className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-full border px-3.5 text-sm font-semibold transition-colors duration-300 outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]
          ${isOpen ? 'border-transparent bg-blue-600 text-white' : 'border-slate-200/80 bg-slate-100/85 text-slate-600 hover:bg-slate-200/90 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800/80'}
        `}
        style={{ WebkitTapHighlightColor: 'transparent' }}
        onClick={() => setIsOpen(!isOpen)}
        aria-label={t("app_panel_controls")}
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
        </svg>
        <span className="hidden sm:inline">{t("app_panel_controls")}</span>
        <svg
          className={`w-4 h-4 transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {hasWidgets && (
        <AnimatePresence>
          {isOpen && (
            <motion.div
              initial={{ opacity: 0, y: -10, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.95 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              className={`${HEADER_MENU_PANEL_CLASS} w-56`}
            >
              {filteredRegistry.map((config) => {
                const isActive = visibleWidgetIds.includes(config.id);
                return (
                  <button
                    key={config.id}
                    data-testid={`widget-toggle-${config.id}`}
                    className={`
                      flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-semibold tracking-wide transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]
                      ${
                        isActive
                          ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400"
                          : "bg-transparent text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-[var(--nav-chip-hover)]"
                      }
                    `}
                    onClick={() => toggleVisible(config.id)}
                  >
                    <span
                      className={`w-2 h-2 rounded-full transition-colors duration-300 ${isActive ? 'bg-blue-500 shadow-[0_0_6px_rgba(59,130,246,0.6)]' : 'bg-slate-300 dark:bg-slate-600'}`}
                    />
                    {t(config.titleKey)}
                  </button>
                );
              })}

              <div className="mx-2 my-2 h-0.5 shrink-0 bg-[var(--surface-divider)]" />

              <button
                data-testid="widget-reset-layout"
                className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-semibold tracking-wide transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]
                  bg-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-[var(--nav-chip-hover)]"
                onClick={() => {
                  resetLayout();
                  setIsOpen(false);
                }}
              >
                <svg className="w-4 h-4 ml-0.5 text-slate-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                {t("app_reset_layout")}
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      )}
    </div>
  );
}

/* ---------- App Content (inside I18nProvider) ---------- */

function AppContent({ connected }: { connected: boolean | null }) {
  const { t } = useI18n();
  const announcement = useAnnouncement();
  const converterSessionId = useConverterStore((s) => s.sessionId);
  const converterKeepFileIds = useConverterStore(
    useShallow((s) => collectConverterKeepFileIds(s)),
  );
  const singleStageSessionId = useSingleStageStore((s) => s.sessionId);
  useSessionLease(converterSessionId, "converter", converterKeepFileIds);
  useSessionLease(singleStageSessionId, "single_stage");
  useActionHistoryBootstrap();
  useAutoPreview();
  useVectorPreviewRenderer();
  usePuzzleLayoutPreview();
  useElectronLanguageSync();
  useApplicationMenuLanguage();
  useElectronGeneratedFileDirectorySync();
  useSharedSettingsPersistence();
  useDocumentThemeClass();
  useConversionPreferences();
  const workspace = useWorkspaceMode();
  const reproMode = useReproMode();
  const headerNavAlignment = useSettingsStore((s) => s.headerNavAlignment);
  const mergedTitlebar = electronAPI?.platform === "darwin" || electronAPI?.platform === "win32";
  const headerRef = useRef<HTMLElement>(null);
  const headerContentProbeRef = useRef<HTMLSpanElement>(null);
  const headerBrandLogoRef = useRef<HTMLImageElement>(null);
  const headerBrandTitleRef = useRef<HTMLHeadingElement>(null);
  const headerToolsRef = useRef<HTMLDivElement>(null);
  const primaryTabsRef = useRef<HTMLElement>(null);
  const windowControlsProbeRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (electronAPI?.platform !== "darwin" || !electronAPI.alignTrafficLights) return;
    const alignTrafficLights = electronAPI.alignTrafficLights;
    const header = headerRef.current;
    const logo = headerBrandLogoRef.current;
    const controlsProbe = windowControlsProbeRef.current;
    if (!header || !logo || !controlsProbe) return;
    const align = () => {
      const bounds = logo.getBoundingClientRect();
      void alignTrafficLights(bounds.top + bounds.height / 2, controlsProbe.getBoundingClientRect().height)
        .catch(() => { /* Keep the native title bar if the host is unavailable. */ });
    };
    const observer = new ResizeObserver(align);
    observer.observe(header);
    observer.observe(logo);
    observer.observe(controlsProbe);
    window.addEventListener("resize", align);
    const unsubscribe = electronAPI.onInterfaceScaleChanged?.(align);
    align();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", align);
      unsubscribe?.();
    };
  }, []);
  const headerNavFit = useHeaderNavFit(headerNavAlignment, {
    header: headerRef,
    contentWidthProbe: headerContentProbeRef,
    brandLogo: headerBrandLogoRef,
    brandTitle: headerBrandTitleRef,
    primaryTabs: primaryTabsRef,
    tools: headerToolsRef,
  });
  const headerPaddingXClass = workspace.isCompact
    ? "px-3 sm:px-4"
    : "px-3 sm:px-4 lg:px-6";

  const [announcementReady, setAnnouncementReady] = useState(false);
  const [bugReportOpen, setBugReportOpen] = useState(false);
  const [infoPage, setInfoPage] = useState<"about" | "credits" | null>(null);
  const infoOpen = infoPage !== null;
  const restoreInfoFocus = useRef<(() => void) | null>(null);
  const openAbout = useCallback((restoreFocus?: () => void) => {
    if (!restoreInfoFocus.current) {
      const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      restoreInfoFocus.current = restoreFocus ?? (() => previous?.isConnected && previous.focus({ preventScroll: true }));
    }
    setInfoPage("about");
  }, []);
  const closeAbout = useCallback(() => setInfoPage(null), []);
  useEffect(() => {
    if (infoOpen) return;
    restoreInfoFocus.current?.();
    restoreInfoFocus.current = null;
  }, [infoOpen]);
  useApplicationMenuCommand("about", openAbout);
  const [bugReportPreset, setBugReportPreset] = useState("");
  const errorTicketPrompt = useErrorTicketPromptStore((s) => s.pending);
  const dismissErrorTicketPrompt = useErrorTicketPromptStore((s) => s.dismiss);
  const suppressErrorTicketPrompt = useErrorTicketPromptStore((s) => s.suppressForSession);
  useErrorTicketPromptCapture(!reproMode.enabled);
  const openBugReport = useCallback(
    (preset: string) => {
      dismissErrorTicketPrompt();
      setBugReportPreset(preset);
      setBugReportOpen(true);
    },
    [dismissErrorTicketPrompt],
  );
  const closeBugReport = useCallback(() => {
    // Errors raised while the report form was open are already covered by it.
    // 填写工单期间产生的错误已包含在本次工单中，关闭时一并清除提示。
    dismissErrorTicketPrompt();
    setBugReportOpen(false);
    setBugReportPreset("");
  }, [dismissErrorTicketPrompt]);
  const activeTab = useWidgetStore((s) => s.activeTab);
  const activeConverterSubTab = useWidgetStore((s) => s.activeConverterSubTab);
  const setActiveTab = useWidgetStore((s) => s.setActiveTab);
  const converterEntrySequence = useRef(0);
  const [deferredConverterEntry, setDeferredConverterEntry] = useState<number | null>(null);

  useEffect(() => {
    if (activeTab !== "converter") setDeferredConverterEntry(null);
  }, [activeTab]);

  const handleIndicatorAnimationComplete = useCallback((tab: typeof activeTab) => {
    if (tab !== "converter") return;
    // Ignore completion from an earlier entry interrupted by another click.
    setDeferredConverterEntry((current) => current === deferredConverterEntry ? null : current);
  }, [deferredConverterEntry]);
  const extractorColorcheckerFullIds = useExtractorStore(
    useShallow((s) => [
      s.colorchecker_phase === "done" ? s.calibratedFullFileId : null,
      s.colorchecker_phase === "confirming"
        ? s.previousCalibratedFullFileId
        : null,
    ]),
  );
  const extractorColorcheckerPreviewUrls = useExtractorStore(
    useShallow((s) => [
      s.colorchecker_phase === "done"
        ? s.calibratedPreviewUrl ?? s.imagePreviewUrl
        : null,
      s.colorchecker_phase === "done" && s.calibratedFullFileId
        ? s.originalPreviewUrl
        : null,
      s.colorchecker_phase === "confirming" ? s.imagePreviewUrl : null,
      s.colorchecker_phase === "confirming" ? s.calibratedPreviewUrl : null,
    ]),
  );
  const gradientColorcheckerFullIds = useSingleStageStore(
    useShallow((s) => [s.whiteColorcheckerFileId, s.blackColorcheckerFileId]),
  );
  const gradientColorcheckerPreviewUrls = useSingleStageStore(
    useShallow((s) => [
      s.whiteColorcheckerFileId ? s.whiteImagePreviewUrl : null,
      s.blackColorcheckerFileId ? s.blackImagePreviewUrl : null,
      s.whiteColorcheckerFileId ? s.originalWhitePreviewUrl : null,
      s.blackColorcheckerFileId ? s.originalBlackPreviewUrl : null,
    ]),
  );
  useColorcheckerArtifactLease([
    ...extractorColorcheckerFullIds,
    ...gradientColorcheckerFullIds,
  ], true, [
    ...extractorColorcheckerPreviewUrls,
    ...gradientColorcheckerPreviewUrls,
  ]);
  const clearMaterialVerification = useSingleStageStore(
    (s) => s.clearMaterialVerification,
  );

  // Clicking the gradient-card extract sub-tab from navigation starts a fresh
  // extraction and clears stale verification state. Re-verification from the
  // material library bypasses this handler by setting the store directly.
  // 用户从导航栏点击「提取耗材」视为全新提取，清除遗留校验状态；耗材库再次校验
  // 直接调 store，不受这里影响。
  const handleTabChange = useCallback(
    (tab: typeof activeTab) => {
      if (tab !== activeTab) {
        const entry = ++converterEntrySequence.current;
        setDeferredConverterEntry(tab === "converter" ? entry : null);
      }
      if (tab === "gradient-card-extract") {
        clearMaterialVerification();
      }
      setActiveTab(tab);
    },
    [activeTab, setActiveTab, clearMaterialVerification],
  );

  useApplicationMenuCommand('settings', () => handleTabChange('settings'));
  useApplicationMenuCommand('report', () => openBugReport(''), !reproMode.enabled);

  useEffect(() => {
    trackLuminaEvent("lumina_tab_view", {
      active_tab: activeTab,
      converter_sub_tab:
        activeTab === "converter" ? activeConverterSubTab : null,
      workspace_mode: workspace.mode,
    });
  }, [activeTab, activeConverterSubTab, workspace.mode]);

  useEffect(() => {
    const timer = window.setTimeout(() => setAnnouncementReady(true), 600);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-200 text-slate-900 dark:bg-slate-950 dark:text-white">
      <header
        ref={headerRef}
        inert={infoOpen}
        aria-hidden={infoOpen || undefined}
        style={electronAPI?.platform === "darwin" ? {
          paddingLeft: "calc(env(titlebar-area-x, 80px) + 12px)",
        } : electronAPI?.platform === "win32" ? {
          paddingRight: "calc(100% - env(titlebar-area-x, 0px) - env(titlebar-area-width, calc(100% - 180px)) + 12px)",
          minHeight: "max(3rem, env(titlebar-area-height, 40px))",
        } : undefined}
        className={`${mergedTitlebar ? "desktop-titlebar min-h-12" : ""} relative z-50 grid items-center gap-x-6 gap-y-2 border-b panel-divider ${headerPaddingXClass} ${
          workspace.isCompact ? "py-1.5" : "py-2.5"
        } ${HEADER_NAV_GRID_CLASS}`}
      >
        {electronAPI?.platform === "darwin" && (
          <span
            ref={windowControlsProbeRef}
            aria-hidden="true"
            className="pointer-events-none invisible absolute w-0"
            style={{ height: "env(titlebar-area-height, 0px)" }}
          />
        )}
        <span
          ref={headerContentProbeRef}
          aria-hidden="true"
          className="pointer-events-none col-span-full row-start-1 h-0 self-start"
        />
        <div className="col-start-1 row-start-1 flex w-max items-center justify-self-start">
          <img
            ref={headerBrandLogoRef}
            src="/favicon.ico"
            alt={t("app_logo_alt")}
            draggable={false}
            className="h-8 w-8 shrink-0 rounded"
          />
          {/* Collapses to zero width when the tabs need the room; the title
              keeps its natural width inside so it can still be measured. */}
          <div
            data-testid="header-brand-title"
            className={`overflow-hidden ${headerNavFit.showBrandTitle ? "" : "max-w-0"}`}
          >
            <h1
              ref={headerBrandTitleRef}
              className={`w-max whitespace-nowrap pl-3 font-semibold tracking-tight ${workspace.isCompact ? "hidden text-lg md:block" : "hidden text-xl sm:block"}`}
            >
              {t("app_header_title")}
            </h1>
          </div>
        </div>

        {/* Right Side: Controls */}
        <div
          ref={headerToolsRef}
          className="desktop-titlebar-controls col-start-3 row-start-1 flex w-max items-center gap-2 justify-self-end"
        >
          <WidgetToggles />
          <HeaderMenu
            backendStatus={connected === null ? "checking" : connected ? "ok" : "fail"}
            reproTicketId={reproMode.enabled ? reproMode.ticketId : null}
            onReportBug={() => openBugReport("")}
            onOpenAbout={openAbout}
          />
        </div>

        {/* Primary tabs: same row as brand and tools when they fit */}
        <div className={primaryTabsCellClass(headerNavAlignment, headerNavFit.singleRow)}>
          <AlignedNavStrip
            alignment={headerNavAlignment}
            centerShift={primaryTabsCellShift(headerNavFit)}
          >
            <TabNavBar
              navRef={primaryTabsRef}
              activeTab={activeTab}
              onTabChange={handleTabChange}
              onIndicatorAnimationComplete={handleIndicatorAnimationComplete}
              compact={workspace.isCompact}
            />
          </AlignedNavStrip>
        </div>
      </header>

      <main inert={infoOpen} aria-hidden={infoOpen || undefined}
        style={{ visibility: infoOpen ? "hidden" : undefined }}
        className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50 dark:bg-slate-950">
        {hasSubTabs(activeTab) && (
          <div
            data-testid="sub-tab-row"
            className={`flex shrink-0 border-b panel-divider bg-slate-200 py-0.5 dark:bg-slate-950 ${headerPaddingXClass} ${subTabRowJustifyClass(headerNavAlignment)}`}
            style={
              headerNavAlignment === "left"
                ? { paddingLeft: headerNavFit.primaryTabsInsetPx }
                : { paddingLeft: headerNavFit.paddingLeft, paddingRight: headerNavFit.paddingRight }
            }
          >
            <AlignedNavStrip
              alignment={headerNavAlignment}
              centerShift={subTabsCenterShift(headerNavFit)}
            >
              <SubTabBar
                activeTab={activeTab}
                onTabChange={handleTabChange}
                compact={workspace.isCompact}
              />
            </AlignedNavStrip>
          </div>
        )}

        <div className="relative min-h-0 flex-1">
        {/* Converter: WidgetWorkspace + Scene3D */}
        {activeTab === 'converter' && (
          <div className="h-full min-h-0">
            <WidgetWorkspace>
              <SceneErrorBoundary
                fallback={
                  <div className="absolute inset-0 flex items-center justify-center bg-slate-50 dark:bg-slate-950">
                    <p className="text-red-400 text-sm">{t("app_3d_scene_error")}</p>
                  </div>
                }
              >
                <Suspense fallback={<LoadingSpinner />}>
                  <Scene3D deferInitialization={deferredConverterEntry !== null} suspended={infoOpen} />
                </Suspense>
              </SceneErrorBoundary>
            </WidgetWorkspace>
          </div>
        )}

        {activeTab === 'calibration' && <CalibrationPanel />}
        {activeTab === 'gradient-card-generate' && <GradientCardGeneratePanel />}
        {activeTab === 'gradient-card-extract' && <GradientCardExtractPanel />}
        {activeTab === 'material-library' && <MaterialLibraryPanel />}
        {activeTab === 'material-cloud-sync' && <MaterialCloudSyncPanel />}
        {activeTab === 'material-recipe' && <MaterialRecipeQueryPanel />}

        {activeTab === 'extractor' && (
          <div className="flex h-full min-h-0 flex-col xl:flex-row">
            <ExtractorPanel />
            <div className="relative min-h-[min(54vh,40rem)] flex-1 overflow-hidden border-t border-slate-200/70 dark:border-slate-800/80 xl:min-h-0 xl:border-l xl:border-t-0">
              <ExtractorCanvas />
            </div>
          </div>
        )}

        {activeTab === 'lut-library' && <LutLibraryPanel />}
        {activeTab === 'lut-manager' && <LutManagerPanel />}
        {activeTab === 'lut-cloud-sync' && <LutCloudSyncPanel />}
        {activeTab === 'lut-details' && <LutDetailsPanel />}
        {activeTab === 'lut-compare' && <LutComparePanel />}
        {activeTab === 'five-color' && (
          <div className="flex h-full min-h-0">
            <FiveColorQueryPanel />
          </div>
        )}
        {activeTab === 'vectorizer' && <VectorizerPanel />}
        {activeTab === 'workshop' && <WorkshopPanel />}
        {activeTab === 'settings' && <SettingsPanel />}
        </div>
      </main>
      {infoPage && <Suspense fallback={<LoadingSpinner />}><AboutDialog page={infoPage} onNavigate={setInfoPage} onClose={closeAbout} /></Suspense>}
      <AnnouncementDialog
        open={!infoOpen && announcementReady && announcement.visible}
        entries={announcement.entries}
        entry={announcement.entry}
        onClose={announcement.close}
        onDismissVersion={announcement.dismissThisVersion}
      />
      <BugReportModal
        open={bugReportOpen}
        onClose={closeBugReport}
        presetDescription={bugReportPreset}
      />
      {/* Ask whether to file a ticket after an unexpected error; hidden while
          the report form is open and during bug-report reproduction runs. */}
      <ErrorTicketPrompt
        info={bugReportOpen || reproMode.enabled ? null : errorTicketPrompt}
        onReport={() => {
          if (errorTicketPrompt) {
            openBugReport(buildErrorTicketDescription(errorTicketPrompt, t));
          }
        }}
        onDismiss={dismissErrorTicketPrompt}
        onSuppress={suppressErrorTicketPrompt}
      />
      {/* Beginner tutorial: offered once after the release announcement is
          gone, and never during bug-report reproduction sessions. */}
      <TutorialHost
        canAutoOffer={!infoOpen && announcementReady && !announcement.visible && !reproMode.enabled}
      />
      {/* Extractor ColorChecker calibration popup. Mounted at the app root so
          it appears regardless of whether the extractor is opened as the
          full-page tab or as a dockable widget; it self-gates on the
          extractor store's colorchecker phase. */}
      {/* 提取器 ColorChecker 校色弹窗：挂载在应用根部，无论提取器是以整页标签
          还是可停靠 widget 形式打开都能弹出；其显隐由提取器 store 的
          colorchecker 阶段自行控制。 */}
      <ColorcheckerConfirmDialogExtractor />
      <NativeMaterialSelectionDialog />
    </div>
  );
}

/* ---------- App ---------- */

function AppReadiness() {
  const { t } = useI18n();
  const [connected, setConnected] = useState<boolean | null>(null);
  const [hasConnected, setHasConnected] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let checking = false;
    const controller = new AbortController();
    const checkHealth = async () => {
      if (checking) return;
      checking = true;
      try {
        const response = await apiClient.get<HealthResponse>("/health", {
          suppressClientLog: true,
          timeout: 4_000,
          signal: controller.signal,
        });
        if (!cancelled) {
          const ready = response.data.status === "ok";
          setConnected(ready);
          if (ready) setHasConnected(true);
        }
      } catch {
        if (!cancelled) setConnected(false);
      } finally {
        checking = false;
      }
    };
    void checkHealth();
    const intervalId = window.setInterval(() => void checkHealth(), HEALTH_RECHECK_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, []);

  // Mount initialization effects only after the first successful health check.
  // Later disconnects preserve the workspace and its ordinary error handling.
  if (hasConnected) return <AppContent connected={connected} />;
  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--surface-panel-strong)] p-6">
      <section className="max-w-md space-y-4 text-center" role="status" aria-live="polite">
        <img src="/favicon.ico" alt={t("app_logo_alt")} className="mx-auto h-12 w-12 rounded" />
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">{t("app_starting")}</h1>
        <p className="text-sm leading-6 text-[var(--surface-text-muted)]">{t("app_starting_detail")}</p>
        <div className="flex justify-center gap-2"><LanguageToggle /><ThemeToggle /></div>
      </section>
    </main>
  );
}

function App() {
  return (
    <I18nProvider>
      <AppReadiness />
    </I18nProvider>
  );
}

export default App;
