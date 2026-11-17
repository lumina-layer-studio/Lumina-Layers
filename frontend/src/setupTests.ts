import "@testing-library/jest-dom";
import { vi } from "vitest";
import { translations } from "./i18n/translations";

// Mock useI18n to return Chinese translations in test environment
// so that component text assertions match rendered content.
const mockT = (key: string): string => {
  const entry = translations[key];
  if (!entry) return key;
  return entry["zh"] ?? key;
};

vi.mock("./i18n/context", () => ({
  useI18n: () => ({ t: mockT, lang: "zh" as const }),
  I18nProvider: ({ children }: { children?: React.ReactNode }) => children,
}));

// jsdom has no layout scrolling; dropdown keyboard navigation uses this DOM API.
if (typeof HTMLElement.prototype.scrollIntoView !== "function") {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });
}

// Polyfill ResizeObserver for jsdom (used by WidgetWorkspace)
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof globalThis.ResizeObserver;
}

// Mock @react-three/fiber — Canvas renders as a plain div in jsdom
vi.mock("@react-three/fiber", () => ({
  Canvas: ({ children }: { children?: React.ReactNode }) => children,
}));

// Mock @react-three/drei — stub all used components/hooks
vi.mock("@react-three/drei", () => ({
  OrbitControls: () => null,
  Environment: () => null,
  ContactShadows: () => null,
  useGLTF: () => ({
    scene: { position: { set: () => {} } },
    nodes: {},
    materials: {},
  }),
}));


const localStorageMock = (function () {
  let store: Record<string, string> = {};
  return {
    getItem: function (key: string) {
      return store[key] || null;
    },
    setItem: function (key: string, value: string) {
      store[key] = value.toString();
    },
    removeItem: function (key: string) {
      delete store[key];
    },
    clear: function () {
      store = {};
    }
  };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });
// jsdom exposes dialog elements but does not implement their browser methods.
Object.defineProperties(HTMLDialogElement.prototype, {
  showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true; } },
  close: { configurable: true, value(this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event("close")); } },
});
