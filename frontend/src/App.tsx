import { useState, useEffect, Suspense, Component } from "react";
import type { ReactNode } from "react";
import apiClient from "./api/client";
import type { HealthResponse } from "./api/types";
import { useAutoPreview } from "./hooks/useAutoPreview";
import Scene3D from "./components/Scene3D";
import ExtractorCanvas from "./components/ExtractorCanvas";
import LoadingSpinner from "./components/LoadingSpinner";
import { I18nProvider, useI18n } from "./i18n/context";
import { LanguageToggle } from "./components/LanguageToggle";
import { ThemeToggle } from "./components/ThemeToggle";
import { WidgetWorkspace } from "./components/widget/WidgetWorkspace";
import { useWidgetStore, WIDGET_REGISTRY, TAB_WIDGET_MAP } from "./stores/widgetStore";
import TabNavBar from "./components/widget/TabNavBar";
import FullScreenModal from "./components/ui/FullScreenModal";
import CalibrationPanel from "./components/CalibrationPanel";
import ExtractorPanel from "./components/ExtractorPanel";
import LutManagerPanel from "./components/LutManagerPanel";
import FiveColorQueryPanel from "./components/FiveColorQueryPanel";
import type { TabId } from "./types/widget";

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

function WidgetToggles() {
  const { t } = useI18n();
  const widgets = useWidgetStore((s) => s.widgets);
  const toggleVisible = useWidgetStore((s) => s.toggleVisible);
  const resetLayout = useWidgetStore((s) => s.resetLayout);
  const activeTab = useWidgetStore((s) => s.activeTab);

  // Filter to only show widgets belonging to the current TAB page
  const activeWidgetIds = TAB_WIDGET_MAP[activeTab];
  const filteredRegistry = WIDGET_REGISTRY.filter((c) => activeWidgetIds.includes(c.id));

  return (
    <div className="flex items-center gap-1">
      {filteredRegistry.map((config) => (
        <button
          key={config.id}
          data-testid={`widget-toggle-${config.id}`}
          className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
            widgets[config.id].visible
              ? "bg-blue-600 text-white"
              : "bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
          }`}
          onClick={() => toggleVisible(config.id)}
          title={t(config.titleKey)}
        >
          {t(config.titleKey)}
        </button>
      ))}
      <button
        data-testid="widget-reset-layout"
        className="px-3 py-1.5 rounded text-sm font-medium bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600 transition-colors"
        onClick={resetLayout}
        title={t("app_reset_layout")}
      >
        ↺
      </button>
    </div>
  );
}

/* ---------- Modal Tab 配置 ---------- */

/** 需要以弹窗形式打开的 Tab（独立操作，不需要和 3D 场景交互） */
const MODAL_TABS: TabId[] = ['calibration', 'extractor', 'lut-manager', 'five-color'];

const MODAL_TITLE_KEYS: Record<string, string> = {
  'calibration': 'tab.calibration',
  'extractor': 'tab.extractor',
  'lut-manager': 'tab.lutManager',
  'five-color': 'tab.fiveColor',
};

/* ---------- App Content (inside I18nProvider) ---------- */

function AppContent() {
  const { t } = useI18n();
  useAutoPreview();

  const [connected, setConnected] = useState<boolean | null>(null);
  const [modalTab, setModalTab] = useState<TabId | null>(null);
  const activeTab = useWidgetStore((s) => s.activeTab);
  const setActiveTab = useWidgetStore((s) => s.setActiveTab);

  /** Tab 点击处理：独立操作 Tab 打开弹窗，converter 正常切换 */
  const handleTabChange = (tab: TabId) => {
    if (MODAL_TABS.includes(tab)) {
      setModalTab(tab);
    } else {
      setActiveTab(tab);
    }
  };

  useEffect(() => {
    apiClient
      .get<HealthResponse>("/health")
      .then((res) => setConnected(res.data.status === "ok"))
      .catch(() => setConnected(false));
  }, []);

  return (
    <div className="h-screen bg-gray-100 dark:bg-gray-950 text-gray-900 dark:text-white flex flex-col overflow-hidden">
      <header className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
        <h1 className="text-xl font-semibold tracking-tight">
          {t("app_header_title")}
        </h1>

        <TabNavBar
          activeTab={activeTab}
          modalTab={modalTab}
          onTabChange={handleTabChange}
        />

        <WidgetToggles />

        <div className="flex items-center gap-2">
          <LanguageToggle />
          <ThemeToggle />
          {connected === null ? (
            <span className="text-sm text-gray-500 dark:text-gray-400">{t("app_checking_backend")}</span>
          ) : connected ? (
            <span
              data-testid="health-badge-ok"
              className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-1 text-sm text-green-700 dark:bg-green-900/60 dark:text-green-300"
            >
              <span className="h-2 w-2 rounded-full bg-green-400" />
              {t("app_backend_connected")}
            </span>
          ) : (
            <span
              data-testid="health-badge-fail"
              className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1 text-sm text-red-700 dark:bg-red-900/60 dark:text-red-300"
            >
              <span className="h-2 w-2 rounded-full bg-red-400" />
              {t("app_backend_unreachable")}
            </span>
          )}
        </div>
      </header>

      <main className="flex-1 overflow-hidden">
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
      </main>

      {/* 全屏弹窗：校准 / 提取器 / LUT管理 / 配方查询 */}
      <FullScreenModal
        open={modalTab !== null}
        title={modalTab ? t(MODAL_TITLE_KEYS[modalTab]) : ""}
        onClose={() => setModalTab(null)}
      >
        {modalTab === 'calibration' && <CalibrationPanel />}
        {modalTab === 'extractor' && (
          <div className="flex h-full">
            <ExtractorPanel />
            <div className="flex-1 relative">
              <ExtractorCanvas />
            </div>
          </div>
        )}
        {modalTab === 'lut-manager' && <LutManagerPanel />}
        {modalTab === 'five-color' && <FiveColorQueryPanel />}
      </FullScreenModal>
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
