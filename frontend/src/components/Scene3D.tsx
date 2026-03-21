import { Suspense, useRef, useState, useEffect, useCallback } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Environment } from "@react-three/drei";
import { LIGHTING_CONFIG } from "./lightingConfig";
import * as THREE from "three";
import ModelViewer from "./ModelViewer";
import InteractiveModelViewer from "./InteractiveModelViewer";
import BedPlatform from "./BedPlatform";
import KeychainRing3D from "./KeychainRing3D";
import { useConverterStore } from "../stores/converterStore";
import { computeScaleFactor } from "../utils/scaleUtils";
import { useI18n } from "../i18n/context";
import { useThemeConfig } from "../hooks/useThemeConfig";

interface Scene3DProps {
  modelUrl?: string;
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
    (window as any).__luminaCameraDebug = () => {
      const pos = camera.position;
      const oc = controls as any;
      const target = oc?.target ?? { x: 0, y: 0, z: 0 };
      const info = {
        cameraPosition: { x: +pos.x.toFixed(2), y: +pos.y.toFixed(2), z: +pos.z.toFixed(2) },
        orbitTarget: { x: +target.x.toFixed(2), y: +target.y.toFixed(2), z: +target.z.toFixed(2) },
        fov: (camera as THREE.PerspectiveCamera).fov,
      };
      console.log("📷 Camera Debug:", JSON.stringify(info, null, 2));
      return info;
    };
  }, [camera, controls]);
  return null;
}

/**
 * Inner component that syncs the Canvas clear color with the active theme.
 * Canvas 内部组件，将清除色与当前主题同步。
 */
function ThemeUpdater() {
  const { gl } = useThree();
  const themeColors = useThemeConfig();
  useEffect(() => {
    gl.setClearColor(themeColors.canvasClearColor);
  }, [gl, themeColors.canvasClearColor]);
  return null;
}

function Scene3D({ modelUrl }: Scene3DProps) {
  const { t } = useI18n();
  const themeColors = useThemeConfig();
  const containerRef = useRef<HTMLDivElement>(null);
  const glRef = useRef<THREE.WebGLRenderer | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const colorHeightMap = useConverterStore((s) => s.color_height_map);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const baseHeight = useConverterStore((s) => s.spacer_thick);
  const enableRelief = useConverterStore((s) => s.enable_relief);
  const isLoading = useConverterStore((s) => s.isLoading);
  const setSelectedColor = useConverterStore((s) => s.setSelectedColor);
  const spacerThick = useConverterStore((s) => s.spacer_thick);
  const structureMode = useConverterStore((s) => s.structure_mode);

  // Real-time scale dimensions
  const targetWidth = useConverterStore((s) => s.target_width_mm);
  const targetHeight = useConverterStore((s) => s.target_height_mm);
  const previewWidth = useConverterStore((s) => s.preview_width_mm);
  const previewHeight = useConverterStore((s) => s.preview_height_mm);

  const { scaleX, scaleY } = computeScaleFactor(
    targetWidth, targetHeight, previewWidth, previewHeight
  );

  // Keychain ring params
  const addLoop = useConverterStore((s) => s.add_loop);
  const loopWidth = useConverterStore((s) => s.loop_width);
  const loopLength = useConverterStore((s) => s.loop_length);
  const loopHole = useConverterStore((s) => s.loop_hole);
  const modelBounds = useConverterStore((s) => s.modelBounds);

  // Listen to fullscreenchange event
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  const handleGlReady = useCallback((gl: THREE.WebGLRenderer) => {
    glRef.current = gl;
  }, []);

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

  const takeScreenshot = useCallback(() => {
    const gl = glRef.current;
    if (!gl) return;
    // Render one frame with preserveDrawingBuffer behavior
    try {
      const dataUrl = gl.domElement.toDataURL("image/png");
      const link = document.createElement("a");
      link.download = `lumina-3d-screenshot-${Date.now()}.png`;
      link.href = dataUrl;
      link.click();
    } catch (err) {
      console.warn("Screenshot failed:", err);
    }
  }, []);

  const handleColorClick = useCallback(
    (hex: string | null) => {
      setSelectedColor(hex);
    },
    [setSelectedColor],
  );

  // Check if Fullscreen API is available
  const fullscreenSupported = typeof document.fullscreenElement !== "undefined";

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full"
      data-testid="scene3d-container"
    >
      {/* Toolbar buttons */}
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        {fullscreenSupported && (
          <button
            onClick={toggleFullscreen}
            className="px-2 py-1 rounded text-xs font-medium bg-white/80 text-gray-700 hover:bg-gray-200 dark:bg-gray-700/80 dark:text-gray-200 dark:hover:bg-gray-600 transition-colors backdrop-blur-sm"
            aria-label={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
            title={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
          >
            {isFullscreen ? "⛶" : "⛶"} {isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
          </button>
        )}
        <button
          onClick={takeScreenshot}
          className="px-2 py-1 rounded text-xs font-medium bg-white/80 text-gray-700 hover:bg-gray-200 dark:bg-gray-700/80 dark:text-gray-200 dark:hover:bg-gray-600 transition-colors backdrop-blur-sm"
          aria-label={t("viewer_screenshot")}
          title={t("viewer_screenshot")}
        >
          {t("viewer_screenshot")}
        </button>
      </div>

      {/* Loading indicator overlay (Req 1.4) */}
      {isLoading && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          data-testid="loading-overlay"
        >
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-gray-300 border-t-blue-500" />
        </div>
      )}

      <Canvas
        camera={{ position: [1.3, -129.08, 465.36], fov: 45 }}
        gl={{ preserveDrawingBuffer: true }}
        onPointerMissed={() => {
          // Skip deselection if a color mesh was just clicked via native event
          const hitRef = (window as unknown as Record<string, unknown>).__luminaColorHitRef as
            | React.RefObject<boolean>
            | undefined;
          if (hitRef?.current) {
            hitRef.current = false;
            return;
          }
          setSelectedColor(null);
        }}
        onCreated={({ gl }) => {
          gl.setClearColor(themeColors.canvasClearColor);
          const canvas = gl.domElement;
          canvas.addEventListener("webglcontextlost", (e) => {
            e.preventDefault();
          });
          canvas.addEventListener("webglcontextrestored", () => {
            gl.setSize(canvas.clientWidth, canvas.clientHeight);
          });
        }}
      >
        <ScreenshotHelper onGlReady={handleGlReady} />
        <CameraDebugHelper />
        <ThemeUpdater />
        <Suspense fallback={null}>
          <Environment
            files={LIGHTING_CONFIG.environment.hdrFile}
            background={false}
            environmentIntensity={themeColors.environmentIntensity}
          />
        </Suspense>
        <directionalLight
          position={[...LIGHTING_CONFIG.keyLight.position]}
          intensity={themeColors.keyLightIntensity}
          color={themeColors.keyLightColor}
        />
        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.1}
          minDistance={10}
          maxDistance={2000}
        />
        <BedPlatform />
        {modelUrl ? (
          <Suspense fallback={null}>
            <ModelViewer url={modelUrl} />
          </Suspense>
        ) : previewGlbUrl ? (
          <Suspense fallback={null}>
            <InteractiveModelViewer
              url={previewGlbUrl}
              colorRemapMap={colorRemapMap}
              colorHeightMap={colorHeightMap}
              selectedColor={selectedColor}
              baseHeight={baseHeight}
              enableRelief={enableRelief}
              onColorClick={handleColorClick}
              scaleX={scaleX}
              scaleY={scaleY}
              spacerThick={spacerThick}
              structureMode={structureMode}
            />
          </Suspense>
        ) : null}
        {addLoop && modelBounds && (
          <KeychainRing3D
            enabled={addLoop}
            width={loopWidth}
            length={loopLength}
            hole={loopHole}
            modelBounds={modelBounds}
          />
        )}
      </Canvas>
    </div>
  );
}

export default Scene3D;
