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
        title="Reset Layout"
      >
        ↺
      </button>
    </div>
  );
}

/* ---------- App ---------- */

function App() {
  useAutoPreview();

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
    <I18nProvider>
      <div className="h-screen bg-gray-100 dark:bg-gray-950 text-gray-900 dark:text-white flex flex-col overflow-hidden">
        <header className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <h1 className="text-xl font-semibold tracking-tight">
            Lumina Studio 2.0
          </h1>

          <TabNavBar
            activeTab={activeTab}
            onTabChange={setActiveTab}
          />

          <WidgetToggles />

          <div className="flex items-center gap-2">
            <LanguageToggle />
            <ThemeToggle />
            {connected === null ? (
              <span className="text-sm text-gray-500 dark:text-gray-400">Checking backend…</span>
            ) : connected ? (
              <span
                data-testid="health-badge-ok"
                className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-1 text-sm text-green-700 dark:bg-green-900/60 dark:text-green-300"
              >
                <span className="h-2 w-2 rounded-full bg-green-400" />
                Backend Connected
              </span>
            ) : (
              <span
                data-testid="health-badge-fail"
                className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1 text-sm text-red-700 dark:bg-red-900/60 dark:text-red-300"
              >
                <span className="h-2 w-2 rounded-full bg-red-400" />
                Backend Unreachable
              </span>
            )}
          </div>
        </header>

        <main className="flex-1 overflow-hidden">
          <WidgetWorkspace>
            {activeTab === 'extractor' ? (
              <ExtractorCanvas />
            ) : (
              <SceneErrorBoundary
                fallback={
                  <div className="absolute inset-0 flex items-center justify-center bg-gray-100 dark:bg-gray-950">
                    <p className="text-red-400 text-sm">3D 场景加载失败</p>
                  </div>
                }
              >
                <Suspense fallback={<LoadingSpinner />}>
                  <Scene3D />
                </Suspense>
              </SceneErrorBoundary>
            )}
          </WidgetWorkspace>
        </main>
      </div>
    </I18nProvider>
  );
}

export default App;
