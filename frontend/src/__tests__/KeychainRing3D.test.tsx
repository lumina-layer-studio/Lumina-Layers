import { StrictMode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import * as THREE from "three";
import {
  default as KeychainRing3D,
  createKeychainRingGeometry,
  computeLoopPosition,
  keychainLoopHoleClearance,
  resetKeychainRingGeometryDisposeForTests,
} from "../components/KeychainRing3D";
import type { KeychainRing3DProps } from "../components/KeychainRing3D";
import KeychainLoopSettings from "../components/sections/KeychainLoopSettings";
import { useConverterStore } from "../stores/converter";
import { createPreviewSpace } from "../utils/previewSpace";

const mockControls = { enabled: true };
const mockCanvas = document.createElement("canvas");
mockCanvas.getBoundingClientRect = () => ({
  x: 0,
  y: 0,
  top: 0,
  left: 0,
  right: 200,
  bottom: 200,
  width: 200,
  height: 200,
  toJSON: () => ({}),
});

const mockCamera = new THREE.OrthographicCamera(-100, 100, 100, -100, 0.1, 1000);
mockCamera.position.set(0, 0, 100);
mockCamera.lookAt(0, 0, 0);
mockCamera.updateProjectionMatrix();
mockCamera.updateMatrixWorld(true);

const mockThreeState = {
  controls: mockControls,
  camera: mockCamera,
  gl: { domElement: mockCanvas },
};

// Mock R3F — Canvas renders as plain div in jsdom
vi.mock("@react-three/fiber", () => ({
  Canvas: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="mock-canvas">{children}</div>
  ),
  useThree: () => mockThreeState,
}));

const defaultBounds = {
  minX: -10,
  maxX: 10,
  minY: -15,
  maxY: 15,
  maxZ: 5,
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  resetKeychainRingGeometryDisposeForTests();
  useConverterStore.setState({ add_loop: false, loop_offset_x: 0, loop_offset_y: 0 });
  mockControls.enabled = true;
  document.body.style.cursor = "default";
});

function getReactProps<T extends object>(element: Element): T {
  const reactPropsKey = Object.keys(element).find((key) => key.startsWith("__reactProps"));
  if (!reactPropsKey) {
    throw new Error("React props were not attached to the element");
  }

  return (element as unknown as Record<string, T>)[reactPropsKey];
}

function LiveRing(props: Partial<KeychainRing3DProps>) {
  const offsetX = useConverterStore((state) => state.loop_offset_x);
  const offsetY = useConverterStore((state) => state.loop_offset_y);
  return (
    <>
      <KeychainLoopSettings />
      <KeychainRing3D
        enabled
        width={4}
        length={8}
        hole={2}
        angle={0}
        positionPreset="top-center"
        modelBounds={defaultBounds}
        {...props}
        offsetX={offsetX}
        offsetY={offsetY}
      />
    </>
  );
}

function startRingDrag(container: HTMLElement, x = 0, y = 0) {
  const ring = container.querySelector("mesh");
  expect(ring).not.toBeNull();
  act(() => {
    getReactProps<{
      onPointerDown: (event: {
        button: number;
        stopPropagation: () => void;
        ray: { intersectPlane: (plane: THREE.Plane, target: THREE.Vector3) => THREE.Vector3 };
      }) => void;
    }>(ring as Element).onPointerDown({
      button: 0,
      stopPropagation: () => {},
      ray: { intersectPlane: (_plane, target) => target.set(x, y, 0) },
    });
  });
}

describe("KeychainRing3D", () => {
  describe("live dragging", () => {
    it("does not notify position subscribers when clamping leaves the offsets unchanged", () => {
      useConverterStore.setState({ loop_offset_x: 200, loop_offset_y: 0 });
      const unchanged = useConverterStore.getState();
      unchanged.setLoopOffsetX(250);
      unchanged.setLoopOffsetY(0);
      expect(useConverterStore.getState()).toBe(unchanged);
    });

    it.each([-0, Number.NaN])("preserves numeric identity and skips repeated offset %s", (offset) => {
      useConverterStore.setState({ loop_offset_x: 0, loop_offset_y: 0 });
      const { setLoopOffsetX, setLoopOffsetY, setLoopOffsets } = useConverterStore.getState();
      setLoopOffsetX(offset);
      expect(Object.is(useConverterStore.getState().loop_offset_x, offset)).toBe(true);
      const afterX = useConverterStore.getState();
      setLoopOffsetX(offset);
      expect(useConverterStore.getState()).toBe(afterX);

      setLoopOffsetY(offset);
      expect(Object.is(useConverterStore.getState().loop_offset_y, offset)).toBe(true);
      const afterY = useConverterStore.getState();
      setLoopOffsetY(offset);
      expect(useConverterStore.getState()).toBe(afterY);

      useConverterStore.setState({ loop_offset_x: 0, loop_offset_y: 0 });
      setLoopOffsets(offset, offset);
      const afterBoth = useConverterStore.getState();
      expect(Object.is(afterBoth.loop_offset_x, offset)).toBe(true);
      expect(Object.is(afterBoth.loop_offset_y, offset)).toBe(true);
      setLoopOffsets(offset, offset);
      expect(useConverterStore.getState()).toBe(afterBoth);
    });

    it("publishes one complete position per frame and keeps the settings in sync", () => {
      vi.useFakeTimers();
      useConverterStore.setState({
        add_loop: true, loop_offset_x: 0, loop_offset_y: 0,
        puzzleEnabled: false, enable_fridge_magnet: false,
      });
      const { container } = render(<LiveRing />);
      startRingDrag(container);
      const positions: number[][] = [];
      const unsubscribe = useConverterStore.subscribe((state) => {
        positions.push([state.loop_offset_x, state.loop_offset_y]);
      });
      try {
        for (let index = 1; index <= 100; index += 1) {
          fireEvent.pointerMove(window, { clientX: 100 + index / 10, clientY: 100 - index / 20 });
        }
        expect(positions).toHaveLength(0);
        act(() => vi.advanceTimersToNextFrame());
        expect(positions).toHaveLength(1);
        expect(positions[0][0]).toBeCloseTo(10);
        expect(positions[0][1]).toBeCloseTo(5);
        expect(screen.getByRole("textbox", { name: "X 偏移 value" })).toHaveValue("10.0");
        expect(screen.getByRole("textbox", { name: "Y 偏移 value" })).toHaveValue("5.0");
        expect(mockControls.enabled).toBe(false);

        fireEvent.pointerMove(window, { clientX: 110, clientY: 95 });
        act(() => vi.advanceTimersToNextFrame());
        expect(positions).toHaveLength(1);
        fireEvent.pointerUp(window);
        expect(mockControls.enabled).toBe(true);
      } finally {
        unsubscribe();
      }
    });

    it("applies the destination contour before publishing a drag that crosses its edge", () => {
      vi.useFakeTimers();
      useConverterStore.setState({
        add_loop: true, loop_offset_x: -30, loop_offset_y: -2,
        puzzleEnabled: false, enable_fridge_magnet: false,
      });
      const { container } = render(
        <LiveRing
          contours={{ body: [[[10, 0], [30, 0], [30, 30], [10, 30]]] }}
          contourCanvasBounds={{ minX: -20, maxX: 20, minY: -15, maxY: 15 }}
        />,
      );
      startRingDrag(container, -30, 0);
      const positions: number[][] = [];
      const unsubscribe = useConverterStore.subscribe((state) => {
        positions.push([state.loop_offset_x, state.loop_offset_y]);
      });
      try {
        fireEvent.pointerMove(window, { clientX: 100, clientY: 110 });
        act(() => vi.advanceTimersToNextFrame());
        expect(positions).toEqual([[0, 0]]);
        expect(screen.getByRole("textbox", { name: "Y 偏移 value" })).toHaveValue("0.0");
        fireEvent.pointerUp(window);
      } finally {
        unsubscribe();
      }
    });

    it.each([
      { angle: 0, clientX: 70, expectedX: -30 },
      { angle: 45, clientX: 100, expectedX: 0 },
    ])("allows inward movement when the destination is unconstrained (angle $angle, x $expectedX)", ({ angle, clientX, expectedX }) => {
      vi.useFakeTimers();
      useConverterStore.setState({ loop_offset_x: 0, loop_offset_y: 0 });
      const { container } = render(
        <LiveRing
          angle={angle}
          contours={{ body: [[[10, 0], [30, 0], [30, 30], [10, 30]]] }}
          contourCanvasBounds={{ minX: -20, maxX: 20, minY: -15, maxY: 15 }}
        />,
      );
      startRingDrag(container);
      fireEvent.pointerMove(window, { clientX, clientY: 110 });
      act(() => vi.advanceTimersToNextFrame());
      expect(useConverterStore.getState().loop_offset_x).toBeCloseTo(expectedX);
      expect(useConverterStore.getState().loop_offset_y).toBeCloseTo(-10);
      fireEvent.pointerUp(window);
    });

    it("flushes the final position on release before the next frame", () => {
      vi.useFakeTimers();
      useConverterStore.setState({ loop_offset_x: 0, loop_offset_y: 0 });
      const { container } = render(<LiveRing />);
      startRingDrag(container);
      fireEvent.pointerMove(window, { clientX: 105, clientY: 95 });
      fireEvent.pointerUp(window);
      expect(useConverterStore.getState().loop_offset_x).toBeCloseTo(5);
      expect(useConverterStore.getState().loop_offset_y).toBeCloseTo(5);
      expect(mockControls.enabled).toBe(true);
      expect(document.body.style.cursor).toBe("default");
    });

    it.each(["pointercancel", "blur"])("ends a drag on %s and discards pending movement on unmount", (eventName) => {
      vi.useFakeTimers();
      useConverterStore.setState({ loop_offset_x: 0, loop_offset_y: 0 });
      const { container, unmount } = render(<LiveRing />);
      startRingDrag(container);
      fireEvent.pointerMove(window, { clientX: 105, clientY: 95 });
      fireEvent(window, new Event(eventName));
      expect(mockControls.enabled).toBe(true);
      const stopped = useConverterStore.getState();
      fireEvent.pointerMove(window, { clientX: 150, clientY: 50 });
      act(() => vi.advanceTimersToNextFrame());
      expect(useConverterStore.getState()).toBe(stopped);

      startRingDrag(container);
      fireEvent.pointerMove(window, { clientX: 110, clientY: 90 });
      unmount();
      const unmounted = useConverterStore.getState();
      act(() => vi.advanceTimersToNextFrame());
      expect(useConverterStore.getState()).toBe(unmounted);
      expect(mockControls.enabled).toBe(true);
    });
  });

  describe("enabled/disabled rendering", () => {
    it("returns null when enabled=false", () => {
      const { container } = render(
        <KeychainRing3D
          enabled={false}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );
      expect(container.innerHTML).toBe("");
    });

    it("returns null when modelBounds is null (Req 6.2)", () => {
      const { container } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={null}
        />,
      );
      expect(container.innerHTML).toBe("");
    });

    it("does not crash when enabled=true with valid params", () => {
      // Geometry creation is valid — component should render without error
      const geo = createKeychainRingGeometry(4, 8, 2);
      expect(geo).not.toBeNull();
    });

    it("normalizes a constrained inward offset in the store", () => {
      useConverterStore.setState({ loop_offset_y: -10.5 });
      render(
        <KeychainRing3D
          enabled={true}
          width={7}
          length={13.5}
          hole={4}
          angle={0}
          offsetX={0}
          offsetY={-10.5}
          positionPreset="top-center"
          modelBounds={{ ...defaultBounds, minY: -30, maxY: 30 }}
          contours={{
            spike: [[[0, 0], [4, 0], [4, 60], [0, 60]]],
            body: [[[18, 0], [42, 0], [42, 58], [18, 58]]],
          }}
          contourCanvasBounds={{ minX: -21, maxX: 21, minY: -30, maxY: 30 }}
        />,
      );

      expect(useConverterStore.getState().loop_offset_y).toBe(0);
    });

    it("geometry is null when hole >= width (component would return null)", () => {
      // hole === width → invalid geometry → component returns null
      const geo = createKeychainRingGeometry(3, 8, 3);
      expect(geo).toBeNull();
    });

    it("does not dispose the active geometry during StrictMode mount replay", () => {
      vi.useFakeTimers();
      const disposeSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
      const { unmount } = render(
        <StrictMode>
          <KeychainRing3D
            enabled={true}
            width={4}
            length={8}
            hole={2}
            angle={0}
            offsetX={0}
            offsetY={0}
            positionPreset="top-center"
            modelBounds={defaultBounds}
          />
        </StrictMode>,
      );

      act(() => {
        vi.runAllTimers();
      });

      expect(disposeSpy).not.toHaveBeenCalled();

      unmount();
      act(() => {
        vi.runAllTimers();
      });
    });

    it("disposes replaced geometry only after the deferred timer flushes", () => {
      vi.useFakeTimers();
      const disposeSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
      const { rerender, unmount } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      rerender(
        <KeychainRing3D
          enabled={true}
          width={5}
          length={9}
          hole={1.5}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      expect(disposeSpy).not.toHaveBeenCalled();

      act(() => {
        vi.runAllTimers();
      });

      expect(disposeSpy).toHaveBeenCalledTimes(1);

      unmount();
      act(() => {
        vi.runAllTimers();
      });
    });

    it("disposes geometry when rerendering to null via enabled=false", () => {
      vi.useFakeTimers();
      const disposeSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
      const { rerender, unmount } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      rerender(
        <KeychainRing3D
          enabled={false}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      expect(disposeSpy).not.toHaveBeenCalled();

      act(() => {
        vi.runAllTimers();
      });

      expect(disposeSpy).toHaveBeenCalledTimes(1);

      unmount();
    });

    it("restores orbit controls and cursor when dragging is interrupted by rerender-to-null", () => {
      const { container, rerender } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      const ring = container.querySelector("mesh");
      expect(ring).not.toBeNull();

      act(() => {
        getReactProps<{
          onPointerDown: (event: {
            button: number;
            stopPropagation: () => void;
            ray: { intersectPlane: (plane: THREE.Plane, target: THREE.Vector3) => THREE.Vector3 };
          }) => void;
        }>(ring as Element).onPointerDown({
          button: 0,
          stopPropagation: () => {},
          ray: {
            intersectPlane: (_plane: THREE.Plane, target: THREE.Vector3) => target.set(0, 0, 0),
          },
        });
      });

      expect(mockControls.enabled).toBe(false);
      expect(document.body.style.cursor).toBe("grabbing");

      rerender(
        <KeychainRing3D
          enabled={false}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      expect(mockControls.enabled).toBe(true);
      expect(document.body.style.cursor).toBe("default");
    });

    it("restores orbit controls and cursor when dragging is interrupted by unmount", () => {
      const { container, unmount } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      const ring = container.querySelector("mesh");
      expect(ring).not.toBeNull();

      act(() => {
        getReactProps<{
          onPointerDown: (event: {
            button: number;
            stopPropagation: () => void;
            ray: { intersectPlane: (plane: THREE.Plane, target: THREE.Vector3) => THREE.Vector3 };
          }) => void;
        }>(ring as Element).onPointerDown({
          button: 0,
          stopPropagation: () => {},
          ray: {
            intersectPlane: (_plane: THREE.Plane, target: THREE.Vector3) => target.set(0, 0, 0),
          },
        });
      });

      expect(mockControls.enabled).toBe(false);
      expect(document.body.style.cursor).toBe("grabbing");

      unmount();

      expect(mockControls.enabled).toBe(true);
      expect(document.body.style.cursor).toBe("default");
    });

    it("leaves middle and Space-modified primary drags to camera panning", () => {
      const { container, rerender } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      const middleStopPropagation = vi.fn();
      const intersectPlane = vi.fn();
      const invokePointerDown = (button: number, stopPropagation: () => void) => {
        const ring = container.querySelector("mesh");
        getReactProps<{
          onPointerDown: (event: {
            button: number;
            stopPropagation: () => void;
            ray: { intersectPlane: typeof intersectPlane };
          }) => void;
        }>(ring as Element).onPointerDown({
          button,
          stopPropagation,
          ray: { intersectPlane },
        });
      };

      act(() => invokePointerDown(1, middleStopPropagation));
      expect(middleStopPropagation).not.toHaveBeenCalled();
      expect(intersectPlane).not.toHaveBeenCalled();
      expect(mockControls.enabled).toBe(true);

      rerender(
        <KeychainRing3D
          enabled={true}
          cameraPanModifierActive={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );
      const spaceStopPropagation = vi.fn();
      act(() => invokePointerDown(0, spaceStopPropagation));
      expect(spaceStopPropagation).not.toHaveBeenCalled();
      expect(intersectPlane).not.toHaveBeenCalled();
      expect(mockControls.enabled).toBe(true);
    });
  });
});

describe("createKeychainRingGeometry", () => {
  it("produces valid geometry with default params", () => {
    const geo = createKeychainRingGeometry(4, 8, 2);
    expect(geo).not.toBeNull();
    expect(geo!.attributes.position.count).toBeGreaterThan(0);
  });

  it("produces geometry with vertices for min valid params", () => {
    // width=2, length=4, hole=1 → hole < min(2,4)=2 ✓
    const geo = createKeychainRingGeometry(2, 4, 1);
    expect(geo).not.toBeNull();
    expect(geo!.attributes.position.count).toBeGreaterThan(0);
  });

  it("produces geometry with vertices for max valid params", () => {
    // width=10, length=15, hole=5 → hole < min(10,15)=10 ✓
    const geo = createKeychainRingGeometry(10, 15, 5);
    expect(geo).not.toBeNull();
    expect(geo!.attributes.position.count).toBeGreaterThan(0);
  });

  it("returns null when hole >= min(width, length)", () => {
    // hole=5 >= min(5, 10)=5 → invalid
    expect(createKeychainRingGeometry(5, 10, 5)).toBeNull();
    // hole=6 >= min(4, 8)=4 → invalid
    expect(createKeychainRingGeometry(4, 8, 6)).toBeNull();
  });

  it("returns null when hole > width but < length", () => {
    // hole=4 >= min(3, 8)=3 → invalid
    expect(createKeychainRingGeometry(3, 8, 4)).toBeNull();
  });

  it("returns null for zero or negative dimensions", () => {
    expect(createKeychainRingGeometry(0, 8, 2)).toBeNull();
    expect(createKeychainRingGeometry(4, 0, 2)).toBeNull();
    expect(createKeychainRingGeometry(4, 8, 0)).toBeNull();
    expect(createKeychainRingGeometry(-1, 8, 2)).toBeNull();
  });

  it("geometry has non-degenerate faces (index count > 0)", () => {
    const geo = createKeychainRingGeometry(6, 10, 3);
    expect(geo).not.toBeNull();
    // ExtrudeGeometry uses indexed geometry
    if (geo!.index) {
      expect(geo!.index.count).toBeGreaterThan(0);
    } else {
      // Non-indexed: position count implies triangles
      expect(geo!.attributes.position.count).toBeGreaterThan(0);
    }
  });
});

describe("computeLoopPosition", () => {
  const bounds = { minX: -10, maxX: 10, minY: -15, maxY: 15 };

  it("returns center X, maxY as base position (top-center anchor)", () => {
    const pos = computeLoopPosition("top-center", bounds, 0, 0);
    expect(pos.x).toBe(0);
    expect(pos.y).toBe(15);
  });

  it("ignores preset value — always anchors at top-center", () => {
    // All presets should produce the same base position
    const presets = ["top-left", "top-right", "left-center", "right-center", "bottom-center", "invalid"];
    for (const preset of presets) {
      const pos = computeLoopPosition(preset, bounds, 0, 0);
      expect(pos.x).toBe(0);
      expect(pos.y).toBe(15);
    }
  });

  it("applies offset correctly", () => {
    const pos = computeLoopPosition("top-center", bounds, 5, -3);
    expect(pos.x).toBe(5);
    expect(pos.y).toBe(12);
  });

  it("clamps an inward offset to the contour under the loop", () => {
    const contours = {
      spike: [
        [[0, 0], [4, 0], [4, 60], [0, 60]],
      ],
      body: [
        [[18, 0], [42, 0], [42, 40], [18, 40]],
      ],
    };
    const contourBounds = {
      minX: -21,
      maxX: 21,
      minY: -30,
      maxY: 30,
    };

    const pos = computeLoopPosition(
      "top-center", contourBounds, 0, -25, contours, 8, contourBounds,
    );

    expect(pos).toEqual({ x: 0, y: 10 });
  });

  it("scales the local contour with a live 60 to 90 mm preview resize", () => {
    const contours = {
      spike: [
        [[0, 0], [4, 0], [4, 60], [0, 60]],
      ],
      body: [
        [[18, 0], [42, 0], [42, 40], [18, 40]],
      ],
    };
    const contourBounds = {
      minX: -21,
      maxX: 21,
      minY: -30,
      maxY: 30,
    };
    const previewSpace = createPreviewSpace({ ...contourBounds, maxZ: 2 }, 1.5, 1.5);

    const pos = computeLoopPosition(
      "top-center",
      previewSpace.displayBounds,
      0,
      -25,
      contours,
      8,
      contourBounds,
      previewSpace.toDisplayPoint,
    );

    expect(pos).toEqual({ x: 0, y: 15 });
  });

  it.each([-6.5, -10.5])(
    "keeps the ticket offset %s outside its local contour",
    (capturedOffsetY) => {
      const contours = {
        spike: [
          [[0, 0], [4, 0], [4, 60], [0, 60]],
        ],
        body: [
          [[18, 0], [42, 0], [42, 58], [18, 58]],
        ],
      };
      const contourBounds = {
        minX: -21,
        maxX: 21,
        minY: -30,
        maxY: 30,
      };

      const pos = computeLoopPosition(
        "top-center", contourBounds, 0, capturedOffsetY, contours, 7, contourBounds,
      );

      expect(pos).toEqual({ x: 0, y: 28 });
    },
  );

  it("keeps full-canvas contour coordinates when backing bounds are wider", () => {
    const contours = {
      spike: [
        [[10, 0], [20, 0], [20, 90], [10, 90]],
      ],
      body: [
        [[40, 0], [60, 0], [60, 60], [40, 60]],
      ],
    };
    const backingBounds = {
      minX: -50,
      maxX: 50,
      minY: -50,
      maxY: 50,
    };

    const pos = computeLoopPosition(
      "top-center",
      backingBounds,
      0,
      -10.5,
      contours,
      7,
      backingBounds,
    );

    expect(pos).toEqual({ x: 0, y: 10 });
  });

  it.each([0, -35])(
    "sinks to the lowest point of a sloped edge so the loop stays connected (offset %s)",
    (offsetY) => {
      // Reviewer repro: 90 mm body whose top falls 0.75 mm per mm to the right.
      const contours = {
        body: [
          [[0, 0], [90, 0], [90, 22.5], [0, 90]],
        ],
      };
      const bounds = { minX: -45, maxX: 45, minY: -45, maxY: 45 };

      const pos = computeLoopPosition(
        "top-center",
        bounds,
        0,
        offsetY,
        contours,
        7,
        bounds,
        undefined,
        keychainLoopHoleClearance(7, 13.5, 2.5),
      );

      // Band x in [41.5, 48.5]; lowest top is 90 - 0.75 * 48.5 = 53.625.
      expect(pos.x).toBe(0);
      expect(pos.y).toBeCloseTo(53.625 - 45, 9);
    },
  );

  it("stops sinking on a steep edge before the hole reaches the body", () => {
    const contours = {
      body: [
        [[0, 0], [20, 0], [20, 10], [10, 40], [0, 40]],
      ],
    };
    const bounds = { minX: -10, maxX: 10, minY: -20, maxY: 20 };
    const clearance = keychainLoopHoleClearance(7, 13.5, 2.5);

    const pos = computeLoopPosition(
      "top-center", bounds, 0, 0, contours, 7, bounds, undefined, clearance,
    );

    // Band tops span 40 .. 29.5, deeper than the clearance, so the loop stops
    // one clearance below the highest point.
    expect(clearance).toBeCloseTo(8.75, 9);
    expect(pos.y).toBeCloseTo(40 - clearance - 20, 9);
  });

  it("works with asymmetric bounds", () => {
    const asymBounds = { minX: 0, maxX: 20, minY: -5, maxY: 25 };
    const pos = computeLoopPosition("top-center", asymBounds, 0, 0);
    expect(pos.x).toBe(10);
    expect(pos.y).toBe(25);
  });
});
