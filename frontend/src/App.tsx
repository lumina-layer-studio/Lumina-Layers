import { useState, useEffect, Suspense, Component } from "react";
import type { ReactNode } from "react";
import apiClient from "./api/client";
import type { HealthResponse } from "./api/types";
import Scene3D from "./components/Scene3D";
import LeftPanel from "./components/LeftPanel";
import CalibrationPanel from "./components/CalibrationPanel";
import ExtractorPanel from "./components/ExtractorPanel";
import ExtractorCanvas from "./components/ExtractorCanvas";
import LutManagerPanel from "./components/LutManagerPanel";
import AboutView from "./components/AboutView";
import FiveColorQueryPanel from "./components/FiveColorQueryPanel";
import LoadingSpinner from "./components/LoadingSpinner";
import { useActiveModelUrl } from "./hooks/useActiveModelUrl";
import { I18nProvider } from "./i18n/context";
import { LanguageToggle } from "./components/LanguageToggle";
import { ThemeToggle } from "./components/ThemeToggle";

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

/* ---------- App ---------- */

function App() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [activeTab, setActiveTab] = useState<"converter" | "calibration" | "extractor" | "lut-manager" | "five-color" | "about">("converter");
  const modelUrl = useActiveModelUrl(activeTab);

  useEffect(() => {
    apiClient
      .get<HealthResponse>("/health")
      .then((res) => setConnected(res.data.status === "ok"))
      .catch(() => setConnected(false));
  }, []);

  return (
    <I18nProvider>
    <div className="min-h-screen bg-gray-100 dark:bg-gray-950 text-gray-900 dark:text-white flex flex-col">
      <header className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
        <h1 className="text-xl font-semibold tracking-tight">
          Lumina Studio 2.0
        </h1>

        <nav className="flex items-center gap-1" role="tablist">
          <button
            role="tab"
            data-testid="tab-converter"
            aria-current={activeTab === "converter" ? "page" : undefined}
            aria-selected={activeTab === "converter"}
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
              activeTab === "converter"
                ? "bg-blue-600 text-white"
                : "bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
            }`}
            onClick={() => setActiveTab("converter")}
          >
            Converter
          </button>
          <button
            role="tab"
            data-testid="tab-calibration"
            aria-current={activeTab === "calibration" ? "page" : undefined}
            aria-selected={activeTab === "calibration"}
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
              activeTab === "calibration"
                ? "bg-blue-600 text-white"
                : "bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
            }`}
            onClick={() => setActiveTab("calibration")}
          >
            Calibration
          </button>
          <button
            role="tab"
            data-testid="tab-extractor"
            aria-current={activeTab === "extractor" ? "page" : undefined}
            aria-selected={activeTab === "extractor"}
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
              activeTab === "extractor"
                ? "bg-blue-600 text-white"
                : "bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
            }`}
            onClick={() => setActiveTab("extractor")}
          >
            Extractor
          </button>
          <button
            role="tab"
            data-testid="tab-lut-manager"
            aria-current={activeTab === "lut-manager" ? "page" : undefined}
            aria-selected={activeTab === "lut-manager"}
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
              activeTab === "lut-manager"
                ? "bg-blue-600 text-white"
                : "bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
            }`}
            onClick={() => setActiveTab("lut-manager")}
          >
            LUT Manager
          </button>
          <button
            role="tab"
            data-testid="tab-five-color"
            aria-current={activeTab === "five-color" ? "page" : undefined}
            aria-selected={activeTab === "five-color"}
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
              activeTab === "five-color"
                ? "bg-blue-600 text-white"
                : "bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
            }`}
            onClick={() => setActiveTab("five-color")}
          >
            Five-Color
          </button>
          <button
            role="tab"
            data-testid="tab-about"
            aria-current={activeTab === "about" ? "page" : undefined}
            aria-selected={activeTab === "about"}
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
              activeTab === "about"
                ? "bg-blue-600 text-white"
                : "bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
            }`}
            onClick={() => setActiveTab("about")}
          >
            About
          </button>
        </nav>

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

      <main className="flex-1 flex flex-row overflow-hidden">
        {/* Left panel */}
        {activeTab === "converter" ? (
          <LeftPanel />
        ) : activeTab === "calibration" ? (
          <CalibrationPanel />
        ) : activeTab === "lut-manager" ? (
          <LutManagerPanel />
        ) : activeTab === "about" ? (
          <AboutView />
        ) : activeTab === "five-color" ? (
          <FiveColorQueryPanel />
        ) : (
          <ExtractorPanel />
        )}

        {/* Right area – hidden when About tab is active */}
        {activeTab !== "about" && activeTab !== "five-color" && (
        <section data-testid="canvas-area" className="flex-1 relative">
          {activeTab === "extractor" ? (
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
                <Scene3D modelUrl={modelUrl ?? undefined} />
              </Suspense>
            </SceneErrorBoundary>
          )}
        </section>
        )}
      </main>
    </div>
    </I18nProvider>
  );
}

export default App;
