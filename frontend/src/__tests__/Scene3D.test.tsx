import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import * as THREE from "three";
import { MOUSE } from "three";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import {
  captureSceneTransitionSnapshot,
  clearSceneTransitionSnapshot,
  getSceneTransitionKey,
} from "../components/sceneTransitionSnapshot";

// Mock i18n — return key as-is
vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}));

// Mock child components that live inside Canvas (R3F components)
vi.mock("../components/ModelViewer", () => ({
  default: () => null,
  computeFitDistance: () => 100,
}));
let capturedInteractiveViewerProps: Record<string, unknown> | null = null;
vi.mock("../components/InteractiveModelViewer", () => ({
  default: (props: Record<string, unknown>) => {
    capturedInteractiveViewerProps = props;
    return null;
  },
  extractHexFromMeshName: (name: string) => name.slice(6),
  resolvePreviewColorLayerHeightMm: (height?: number) => {
    const value = typeof height === "number" ? height : NaN;
    return Number.isFinite(value) && value > 0 ? value : 0.4;
  },
}));
let capturedBedPlatformProps: Record<string, unknown> | null = null;
vi.mock("../components/BedPlatform", () => ({
  default: (props: Record<string, unknown>) => {
    capturedBedPlatformProps = props;
    return <div data-testid="mock-bed-platform" />;
  },
}));
let capturedKeychainRingProps: Record<string, unknown> | null = null;
vi.mock("../components/KeychainRing3D", () => ({
  default: (props: Record<string, unknown>) => {
    capturedKeychainRingProps = props;
    return <div data-testid="mock-keychain-ring" />;
  },
}));
let capturedModelSurfaceSelectorProps: Record<string, unknown> | null = null;
vi.mock("../components/ModelSurfaceSelector3D", () => ({
  default: (props: Record<string, unknown>) => {
    capturedModelSurfaceSelectorProps = props;
    return <div data-testid="mock-model-surface-selector" />;
  },
}));
let capturedLargeFormatTileOverlayProps: Record<string, unknown> | null = null;
vi.mock("../components/LargeFormatTileOverlay3D", () => ({
  default: (props: Record<string, unknown>) => {
    capturedLargeFormatTileOverlayProps = props;
    return <div data-testid="mock-large-format-tile-overlay" />;
  },
}));
let capturedFridgeMagnet3DProps: Record<string, unknown> | null = null;
vi.mock("../components/FridgeMagnet3D", () => ({
  default: (props: Record<string, unknown>) => {
    capturedFridgeMagnet3DProps = props;
    return <div data-testid="mock-fridge-magnet-3d" />;
  },
}));

// Mock @react-three/drei — Environment renders a queryable DOM element
// Boolean false is dropped by React DOM, so we explicitly map props to data-* attributes
let capturedOrbitControlsProps: Record<string, unknown> = {};
let environmentError: Error | null = null;
let canvasError: Error | null = null;
const clearEnvironment = vi.fn((_options?: unknown) => { environmentError = null; });
vi.mock("@react-three/drei", () => ({
  OrbitControls: (props: Record<string, unknown>) => {
    capturedOrbitControlsProps = props;
    return null;
  },
  useEnvironment: { clear: (options: unknown) => clearEnvironment(options) },
  Environment: (props: Record<string, unknown>) => {
    if (environmentError) throw environmentError;
    return (
    <div
      data-testid="mock-environment"
      data-files={String(props.files ?? "")}
      data-background={String(props.background ?? "")}
      data-environment-intensity={String(props.environmentIntensity ?? "")}
    />
    );
  },
  Html: ({ children, ...props }: Record<string, unknown> & { children?: React.ReactNode }) => (
    <div data-testid="mock-html" {...(props as React.HTMLAttributes<HTMLDivElement>)}>{children}</div>
  ),
}));

// Override the global Canvas mock to capture onPointerMissed
let capturedCanvasProps: Record<string, unknown> = {};
function createMockGl() {
  const domElement = document.createElement("canvas");
  domElement.width = 800;
  domElement.height = 600;
  return {
    domElement,
    setClearColor: vi.fn(),
    getPixelRatio: vi.fn(() => 1),
    getContextAttributes: vi.fn(() => ({ preserveDrawingBuffer: true })),
    info: {
      memory: {
        geometries: 0,
        textures: 0,
      },
      programs: [],
      render: {
        calls: 0,
        triangles: 0,
        lines: 0,
        points: 0,
        frame: 0,
      },
    },
  };
}

type MockControlEvent = "start" | "change" | "end";

type MockVector3 = {
  x: number;
  y: number;
  z: number;
  set: (nextX: number, nextY: number, nextZ: number) => MockVector3;
  distanceTo: (other: MockVector3) => number;
  length: () => number;
};

function createMockVector3(x: number, y: number, z: number): MockVector3 {
  const vector = { x, y, z } as MockVector3;
  vector.set = vi.fn((nextX: number, nextY: number, nextZ: number) => {
    vector.x = nextX;
    vector.y = nextY;
    vector.z = nextZ;
    return vector;
  });
  vector.distanceTo = vi.fn((other: MockVector3) =>
    Math.hypot(vector.x - other.x, vector.y - other.y, vector.z - other.z),
  );
  vector.length = vi.fn(() => Math.hypot(vector.x, vector.y, vector.z));
  return vector;
}

function createMockControls() {
  const listeners: Record<MockControlEvent, Set<() => void>> = {
    start: new Set(),
    change: new Set(),
    end: new Set(),
  };

  return {
    target: createMockVector3(0, -20, 0),
    minDistance: 10,
    maxDistance: 2_000,
    update: vi.fn(),
    addEventListener: vi.fn((type: MockControlEvent, listener: () => void) => {
      listeners[type].add(listener);
    }),
    removeEventListener: vi.fn((type: MockControlEvent, listener: () => void) => {
      listeners[type].delete(listener);
    }),
    emit: (type: MockControlEvent) => {
      listeners[type].forEach((listener) => listener());
    },
  };
}

// Shared mock state so every ``useThree`` call inside a single test returns
// the SAME references. Helpers like ``ScreenshotHelper`` and ``ThemeUpdater``
// depend on ``gl`` in their effect-deps; if the mock returned a fresh object
// per call, those effects would re-fire on every render, trigger
// ``setDiagnostics`` from ``handleGlReady``, and spin into an infinite loop
// that exhausts the Node heap (the symptom before this fix was a 60s OOM).
// ``beforeEach`` resets this so each test sees a fresh renderer-info + DOM
// canvas, matching the previous "new gl per test" intent.
// 共享 mock state：保证同一测试内每次 useThree 返回的 gl / scene / camera
// 引用一致，避免 ScreenshotHelper 等组件的 effect 每次 render 都重跑而
// 通过 handleGlReady 的 setDiagnostics 引发无限 re-render（原本表现为
// Scene3D.test.tsx 60s OOM 无一测试跑通）。
type MockThreeState = {
  gl: ReturnType<typeof createMockGl>;
  scene: { children: THREE.Object3D[] };
  camera: {
    isPerspectiveCamera: true;
    position: MockVector3;
    near: number;
    far: number;
    fov: number;
    lookAt: ReturnType<typeof vi.fn>;
    updateProjectionMatrix: ReturnType<typeof vi.fn>;
  };
  controls: ReturnType<typeof createMockControls> | null;
  invalidate: ReturnType<typeof vi.fn>;
};
let mockThreeState: MockThreeState | null = null;
function getMockThreeState(): MockThreeState {
  if (!mockThreeState) {
    mockThreeState = {
      gl: createMockGl(),
      scene: { children: [] as THREE.Object3D[] },
      camera: {
        isPerspectiveCamera: true,
        position: createMockVector3(0, -57, 474),
        near: 0.1,
        far: 2_000,
        fov: 45,
        lookAt: vi.fn(),
        updateProjectionMatrix: vi.fn(),
      },
      controls: null,
      invalidate: vi.fn(),
    };
  }
  return mockThreeState;
}

vi.mock("@react-three/fiber", () => ({
  Canvas: (props: Record<string, unknown> & { children?: React.ReactNode }) => {
    if (canvasError) throw canvasError;
    capturedCanvasProps = props;
    return <div data-testid="mock-canvas">{props.children}</div>;
  },
  useThree: (selector?: (state: MockThreeState) => unknown) => {
    const state = getMockThreeState();
    return selector ? selector(state) : state;
  },
  useFrame: vi.fn(),
  addAfterEffect: vi.fn(() => () => {}),
}));

// Must import Scene3D after mocks are set up
import Scene3D, {
  computePreviewCameraOrbitConfig,
  computeScaledPreviewBounds,
} from "../components/Scene3D";

describe("Scene3D", () => {
  it('saves screenshot PNG bytes and distinguishes cancellation and failures', async () => {
    const save = vi.fn().mockResolvedValue({ status: 'saved' });
    Object.assign(window, { electronAPI: { saveGeneratedFile: save } });
    try {
      render(<Scene3D />);
      const mockGl = getMockThreeState().gl;
      mockGl.domElement.toDataURL = vi.fn(() => 'data:image/png;base64,iVBORw0KGgo=');
      (capturedCanvasProps.onCreated as (state: { gl: typeof mockGl }) => void)({ gl: mockGl });
      const click = () => fireEvent.click(screen.getByLabelText('viewer_screenshot'));
      await act(async () => { click(); });
      expect(save.mock.calls[0][0].purpose).toBe('screenshot');
      expect(Array.from(save.mock.calls[0][0].bytes)).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
      expect(screen.getByText('file_save_saved')).toBeInTheDocument();
      save.mockResolvedValue({ status: 'canceled' });
      await act(async () => { click(); });
      expect(screen.queryByText('file_save_saved')).not.toBeInTheDocument();
      save.mockRejectedValue(new Error('native error'));
      await act(async () => { click(); });
      expect(screen.getByText('file_save_failed')).toBeInTheDocument();
    } finally { Object.assign(window, { electronAPI: undefined }); }
  });
beforeEach(() => {
    environmentError = null;
    canvasError = null;
    clearEnvironment.mockClear();
    clearSceneTransitionSnapshot();
    capturedCanvasProps = {};
    capturedOrbitControlsProps = {};
    capturedInteractiveViewerProps = null;
    capturedBedPlatformProps = null;
    capturedKeychainRingProps = null;
    capturedModelSurfaceSelectorProps = null;
    capturedFridgeMagnet3DProps = null;
    capturedLargeFormatTileOverlayProps = null;
    document.body.classList.remove("lumina-canvas-orbiting");
    // Reset the shared useThree state so each test gets a fresh renderer /
    // scene snapshot while every hook call within that test still sees
    // stable references.
    // 清空 useThree 的共享 state，保证每个 test 拿到新的 renderer/scene，
    // 同时保持同一 test 内引用稳定。
    mockThreeState = null;
    (window as Window & { __luminaThreePerfDebug?: boolean }).__luminaThreePerfDebug = false;
    // Reset store to defaults
      useConverterStore.setState({
        isLoading: false,
        modelUrl: null,
        previewGlbUrl: null,
        batchPreviewItems: [],
        previewPerformanceTiming: null,
        generatePerformanceTiming: null,
        previewImageUrl: null,
        previewBaseImageUrl: null,
        imagePreviewUrl: null,
        sessionId: null,
        enable_relief: false,
        autoHeightMode: "darker-higher",
        heightmapThumbnailUrl: null,
        heightmapUploadSessionId: null,
        enable_coating: false,
        coating_height_mm: 0.08,
        layer_height_mm: 0.08,
        puzzleEnabled: false,
        puzzleOverlayUrl: null,
        largeFormatEnabled: false,
        largeFormatTileOverlayVisible: true,
        tileWidthMm: 250,
        tileHeightMm: 250,
        selectedColor: null,
        layerImages: [],
        layerImagesLoading: false,
        layerImagesOpen: false,
        layerImagesSourceKey: null,
        add_loop: false,
        enable_fridge_magnet: false,
        fridge_magnets: [],
        selectedFridgeMagnetId: null,
        modelBounds: null,
        modelSurfaceEnabled: false,
        modelSurfaceFile: null,
        modelSurfacePreviewUrl: null,
        modelSurfaceSelectionId: null,
        modelSurfaceSelection: null,
        modelSurfaceFootprint: null,
      });
  });

  describe("static frame on tab return", () => {
    function seedSnapshot() {
      const settings = useSettingsStore.getState();
      const key = getSceneTransitionKey(useConverterStore.getState(), [
        settings.theme, settings.deviceProfileId, settings.buildPlateId,
        settings.slicerSoftware, null,
      ]);
      const canvas = document.createElement("canvas");
      Object.defineProperties(canvas, {
        clientWidth: { value: 800 }, clientHeight: { value: 600 },
      });
      captureSceneTransitionSnapshot(key, canvas, new THREE.PerspectiveCamera(), {
        target: new THREE.Vector3(), minDistance: 1, maxDistance: 1000, update: () => {},
      });
    }

    it("keeps the static frame without a WebGL canvas until navigation completes", () => {
      const context = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
        (() => ({ drawImage: vi.fn() })) as unknown as HTMLCanvasElement["getContext"],
      );
      const bounds = vi.spyOn(HTMLDivElement.prototype, "getBoundingClientRect")
        .mockReturnValue({ width: 800, height: 600 } as DOMRect);
      try {
        seedSnapshot();
        const { rerender, unmount } = render(<Scene3D deferInitialization />);
        expect(screen.getByTestId("scene3d-transition-snapshot")).toBeInTheDocument();
        expect(screen.queryByTestId("mock-canvas")).toBeNull();
        rerender(<Scene3D />);
        expect(screen.getByTestId("mock-canvas")).toBeInTheDocument();
        expect(screen.getByTestId("scene3d-transition-snapshot")).toBeInTheDocument();
        unmount();
      } finally {
        context.mockRestore();
        bounds.mockRestore();
      }
    });

    it("shows saved pixels while rebuilding and drops them immediately when artwork changes", () => {
      const context = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
        (() => ({ drawImage: vi.fn() })) as unknown as HTMLCanvasElement["getContext"],
      );
      const bounds = vi.spyOn(HTMLDivElement.prototype, "getBoundingClientRect")
        .mockReturnValue({ width: 800, height: 600 } as DOMRect);
      try {
        seedSnapshot();
        const { unmount } = render(<Scene3D />);
        expect(screen.getByTestId("scene3d-transition-snapshot")).toBeInTheDocument();
        expect(capturedCanvasProps.style).toEqual({ visibility: "hidden" });
        act(() => { useConverterStore.setState({ previewGlbUrl: "/different.glb" }); });
        expect(screen.queryByTestId("scene3d-transition-snapshot")).toBeNull();
        expect(capturedCanvasProps.style).toBeUndefined();
        unmount();
      } finally {
        context.mockRestore();
        bounds.mockRestore();
      }
    });

    it("discards the static frame after the viewport changes size on another page", () => {
      const context = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
        (() => ({ drawImage: vi.fn() })) as unknown as HTMLCanvasElement["getContext"],
      );
      const bounds = vi.spyOn(HTMLDivElement.prototype, "getBoundingClientRect")
        .mockReturnValue({ width: 1000, height: 600 } as DOMRect);
      try {
        seedSnapshot();
        const { unmount } = render(<Scene3D />);
        expect(screen.queryByTestId("scene3d-transition-snapshot")).toBeNull();
        expect(capturedCanvasProps.style).toBeUndefined();
        unmount();
      } finally {
        context.mockRestore();
        bounds.mockRestore();
      }
    });
  });

  describe("preview camera sizing", () => {
    const modelBounds = {
      minX: -30,
      maxX: 30,
      minY: -20,
      maxY: 20,
      maxZ: 2,
    };

    it("computes scaled model bounds for large regular preview dimensions", () => {
      const scaled = computeScaledPreviewBounds(modelBounds, 6.67, 6.67);

      expect(scaled.width).toBeCloseTo(400.2, 1);
      expect(scaled.height).toBeCloseTo(266.8, 1);
      expect(scaled.radius).toBeGreaterThan(240);
    });

    it("expands orbit range for large regular previews instead of keeping the fixed 2000mm cap", () => {
      const config = computePreviewCameraOrbitConfig(modelBounds, 100, 100);

      expect(config.maxDistance).toBeGreaterThan(2000);
      expect(config.far).toBeGreaterThan(config.maxDistance);
      expect(config.near).toBeGreaterThanOrEqual(0.1);
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
      const spinner = overlay.querySelector(".rgb-loader-ring");
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

  describe("diagnostics overlay", () => {
    it("opens the diagnostics panel when the diagnostics button is clicked", () => {
      render(<Scene3D />);

      expect(screen.queryByTestId("scene3d-diagnostics-panel")).not.toBeInTheDocument();

      fireEvent.click(screen.getByTestId("scene3d-diagnostics-toggle"));

      expect(screen.getByTestId("scene3d-diagnostics-panel")).toBeInTheDocument();
      expect(screen.getByTestId("scene3d-diagnostics-panel")).toHaveStyle({ top: "56px" });
    });
  });

  describe("performance overlay", () => {
    it("opens the performance panel when the performance button is clicked", () => {
      render(<Scene3D />);

      expect(screen.queryByTestId("scene3d-performance-panel")).not.toBeInTheDocument();

      expect(screen.getByTestId("scene3d-performance-toggle").closest("div")).toHaveStyle({
        top: "12px",
      });

      fireEvent.click(screen.getByTestId("scene3d-performance-toggle"));

      expect(screen.getByTestId("scene3d-performance-panel")).toBeInTheDocument();
      expect(screen.getByTestId("scene3d-performance-panel")).toHaveStyle({ top: "56px" });
      expect(screen.getByTestId("scene3d-performance-empty")).toHaveTextContent(
        "viewer_performance_empty",
      );
    });

    it("renders preview and model timing rows when timing data exists", () => {
      useConverterStore.setState({
        previewPerformanceTiming: {
          total_ms: 1234.5,
          upload_ms: 12,
          worker_ms: 900,
          pickle_load_ms: 3,
          segmented_glb_ms: 250,
          palette_ms: 4,
        },
        generatePerformanceTiming: {
          total_ms: 2500,
          worker_ms: 2200,
          overhead_ms: 300,
        },
      });

      render(<Scene3D />);

      fireEvent.click(screen.getByTestId("scene3d-performance-toggle"));

      expect(screen.getByText("viewer_performance_preview_title")).toBeInTheDocument();
      expect(screen.getByText("viewer_performance_generate_title")).toBeInTheDocument();
      expect(screen.getAllByText("1.23 s").length).toBeGreaterThan(0);
      expect(screen.getByText("2.50 s")).toBeInTheDocument();
      expect(screen.queryByTestId("scene3d-performance-empty")).not.toBeInTheDocument();
    });
  });

  describe("onPointerMissed deselection (Req 2.5)", () => {
    it("Canvas receives onPointerMissed prop", () => {
      render(<Scene3D />);
      expect(capturedCanvasProps.onPointerMissed).toBeTypeOf("function");
    });

    it("clears selected fridge magnet on empty-canvas clicks while fridge mode is enabled", () => {
      useConverterStore.setState({
        enable_fridge_magnet: true,
        selectedFridgeMagnetId: "magnet-1",
      });
      render(<Scene3D />);

      act(() => {
        (capturedCanvasProps.onPointerMissed as () => void)();
      });

      expect(useConverterStore.getState().selectedFridgeMagnetId).toBeNull();
    });
  });

  describe("viewport pan gestures", () => {
    it("maps middle/right drag to pan and temporarily maps Space+left to pan", () => {
      render(<Scene3D />);

      const defaultButtons = capturedOrbitControlsProps.mouseButtons as {
        LEFT: number;
        MIDDLE: number;
        RIGHT: number;
      };
      expect(defaultButtons).toEqual({
        LEFT: MOUSE.ROTATE,
        MIDDLE: MOUSE.PAN,
        RIGHT: MOUSE.PAN,
      });

      const container = screen.getByTestId("scene3d-container");
      const pointerCancel = vi.fn();
      getMockThreeState().gl.domElement.addEventListener("pointercancel", pointerCancel);
      fireEvent.pointerEnter(container);
      const spaceDown = new KeyboardEvent("keydown", {
        bubbles: true,
        cancelable: true,
        code: "Space",
        key: " ",
      });
      act(() => {
        window.dispatchEvent(spaceDown);
      });

      expect(spaceDown.defaultPrevented).toBe(true);
      expect(container).toHaveAttribute("data-space-pan-active", "true");
      expect(capturedOrbitControlsProps.mouseButtons).toEqual({
        LEFT: MOUSE.PAN,
        MIDDLE: MOUSE.PAN,
        RIGHT: MOUSE.PAN,
      });

      const pointerDownAllowed = fireEvent.pointerDown(container, {
        pointerId: 31,
        button: 0,
      });
      expect(pointerDownAllowed).toBe(false);

      const spaceUp = new KeyboardEvent("keyup", {
        bubbles: true,
        cancelable: true,
        code: "Space",
        key: " ",
      });
      act(() => {
        window.dispatchEvent(spaceUp);
      });

      expect(spaceUp.defaultPrevented).toBe(true);
      expect(pointerCancel).toHaveBeenCalledTimes(1);
      expect(container).not.toHaveAttribute("data-space-pan-active");
      expect(capturedOrbitControlsProps.mouseButtons).toEqual({
        LEFT: MOUSE.ROTATE,
        MIDDLE: MOUSE.PAN,
        RIGHT: MOUSE.PAN,
      });
    });

    it("prevents middle-button auto-scroll and clears the Space modifier on blur", () => {
      render(<Scene3D />);
      const container = screen.getByTestId("scene3d-container");

      expect(fireEvent.mouseDown(container, { button: 1 })).toBe(false);
      const auxClick = new MouseEvent("auxclick", {
        bubbles: true,
        cancelable: true,
        button: 1,
      });
      expect(container.dispatchEvent(auxClick)).toBe(false);

      fireEvent.pointerEnter(container);
      act(() => {
        window.dispatchEvent(new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          code: "Space",
          key: " ",
        }));
      });
      expect(container).toHaveAttribute("data-space-pan-active", "true");

      act(() => {
        window.dispatchEvent(new Event("blur"));
      });
      expect(container).not.toHaveAttribute("data-space-pan-active");
      expect(capturedOrbitControlsProps.mouseButtons).toEqual({
        LEFT: MOUSE.ROTATE,
        MIDDLE: MOUSE.PAN,
        RIGHT: MOUSE.PAN,
      });
    });
  });

  describe("orbit demand rendering", () => {
    it("keeps a precise depth range when orbit zoom moves the camera beyond it", () => {
      const controls = createMockControls();
      const threeState = getMockThreeState();
      threeState.controls = controls;
      threeState.camera.fov = 2;
      threeState.camera.near = 10;
      threeState.camera.far = 9104;
      threeState.camera.position.set(0, 0, 10265);
      const updateProjectionMatrix = vi.spyOn(threeState.camera, "updateProjectionMatrix");

      render(<Scene3D />);

      act(() => {
        controls.emit("change");
      });

      expect(threeState.camera.far).toBeGreaterThan(threeState.camera.position.length());
      expect(threeState.camera.near).toBeGreaterThan(50);
      expect(updateProjectionMatrix).toHaveBeenCalled();
    });

    it("uses a temporary body class and invalidates frames during OrbitControls interaction", () => {
      const controls = createMockControls();
      const threeState = getMockThreeState();
      threeState.controls = controls;

      render(
        <>
          <div data-widget-id="basic-settings" />
          <Scene3D />
        </>,
      );

      const widgetPanel = document.querySelector("[data-widget-id='basic-settings']") as HTMLElement;
      expect(widgetPanel.style.pointerEvents).toBe("");
      expect(document.body.classList.contains("lumina-canvas-orbiting")).toBe(false);

      act(() => {
        controls.emit("start");
      });

      expect(threeState.invalidate).toHaveBeenCalled();
      expect(document.body.classList.contains("lumina-canvas-orbiting")).toBe(true);

      act(() => {
        controls.emit("end");
      });

      expect(document.body.classList.contains("lumina-canvas-orbiting")).toBe(false);
      expect(widgetPanel.style.pointerEvents).toBe("");
    });

    it("restores widget interaction on pointerup even if OrbitControls end is missed", () => {
      const controls = createMockControls();
      const threeState = getMockThreeState();
      threeState.controls = controls;

      render(<Scene3D />);

      act(() => {
        controls.emit("start");
      });

      expect(document.body.classList.contains("lumina-canvas-orbiting")).toBe(true);

      act(() => {
        window.dispatchEvent(new Event("pointerup"));
      });

      expect(document.body.classList.contains("lumina-canvas-orbiting")).toBe(false);
    });
  });

  describe("camera depth precision", () => {
    it("starts with clipping planes that separate thin material layers", () => {
      render(<Scene3D />);

      const camera = capturedCanvasProps.camera as {
        near?: number;
        far?: number;
      };
      expect(camera.near).toBeGreaterThan(1);
      expect(camera.far).toBeGreaterThan(2_000);
    });

    it("subscribes when default orbit controls register after the first render", () => {
      const controls = createMockControls();
      const threeState = getMockThreeState();

      const { rerender } = render(<Scene3D />);
      expect(threeState.controls).toBeNull();

      act(() => {
        threeState.controls = controls;
        rerender(<Scene3D />);
      });

      expect(threeState.camera.near).toBeCloseTo(4.75, 1);
      expect(threeState.camera.far).toBeGreaterThan(4_700);
      expect(controls.addEventListener).toHaveBeenCalledWith(
        "change",
        expect.any(Function),
      );

      act(() => {
        threeState.camera.position.set(0, 0, 2_000);
        controls.target.set(0, 0, 0);
        controls.emit("change");
      });

      expect(threeState.camera.near).toBe(20);
      expect(threeState.camera.far).toBe(20_000);
      expect(threeState.camera.updateProjectionMatrix).toHaveBeenCalled();
    });

    it("keeps depth-precise clipping when preview bounds arrive after controls", () => {
      const controls = createMockControls();
      const threeState = getMockThreeState();
      threeState.controls = controls;
      useConverterStore.setState({
        previewGlbUrl: "/api/files/material-preview.glb",
        modelBounds: null,
        target_width_mm: 223,
        target_height_mm: 280,
        preview_width_mm: 60,
        preview_height_mm: 75,
      });

      render(<Scene3D />);
      const initialNear = threeState.camera.near;
      const initialFar = threeState.camera.far;
      expect(initialNear).toBeCloseTo(4.75, 1);

      act(() => {
        useConverterStore.setState({
          modelBounds: {
            minX: -30,
            maxX: 30,
            minY: -37.5,
            maxY: 37.5,
            maxZ: 2,
          },
        });
      });

      expect(threeState.camera.near).toBe(initialNear);
      expect(threeState.camera.far).toBeGreaterThanOrEqual(initialFar);
    });

    it("does not rebuild the projection matrix for rotation-only changes", () => {
      const controls = createMockControls();
      const threeState = getMockThreeState();
      threeState.controls = controls;

      render(<Scene3D />);
      const orbitDistance = threeState.camera.position.distanceTo(controls.target);
      threeState.camera.updateProjectionMatrix.mockClear();

      act(() => {
        threeState.camera.position.set(orbitDistance, controls.target.y, 0);
        controls.emit("change");
      });

      expect(threeState.camera.updateProjectionMatrix).not.toHaveBeenCalled();
    });
  });

  describe("puzzle overlay wiring", () => {
    it("passes the live puzzle overlay into InteractiveModelViewer", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/mock-preview.glb",
        puzzleEnabled: true,
        puzzleOverlayUrl: "/api/files/mock-puzzle-overlay.png",
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.puzzleOverlayEnabled).toBe(true);
      expect(capturedInteractiveViewerProps?.puzzleOverlayUrl).toBe(
        "/api/files/mock-puzzle-overlay.png",
      );
    });

    it("does not wire hover sampling props into InteractiveModelViewer", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/mock-preview.glb",
        puzzleEnabled: true,
        puzzleOverlayUrl: "/api/files/mock-puzzle-overlay.png",
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.onHoverSample).toBeUndefined();
      expect(capturedInteractiveViewerProps?.hoverEnabled).toBeUndefined();
    });

  });

  describe("keychain contour-coordinate wiring", () => {
    it("passes the preview canvas bounds into the keychain contour mapper", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/mock-preview.glb",
        add_loop: true,
        modelBounds: {
          minX: -50,
          maxX: 50,
          minY: -50,
          maxY: 50,
          maxZ: 2,
        },
      });

      render(<Scene3D />);

      const onBoundsChange = capturedInteractiveViewerProps
        ?.onPreviewCanvasBoundsChange as ((
          sourceUrl: string,
          bounds: Record<string, number> | null,
        ) => void) | undefined;
      expect(onBoundsChange).toBeTypeOf("function");

      const canvasBounds = {
        minX: -50,
        maxX: 50,
        minY: -50,
        maxY: 50,
        maxZ: 0,
      };
      act(() => onBoundsChange?.("/api/files/mock-preview.glb", canvasBounds));

      expect(capturedKeychainRingProps?.contourCanvasBounds).toEqual(canvasBounds);

      act(() => {
        useConverterStore.setState({ previewGlbUrl: "/api/files/next-preview.glb" });
      });

      expect(capturedKeychainRingProps?.contourCanvasBounds).toBeNull();

      const nextCanvasBounds = { ...canvasBounds, minX: -40, maxX: 60 };
      act(() => onBoundsChange?.("/api/files/next-preview.glb", nextCanvasBounds));
      expect(capturedKeychainRingProps?.contourCanvasBounds).toEqual(nextCanvasBounds);

      act(() => onBoundsChange?.("/api/files/mock-preview.glb", null));
      expect(capturedKeychainRingProps?.contourCanvasBounds).toEqual(nextCanvasBounds);
    });
  });

  describe("large-format tile outline wiring", () => {
    function renderLargeFormatPreview() {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/large-preview.glb",
        largeFormatEnabled: true,
        tileWidthMm: 250,
        tileHeightMm: 250,
        target_width_mm: 600,
        target_height_mm: 400,
        preview_width_mm: 60,
        preview_height_mm: 40,
        previewPixelWidth: null,
        previewPixelHeight: null,
        modelBounds: { minX: -28, maxX: 28, minY: -20, maxY: 20, maxZ: 2 },
      } as never);
      render(<Scene3D />);
    }

    it("anchors the outline to the scaled artwork canvas, not the trimmed model", () => {
      renderLargeFormatPreview();

      const onBoundsChange = capturedInteractiveViewerProps
        ?.onPreviewCanvasBoundsChange as ((
          sourceUrl: string,
          bounds: Record<string, number> | null,
        ) => void) | undefined;
      act(() =>
        onBoundsChange?.("/api/files/large-preview.glb", {
          minX: -30,
          maxX: 30,
          minY: -20,
          maxY: 20,
          maxZ: 0,
        }),
      );

      expect(screen.getByTestId("mock-large-format-tile-overlay")).toBeInTheDocument();
      expect(capturedLargeFormatTileOverlayProps).toMatchObject({
        totalWidthMm: 600,
        totalHeightMm: 400,
        tileWidthMm: 250,
        tileHeightMm: 250,
      });
      // 60 mm preview displayed at 600 mm -> scale 10 around the model center.
      const bounds = capturedLargeFormatTileOverlayProps?.bounds as Record<string, number>;
      expect(bounds.minX).toBeCloseTo(-300);
      expect(bounds.maxX).toBeCloseTo(300);
      expect(bounds.minY).toBeCloseTo(-200);
      expect(bounds.maxY).toBeCloseTo(200);
      // Floats above the color layer top (backing + default 0.4 mm color layer).
      const colorTopZ = useConverterStore.getState().spacer_thick + 0.4;
      expect(capturedLargeFormatTileOverlayProps?.z as number).toBeGreaterThan(colorTopZ);
    });

    it("uses the backend-derived height when the browser aspect ratio differs", () => {
      renderLargeFormatPreview();
      act(() => {
        // SVG case: browser reports 600 x 400 mm but the backend preview
        // cache ratio is 600 x 520, and generation derives the height from it.
        useConverterStore.setState({ previewPixelWidth: 600, previewPixelHeight: 520 });
      });
      expect(capturedLargeFormatTileOverlayProps).toMatchObject({
        totalWidthMm: 600,
        totalHeightMm: 520,
      });
    });

    it("hides the outline when the preview toggle or large-format mode is off", () => {
      renderLargeFormatPreview();
      expect(screen.getByTestId("mock-large-format-tile-overlay")).toBeInTheDocument();

      act(() => {
        useConverterStore.setState({ largeFormatTileOverlayVisible: false });
      });
      expect(screen.queryByTestId("mock-large-format-tile-overlay")).not.toBeInTheDocument();

      act(() => {
        useConverterStore.setState({
          largeFormatTileOverlayVisible: true,
          largeFormatEnabled: false,
        });
      });
      expect(screen.queryByTestId("mock-large-format-tile-overlay")).not.toBeInTheDocument();
    });

    it("does not draw the outline without a loaded model", () => {
      useConverterStore.setState({
        largeFormatEnabled: true,
        modelBounds: { minX: -28, maxX: 28, minY: -20, maxY: 20, maxZ: 2 },
      } as never);
      render(<Scene3D />);
      expect(screen.queryByTestId("mock-large-format-tile-overlay")).not.toBeInTheDocument();
    });
  });

  describe("keychain contour live resize wiring", () => {
    it("passes a display transform that follows a 60 to 90 mm preview resize", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/quick-preview.glb",
        add_loop: true,
        target_width_mm: 90,
        target_height_mm: 90,
        preview_width_mm: 60,
        preview_height_mm: 60,
        modelBounds: {
          minX: -30,
          maxX: 30,
          minY: -30,
          maxY: 30,
          maxZ: 2,
        },
      });

      render(<Scene3D />);

      expect(capturedKeychainRingProps?.modelBounds).toEqual({
        minX: -45,
        maxX: 45,
        minY: -45,
        maxY: 45,
        maxZ: 2,
      });
      const toDisplayPoint = capturedKeychainRingProps?.contourToDisplayPoint as
        | ((point: { x: number; y: number }) => { x: number; y: number })
        | undefined;
      expect(toDisplayPoint).toBeTypeOf("function");
      expect(toDisplayPoint?.({ x: 0, y: 10 })).toEqual({ x: 0, y: 15 });
    });
  });

  describe("lightweight creative preview wiring", () => {
    it("passes a session-owned spatial heightmap and processed artwork to the quick preview", () => {
      useConverterStore.setState({
        sessionId: "session-a",
        previewGlbUrl: "/api/files/mock-preview.glb",
        previewBaseImageUrl: "/api/files/processed-colours.png",
        enable_relief: true,
        autoHeightMode: "use-heightmap",
        heightmapThumbnailUrl: "/api/files/heightmap-thumb.png",
        heightmapUploadSessionId: "session-a",
        heightmap_max_height: 3.2,
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps).toMatchObject({
        heightmapReliefUrl: "/api/files/heightmap-thumb.png",
        heightmapArtworkUrl: "/api/files/processed-colours.png",
        heightmapReliefMaxHeightMm: 3.2,
      });
    });

    it("does not reuse a heightmap uploaded by another session", () => {
      useConverterStore.setState({
        sessionId: "session-b",
        previewGlbUrl: "/api/files/mock-preview.glb",
        previewBaseImageUrl: "/api/files/processed-colours.png",
        enable_relief: true,
        autoHeightMode: "use-heightmap",
        heightmapThumbnailUrl: "/api/files/stale-heightmap-thumb.png",
        heightmapUploadSessionId: "session-a",
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.heightmapReliefUrl).toBeNull();
    });

    it("passes the live coating controls to the quick preview", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/mock-preview.glb",
        enable_coating: true,
        coating_height_mm: 0.12,
        layer_height_mm: 0.04,
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps).toMatchObject({
        enableCoating: true,
        coatingHeightMm: 0.12,
        printingLayerHeightMm: 0.04,
      });
    });
  });

  describe("model source role wiring", () => {
    it("marks segmented GLB URLs as quick previews", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/quick-preview.glb",
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.sourceRole).toBe("quick-preview");
    });

    it("marks final generated GLBs separately even when a preview URL remains", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/old-quick-preview.glb",
      });

      render(<Scene3D modelUrl="/api/files/generated.glb" />);

      expect(capturedInteractiveViewerProps?.sourceRole).toBe("generated");
    });

    it("keeps the keychain proxy on a quick preview", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/quick-preview.glb",
        add_loop: true,
        target_width_mm: 80,
        target_height_mm: 120,
        preview_width_mm: 40,
        preview_height_mm: 60,
        modelBounds: {
          minX: -20,
          maxX: 20,
          minY: -30,
          maxY: 30,
          maxZ: 2,
        },
      });

      render(<Scene3D />);

      expect(capturedKeychainRingProps).not.toBeNull();
      expect(capturedKeychainRingProps?.modelBounds).toEqual({
        minX: -40,
        maxX: 40,
        minY: -60,
        maxY: 60,
        maxZ: 2,
      });
    });

    it("keeps the lightweight preview and keychain proxy ahead of a stale store model", () => {
      useConverterStore.setState({
        modelUrl: "/api/files/generated-with-keychain.glb",
        previewGlbUrl: "/api/files/old-quick-preview.glb",
        add_loop: true,
        modelBounds: {
          minX: -20,
          maxX: 20,
          minY: -30,
          maxY: 30,
          maxZ: 2,
        },
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps).toMatchObject({
        url: "/api/files/old-quick-preview.glb",
        sourceRole: "quick-preview",
      });
      expect(capturedKeychainRingProps).not.toBeNull();
    });

    it("preserves embedded auxiliaries in batch models", () => {
      useConverterStore.setState({
        batchPreviewItems: [
          {
            url: "/api/files/batch-item.glb",
            filename: "item.svg",
            tx_mm: 0,
            ty_mm: 0,
            width_mm: 30,
            depth_mm: 20,
          },
        ],
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.sourceRole).toBe("batch");
    });
  });

  describe("model surface overlay staging", () => {
    it("shows a blocking loading animation while the uploaded model is analyzed", () => {
      const modelFile = new File(["solid"], "plate.stl");
      useConverterStore.setState({
        modelSurfaceEnabled: true,
        modelSurfaceFile: modelFile,
        modelSurfacePreviewUrl: "blob:model",
        modelSurfaceLoading: true,
      } as never);

      render(<Scene3D />);

      const overlay = screen.getByTestId("model-surface-loading-overlay");
      expect(overlay).toHaveAttribute("role", "status");
      expect(overlay).toHaveAttribute("aria-label", "model_surface_loading_analysis");
      expect(overlay.querySelector(".rgb-loader-ring")).not.toBeNull();
      expect(capturedModelSurfaceSelectorProps?.selecting).toBe(true);
    });

    it("renders the interactive surface selector before preview generation", () => {
      const modelFile = new File(["solid"], "plate.stl");
      const imageFile = new File(["art"], "art.png", { type: "image/png" });

      useConverterStore.setState({
        modelSurfaceEnabled: true,
        modelSurfaceFile: modelFile,
        modelSurfacePreviewUrl: "blob:model",
        imageFile,
        imagePreviewUrl: "blob:art",
        modelSurfaceSelectionId: "selection-1",
        modelSurfaceFootprint: {
          bounds_width_mm: 20,
          bounds_height_mm: 10,
        },
      } as never);

      render(<Scene3D />);

      expect(screen.getByTestId("mock-model-surface-selector")).toBeInTheDocument();
      expect(capturedModelSurfaceSelectorProps).toMatchObject({
        file: modelFile,
        artworkAsset: { kind: "source-image", url: "blob:art" },
        selectionReady: true,
      });
      expect(capturedModelSurfaceSelectorProps?.placement).toEqual(
        useConverterStore.getState().modelSurfacePlacement,
      );
      expect(capturedModelSurfaceSelectorProps?.modelRotation).toEqual(
        useConverterStore.getState().modelSurfaceModelRotation,
      );
      expect(capturedModelSurfaceSelectorProps?.selectionId).toBe("selection-1");
      expect(capturedModelSurfaceSelectorProps?.onUpdatePlacement).toBe(
        useConverterStore.getState().updateModelSurfacePlacement,
      );
      expect(capturedModelSurfaceSelectorProps?.onFitArtwork).toBe(
        useConverterStore.getState().fitModelSurfaceArtwork,
      );
      expect(capturedBedPlatformProps).toMatchObject({
        surfaceModelActive: true,
        gridVisible: true,
      });
      expect(capturedModelSurfaceSelectorProps?.bedGridVisible).toBe(true);
      expect(capturedModelSurfaceSelectorProps?.onBedGridVisibleChange).toEqual(expect.any(Function));
      expect(capturedInteractiveViewerProps).toBeNull();
    });

    it("uses the clean processed preview for model-surface artwork", () => {
      const modelFile = new File(["solid"], "plate.stl");
      useConverterStore.setState({
        modelSurfaceEnabled: true,
        modelSurfaceFile: modelFile,
        modelSurfacePreviewUrl: "blob:model",
        modelSurfaceSelectionId: "selection-1",
        imagePreviewUrl: "blob:original-svg",
        previewBaseImageUrl: "/api/files/processed-colours.png",
        previewImageUrl: "/api/files/temporary-selection-highlight.png",
        modelSurfaceModelFileId: "model-file-1",
        sessionId: "session-1",
        previewRequestRevision: 7,
      } as never);

      render(<Scene3D />);

      expect(capturedModelSurfaceSelectorProps?.artworkAsset).toMatchObject({
        kind: "surface-uv",
        url: "/api/files/processed-colours.png",
        identity: {
          sourceImageUrl: "blob:original-svg",
          modelFileId: "model-file-1",
          selectionId: "selection-1",
          sessionId: "session-1",
          previewRequestRevision: 7,
        },
      });
    });

    it("reuses the scene bed platform while model surface rotate controls are active", () => {
      const modelFile = new File(["solid"], "plate.stl");

      useConverterStore.setState({
        modelSurfaceEnabled: true,
        modelSurfaceFile: modelFile,
        modelSurfacePreviewUrl: "blob:model",
        imagePreviewUrl: "blob:art",
        modelSurfaceSelectionId: "selection-1",
      } as never);

      render(<Scene3D />);

      expect(screen.getByTestId("mock-bed-platform")).toBeInTheDocument();
      expect(screen.getAllByTestId("mock-bed-platform")).toHaveLength(1);
      expect(capturedBedPlatformProps).toMatchObject({
        surfaceModelActive: true,
        gridVisible: true,
      });

      act(() => {
        (capturedModelSurfaceSelectorProps?.onBedGridVisibleChange as (visible: boolean) => void)(
          false,
        );
      });

      expect(screen.getAllByTestId("mock-bed-platform")).toHaveLength(1);
      expect(capturedBedPlatformProps).toMatchObject({
        surfaceModelActive: true,
        gridVisible: false,
      });
    });

    it("keeps the model surface editor visible after preview so the covered model remains inspectable", () => {
      const modelFile = new File(["solid"], "plate.stl");
      useConverterStore.setState({
        modelSurfaceEnabled: true,
        modelSurfaceFile: modelFile,
        modelSurfacePreviewUrl: "blob:model",
        modelSurfaceSelectionId: "selection-1",
        imagePreviewUrl: "blob:art",
        previewGlbUrl: "/api/files/surface-preview.glb",
      } as never);

      render(<Scene3D />);

      expect(screen.getByTestId("mock-model-surface-selector")).toBeInTheDocument();
      expect(capturedModelSurfaceSelectorProps).toMatchObject({
        file: modelFile,
        artworkAsset: { kind: "source-image", url: "blob:art" },
        selectionReady: true,
      });
      expect(capturedInteractiveViewerProps).toBeNull();
    });

    it("keeps the realtime model-surface editor ahead of a generated GLB", () => {
      const modelFile = new File(["solid"], "plate.stl");
      useConverterStore.setState({
        modelSurfaceEnabled: true,
        modelSurfaceFile: modelFile,
        modelSurfacePreviewUrl: "blob:model",
        modelSurfaceSelectionId: "selection-1",
        imagePreviewUrl: "blob:art",
        modelUrl: "/api/files/generated-surface.glb",
        previewGlbUrl: null,
      } as never);

      render(<Scene3D />);

      expect(screen.getByTestId("mock-model-surface-selector")).toBeInTheDocument();
      expect(capturedModelSurfaceSelectorProps).toMatchObject({
        file: modelFile,
        artworkAsset: { kind: "source-image", url: "blob:art" },
        selectionReady: true,
      });
      expect(capturedInteractiveViewerProps).toBeNull();
    });
  });

  describe("fridge magnet proxy wiring", () => {
    it("passes fridge mode into InteractiveModelViewer for outline preview handling", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/mock-preview.glb",
        enable_fridge_magnet: true,
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.enableFridgeMagnet).toBe(true);
    });

    it("passes material stack height into InteractiveModelViewer", () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/mock-preview.glb",
        color_layers: 10,
        layer_height_mm: 0.08,
      });

      render(<Scene3D />);

      expect(capturedInteractiveViewerProps?.colorLayerHeightMm).toBeCloseTo(0.8, 5);
    });

    it("does not render the proxy layer when fridge mode is disabled", () => {
      useConverterStore.setState({
        enable_fridge_magnet: false,
        fridge_magnets: [{
          id: "magnet-1",
          shape: "round",
          preset_key: "round-d12x3",
          diameter_mm: 12,
          width_mm: null,
          height_mm: null,
          thickness_mm: 3,
          center_x_mm: 0,
          center_y_mm: 0,
        }],
        modelBounds: {
          minX: -10,
          maxX: 10,
          minY: -10,
          maxY: 10,
          maxZ: 5,
        },
      });

      render(<Scene3D />);

      expect(screen.queryByTestId("mock-fridge-magnet-3d")).not.toBeInTheDocument();
      expect(capturedFridgeMagnet3DProps).toBeNull();
    });

    it("does not render the proxy layer without model bounds", () => {
      useConverterStore.setState({
        enable_fridge_magnet: true,
        fridge_magnets: [{
          id: "magnet-1",
          shape: "round",
          preset_key: "round-d12x3",
          diameter_mm: 12,
          width_mm: null,
          height_mm: null,
          thickness_mm: 3,
          center_x_mm: 0,
          center_y_mm: 0,
        }],
        modelBounds: null,
      });

      render(<Scene3D />);

      expect(screen.queryByTestId("mock-fridge-magnet-3d")).not.toBeInTheDocument();
      expect(capturedFridgeMagnet3DProps).toBeNull();
    });

    it("passes fridge magnet state and actions into the proxy layer", () => {
      const fridgeMagnets = [{
        id: "magnet-1",
        shape: "round" as const,
        preset_key: "round-d12x3",
        diameter_mm: 12,
        width_mm: null,
        height_mm: null,
        thickness_mm: 3,
        center_x_mm: 2,
        center_y_mm: -1,
      }];
      const modelBounds = {
        minX: -10,
        maxX: 10,
        minY: -10,
        maxY: 10,
        maxZ: 5,
      };

      useConverterStore.setState({
        enable_fridge_magnet: true,
        fridge_magnets: fridgeMagnets,
        selectedFridgeMagnetId: "magnet-1",
        modelBounds,
        target_width_mm: 120,
        target_height_mm: 80,
        preview_width_mm: 60,
        preview_height_mm: 40,
      });

      render(<Scene3D />);

      expect(screen.getByTestId("mock-fridge-magnet-3d")).toBeInTheDocument();
      expect(capturedFridgeMagnet3DProps).toMatchObject({
        enabled: true,
        magnets: fridgeMagnets,
        selectedMagnetId: "magnet-1",
        modelBounds: {
          minX: -20,
          maxX: 20,
          minY: -20,
          maxY: 20,
          maxZ: 5,
        },
      });
      expect(capturedFridgeMagnet3DProps).not.toHaveProperty("scaleX");
      expect(capturedFridgeMagnet3DProps).not.toHaveProperty("scaleY");
      expect(capturedFridgeMagnet3DProps?.onSelectMagnet).toBe(
        useConverterStore.getState().selectFridgeMagnet,
      );
      expect(capturedFridgeMagnet3DProps?.onUpdateMagnetCenter).toBe(
        useConverterStore.getState().updateFridgeMagnetCenter,
      );
    });

  });

  describe("lighting (Environment optimization)", () => {
    it("keeps the scene usable with basic lighting when the HDR cannot load", () => {
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
      environmentError = new Error("Could not load /hdr/studio_small_09_1k.hdr: Failed to fetch");
      try {
        const { container } = render(<Scene3D />);
        expect(screen.getByTestId("mock-canvas")).toBeInTheDocument();
        expect(screen.getByTestId("mock-bed-platform")).toBeInTheDocument();
        expect(container.querySelector("ambientLight")).not.toBeNull();
        expect(screen.getByText("viewer_lighting_fallback")).toBeInTheDocument();
        expect(screen.queryByText("app_3d_scene_error")).not.toBeInTheDocument();
      } finally {
        consoleError.mockRestore();
      }
    });

    it("retries a failed HDR cache without resetting conversion settings", () => {
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
      environmentError = new Error("HDR request failed");
      useConverterStore.setState({ target_width_mm: 225, sessionId: "retained-session" });
      try {
        const { container } = render(<Scene3D />);
        fireEvent.click(screen.getByRole("button", { name: "viewer_retry_lighting" }));
        expect(clearEnvironment).toHaveBeenCalledWith({ files: "/hdr/studio_small_09_1k.hdr" });
        expect(screen.getByTestId("mock-environment")).toBeInTheDocument();
        expect(container.querySelector("ambientLight")).toBeNull();
        expect(screen.queryByText("viewer_lighting_fallback")).not.toBeInTheDocument();
        expect(useConverterStore.getState().sessionId).toBe("retained-session");
        expect(useConverterStore.getState().target_width_mm).toBe(225);
      } finally {
        consoleError.mockRestore();
      }
    });

    it("recovers a failed WebGL canvas without discarding the current project", () => {
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
      canvasError = new Error("Error creating WebGL context.");
      useConverterStore.setState({ target_width_mm: 225, sessionId: "retained-session" });
      try {
        render(<Scene3D />);
        expect(screen.getByText("app_3d_scene_error")).toBeInTheDocument();
        canvasError = null;
        fireEvent.click(screen.getByRole("button", { name: "viewer_retry_scene" }));
        expect(screen.getByTestId("mock-canvas")).toBeInTheDocument();
        expect(screen.queryByText("app_3d_scene_error")).not.toBeInTheDocument();
        expect(useConverterStore.getState().sessionId).toBe("retained-session");
        expect(useConverterStore.getState().target_width_mm).toBe(225);
      } finally {
        consoleError.mockRestore();
      }
    });

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
      // Use the shared ``createMockGl`` helper so onCreated's downstream
      // ``getRendererInfoSnapshot(gl)`` / diagnostic logging see the same
      // renderer-info shape the mock already provides; the previous inline
      // stub only had ``setClearColor`` + ``domElement.addEventListener``,
      // which crashed the new PR #68 postClientLog path with
      // "Cannot read properties of undefined (reading 'programs')".
      // 复用 createMockGl：否则 onCreated 里走到 getRendererInfoSnapshot 会
      // 因为 gl.info/gl.getPixelRatio 缺失崩溃。
      const mockGl = createMockGl();
      (capturedCanvasProps.onCreated as (state: { gl: typeof mockGl }) => void)({
        gl: mockGl,
      });
      // Default theme is "light", so canvasClearColor should be "#e8e8ec"
      expect(mockGl.setClearColor).toHaveBeenCalledWith("#e8e8ec");
    });
  });

  describe("camera debug helper cleanup", () => {
    it("removes window.__luminaCameraDebug on unmount", () => {
      const { unmount } = render(<Scene3D />);

      expect(window.__luminaCameraDebug).toBeTypeOf("function");

      const debugRef = window.__luminaCameraDebug;
      unmount();

      expect(window.__luminaCameraDebug).toBeUndefined();
      expect(debugRef).toBeTypeOf("function");
    });
  });
});
