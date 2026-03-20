import { useEffect, useMemo, useState } from "react";
import type { WorkspaceMode, WorkspaceViewport } from "../types/workspace";

function readViewport(): WorkspaceViewport {
  if (typeof window === "undefined") {
    return { width: 1440, height: 900, dpr: 1 };
  }

  return {
    width: window.innerWidth,
    height: window.innerHeight,
    dpr: window.devicePixelRatio || 1,
  };
}

export function resolveWorkspaceMode({
  width,
  height,
  dpr,
}: WorkspaceViewport): WorkspaceMode {
  const aspect = width / Math.max(height, 1);
  const highDensity = dpr >= 2.25;

  if (
    width < 2000 ||
    height < 1040 ||
    (highDensity && width < 2200) ||
    (aspect < 1.45 && height < 1180)
  ) {
    return "compact";
  }

  if (
    (width >= 3000 && height >= 1300) ||
    (width >= 2600 && height >= 1100 && aspect >= 2.2)
  ) {
    return "wide";
  }

  return "standard";
}

export function useWorkspaceMode() {
  const [viewport, setViewport] = useState<WorkspaceViewport>(() => readViewport());

  useEffect(() => {
    const updateViewport = () => setViewport(readViewport());
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => window.removeEventListener("resize", updateViewport);
  }, []);

  return useMemo(() => {
    const mode = resolveWorkspaceMode(viewport);
    return {
      ...viewport,
      mode,
      isCompact: mode === "compact",
      isStandard: mode === "standard",
      isWide: mode === "wide",
    };
  }, [viewport]);
}
