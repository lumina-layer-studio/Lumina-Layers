import PreviewOrbitControls from "./ui/PreviewOrbitControls";
import { saveGeneratedFile } from "../utils/saveGeneratedFile";
import {
  Suspense,
  useRef,
  useState,
  useEffect,
  useLayoutEffect,
  useCallback,
  useMemo,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, Html, useEnvironment } from "@react-three/drei";
import { LIGHTING_CONFIG } from "./lightingConfig";
import * as THREE from "three";
import { computeFitDistance } from "./ModelViewer";
import InteractiveModelViewer, {
  resolvePreviewColorLayerHeightMm,
} from "./InteractiveModelViewer";
import BedPlatform from "./BedPlatform";
import SceneErrorBoundary from "./SceneErrorBoundary";
import Button from "./ui/Button";
import { SceneAssetReady, SceneTransitionBridge } from "./SceneTransitionBridge";
import {
  clearSceneTransitionSnapshot,
  getSceneTransitionKey,
  getSceneTransitionSnapshot,
} from "./sceneTransitionSnapshot";
import KeychainRing3D from "./KeychainRing3D";
import FridgeMagnet3D from "./FridgeMagnet3D";
import LargeFormatTileOverlay3D from "./LargeFormatTileOverlay3D";
import { computePuzzleOverlayPlacement } from "./puzzleOverlay3DUtils";
import { resolveLargeFormatTotalHeightMm } from "../utils/largeFormatTileLayout";
import ModelSurfaceSelector3D from "./ModelSurfaceSelector3D";
import { resolveModelSurfaceArtworkAsset } from "./modelSurface/artworkAsset";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { computeScaleFactor } from "../utils/scaleUtils";
import { createPreviewSpace } from "../utils/previewSpace";
import { resolveCameraClippingPlanes } from "../utils/cameraDepthPrecision";
import { useI18n } from "../i18n/context";
import { useThemeConfig } from "../hooks/useThemeConfig";
import { useWittyMessage } from "../hooks/useWittyMessage";
import { useSpacePanModifier } from "../hooks/useSpacePanModifier";
import {
  debugThreeLog,
  getHeapMemorySnapshot,
  getRendererInfoSnapshot,
  getThreePerfDebugConfig,
} from "../utils/threeDebug";
import { postClientLog } from "../utils/clientLog";
import { HeaderTooltip } from "./ui/HeaderTooltip";
import {
  ActivityIcon,
  CameraIcon,
  MaximizeIcon,
  MinimizeIcon,
  StopwatchIcon,
} from "./ui/icons";
import type { BatchPreviewItem, PerformanceTiming } from "../api/types";

declare global {
  interface Window {
    __luminaCameraDebug?: () => {
      cameraPosition: { x: number; y: number; z: number };
      orbitTarget: { x: number; y: number; z: number };
      fov: number;
      near: number;
      far: number;
    };
  }
}

interface Scene3DProps {
  modelUrl?: string;
  /** Keep only the static frame while the primary tab indicator is moving. */
  deferInitialization?: boolean;
  /** Pause rendering behind modal pages without discarding the scene state. */
  suspended?: boolean;
}

export interface PreviewModelBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  maxZ: number;
}

export interface ScaledPreviewBounds {
  width: number;
  height: number;
  depth: number;
  radius: number;
}

export interface PreviewCameraOrbitConfig {
  near: number;
  far: number;
  minDistance: number;
  maxDistance: number;
}

export function computeScaledPreviewBounds(
  modelBounds: PreviewModelBounds,
  scaleX: number,
  scaleY: number,
): ScaledPreviewBounds {
  const displayBounds = createPreviewSpace(
    modelBounds,
    scaleX,
    scaleY,
  ).displayBounds;
  const width = Math.max(0, displayBounds.maxX - displayBounds.minX);
  const height = Math.max(0, displayBounds.maxY - displayBounds.minY);
  const depth = Math.max(0, modelBounds.maxZ);
  return {
    width,
    height,
    depth,
    radius: Math.sqrt(width * width + height * height + depth * depth) / 2,
  };
}

export function computePreviewCameraOrbitConfig(
  modelBounds: PreviewModelBounds,
  scaleX: number,
  scaleY: number,
): PreviewCameraOrbitConfig {
  const bounds = computeScaledPreviewBounds(modelBounds, scaleX, scaleY);
  const radius = Math.max(bounds.radius, 1);
  const maxDistance = Math.max(2000, radius * 10);
  return {
    near: Math.max(0.1, Math.min(5, radius / 2000)),
    far: Math.max(2000, maxDistance + radius * 4),
    minDistance: Math.max(2, Math.min(10, radius / 50)),
    maxDistance,
  };
}

interface ActiveOrbitPanPointer {
  pointerId: number;
  spaceModified: boolean;
}

interface SceneDiagnosticsSnapshot {
  renderer: ReturnType<typeof getRendererInfoSnapshot>;
  heap: ReturnType<typeof getHeapMemorySnapshot>;
  fps: number | null;
}

const DEFAULT_CAMERA_POSITION = [0, -57, 474] as const;
const DEFAULT_ORBIT_TARGET = [0, -20, 0] as const;
const DEFAULT_CAMERA_CLIPPING_PLANES = resolveCameraClippingPlanes(
  Math.hypot(
    DEFAULT_CAMERA_POSITION[0] - DEFAULT_ORBIT_TARGET[0],
    DEFAULT_CAMERA_POSITION[1] - DEFAULT_ORBIT_TARGET[1],
    DEFAULT_CAMERA_POSITION[2] - DEFAULT_ORBIT_TARGET[2],
  ),
);
const CLIPPING_PLANE_RELATIVE_TOLERANCE = 1e-6;

function dispatchPointerCancel(element: HTMLElement, pointerId: number): void {
  let event: Event;
  if (typeof PointerEvent === "function") {
    event = new PointerEvent("pointercancel", {
      bubbles: true,
      cancelable: true,
      pointerId,
    });
  } else {
    event = new Event("pointercancel", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "pointerId", { configurable: true, value: pointerId });
  }
  element.dispatchEvent(event);
}

function clippingPlaneNeedsUpdate(currentValue: number, nextValue: number): boolean {
  const tolerance = Math.max(
    Number.EPSILON,
    Math.abs(nextValue) * CLIPPING_PLANE_RELATIVE_TOLERANCE,
  );
  return Math.abs(currentValue - nextValue) > tolerance;
}

function formatTimingMs(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)} s`;
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ms`;
}

function TimingRow({
  label,
  value,
}: {
  label: string;
  value: number | null | undefined;
}) {
  return (
    <>
      <span>{label}</span>
      <span className="text-right">{formatTimingMs(value)}</span>
    </>
  );
}

function TimingSection({
  title,
  timing,
  rows,
}: {
  title: string;
  timing: PerformanceTiming | null;
  rows: Array<{ key: keyof PerformanceTiming; label: string }>;
}) {
  if (!timing) {
    return null;
  }

  return (
    <div className="space-y-1.5">
      <div className="text-xs font-semibold text-slate-900 dark:text-slate-50">
        {title}
      </div>
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {rows.map((row) => (
          <TimingRow key={row.key} label={row.label} value={timing[row.key]} />
        ))}
      </div>
    </div>
  );
}

function FrameSampler({
  onFps,
}: {
  onFps: (fps: number) => void;
}) {
  const frameCountRef = useRef(0);
  const lastFpsAtRef = useRef(performance.now());

  useFrame(() => {
    frameCountRef.current += 1;
  });

  useEffect(() => {
    const timerId = window.setInterval(() => {
      const now = performance.now();
      const elapsed = now - lastFpsAtRef.current;
      if (elapsed < 1000) {
        return;
      }
      const fps = Math.round((frameCountRef.current * 10000) / elapsed) / 10;
      frameCountRef.current = 0;
      lastFpsAtRef.current = now;
      onFps(fps);
    }, 1000);
    return () => {
      window.clearInterval(timerId);
    };
  }, [onFps]);

  return null;
}

function RendererDiagnosticsBridge({
  enabled,
  onSample,
}: {
  enabled: boolean;
  onSample: (snapshot: SceneDiagnosticsSnapshot) => void;
}) {
  const { gl } = useThree();
  const latestFpsRef = useRef<number | null>(null);

  const publishSnapshot = useCallback(() => {
    onSample({
      renderer: getRendererInfoSnapshot(gl),
      heap: getHeapMemorySnapshot(),
      fps: latestFpsRef.current,
    });
  }, [gl, onSample]);

  useEffect(() => {
    publishSnapshot();
  }, [publishSnapshot]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const { intervalMs } = getThreePerfDebugConfig();
    const timerId = window.setInterval(() => {
      publishSnapshot();
    }, intervalMs);
    return () => {
      window.clearInterval(timerId);
    };
  }, [enabled, publishSnapshot]);

  const handleFps = useCallback((fps: number) => {
    latestFpsRef.current = fps;
  }, []);

  if (!enabled) {
    return null;
  }

  return <FrameSampler onFps={handleFps} />;
}

/**
 * Helper component rendered inside <Canvas> to expose the gl context
 * for screenshot functionality via a callback ref.
 */
function ScreenshotHelper({
  onGlReady,
}: {
  onGlReady: (gl: THREE.WebGLRenderer) => void;
}) {
  const { gl } = useThree();
  useEffect(() => {
    onGlReady(gl);
  }, [gl, onGlReady]);
  return null;
}

/**
 * Expose camera debug info to window for tuning default view.
 * Run `window.__luminaCameraDebug()` in browser console to print current values.
 * 将相机调试信息暴露到 window，用于调优默认视角。
 */
function CameraDebugHelper() {
  const { camera, controls } = useThree();
  useEffect(() => {
    window.__luminaCameraDebug = () => {
      const pos = camera.position;
      const orbitControls =
        controls && "target" in controls
          ? (controls as { target?: THREE.Vector3 | null })
          : null;
      const target = orbitControls?.target ?? { x: 0, y: 0, z: 0 };
      const info = {
        cameraPosition: { x: +pos.x.toFixed(2), y: +pos.y.toFixed(2), z: +pos.z.toFixed(2) },
        orbitTarget: { x: +target.x.toFixed(2), y: +target.y.toFixed(2), z: +target.z.toFixed(2) },
        fov: (camera as THREE.PerspectiveCamera).fov,
        near: (camera as THREE.PerspectiveCamera).near,
        far: (camera as THREE.PerspectiveCamera).far,
      };
      console.log("📷 Camera Debug:", JSON.stringify(info, null, 2));
      return info;
    };
    return () => {
      delete window.__luminaCameraDebug;
    };
  }, [camera, controls]);
  return null;
}

function PreviewCameraRangeBridge({
  active,
  modelBounds,
  scaleX,
  scaleY,
}: {
  active: boolean;
  modelBounds: PreviewModelBounds | null;
  scaleX: number;
  scaleY: number;
}) {
  const { camera, controls, invalidate } = useThree();

  useEffect(() => {
    if (!active || !modelBounds) {
      return;
    }

    const config = computePreviewCameraOrbitConfig(modelBounds, scaleX, scaleY);
    const perspectiveCamera = camera as THREE.PerspectiveCamera;
    if (perspectiveCamera.isPerspectiveCamera) {
      // Model bounds arrive after the depth guard on a fresh preview. Do not
      // loosen its clipping range here; OrbitControls will resync it as the
      // camera actually moves.
      const nextNear = Math.max(perspectiveCamera.near, config.near);
      const nextFar = Math.max(perspectiveCamera.far, config.far);
      if (
        Math.abs(perspectiveCamera.near - nextNear) > 1e-6 ||
        Math.abs(perspectiveCamera.far - nextFar) > 1e-6
      ) {
        perspectiveCamera.near = nextNear;
        perspectiveCamera.far = nextFar;
        perspectiveCamera.updateProjectionMatrix();
      }
    }

    if (controls) {
      const orbitControls = controls as unknown as {
        minDistance?: number;
        maxDistance?: number;
        update?: () => void;
      };
      orbitControls.minDistance = Math.min(
        orbitControls.minDistance ?? config.minDistance,
        config.minDistance,
      );
      orbitControls.maxDistance = config.maxDistance;
      orbitControls.update?.();
    }
    invalidate();
  }, [active, modelBounds, scaleX, scaleY, camera, controls, invalidate]);

  return null;
}

/**
 * Keep perspective depth precision high enough for 0.08 mm material layers.
 * 动态收紧相机裁剪范围，避免 0.08 mm 材料层发生深度冲突。
 */
function CameraDepthPrecisionGuard() {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  const invalidate = useThree((state) => state.invalidate);

  useEffect(() => {
    const perspectiveCamera = camera as THREE.PerspectiveCamera;
    if (!perspectiveCamera.isPerspectiveCamera) {
      return;
    }

    const orbitControls =
      controls && "target" in controls
        ? (controls as {
            target?: THREE.Vector3 | null;
            addEventListener?: (type: "change", listener: () => void) => void;
            removeEventListener?: (type: "change", listener: () => void) => void;
          })
        : null;

    const syncClippingPlanes = () => {
      const target = orbitControls?.target;
      const distanceToTarget = target
        ? perspectiveCamera.position.distanceTo(target)
        : Math.hypot(
            perspectiveCamera.position.x,
            perspectiveCamera.position.y,
            perspectiveCamera.position.z,
          );
      const clippingPlanes = resolveCameraClippingPlanes(distanceToTarget);
      if (
        !clippingPlaneNeedsUpdate(perspectiveCamera.near, clippingPlanes.near) &&
        !clippingPlaneNeedsUpdate(perspectiveCamera.far, clippingPlanes.far)
      ) {
        return;
      }

      perspectiveCamera.near = clippingPlanes.near;
      perspectiveCamera.far = clippingPlanes.far;
      perspectiveCamera.updateProjectionMatrix();
      invalidate();
    };

    syncClippingPlanes();
    orbitControls?.addEventListener?.("change", syncClippingPlanes);
    return () => {
      orbitControls?.removeEventListener?.("change", syncClippingPlanes);
    };
  }, [camera, controls, invalidate]);

  return null;
}

/**
 * Inner component that syncs the Canvas clear color with the active theme.
 * Canvas 内部组件，将清除色与当前主题同步。
 */
function ThemeUpdater() {
  const { gl, invalidate } = useThree();
  const themeColors = useThemeConfig();
  useEffect(() => {
    gl.setClearColor(themeColors.canvasClearColor);
    invalidate();
  }, [gl, themeColors.canvasClearColor, invalidate]);
  return null;
}

const ORBIT_DAMPING_SETTLE_MS = 500;
const ORBIT_CHANGE_BURST_MS = 180;
const ORBIT_PASSTHROUGH_MAX_MS = 10000;
const ORBIT_PASSTHROUGH_CLASS = "lumina-canvas-orbiting";
const ORBIT_CAMERA_MIN_FAR = 2000;
const ORBIT_CAMERA_FAR_PADDING_RATIO = 0.25;
const ORBIT_CAMERA_FAR_PADDING_MIN = 100;
const ORBIT_CAMERA_MIN_NEAR = 0.1;
const ORBIT_CAMERA_NEAR_DISTANCE_RATIO = 0.01;

function syncOrbitCameraDepthClipping(
  camera: THREE.Camera,
  target: THREE.Vector3 | null | undefined,
): boolean {
  if (!target) {
    return false;
  }
  const clippingCamera = camera as THREE.PerspectiveCamera | THREE.OrthographicCamera;
  if (typeof clippingCamera.near !== "number" || typeof clippingCamera.far !== "number") {
    return false;
  }
  const distance = camera.position.distanceTo(target);
  if (!Number.isFinite(distance) || distance <= 0) {
    return false;
  }

  const requiredFar = Math.max(
    ORBIT_CAMERA_MIN_FAR,
    distance * (1 + ORBIT_CAMERA_FAR_PADDING_RATIO) + ORBIT_CAMERA_FAR_PADDING_MIN,
  );
  const nextNear = Math.max(
    ORBIT_CAMERA_MIN_NEAR,
    distance * ORBIT_CAMERA_NEAR_DISTANCE_RATIO,
  );
  let changed = false;
  if (requiredFar > clippingCamera.far) {
    clippingCamera.far = requiredFar;
    changed = true;
  }
  if (Math.abs(nextNear - clippingCamera.near) > 1e-6) {
    clippingCamera.near = nextNear;
    changed = true;
  }
  if (changed) {
    clippingCamera.updateProjectionMatrix();
  }
  return changed;
}

function setWidgetPassthroughForCanvasInteraction(enabled: boolean): void {
  document.body.classList.toggle(ORBIT_PASSTHROUGH_CLASS, enabled);
  if (enabled) {
    return;
  }
  // Recover panels left non-interactive by older builds or interrupted HMR.
  document.querySelectorAll<HTMLElement>("[data-widget-id]").forEach((panel) => {
    if (
      panel.style.pointerEvents === "none" &&
      panel.style.getPropertyPriority("pointer-events") === "important"
    ) {
      panel.style.pointerEvents = "auto";
    }
  });
}

function CanvasInteractionBridge() {
  const { camera, controls, invalidate } = useThree();
  useEffect(() => {
    if (!controls) return;
    const controlsWithEvents = controls as {
      target?: THREE.Vector3 | null;
      addEventListener: (type: "start" | "change" | "end", listener: () => void) => void;
      removeEventListener: (type: "start" | "change" | "end", listener: () => void) => void;
    };

    let rafId: number | null = null;
    let passthroughTimerId: number | null = null;
    let keepRenderingUntil = 0;
    let interacting = false;

    const stopLoop = () => {
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    };

    const tick = () => {
      invalidate();
      if (interacting || performance.now() < keepRenderingUntil) {
        rafId = requestAnimationFrame(tick);
        return;
      }
      rafId = null;
    };

    const ensureLoop = () => {
      if (rafId === null) {
        rafId = requestAnimationFrame(tick);
      }
    };

    const stopPassthroughTimer = () => {
      if (passthroughTimerId !== null) {
        window.clearTimeout(passthroughTimerId);
        passthroughTimerId = null;
      }
    };

    const finishInteraction = () => {
      if (!interacting) {
        setWidgetPassthroughForCanvasInteraction(false);
        return;
      }
      interacting = false;
      keepRenderingUntil = performance.now() + ORBIT_DAMPING_SETTLE_MS;
      stopPassthroughTimer();
      setWidgetPassthroughForCanvasInteraction(false);
      invalidate();
      ensureLoop();
    };

    const onStart = () => {
      interacting = true;
      keepRenderingUntil = Number.POSITIVE_INFINITY;
      setWidgetPassthroughForCanvasInteraction(true);
      stopPassthroughTimer();
      passthroughTimerId = window.setTimeout(finishInteraction, ORBIT_PASSTHROUGH_MAX_MS);
      invalidate();
      ensureLoop();
    };

    const onChange = () => {
      syncOrbitCameraDepthClipping(camera, controlsWithEvents.target);
      if (!interacting) {
        keepRenderingUntil = Math.max(keepRenderingUntil, performance.now() + ORBIT_CHANGE_BURST_MS);
        ensureLoop();
      }
      invalidate();
    };

    controlsWithEvents.addEventListener("start", onStart);
    controlsWithEvents.addEventListener("change", onChange);
    controlsWithEvents.addEventListener("end", finishInteraction);
    window.addEventListener("pointerup", finishInteraction);
    window.addEventListener("pointercancel", finishInteraction);
    window.addEventListener("blur", finishInteraction);
    window.addEventListener("contextmenu", finishInteraction);

    return () => {
      controlsWithEvents.removeEventListener("start", onStart);
      controlsWithEvents.removeEventListener("change", onChange);
      controlsWithEvents.removeEventListener("end", finishInteraction);
      window.removeEventListener("pointerup", finishInteraction);
      window.removeEventListener("pointercancel", finishInteraction);
      window.removeEventListener("blur", finishInteraction);
      window.removeEventListener("contextmenu", finishInteraction);
      stopLoop();
      stopPassthroughTimer();
      setWidgetPassthroughForCanvasInteraction(false);
    };
  }, [camera, controls, invalidate]);
  return null;
}

interface BatchPreviewModelsProps {
  items: BatchPreviewItem[];
  colorRemapMap: Record<string, string>;
  colorHeightMap: Record<string, number>;
  baseHeight: number;
  enableRelief: boolean;
  spacerThick: number;
  structureMode: string;
  enableOutline: boolean;
  outlineWidth: number;
  enableCloisonne: boolean;
  wireWidthMm: number;
  wireHeightMm: number;
  enableFridgeMagnet: boolean;
  rasterCellSize?: number;
  colorLayerHeightMm: number;
}

function BatchPreviewModels({
  items,
  colorRemapMap,
  colorHeightMap,
  baseHeight,
  enableRelief,
  spacerThick,
  structureMode,
  enableOutline,
  outlineWidth,
  enableCloisonne,
  wireWidthMm,
  wireHeightMm,
  enableFridgeMagnet,
  rasterCellSize,
  colorLayerHeightMm,
}: BatchPreviewModelsProps) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  const bed_label = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);

  const bedDims = useMemo(() => {
    const found = bedSizes.find((b) => b.label === bed_label);
    return found ? { w: found.width_mm, h: found.height_mm } : { w: 256, h: 256 };
  }, [bed_label, bedSizes]);

  const positionedItems = useMemo(
    () =>
      items.map((item) => ({
        ...item,
        position: [
          item.tx_mm + item.width_mm / 2 - bedDims.w / 2,
          item.ty_mm + item.depth_mm / 2 - bedDims.h / 2,
          0,
        ] as [number, number, number],
      })),
    [bedDims.h, bedDims.w, items],
  );

  useEffect(() => {
    if (positionedItems.length === 0) {
      return;
    }
    const minX = Math.min(
      -bedDims.w / 2,
      ...items.map((item) => item.tx_mm - bedDims.w / 2),
    );
    const maxX = Math.max(
      bedDims.w / 2,
      ...items.map((item) => item.tx_mm + item.width_mm - bedDims.w / 2),
    );
    const minY = Math.min(
      -bedDims.h / 2,
      ...items.map((item) => item.ty_mm - bedDims.h / 2),
    );
    const maxY = Math.max(
      bedDims.h / 2,
      ...items.map((item) => item.ty_mm + item.depth_mm - bedDims.h / 2),
    );
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const radius = Math.max(maxX - minX, maxY - minY) / 2;
    const perspCam = camera as THREE.PerspectiveCamera;
    const dist = computeFitDistance(radius, perspCam.fov) * 1.25;

    camera.position.set(centerX, centerY - 57, dist);
    camera.lookAt(centerX, centerY, 0);
    camera.updateProjectionMatrix();

    if (controls) {
      const oc = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      oc.target.set(centerX, centerY, 0);
      oc.maxDistance = dist * 5;
      oc.minDistance = dist * 0.1;
      oc.update();
    }
  }, [bedDims.h, bedDims.w, camera, controls, items, positionedItems.length]);

  return (
    <>
      {positionedItems.map((item, index) => (
        <group key={`${item.url}-${index}`} position={item.position}>
          <InteractiveModelViewer
            url={item.url}
            sourceRole="batch"
            colorRemapMap={colorRemapMap}
            colorHeightMap={colorHeightMap}
            baseHeight={baseHeight}
            enableRelief={enableRelief}
            scaleX={1}
            scaleY={1}
            spacerThick={spacerThick}
            structureMode={structureMode}
            enableOutline={enableOutline}
            outlineWidth={outlineWidth}
            enableCloisonne={enableCloisonne}
            wireWidthMm={wireWidthMm}
            wireHeightMm={wireHeightMm}
            enableFridgeMagnet={enableFridgeMagnet}
            rasterCellSize={rasterCellSize}
            puzzleOverlayEnabled={false}
            puzzleOverlayUrl={null}
            colorLayerHeightMm={colorLayerHeightMm}
          />
        </group>
      ))}
    </>
  );
}

function requireCanvasContext(canvas: HTMLCanvasElement | null) {
  // R3F configures the renderer asynchronously, outside React's error boundary.
  // Acquire its actual context at ref attachment, before that initialization.
  // Three.js reuses this same context, including its drawing-buffer attributes.
  if (canvas && !canvas.getContext("webgl2", {
    alpha: true,
    antialias: true,
    powerPreference: "high-performance",
    preserveDrawingBuffer: true,
  })) {
    throw new Error("Error creating WebGL context.");
  }
}

function Scene3D({ modelUrl, deferInitialization = false, suspended = false }: Scene3DProps) {
  const { t } = useI18n();
  const themeColors = useThemeConfig();
  const containerRef = useRef<HTMLDivElement>(null);
  const glRef = useRef<THREE.WebGLRenderer | null>(null);
  const getTransitionKey = useCallback(() => {
    const settings = useSettingsStore.getState();
    return getSceneTransitionKey(useConverterStore.getState(), [
      settings.theme, settings.deviceProfileId, settings.buildPlateId,
      settings.slicerSoftware, modelUrl ?? null,
    ]);
  }, [modelUrl]);
  const transitionKey = getTransitionKey();
  const [transitionSnapshot, setTransitionSnapshot] = useState(
    () => getSceneTransitionSnapshot(transitionKey),
  );
  const snapshotCanvasRef = useRef<HTMLCanvasElement>(null);
  const captureTransitionRef = useRef<(() => void) | null>(null);
  const [environmentReady, setEnvironmentReady] = useState(false);
  const [environmentFailed, setEnvironmentFailed] = useState(false);
  const [environmentAttempt, setEnvironmentAttempt] = useState(0);
  const [sceneAttempt, setSceneAttempt] = useState(0);
  const [bedReady, setBedReady] = useState(false);
  const [readyModelKey, setReadyModelKey] = useState<string | null>(null);
  const visibleSnapshot = transitionSnapshot?.key === transitionKey ? transitionSnapshot : null;
  const handleFrameReady = useCallback(() => {
    setTransitionSnapshot(null);
    clearSceneTransitionSnapshot();
  }, []);
  const handleEnvironmentError = useCallback((error: Error) => {
    setEnvironmentFailed(true);
    postClientLog("viewer: environment unavailable; using basic lighting", {
      scope: "viewer", phase: "environment-fallback", method: "warn",
      details: { message: error.message },
    });
  }, []);
  const retryEnvironment = () => {
    useEnvironment.clear({ files: LIGHTING_CONFIG.environment.hdrFile });
    setEnvironmentFailed(false);
    setEnvironmentAttempt((attempt) => attempt + 1);
  };
  const handleSceneError = useCallback((error: Error) => {
    glRef.current = null;
    setEnvironmentFailed(false);
    setTransitionSnapshot(null);
    clearSceneTransitionSnapshot();
    postClientLog("viewer: scene unavailable; retry is available", {
      scope: "viewer", phase: "scene-failed", method: "error",
      details: { message: error.message },
    });
  }, []);

  useLayoutEffect(() => () => {
    // Capture before React removes the DOM; R3F can then dispose normally.
    captureTransitionRef.current?.();
  }, []);

  useLayoutEffect(() => {
    if (!visibleSnapshot || !snapshotCanvasRef.current || !containerRef.current) return;
    const { width, height } = containerRef.current.getBoundingClientRect();
    if (Math.abs(width - visibleSnapshot.width) > 1 || Math.abs(height - visibleSnapshot.height) > 1) {
      setTransitionSnapshot(null);
      clearSceneTransitionSnapshot();
      return;
    }
    try {
      const context = snapshotCanvasRef.current.getContext("2d");
      if (context) context.drawImage(visibleSnapshot.image, 0, 0);
      else setTransitionSnapshot(null);
    } catch {
      setTransitionSnapshot(null);
      clearSceneTransitionSnapshot();
    }
  }, [visibleSnapshot]);
  const activeOrbitPanPointerRef = useRef<ActiveOrbitPanPointer | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [screenshotNotice, setScreenshotNotice] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<SceneDiagnosticsSnapshot | null>(null);
  const [diagnosticsVisible, setDiagnosticsVisible] = useState(false);
  const [performanceVisible, setPerformanceVisible] = useState(false);
  const [previewCanvasBoundsState, setPreviewCanvasBoundsState] = useState<{
    sourceUrl: string;
    bounds: PreviewModelBounds;
  } | null>(null);
  const [modelSurfaceBedGridVisible, setModelSurfaceBedGridVisible] = useState(true);

  const cancelOrbitPanPointer = useCallback((spaceOnly: boolean) => {
    const activePointer = activeOrbitPanPointerRef.current;
    if (!activePointer || (spaceOnly && !activePointer.spaceModified)) {
      return;
    }
    activeOrbitPanPointerRef.current = null;
    const canvas = glRef.current?.domElement ?? containerRef.current?.querySelector("canvas");
    if (canvas) {
      dispatchPointerCancel(canvas, activePointer.pointerId);
    }
  }, []);

  const handlePreviewCanvasBoundsChange = useCallback((
    sourceUrl: string,
    bounds: PreviewModelBounds | null,
  ) => {
    setPreviewCanvasBoundsState((current) => {
      if (bounds) {
        return { sourceUrl, bounds };
      }
      return current?.sourceUrl === sourceUrl ? null : current;
    });
  }, []);
  const handleSpacePanDeactivate = useCallback(() => {
    cancelOrbitPanPointer(true);
  }, [cancelOrbitPanPointer]);
  const {
    isActive: isSpacePanActive,
    isActiveRef: isSpacePanActiveRef,
    handlePointerEnter: handleSpacePanPointerEnter,
    handlePointerLeave: handleSpacePanPointerLeave,
  } = useSpacePanModifier({ onDeactivate: handleSpacePanDeactivate });
  const orbitMouseButtons = useMemo(
    () => ({
      LEFT: isSpacePanActive ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.PAN,
      RIGHT: THREE.MOUSE.PAN,
    }),
    [isSpacePanActive],
  );

  const handleViewportPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const spaceModified = event.button === 0 && isSpacePanActiveRef.current;
      if (!spaceModified && event.button !== 1 && event.button !== 2) {
        return;
      }
      if (spaceModified || event.button === 1) {
        event.preventDefault();
      }
      activeOrbitPanPointerRef.current = {
        pointerId: event.pointerId,
        spaceModified,
      };
    },
    [isSpacePanActiveRef],
  );
  const finishViewportPointer = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (activeOrbitPanPointerRef.current?.pointerId === event.pointerId) {
      activeOrbitPanPointerRef.current = null;
    }
  }, []);
  const handleViewportMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (
        event.button === 1
        || (event.button === 0 && isSpacePanActiveRef.current)
      ) {
        event.preventDefault();
      }
    },
    [isSpacePanActiveRef],
  );
  const handleViewportAuxClick = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    if (event.button === 1) {
      event.preventDefault();
    }
  }, []);

  useEffect(() => {
    const handleWindowPointerEnd = (event: PointerEvent) => {
      if (activeOrbitPanPointerRef.current?.pointerId === event.pointerId) {
        activeOrbitPanPointerRef.current = null;
      }
    };
    const handleWindowBlur = () => cancelOrbitPanPointer(false);

    window.addEventListener("pointerup", handleWindowPointerEnd);
    window.addEventListener("pointercancel", handleWindowPointerEnd);
    window.addEventListener("blur", handleWindowBlur);
    return () => {
      window.removeEventListener("pointerup", handleWindowPointerEnd);
      window.removeEventListener("pointercancel", handleWindowPointerEnd);
      window.removeEventListener("blur", handleWindowBlur);
      cancelOrbitPanPointer(false);
    };
  }, [cancelOrbitPanPointer]);

  // Witty Loading Messages (Req 1.4 & Enhancements)
  const isLoading = useConverterStore((s) => s.isLoading);
  const enableWittyLoading = useSettingsStore((s) => s.enableWittyLoading);
  const wittyMsg = useWittyMessage(2000, isLoading && enableWittyLoading);

  const storeModelUrl = useConverterStore((s) => s.modelUrl);
  const batchPreviewItems = useConverterStore((s) => s.batchPreviewItems);
  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const effectiveModelUrl =
    modelUrl ?? (previewGlbUrl ? null : storeModelUrl);
  const modelSurfaceEnabled = useConverterStore((s) => s.modelSurfaceEnabled);
  const modelSurfaceFile = useConverterStore((s) => s.modelSurfaceFile);
  const modelSurfacePreviewUrl = useConverterStore((s) => s.modelSurfacePreviewUrl);
  const modelSurfaceSelectionId = useConverterStore((s) => s.modelSurfaceSelectionId);
  const modelSurfaceModelFileId = useConverterStore((s) => s.modelSurfaceModelFileId);
  const modelSurfaceFootprint = useConverterStore((s) => s.modelSurfaceFootprint);
  const modelSurfaceCandidates = useConverterStore((s) => s.modelSurfaceCandidates);
  const modelSurfacePlacement = useConverterStore((s) => s.modelSurfacePlacement);
  const modelSurfaceModelRotation = useConverterStore((s) => s.modelSurfaceModelRotation);
  const modelSurfaceLoading = useConverterStore((s) => s.modelSurfaceLoading);
  const modelSurfaceSelecting = useConverterStore((s) => s.modelSurfaceSelecting);
  const imagePreviewUrl = useConverterStore((s) => s.imagePreviewUrl);
  const aspectRatio = useConverterStore((s) => s.aspectRatio);
  const previewBaseImageUrl = useConverterStore((s) => s.previewBaseImageUrl);
  const previewRequestRevision = useConverterStore((s) => s.previewRequestRevision);
  const selectModelSurfaceFace = useConverterStore((s) => s.selectModelSurfaceFace);
  const updateModelSurfacePlacement = useConverterStore((s) => s.updateModelSurfacePlacement);
  const updateModelSurfaceModelRotation = useConverterStore((s) => s.updateModelSurfaceModelRotation);
  const fitModelSurfaceArtwork = useConverterStore((s) => s.fitModelSurfaceArtwork);
  const previewPerformanceTiming = useConverterStore((s) => s.previewPerformanceTiming);
  const generatePerformanceTiming = useConverterStore((s) => s.generatePerformanceTiming);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const colorHeightMap = useConverterStore((s) => s.color_height_map);
  const baseHeight = useConverterStore((s) => s.spacer_thick);
  const enableRelief = useConverterStore((s) => s.enable_relief);
  const autoHeightMode = useConverterStore((s) => s.autoHeightMode);
  const heightmapThumbnailUrl = useConverterStore((s) => s.heightmapThumbnailUrl);
  const heightmapUploadSessionId = useConverterStore((s) => s.heightmapUploadSessionId);
  const heightmapMaxHeight = useConverterStore((s) => s.heightmap_max_height);
  const sessionId = useConverterStore((s) => s.sessionId);
  const spacerThick = useConverterStore((s) => s.spacer_thick);
  const structureMode = useConverterStore((s) => s.structure_mode);
  const enableOutline = useConverterStore((s) => s.enable_outline);
  const outlineWidth = useConverterStore((s) => s.outline_width);
  const enableCloisonne = useConverterStore((s) => s.enable_cloisonne);
  const wireWidthMm = useConverterStore((s) => s.wire_width_mm);
  const wireHeightMm = useConverterStore((s) => s.wire_height_mm);
  const enableCoating = useConverterStore((s) => s.enable_coating);
  const coatingHeightMm = useConverterStore((s) => s.coating_height_mm);
  const colorLayers = useConverterStore((s) => s.color_layers);
  const layerHeightMm = useConverterStore((s) => s.layer_height_mm);
  const puzzleEnabled = useConverterStore((s) => s.puzzleEnabled);
  const puzzleOverlayUrl = useConverterStore((s) => s.puzzleOverlayUrl);
  const largeFormatEnabled = useConverterStore((s) => s.largeFormatEnabled);
  const largeFormatTileOverlayVisible = useConverterStore(
    (s) => s.largeFormatTileOverlayVisible,
  );
  const tileWidthMm = useConverterStore((s) => s.tileWidthMm);
  const tileHeightMm = useConverterStore((s) => s.tileHeightMm);

  // Real-time scale dimensions
  const targetWidth = useConverterStore((s) => s.target_width_mm);
  const targetHeight = useConverterStore((s) => s.target_height_mm);
  const previewWidth = useConverterStore((s) => s.preview_width_mm);
  const previewHeight = useConverterStore((s) => s.preview_height_mm);
  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth);
  const previewPixelHeight = useConverterStore((s) => s.previewPixelHeight);

  const { scaleX, scaleY } = computeScaleFactor(
    targetWidth, targetHeight, previewWidth, previewHeight
  );
  const rasterCellSize = previewWidth && previewPixelWidth && previewPixelWidth > 0
    ? previewWidth / previewPixelWidth
    : undefined;
  const colorLayerHeightMm = resolvePreviewColorLayerHeightMm(
    typeof colorLayers === "number" && typeof layerHeightMm === "number"
      ? colorLayers * layerHeightMm
      : undefined,
  );
  const heightmapReliefUrl =
    enableRelief
    && autoHeightMode === "use-heightmap"
    && Boolean(sessionId)
    && heightmapUploadSessionId === sessionId
      ? heightmapThumbnailUrl
      : null;
  const heightmapArtworkUrl = previewBaseImageUrl ?? imagePreviewUrl;

  // Keychain ring params
  const addLoop = useConverterStore((s) => s.add_loop);
  const loopWidth = useConverterStore((s) => s.loop_width);
  const loopLength = useConverterStore((s) => s.loop_length);
  const loopHole = useConverterStore((s) => s.loop_hole);
  const loopAngle = useConverterStore((s) => s.loop_angle);
  const loopOffsetX = useConverterStore((s) => s.loop_offset_x);
  const loopOffsetY = useConverterStore((s) => s.loop_offset_y);
  const loopPositionPreset = useConverterStore((s) => s.loop_position_preset);
  const enableFridgeMagnet = useConverterStore((s) => s.enable_fridge_magnet);
  const fridgeMagnets = useConverterStore((s) => s.fridge_magnets);
  const selectedFridgeMagnetId = useConverterStore((s) => s.selectedFridgeMagnetId);
  const selectFridgeMagnet = useConverterStore((s) => s.selectFridgeMagnet);
  const updateFridgeMagnetCenter = useConverterStore((s) => s.updateFridgeMagnetCenter);
  const showModelSurfaceSelector =
    modelSurfaceEnabled &&
    Boolean(modelSurfacePreviewUrl) &&
    Boolean(modelSurfaceFile) &&
    batchPreviewItems.length === 0;
  const modelSurfaceArtworkAsset = useMemo(
    () =>
      resolveModelSurfaceArtworkAsset({
        sourceImageUrl: imagePreviewUrl,
        processedPreviewUrl: previewBaseImageUrl,
        sourceAspectRatio: aspectRatio,
        modelSurfaceEnabled,
        modelFileId: modelSurfaceModelFileId,
        selectionId: modelSurfaceSelectionId,
        sessionId,
        previewRequestRevision,
        placement: modelSurfacePlacement,
      }),
    [
      aspectRatio,
      imagePreviewUrl,
      modelSurfaceEnabled,
      modelSurfaceModelFileId,
      modelSurfacePlacement,
      modelSurfaceSelectionId,
      previewBaseImageUrl,
      previewRequestRevision,
      sessionId,
    ],
  );
  const modelSurfaceBusy =
    showModelSurfaceSelector && (modelSurfaceLoading || modelSurfaceSelecting);
  const modelBounds = useConverterStore((s) => s.modelBounds);
  const colorContours = useConverterStore((s) => s.colorContours);
  const modelPreviewSpace = useMemo(
    () => (modelBounds ? createPreviewSpace(modelBounds, scaleX, scaleY) : null),
    [modelBounds, scaleX, scaleY],
  );
  const displayModelBounds = modelPreviewSpace?.displayBounds ?? null;
  const activeModelUrl = effectiveModelUrl || previewGlbUrl;
  const modelReadyKey = showModelSurfaceSelector
    ? modelSurfacePreviewUrl!
    : batchPreviewItems.length > 0
      ? JSON.stringify(batchPreviewItems.map((item) => item.url))
      : activeModelUrl ?? "empty";
  const handleModelReadyChange = useCallback((ready: boolean) => {
    setReadyModelKey(ready ? modelReadyKey : null);
  }, [modelReadyKey]);
  const activePreviewCanvasBounds =
    previewCanvasBoundsState?.sourceUrl === activeModelUrl
      ? previewCanvasBoundsState.bounds
      : null;
  // The large-format split covers the full artwork canvas (including
  // transparent margins), so anchor the outline to the canvas bounds.
  // 大画幅按完整画布（含透明边距）切分，因此轮廓锚定在画布范围上。
  const largeFormatTilePlacement = useMemo(() => {
    if (!largeFormatEnabled || !largeFormatTileOverlayVisible || !modelPreviewSpace) {
      return null;
    }
    let displayCanvasBounds: PreviewModelBounds | null = null;
    if (activePreviewCanvasBounds) {
      const min = modelPreviewSpace.toDisplayPoint({
        x: activePreviewCanvasBounds.minX,
        y: activePreviewCanvasBounds.minY,
      });
      const max = modelPreviewSpace.toDisplayPoint({
        x: activePreviewCanvasBounds.maxX,
        y: activePreviewCanvasBounds.maxY,
      });
      displayCanvasBounds = {
        minX: Math.min(min.x, max.x),
        maxX: Math.max(min.x, max.x),
        minY: Math.min(min.y, max.y),
        maxY: Math.max(min.y, max.y),
        maxZ: activePreviewCanvasBounds.maxZ,
      };
    }
    const placement = computePuzzleOverlayPlacement(
      modelPreviewSpace.displayBounds,
      spacerThick,
      enableRelief,
      colorHeightMap,
      enableOutline,
      enableCloisonne,
      wireHeightMm,
      displayCanvasBounds,
    );
    if (!placement) return null;
    return {
      bounds: {
        minX: placement.centerX - placement.width / 2,
        maxX: placement.centerX + placement.width / 2,
        minY: placement.centerY - placement.height / 2,
        maxY: placement.centerY + placement.height / 2,
      },
      z: placement.z,
    };
  }, [
    activePreviewCanvasBounds,
    colorHeightMap,
    enableCloisonne,
    enableOutline,
    enableRelief,
    largeFormatEnabled,
    largeFormatTileOverlayVisible,
    modelPreviewSpace,
    spacerThick,
    wireHeightMm,
  ]);
  const diagnosticsSamplingEnabled = diagnosticsVisible || getThreePerfDebugConfig().enabled;
  const hasPerformanceTiming = Boolean(previewPerformanceTiming || generatePerformanceTiming);

  const diagnosticsSourceLabel = batchPreviewItems.length > 0
    ? t("viewer_diagnostics_source_generate")
    : effectiveModelUrl
    ? t("viewer_diagnostics_source_generate")
    : previewGlbUrl
      ? t("viewer_diagnostics_source_preview")
      : t("viewer_diagnostics_source_idle");

  // Listen to fullscreenchange event
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  const handleGlReady = useCallback((gl: THREE.WebGLRenderer) => {
    glRef.current = gl;
    const snapshot = {
      renderer: getRendererInfoSnapshot(gl),
      heap: getHeapMemorySnapshot(),
      fps: null,
    };
    setDiagnostics((current) => ({
      ...snapshot,
      fps: current?.fps ?? snapshot.fps,
    }));
    debugThreeLog("Scene3D.gl", {
      event: "ready",
      renderer: snapshot.renderer,
      heap: snapshot.heap,
    });
    postClientLog("viewer: gl ready", {
      scope: "viewer",
      phase: "gl-ready",
      dedupeMs: 250,
      details: {
        renderer: snapshot.renderer,
        heap: snapshot.heap,
      },
    });
  }, []);

  const handleDiagnosticsSample = useCallback((snapshot: SceneDiagnosticsSnapshot) => {
    setDiagnostics(snapshot);
  }, []);

  const toggleDiagnostics = useCallback(() => {
    const next = !diagnosticsVisible;
    setDiagnosticsVisible(next);
    if (next) {
      setPerformanceVisible(false);
    }
    postClientLog("viewer: diagnostics toggled", {
      scope: "viewer",
      phase: "diagnostics-toggle",
      details: {
        open: next,
        source: batchPreviewItems.length > 0
          ? "batch-preview"
          : effectiveModelUrl
            ? "generate"
            : previewGlbUrl
              ? "preview"
              : "idle",
      },
    });
  }, [batchPreviewItems.length, diagnosticsVisible, effectiveModelUrl, previewGlbUrl]);

  const togglePerformance = useCallback(() => {
    const next = !performanceVisible;
    setPerformanceVisible(next);
    if (next) {
      setDiagnosticsVisible(false);
    }
    postClientLog("viewer: performance toggled", {
      scope: "viewer",
      phase: "performance-toggle",
      details: {
        open: next,
        has_preview_timing: Boolean(previewPerformanceTiming),
        has_generate_timing: Boolean(generatePerformanceTiming),
      },
    });
  }, [generatePerformanceTiming, performanceVisible, previewPerformanceTiming]);

  const toggleFullscreen = useCallback(() => {
    if (!containerRef.current) return;
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      containerRef.current.requestFullscreen().catch(() => {
        // Fullscreen API not available, fail silently
      });
    }
  }, []);

  const takeScreenshot = useCallback(async () => {
    const gl = glRef.current;
    if (!gl) return;
    setScreenshotNotice(null);
    // Render one frame with preserveDrawingBuffer behavior
    try {
      const dataUrl = gl.domElement.toDataURL("image/png");
      const bytes = Uint8Array.from(atob(dataUrl.split(',')[1]), char => char.charCodeAt(0));
      const outcome = await saveGeneratedFile(new Blob([bytes], { type: 'image/png' }), `lumina-3d-screenshot-${Date.now()}.png`, 'screenshot');
      setScreenshotNotice(outcome === 'canceled' ? null : t(outcome === 'saved' ? 'file_save_saved' : 'file_save_download_started'));
    } catch (err) {
      setScreenshotNotice(t(err instanceof Error && err.message === 'file_save_too_large' ? 'file_save_too_large' : 'file_save_failed'));
    }
  }, [t]);

  useEffect(() => {
    postClientLog("viewer: source updated", {
      scope: "viewer",
      phase: "source-updated",
      dedupeMs: 250,
      details: {
        model_url: effectiveModelUrl ?? null,
        preview_glb_url: previewGlbUrl ?? null,
      },
    });
  }, [effectiveModelUrl, previewGlbUrl]);

  // Check if Fullscreen API is available
  const fullscreenSupported = typeof document.fullscreenElement !== "undefined";

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full"
      data-testid="scene3d-container"
      data-space-pan-active={isSpacePanActive || undefined}
      onMouseDown={handleViewportMouseDown}
      onAuxClick={handleViewportAuxClick}
      onPointerEnter={handleSpacePanPointerEnter}
      onPointerLeave={handleSpacePanPointerLeave}
      onPointerDown={handleViewportPointerDown}
      onPointerUp={finishViewportPointer}
      onPointerCancel={finishViewportPointer}
    >
      {screenshotNotice && <div role="status" className="absolute bottom-4 left-4 z-30 rounded bg-[var(--surface-panel-strong)] p-2 text-sm">{screenshotNotice}</div>}
      {/* Beginner-tutorial anchor: the visible 3D area between the docks
          (the canvas itself spans underneath both docks). */}
      <div
        aria-hidden="true"
        data-tutorial="viewport-3d"
        className="pointer-events-none absolute inset-y-0"
        style={{
          left: "var(--lumina-left-dock-width, 0px)",
          right: "var(--lumina-right-dock-width, 0px)",
        }}
      />
      {/* Floating action buttons — top-right with right-dock avoidance.
       * 浮动按钮组：右上角悬浮，依赖 WidgetWorkspace 注入的
       * `--lumina-right-dock-width` CSS 变量自动避开右侧坞内的 widget。
       */}
      <div
        className="absolute z-10 flex gap-0.5 rounded-full border border-slate-200/80 bg-slate-100/85 p-1 backdrop-blur-sm dark:border-slate-700/80 dark:bg-slate-900/70"
        style={{
          top: "12px",
          right: "calc(var(--lumina-right-dock-width, 0px) + 12px)",
        }}
      >
        <HeaderTooltip
          label={t("viewer_performance_toggle")}
          suppressed={performanceVisible || diagnosticsVisible}
        >
          <button
            onClick={togglePerformance}
            aria-pressed={performanceVisible}
            aria-label={t("viewer_performance_toggle")}
            data-testid="scene3d-performance-toggle"
            className="ghost-control inline-flex h-7 w-7 items-center justify-center rounded-full text-slate-600 dark:text-slate-300"
          >
            <StopwatchIcon className="h-4 w-4" />
          </button>
        </HeaderTooltip>
        <HeaderTooltip
          label={t("viewer_diagnostics_toggle")}
          suppressed={performanceVisible || diagnosticsVisible}
        >
          <button
            onClick={toggleDiagnostics}
            aria-pressed={diagnosticsVisible}
            aria-label={t("viewer_diagnostics_toggle")}
            data-testid="scene3d-diagnostics-toggle"
            className="ghost-control inline-flex h-7 w-7 items-center justify-center rounded-full text-slate-600 dark:text-slate-300"
          >
            <ActivityIcon className="h-4 w-4" />
          </button>
        </HeaderTooltip>
        {fullscreenSupported && (
          <HeaderTooltip
            label={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
            suppressed={performanceVisible || diagnosticsVisible}
          >
            <button
              onClick={toggleFullscreen}
              aria-label={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
              className="ghost-control inline-flex h-7 w-7 items-center justify-center rounded-full text-slate-600 dark:text-slate-300"
            >
              {isFullscreen ? <MinimizeIcon className="h-4 w-4" /> : <MaximizeIcon className="h-4 w-4" />}
            </button>
          </HeaderTooltip>
        )}
        <HeaderTooltip
          label={t("viewer_screenshot")}
          suppressed={performanceVisible || diagnosticsVisible}
        >
          <button
            onClick={takeScreenshot}
            aria-label={t("viewer_screenshot")}
            className="ghost-control inline-flex h-7 w-7 items-center justify-center rounded-full text-slate-600 dark:text-slate-300"
          >
            <CameraIcon className="h-4 w-4" />
          </button>
        </HeaderTooltip>
      </div>

      {performanceVisible && (
        <div
          role="dialog"
          aria-label={t("viewer_performance_title")}
          className="absolute z-10 w-[300px] rounded-xl border px-3 py-2 text-[11px] shadow-xl"
          style={{
            top: "56px",
            right: "calc(var(--lumina-right-dock-width, 0px) + 12px)",
            borderColor: "var(--surface-outline)",
            background: "color-mix(in srgb, var(--surface-panel-strong) 90%, transparent)",
            color: "var(--surface-text-muted)",
          }}
          data-testid="scene3d-performance-panel"
        >
          <div className="mb-2">
            <span className="text-xs font-semibold text-slate-900 dark:text-slate-50">
              {t("viewer_performance_title")}
            </span>
          </div>
          {hasPerformanceTiming ? (
            <div className="space-y-3">
              <TimingSection
                title={t("viewer_performance_preview_title")}
                timing={previewPerformanceTiming}
                rows={[
                  { key: "total_ms", label: t("viewer_performance_total") },
                  { key: "upload_ms", label: t("viewer_performance_upload") },
                  { key: "worker_ms", label: t("viewer_performance_worker") },
                  { key: "pickle_load_ms", label: t("viewer_performance_pickle_load") },
                  { key: "segmented_glb_ms", label: t("viewer_performance_segmented_glb") },
                  { key: "palette_ms", label: t("viewer_performance_palette") },
                ]}
              />
              <TimingSection
                title={t("viewer_performance_generate_title")}
                timing={generatePerformanceTiming}
                rows={[
                  { key: "total_ms", label: t("viewer_performance_total") },
                  { key: "worker_ms", label: t("viewer_performance_worker") },
                  { key: "overhead_ms", label: t("viewer_performance_overhead") },
                ]}
              />
            </div>
          ) : (
            <p className="text-[11px]" data-testid="scene3d-performance-empty">
              {t("viewer_performance_empty")}
            </p>
          )}
        </div>
      )}

      {diagnosticsVisible && (
        <div
          role="dialog"
          aria-label={t("viewer_diagnostics_title")}
          className="absolute z-10 w-[260px] rounded-xl border px-3 py-2 text-[11px] shadow-xl"
          style={{
            top: "56px",
            right: "calc(var(--lumina-right-dock-width, 0px) + 12px)",
            borderColor: "var(--surface-outline)",
            background: "color-mix(in srgb, var(--surface-panel-strong) 90%, transparent)",
            color: "var(--surface-text-muted)",
          }}
          data-testid="scene3d-diagnostics-panel"
        >
          <div className="mb-2">
            <span className="text-xs font-semibold text-slate-900 dark:text-slate-50">
              {t("viewer_diagnostics_title")}
            </span>
          </div>
          <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <span>{t("viewer_diagnostics_source")}</span>
            <span className="truncate text-right">{diagnosticsSourceLabel}</span>
            <span>{t("viewer_diagnostics_fps")}</span>
            <span className="text-right flex items-center justify-end gap-1.5">
              {diagnostics?.fps != null ? (
                <>
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full flex-shrink-0"
                    style={{
                      backgroundColor:
                        diagnostics.fps >= 50
                          ? "#22c55e"
                          : diagnostics.fps >= 30
                            ? "#eab308"
                            : "#ef4444",
                    }}
                  />
                  {diagnostics.fps.toFixed(1)}
                </>
              ) : (
                "—"
              )}
            </span>
            <span>{t("viewer_diagnostics_frame_time")}</span>
            <span className="text-right">
              {diagnostics?.fps != null && diagnostics.fps > 0
                ? `${(1000 / diagnostics.fps).toFixed(1)} ms`
                : "—"}
            </span>
            <span>{t("viewer_diagnostics_js_heap")}</span>
            <span className="text-right">
              {diagnostics?.heap
                ? `${diagnostics.heap.used_js_heap_mb} / ${diagnostics.heap.total_js_heap_mb} MB`
                : t("viewer_diagnostics_js_heap_unavailable")}
            </span>
            <span>{t("viewer_diagnostics_triangles")}</span>
            <span className="text-right">{diagnostics?.renderer.triangles ?? "—"}</span>
            <span>{t("viewer_diagnostics_draw_calls")}</span>
            <span className="text-right">{diagnostics?.renderer.calls ?? "—"}</span>
            <span>{t("viewer_diagnostics_textures")}</span>
            <span className="text-right">{diagnostics?.renderer.textures ?? "—"}</span>
            <span>{t("viewer_diagnostics_canvas")}</span>
            <span className="text-right">
              {diagnostics?.renderer
                ? `${diagnostics.renderer.canvas_width}×${diagnostics.renderer.canvas_height} @${diagnostics.renderer.pixel_ratio}x`
                : "—"}
            </span>
          </div>
        </div>
      )}

      {/* Loading indicator is now 3D-anchored inside Canvas */}

      {!deferInitialization && <SceneErrorBoundary
        key={sceneAttempt}
        onError={handleSceneError}
        fallback={(
          <div
            role="alert"
            className="absolute inset-y-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-sm"
            style={{
              left: "var(--lumina-left-dock-width, 0px)",
              right: "var(--lumina-right-dock-width, 0px)",
              color: "var(--surface-text-muted)",
            }}
          >
            <p>{t("app_3d_scene_error")}</p>
            <p>{t("viewer_scene_recovery_hint")}</p>
            <Button label={t("viewer_retry_scene")} onClick={() => setSceneAttempt((attempt) => attempt + 1)} />
          </div>
        )}
      ><Canvas
        ref={requireCanvasContext}
        style={visibleSnapshot ? { visibility: "hidden" } : undefined}
        frameloop={suspended ? "never" : "demand"}
        camera={{
          position: [...DEFAULT_CAMERA_POSITION],
          fov: 45,
          near: DEFAULT_CAMERA_CLIPPING_PLANES.near,
          far: DEFAULT_CAMERA_CLIPPING_PLANES.far,
        }}
        gl={{ preserveDrawingBuffer: true, toneMapping: THREE.NeutralToneMapping }}
        onPointerMissed={() => {
          if (enableFridgeMagnet) {
            selectFridgeMagnet(null);
          }
        }}
        onCreated={({ gl }) => {
          gl.setClearColor(themeColors.canvasClearColor);
          const canvas = gl.domElement;
          postClientLog("viewer: canvas created", {
            scope: "viewer",
            phase: "canvas-created",
            dedupeMs: 250,
            details: {
              renderer: getRendererInfoSnapshot(gl),
              heap: getHeapMemorySnapshot(),
            },
          });
          canvas.addEventListener("webglcontextlost", (e) => {
            e.preventDefault();
            postClientLog("viewer: webgl context lost", {
              scope: "viewer",
              phase: "context-lost",
              method: "warn",
              details: {
                canvas_width: canvas.width,
                canvas_height: canvas.height,
              },
            });
          });
          canvas.addEventListener("webglcontextrestored", () => {
            gl.setSize(canvas.clientWidth, canvas.clientHeight);
            postClientLog("viewer: webgl context restored", {
              scope: "viewer",
              phase: "context-restored",
              details: {
                renderer: getRendererInfoSnapshot(gl),
                heap: getHeapMemorySnapshot(),
              },
            });
          });
        }}
      >
        <ScreenshotHelper onGlReady={handleGlReady} />
        <SceneTransitionBridge
          snapshotKey={transitionKey}
          getCurrentKey={getTransitionKey}
          snapshot={visibleSnapshot}
          ready={environmentReady && bedReady && (modelReadyKey === "empty" || readyModelKey === modelReadyKey)}
          captureRef={captureTransitionRef}
          onFrameReady={handleFrameReady}
        />
        <RendererDiagnosticsBridge
          enabled={diagnosticsSamplingEnabled}
          onSample={handleDiagnosticsSample}
        />
        <CameraDebugHelper />
        <PreviewCameraRangeBridge
          active={
            !showModelSurfaceSelector &&
            batchPreviewItems.length === 0 &&
            Boolean(effectiveModelUrl || previewGlbUrl)
          }
          modelBounds={modelBounds}
          scaleX={scaleX}
          scaleY={scaleY}
        />
        <CameraDepthPrecisionGuard />
        <ThemeUpdater />
        <CanvasInteractionBridge />
        <SceneErrorBoundary
          key={environmentAttempt}
          onError={handleEnvironmentError}
          fallback={<><ambientLight intensity={1} /><SceneAssetReady onReadyChange={setEnvironmentReady} /></>}
        ><Suspense fallback={<ambientLight intensity={1} />}>
          <Environment
            files={LIGHTING_CONFIG.environment.hdrFile}
            background={false}
            environmentIntensity={themeColors.environmentIntensity}
          />
          <SceneAssetReady onReadyChange={setEnvironmentReady} />
        </Suspense></SceneErrorBoundary>
        <directionalLight
          position={[...LIGHTING_CONFIG.keyLight.position]}
          intensity={themeColors.keyLightIntensity}
          color={themeColors.keyLightColor}
        />
        <PreviewOrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.1}
          minDistance={10}
          maxDistance={2000}
          mouseButtons={orbitMouseButtons}
        />
        <BedPlatform
          surfaceModelActive={showModelSurfaceSelector}
          gridVisible={showModelSurfaceSelector ? modelSurfaceBedGridVisible : true}
          onReadyChange={setBedReady}
        />
        {showModelSurfaceSelector && modelSurfacePreviewUrl && modelSurfaceFile ? (
          <ModelSurfaceSelector3D
            file={modelSurfaceFile}
            artworkAsset={modelSurfaceArtworkAsset}
            footprint={modelSurfaceFootprint}
            surfaceCandidates={modelSurfaceCandidates}
            placement={modelSurfacePlacement}
            modelRotation={modelSurfaceModelRotation}
            selectionId={modelSurfaceSelectionId}
            bedGridVisible={modelSurfaceBedGridVisible}
            selectionReady={Boolean(modelSurfaceSelectionId)}
            selecting={modelSurfaceLoading || modelSurfaceSelecting}
            onSelectFace={(faceIndex, candidateId) => {
              void selectModelSurfaceFace(faceIndex, candidateId);
            }}
            onUpdatePlacement={updateModelSurfacePlacement}
            onUpdateModelRotation={updateModelSurfaceModelRotation}
            onFitArtwork={fitModelSurfaceArtwork}
            onBedGridVisibleChange={setModelSurfaceBedGridVisible}
            onReadyChange={handleModelReadyChange}
          />
        ) : batchPreviewItems.length > 0 ? (
          <Suspense fallback={null}>
            <BatchPreviewModels
              items={batchPreviewItems}
              colorRemapMap={colorRemapMap}
              colorHeightMap={colorHeightMap}
              baseHeight={baseHeight}
              enableRelief={enableRelief}
              spacerThick={spacerThick}
              structureMode={structureMode}
              enableOutline={enableOutline}
              outlineWidth={outlineWidth}
              enableCloisonne={enableCloisonne}
              wireWidthMm={wireWidthMm}
              wireHeightMm={wireHeightMm}
              enableFridgeMagnet={enableFridgeMagnet}
              rasterCellSize={rasterCellSize}
              colorLayerHeightMm={colorLayerHeightMm}
            />
            <SceneAssetReady onReadyChange={handleModelReadyChange} />
          </Suspense>
        ) : effectiveModelUrl ? (
          <Suspense fallback={null}>
            <InteractiveModelViewer
              url={effectiveModelUrl}
              sourceRole="generated"
              colorRemapMap={colorRemapMap}
              colorHeightMap={colorHeightMap}
              baseHeight={baseHeight}
              enableRelief={enableRelief}
              scaleX={scaleX}
              scaleY={scaleY}
              spacerThick={spacerThick}
              structureMode={structureMode}
              enableOutline={enableOutline}
              outlineWidth={outlineWidth}
              enableCloisonne={enableCloisonne}
              wireWidthMm={wireWidthMm}
              wireHeightMm={wireHeightMm}
              enableFridgeMagnet={enableFridgeMagnet}
              rasterCellSize={rasterCellSize}
              puzzleOverlayEnabled={puzzleEnabled && Boolean(puzzleOverlayUrl)}
              puzzleOverlayUrl={puzzleOverlayUrl}
              colorLayerHeightMm={colorLayerHeightMm}
              onPreviewCanvasBoundsChange={handlePreviewCanvasBoundsChange}
            />
            <SceneAssetReady onReadyChange={handleModelReadyChange} />
          </Suspense>
        ) : previewGlbUrl ? (
          <Suspense fallback={null}>
            <InteractiveModelViewer
              url={previewGlbUrl}
              sourceRole="quick-preview"
              colorRemapMap={colorRemapMap}
              colorHeightMap={colorHeightMap}
              baseHeight={baseHeight}
              enableRelief={enableRelief}
              scaleX={scaleX}
              scaleY={scaleY}
              spacerThick={spacerThick}
              structureMode={structureMode}
              enableOutline={enableOutline}
              outlineWidth={outlineWidth}
              enableCloisonne={enableCloisonne}
              wireWidthMm={wireWidthMm}
              wireHeightMm={wireHeightMm}
              enableFridgeMagnet={enableFridgeMagnet}
              rasterCellSize={rasterCellSize}
              puzzleOverlayEnabled={puzzleEnabled && Boolean(puzzleOverlayUrl)}
              puzzleOverlayUrl={puzzleOverlayUrl}
              colorLayerHeightMm={colorLayerHeightMm}
              onPreviewCanvasBoundsChange={handlePreviewCanvasBoundsChange}
              heightmapReliefUrl={heightmapReliefUrl}
              heightmapArtworkUrl={heightmapArtworkUrl}
              heightmapReliefMaxHeightMm={heightmapMaxHeight}
              enableCoating={enableCoating}
              coatingHeightMm={coatingHeightMm}
              printingLayerHeightMm={layerHeightMm ?? 0.08}
            />
            <SceneAssetReady onReadyChange={handleModelReadyChange} />
          </Suspense>
        ) : null}
        {batchPreviewItems.length === 0 && addLoop && displayModelBounds && (
          <KeychainRing3D
            enabled={addLoop}
            width={loopWidth}
            length={loopLength}
            hole={loopHole}
            angle={loopAngle}
            offsetX={loopOffsetX}
            offsetY={loopOffsetY}
            positionPreset={loopPositionPreset}
            modelBounds={displayModelBounds}
            contours={colorContours}
            contourCanvasBounds={activePreviewCanvasBounds}
            contourToDisplayPoint={modelPreviewSpace?.toDisplayPoint}
            cameraPanModifierActive={isSpacePanActive}
          />
          )}
        {batchPreviewItems.length === 0
          && !showModelSurfaceSelector
          && Boolean(activeModelUrl)
          && largeFormatTilePlacement && (
          <LargeFormatTileOverlay3D
            bounds={largeFormatTilePlacement.bounds}
            z={largeFormatTilePlacement.z}
            totalWidthMm={targetWidth}
            totalHeightMm={resolveLargeFormatTotalHeightMm(
              targetWidth,
              targetHeight,
              previewPixelWidth,
              previewPixelHeight,
            )}
            tileWidthMm={tileWidthMm}
            tileHeightMm={tileHeightMm}
          />
        )}
        {batchPreviewItems.length === 0 && enableFridgeMagnet && displayModelBounds && fridgeMagnets.length > 0 && (
          <FridgeMagnet3D
            enabled={enableFridgeMagnet}
            magnets={fridgeMagnets}
            selectedMagnetId={selectedFridgeMagnetId}
            modelBounds={displayModelBounds}
            onSelectMagnet={selectFridgeMagnet}
            onUpdateMagnetCenter={updateFridgeMagnetCenter}
            cameraPanModifierActive={isSpacePanActive}
          />
        )}

        {/* 3D-Anchored Loading & Witty Messages (Req 1.4) */}
        {isLoading && (
          <Html center position={[0, 0, 80]} zIndexRange={[100, 0]}>
            <div
              className="flex flex-col items-center justify-center gap-4 select-none pointer-events-none"
              data-testid="loading-overlay"
            >
              <div className="relative flex items-center justify-center p-4">
                <div className="relative flex h-20 w-20 items-center justify-center">
                  <div className="absolute inset-0 rgb-loader-ring" />
                  <div className="h-3 w-3 rounded-full bg-slate-100/90 dark:bg-slate-50/90" />
                </div>
              </div>
              {enableWittyLoading && (
                <div className="rounded-full border border-white/10 bg-slate-900/92 px-4 py-2">
                  <p className="whitespace-nowrap text-sm font-medium tracking-wide text-white">
                    {wittyMsg}
                  </p>
                </div>
              )}
            </div>
          </Html>
        )}
      </Canvas></SceneErrorBoundary>}
      {environmentFailed && (
        <div
          role="status"
          className="absolute bottom-3 z-20 flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs"
          style={{
            left: "calc(var(--lumina-left-dock-width, 0px) + 12px)",
            right: "calc(var(--lumina-right-dock-width, 0px) + 12px)",
            borderColor: "var(--surface-outline)",
            background: "var(--surface-panel-strong)",
            color: "var(--surface-text-muted)",
          }}
        >
          <span>{t("viewer_lighting_fallback")}</span>
          <Button label={t("viewer_retry_lighting")} size="sm" onClick={retryEnvironment} />
        </div>
      )}
      {visibleSnapshot && (
        <canvas
          ref={snapshotCanvasRef}
          width={visibleSnapshot.image.width}
          height={visibleSnapshot.image.height}
          className="absolute inset-0 h-full w-full"
          aria-hidden="true"
          data-testid="scene3d-transition-snapshot"
        />
      )}

      {modelSurfaceBusy ? (
        <div
          role="status"
          aria-live="polite"
          aria-label={t(
            modelSurfaceLoading
              ? "model_surface_loading_analysis"
              : "model_surface_status_selecting",
          )}
          aria-busy="true"
          data-testid="model-surface-loading-overlay"
          className="absolute inset-0 z-50 flex cursor-wait select-none items-center justify-center bg-slate-100/58 backdrop-blur-[1px] dark:bg-slate-950/58"
        >
          <div className="flex flex-col items-center gap-3">
            <div className="relative flex h-16 w-16 items-center justify-center">
              <div className="absolute inset-0 rgb-loader-ring" />
              <div className="h-2.5 w-2.5 rounded-full bg-slate-700/90 dark:bg-slate-100/90" />
            </div>
            <span className="rounded-lg border border-slate-200/80 bg-slate-100/90 px-3 py-2 text-xs font-semibold text-slate-700 shadow-[var(--shadow-control)] dark:border-slate-700/80 dark:bg-slate-950/90 dark:text-slate-100">
              {t(
                modelSurfaceLoading
                  ? "model_surface_loading_analysis"
                  : "model_surface_status_selecting",
              )}
            </span>
          </div>
        </div>
      ) : null}

    </div>
  );
}

export default Scene3D;
