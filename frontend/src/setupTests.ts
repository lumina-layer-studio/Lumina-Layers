import "@testing-library/jest-dom";
import { vi } from "vitest";

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
