import { useState, useEffect, Suspense, Component } from "react";
import type { ReactNode } from "react";
import apiClient from "./api/client";
import type { HealthResponse } from "./api/types";
import { useAutoPreview } from "./hooks/useAutoPreview";
import { useWorkspaceMode } from "./hooks/useWorkspaceMode";
import Scene3D from "./components/Scene3D";
import ExtractorCanvas from "./components/ExtractorCanvas";
import LoadingSpinner from "./components/LoadingSpinner";
import { I18nProvider, useI18n } from "./i18n/context";
import { LanguageToggle } from "./components/LanguageToggle";
import { ThemeToggle } from "./components/ThemeToggle";
import { WidgetWorkspace } from "./components/widget/WidgetWorkspace";
import { useWidgetStore, WIDGET_REGISTRY, TAB_WIDGET_MAP } from "./stores/widgetStore";
import TabNavBar from "./components/widget/TabNavBar";
import CalibrationPanel from "./components/CalibrationPanel";
import ExtractorPanel from "./components/ExtractorPanel";
import LutManagerPanel from "./components/LutManagerPanel";
import FiveColorQueryPanel from "./components/FiveColorQueryPanel";
import SettingsPanel from "./components/SettingsPanel";
import VectorizerPanel from "./components/VectorizerPanel";
import { useShallow } from "zustand/react/shallow";

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

import { useRef } from "react";

function useOutsideClick(ref: React.RefObject<HTMLElement | null>, handler: () => void) {
  useEffect(() => {
    const listener = (event: MouseEvent | TouchEvent) => {
      if (!ref.current || ref.current.contains(event.target as Node)) {
        return;
      }
      handler();
    };
    document.addEventListener('mousedown', listener);
    document.addEventListener('touchstart', listener);
    return () => {
      document.removeEventListener('mousedown', listener);
      document.removeEventListener('touchstart', listener);
    };
  }, [ref, handler]);
}

import { AnimatePresence, motion } from "framer-motion";

function WidgetToggles() {
  const { t } = useI18n();
  const toggleVisible = useWidgetStore((s) => s.toggleVisible);
  const resetLayout = useWidgetStore((s) => s.resetLayout);
  const activeTab = useWidgetStore((s) => s.activeTab);
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useOutsideClick(dropdownRef, () => setIsOpen(false));

  // Filter to only show widgets belonging to the current TAB page
  const activeWidgetIds = TAB_WIDGET_MAP[activeTab];
  const visibleWidgetIds = useWidgetStore(
    useShallow((s) => activeWidgetIds.filter((id) => s.widgets[id].visible))
  );
  const filteredRegistry = WIDGET_REGISTRY.filter((c) => activeWidgetIds.includes(c.id));

  // If there are no widgets for this tab, don't show the button
  if (filteredRegistry.length === 0) {
    return null;
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        data-testid="panel-controls-toggle"
        className={`flex items-center gap-2 px-4 py-2 text-sm font-semibold transition-all duration-300 rounded-xl outline-none
          ${isOpen ? 'bg-blue-600 shadow-[0_4px_12px_rgba(37,99,235,0.25)] text-white' : 'bg-slate-100 dark:bg-slate-900 text-gray-700 dark:text-gray-200 hover:bg-white dark:hover:bg-slate-800 border border-slate-200/80 dark:border-slate-800/80'}
        `}
        style={{ WebkitTapHighlightColor: 'transparent' }}
        onClick={() => setIsOpen(!isOpen)}
        title={t("app_panel_controls")}
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

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.95 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="absolute right-0 top-full mt-2 z-50 flex w-56 flex-col gap-1 overflow-hidden rounded-2xl border border-slate-200/80 bg-white/98 p-2 shadow-[var(--shadow-control-hover)] dark:border-slate-800/80 dark:bg-slate-900/98 origin-top-right"
          >
            {filteredRegistry.map((config) => {
              const isActive = visibleWidgetIds.includes(config.id);
              return (
                <button
                  key={config.id}
                  data-testid={`widget-toggle-${config.id}`}
                  className={`
                    flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-semibold tracking-wide transition-all duration-200 outline-none
                    ${
                      isActive
                        ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400"
                        : "bg-transparent text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100/80 dark:hover:bg-gray-700/50"
                    }
                  `}
                  onClick={() => toggleVisible(config.id)}
                >
                  <span 
                    className={`w-2 h-2 rounded-full transition-colors duration-300 ${isActive ? 'bg-blue-500 shadow-[0_0_6px_rgba(59,130,246,0.6)]' : 'bg-gray-300 dark:bg-gray-600'}`}
                  />
                  {t(config.titleKey)}
                </button>
              );
            })}
            
            <div className="h-px bg-gray-200 dark:bg-gray-700/80 my-1 mx-2" />

            <button
              data-testid="widget-reset-layout"
              className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-semibold tracking-wide transition-all duration-200 outline-none
                bg-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100/80 dark:hover:bg-gray-700/50"
              onClick={() => {
                resetLayout();
                setIsOpen(false);
              }}
            >
              <svg className="w-4 h-4 ml-0.5 text-gray-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {t("app_reset_layout")}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ---------- App Content (inside I18nProvider) ---------- */

function AppContent() {
  const { t } = useI18n();
  useAutoPreview();
  const workspace = useWorkspaceMode();

  const [connected, setConnected] = useState<boolean | null>(null);
  const activeTab = useWidgetStore((s) => s.activeTab);
  const setActiveTab = useWidgetStore((s) => s.setActiveTab);

  useEffect(() => {
    apiClient
      .get<HealthResponse>("/health")
      .then((res) => setConnected(res.data.status === "ok"))
      .catch(() => setConnected(false));
  }, []);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gray-100 text-gray-900 dark:bg-gray-950 dark:text-white">
      <header
        className={`relative z-50 border-b border-gray-200 dark:border-gray-800 ${
          workspace.isCompact
            ? "grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 px-3 py-2.5 sm:px-4"
            : "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3 py-3 sm:px-4 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:px-6 lg:py-4"
        }`}
      >
        <div className="flex min-w-0 items-center gap-3">
          <img src="/favicon.ico" alt="Lumina Studio Logo" className="h-8 w-8 shrink-0 rounded" />
          <h1 className={`min-w-0 truncate font-semibold tracking-tight ${workspace.isCompact ? "hidden text-lg md:block" : "hidden text-xl sm:block"}`}>
            {t("app_header_title")}
          </h1>
        </div>

        {/* Right Side: Controls */}
        <div className={`flex min-w-0 flex-wrap items-center justify-end gap-2 ${workspace.isCompact ? "" : "lg:col-start-3 lg:row-start-1"}`}>
          {activeTab === 'converter' && <WidgetToggles />}
          <LanguageToggle />
          <ThemeToggle />
          {connected === null ? (
            <span className="text-sm text-gray-500 dark:text-gray-400">{t("app_checking_backend")}</span>
          ) : connected ? (
            <span
              data-testid="health-badge-ok"
              className={`inline-flex items-center gap-1.5 rounded-full bg-green-100 text-green-700 dark:bg-green-900/60 dark:text-green-300 ${workspace.isCompact ? "px-2.5 py-1 text-xs" : "px-3 py-1 text-sm"}`}
            >
              <span className="h-2 w-2 rounded-full bg-green-400" />
              <span className={workspace.isCompact ? "hidden" : "hidden sm:inline"}>{t("app_backend_connected")}</span>
            </span>
          ) : (
            <span
              data-testid="health-badge-fail"
              className={`inline-flex items-center gap-1.5 rounded-full bg-red-100 text-red-700 dark:bg-red-900/60 dark:text-red-300 ${workspace.isCompact ? "px-2.5 py-1 text-xs" : "px-3 py-1 text-sm"}`}
            >
              <span className="h-2 w-2 rounded-full bg-red-400" />
              <span className={workspace.isCompact ? "hidden" : "hidden sm:inline"}>{t("app_backend_unreachable")}</span>
            </span>
          )}
        </div>

        {/* Center: Tabs */}
        <div className={`min-w-0 ${workspace.isCompact ? "col-span-3 row-start-2" : "col-span-2 lg:col-span-1 lg:col-start-2 lg:row-start-1"}`}>
          <TabNavBar
            activeTab={activeTab}
            onTabChange={setActiveTab}
            compact={workspace.isCompact}
          />
        </div>
      </header>

      <main className="relative flex-1 min-h-0 overflow-hidden bg-slate-50 dark:bg-slate-950">
        {/* Converter: WidgetWorkspace + Scene3D */}
        <div className={activeTab !== 'converter' ? 'hidden' : 'h-full min-h-0'}>
          <WidgetWorkspace>
            <SceneErrorBoundary
              fallback={
                <div className="absolute inset-0 flex items-center justify-center bg-gray-100 dark:bg-gray-950">
                  <p className="text-red-400 text-sm">{t("app_3d_scene_error")}</p>
                </div>
              }
            >
              <Suspense fallback={<LoadingSpinner />}>
                <Scene3D />
              </Suspense>
            </SceneErrorBoundary>
          </WidgetWorkspace>
        </div>

        {activeTab === 'calibration' && <CalibrationPanel />}

        {activeTab === 'extractor' && (
          <div className={`flex h-full min-h-0 flex-col ${workspace.isWide ? "2xl:flex-row" : ""}`}>
            <ExtractorPanel />
            <div className={`relative min-h-0 flex-1 overflow-hidden border-slate-200/70 dark:border-slate-800/80 ${workspace.isWide ? "border-t 2xl:border-l 2xl:border-t-0" : "border-t"}`}>
              <ExtractorCanvas />
            </div>
          </div>
        )}

        {activeTab === 'lut-manager' && <LutManagerPanel />}
        {activeTab === 'five-color' && <FiveColorQueryPanel />}
        {activeTab === 'vectorizer' && <VectorizerPanel />}
        {activeTab === 'settings' && <SettingsPanel />}
      </main>
    </div>
  );
}

/* ---------- App ---------- */

function App() {
  return (
    <I18nProvider>
      <AppContent />
    </I18nProvider>
  );
}

export default App;
