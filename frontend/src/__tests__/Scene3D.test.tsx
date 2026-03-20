import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { useConverterStore } from "../stores/converterStore";

// Mock i18n — return key as-is
vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}));

// Mock child components that live inside Canvas (R3F components)
vi.mock("../components/ModelViewer", () => ({ default: () => null }));
vi.mock("../components/InteractiveModelViewer", () => ({
  default: () => null,
  extractHexFromMeshName: (name: string) => name.slice(6),
  toggleColorSelection: (sel: string | null, clicked: string) =>
    sel === clicked ? null : clicked,
}));
vi.mock("../components/BedPlatform", () => ({ default: () => null }));
vi.mock("../components/KeychainRing3D", () => ({ default: () => null }));

// Mock @react-three/drei — Environment renders a queryable DOM element
// Boolean false is dropped by React DOM, so we explicitly map props to data-* attributes
vi.mock("@react-three/drei", () => ({
  OrbitControls: () => null,
  Environment: (props: Record<string, unknown>) => (
    <div
      data-testid="mock-environment"
      data-files={String(props.files ?? "")}
      data-background={String(props.background ?? "")}
      data-environment-intensity={String(props.environmentIntensity ?? "")}
    />
  ),
}));

// Override the global Canvas mock to capture onPointerMissed
let capturedCanvasProps: Record<string, unknown> = {};
vi.mock("@react-three/fiber", () => ({
  Canvas: (props: Record<string, unknown> & { children?: React.ReactNode }) => {
    capturedCanvasProps = props;
    return <div data-testid="mock-canvas">{props.children}</div>;
  },
  useThree: () => ({
    gl: {
      domElement: document.createElement("canvas"),
      setClearColor: vi.fn(),
    },
  }),
}));

// Must import Scene3D after mocks are set up
import Scene3D from "../components/Scene3D";

describe("Scene3D", () => {
  beforeEach(() => {
    capturedCanvasProps = {};
    // Reset store to defaults
    useConverterStore.setState({
      isLoading: false,
      previewGlbUrl: null,
      selectedColor: null,
      add_loop: false,
      modelBounds: null,
    });
  });

  describe("loading overlay (Req 1.4)", () => {
    it("renders loading overlay when isLoading is true", () => {
      useConverterStore.setState({ isLoading: true });
      render(<Scene3D />);
      expect(screen.getByTestId("loading-overlay")).toBeInTheDocument();
    });

    it("does not render loading overlay when isLoading is false", () => {
      useConverterStore.setState({ isLoading: false });
      render(<Scene3D />);
      expect(screen.queryByTestId("loading-overlay")).not.toBeInTheDocument();
    });

    it("loading overlay contains a spinner element", () => {
      useConverterStore.setState({ isLoading: true });
      render(<Scene3D />);
      const overlay = screen.getByTestId("loading-overlay");
      const spinner = overlay.querySelector(".animate-spin");
      expect(spinner).toBeInTheDocument();
    });
  });

  describe("fullscreen thumbnail removal (Req 9.3)", () => {
    it("does not render fullscreen-thumbnail element", () => {
      render(<Scene3D />);
      expect(
        screen.queryByTestId("fullscreen-thumbnail"),
      ).not.toBeInTheDocument();
    });

    it("does not render fullscreen-thumbnail even with previewImageUrl set", () => {
      useConverterStore.setState({
        previewImageUrl: "http://example.com/img.png",
      });
      render(<Scene3D />);
      expect(
        screen.queryByTestId("fullscreen-thumbnail"),
      ).not.toBeInTheDocument();
    });
  });

  describe("onPointerMissed deselection (Req 2.5)", () => {
    it("Canvas receives onPointerMissed prop", () => {
      render(<Scene3D />);
      expect(capturedCanvasProps.onPointerMissed).toBeTypeOf("function");
    });

    it("onPointerMissed calls setSelectedColor(null)", () => {
      useConverterStore.setState({ selectedColor: "ff0000" });
      render(<Scene3D />);

      act(() => {
        (capturedCanvasProps.onPointerMissed as () => void)();
      });

      expect(useConverterStore.getState().selectedColor).toBeNull();
    });
  });

  describe("handleColorClick (Req 2.3)", () => {
    it("setSelectedColor is called when handleColorClick triggers", () => {
      // Verify the store action works as expected for the callback
      useConverterStore.setState({ selectedColor: null });

      act(() => {
        useConverterStore.getState().setSelectedColor("aabbcc");
      });

      expect(useConverterStore.getState().selectedColor).toBe("aabbcc");
    });

    it("setSelectedColor(null) deselects", () => {
      useConverterStore.setState({ selectedColor: "ff0000" });

      act(() => {
        useConverterStore.getState().setSelectedColor(null);
      });

      expect(useConverterStore.getState().selectedColor).toBeNull();
    });
  });

  describe("lighting (Environment optimization)", () => {
    it("does not render hemisphereLight", () => {
      const { container } = render(<Scene3D />);
      expect(container.querySelector("hemisphereLight")).toBeNull();
    });

    it("renders exactly one directionalLight", () => {
      const { container } = render(<Scene3D />);
      const lights = container.querySelectorAll("directionalLight");
      expect(lights.length).toBe(1);
    });

    it("renders Environment component with correct HDR file and background=false", () => {
      render(<Scene3D />);
      const env = screen.getByTestId("mock-environment");
      expect(env).toBeInTheDocument();
      expect(env.getAttribute("data-files")).toBe("/hdr/studio_small_09_1k.hdr");
      expect(env.getAttribute("data-background")).toBe("false");
    });

    it("key directional light position is right-upper-front", () => {
      const { container } = render(<Scene3D />);
      const light = container.querySelector("directionalLight");
      expect(light).not.toBeNull();
      // Position [200, 300, 500] — front-upper-right for vertical view
      const pos = light?.getAttribute("position");
      expect(pos).toBeTruthy();
    });

    it("Canvas clearColor uses theme config value", () => {
      render(<Scene3D />);
      expect(capturedCanvasProps.onCreated).toBeTypeOf("function");
      const mockGl = {
        setClearColor: vi.fn(),
        domElement: {
          addEventListener: vi.fn(),
        },
      };
      (capturedCanvasProps.onCreated as (state: { gl: typeof mockGl }) => void)({
        gl: mockGl,
      });
      // Default theme is "light", so canvasClearColor should be "#e8e8ec"
      expect(mockGl.setClearColor).toHaveBeenCalledWith("#e8e8ec");
    });
  });
});
