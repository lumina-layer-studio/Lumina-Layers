import { StrictMode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import * as THREE from "three";
import {
  default as KeychainRing3D,
  createKeychainRingGeometry,
  resetKeychainRingGeometryDisposeForTests,
} from "../components/KeychainRing3D";
import type { KeychainRing3DProps } from "../components/KeychainRing3D";
import KeychainLoopSettings from "../components/sections/KeychainLoopSettings";
import { useConverterStore } from "../stores/converter";

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

const defaultAnchor = { x: -2.4, y: 15 };

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

        anchor={defaultAnchor}
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
  it.each([0, -45, 45, -90, 90, 180, 37])("transforms the whole ring about the solved %s° foot", (angle) => {
    const { container } = render(<LiveRing width={6} length={8} hole={2.5} angle={angle} />);
    const ring = getReactProps<{
      geometry: THREE.BufferGeometry;
      position: [number, number, number];
      rotation: [number, number, number];
    }>(container.querySelector("mesh")!);
    const mesh = new THREE.Mesh(ring.geometry);
    mesh.position.set(...ring.position);
    mesh.rotation.set(...ring.rotation);
    mesh.updateMatrixWorld(true);
    const positions = ring.geometry.attributes.position;
    const targets = [[-3, 0], [3, 0], [0, 8], [1.25, 5], [-1.25, 5]];
    for (const [x, y] of targets) {
      const world = new THREE.Vector2(x, y).rotateAround(new THREE.Vector2(), angle * Math.PI / 180);
      world.add(new THREE.Vector2(defaultAnchor.x, defaultAnchor.y));
      const vertex = new THREE.Vector3();
      let distance = Infinity;
      for (let index = 0; index < positions.count; index += 1) {
        vertex.fromBufferAttribute(positions, index).applyMatrix4(mesh.matrixWorld);
        distance = Math.min(distance, Math.hypot(vertex.x - world.x, vertex.y - world.y));
      }
      expect(distance).toBeLessThan(1e-5);
    }
  });

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

    it("keeps the negative offset after dragging and publishes the exact signed delta", () => {
      vi.useFakeTimers();
      useConverterStore.setState({
        add_loop: true, loop_offset_x: 0, loop_offset_y: -2,
        puzzleEnabled: false, enable_fridge_magnet: false,
      });
      const { container } = render(<LiveRing angle={-90} />);
      startRingDrag(container);
      fireEvent.pointerMove(window, { clientX: 98, clientY: 102 });
      fireEvent.pointerUp(window);
      const { loop_offset_x, loop_offset_y } = useConverterStore.getState();
      expect(loop_offset_x).toBeCloseTo(-2);
      expect(loop_offset_y).toBeCloseTo(-4);
      expect(screen.getByRole("textbox", { name: "Y 偏移 value" })).toHaveValue("-4.0");
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

          anchor={defaultAnchor}
        />,
      );
      expect(container.innerHTML).toBe("");
    });

    it("returns null while no solved anchor is available", () => {
      const { container } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}

          anchor={null}
        />,
      );
      expect(container.innerHTML).toBe("");
    });

    it("does not crash when enabled=true with valid params", () => {
      // Geometry creation is valid — component should render without error
      const geo = createKeychainRingGeometry(4, 8, 2);
      expect(geo).not.toBeNull();
    });

    it("preserves the saved inward adjustment and displays it from the solved foot", () => {
      useConverterStore.setState({ loop_offset_x: -1, loop_offset_y: -4 });
      const { container } = render(<LiveRing angle={-90} />);
      const ring = getReactProps<{ position: number[] }>(container.querySelector("mesh")!);
      expect(ring.position).toEqual([defaultAnchor.x - 1, defaultAnchor.y - 4, 0]);
      expect(useConverterStore.getState().loop_offset_y).toBe(-4);
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

            anchor={defaultAnchor}
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

          anchor={defaultAnchor}
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

          anchor={defaultAnchor}
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

          anchor={defaultAnchor}
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

          anchor={defaultAnchor}
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

          anchor={defaultAnchor}
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

          anchor={defaultAnchor}
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

          anchor={defaultAnchor}
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

          anchor={defaultAnchor}
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

          anchor={defaultAnchor}
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

  it("keeps the preview visible with the same hole limit as the printable ring", () => {
    const oversized = createKeychainRingGeometry(3, 8, 4)!;
    const limited = createKeychainRingGeometry(3, 8, 2.4)!;
    expect(oversized.attributes.position.array).toEqual(limited.attributes.position.array);
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
