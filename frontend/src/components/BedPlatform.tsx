import { useMemo, useEffect, useLayoutEffect, useState } from "react";
import { useThree } from "@react-three/fiber";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { getMachineBedModelUrl } from "../api/system";
import { electronAPI } from "../integrations/electron";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { getSlicerLogoSource } from "../utils/slicerBranding";
import { disposeMeshResources } from "../utils/threeDisposal";
import { resolveBedPlatformColors } from "./themeConfig";
import {
  LUMINA_BED_MARK_URL,
  createBedTextureRequest,
  stageBedTextureReplacement,
} from "./bedPlatformTexture";
import {
  BED_BODY_MATERIAL_INDEX,
  BED_SURFACE_MATERIAL_INDEX,
  computeBedPreviewCameraPose,
  createBedPlatformMesh,
  createFallbackBedGeometry,
  loadNativeBedGeometrySource,
  prepareNativeBedGeometry,
} from "./bedPlatformGeometry";

function useBedImage(source: string | null): { image: HTMLImageElement | null; ready: boolean } {
  const [loaded, setLoaded] = useState<{ source: string; image: HTMLImageElement | null } | null>(null);

  useEffect(() => {
    if (!source) return;
    let active = true;
    const image = new Image();
    const handleLoad = () => {
      if (active) setLoaded({ source, image });
    };
    const handleError = () => {
      if (active) setLoaded({ source, image: null });
    };
    image.addEventListener("load", handleLoad, { once: true });
    image.addEventListener("error", handleError, { once: true });
    image.src = source;
    return () => {
      active = false;
      image.removeEventListener("load", handleLoad);
      image.removeEventListener("error", handleError);
    };
  }, [source]);

  return {
    image: loaded?.source === source ? loaded.image : null,
    ready: !source || loaded?.source === source,
  };
}

function imageElementToDataUrl(image: HTMLImageElement | null): string | null {
  if (!image) return null;
  if (image.currentSrc.startsWith("data:")) return image.currentSrc;

  const sourceWidth = image.naturalWidth || image.width;
  const sourceHeight = image.naturalHeight || image.height;
  if (sourceWidth <= 0 || sourceHeight <= 0) return null;

  const canvas = document.createElement("canvas");
  canvas.width = sourceWidth;
  canvas.height = sourceHeight;
  const context = canvas.getContext("2d");
  if (!context) return null;

  try {
    context.drawImage(image, 0, 0, sourceWidth, sourceHeight);
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
}

function useNativeBedGeometry(
  deviceProfileId: string,
  printableWidthMm: number,
  printableHeightMm: number,
): { geometry: THREE.BufferGeometry | null; ready: boolean } {
  const modelUrl = useMemo(
    () => getMachineBedModelUrl(deviceProfileId),
    [deviceProfileId],
  );
  const requestKey = JSON.stringify([deviceProfileId, modelUrl, printableWidthMm, printableHeightMm]);
  const [loaded, setLoaded] = useState<{
    key: string;
    geometry: THREE.BufferGeometry | null;
  } | null>(null);

  useEffect(() => {
    if (!modelUrl) {
      setLoaded(null);
      return;
    }
    let active = true;
    let ownedGeometry: THREE.BufferGeometry | null = null;
    const loader = new STLLoader();
    void loadNativeBedGeometrySource({
      desktopModelReader: electronAPI?.getNativeBedModel,
      deviceProfileId,
      loader,
      modelUrl,
    })
      .then((sourceGeometry) => {
        if (!sourceGeometry) {
          if (active) setLoaded({ key: requestKey, geometry: null });
          return;
        }
        const prepared = prepareNativeBedGeometry(
          sourceGeometry,
          printableWidthMm,
          printableHeightMm,
        );
        sourceGeometry.dispose();
        if (!active) {
          prepared.dispose();
          return;
        }
        ownedGeometry = prepared;
        setLoaded({ key: requestKey, geometry: prepared });
      })
      .catch(() => {
        if (active) setLoaded({ key: requestKey, geometry: null });
      });
    return () => {
      active = false;
      ownedGeometry?.dispose();
    };
  }, [deviceProfileId, modelUrl, printableWidthMm, printableHeightMm, requestKey]);

  return {
    geometry: loaded?.key === requestKey ? loaded.geometry : null,
    ready: !modelUrl || loaded?.key === requestKey,
  };
}

interface BedPlatformProps {
  surfaceModelActive?: boolean;
  gridVisible?: boolean;
  onReadyChange?: (ready: boolean) => void;
}

export default function BedPlatform({
  surfaceModelActive = false,
  gridVisible = true,
  onReadyChange,
}: BedPlatformProps) {
  const bed_label = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);
  const modelUrl = useConverterStore((s) => s.modelUrl);
  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const batchPreviewItems = useConverterStore((s) => s.batchPreviewItems);
  const projectSettings = useConverterStore((s) => s.projectSettings);
  const theme = useSettingsStore((s) => s.theme);
  const globalBuildPlateId = useSettingsStore((s) => s.buildPlateId);
  const globalDeviceProfileId = useSettingsStore((s) => s.deviceProfileId);
  const globalSlicerSoftware = useSettingsStore((s) => s.slicerSoftware);
  const buildPlateId = projectSettings?.buildPlateId ?? globalBuildPlateId;
  const deviceProfileId = projectSettings?.deviceProfileId ?? globalDeviceProfileId;
  const slicerSoftware = projectSettings?.slicerSoftware ?? globalSlicerSoftware;
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  const invalidate = useThree((state) => state.invalidate);

  const selectedBed = useMemo(
    () => bedSizes.find((bed) => bed.label === bed_label),
    [bedSizes, bed_label],
  );

  const bedWidthMm = selectedBed?.width_mm ?? 256;
  const bedHeightMm = selectedBed?.height_mm ?? 256;
  const bedDims = useMemo(
    () => ({ w: bedWidthMm, h: bedHeightMm }),
    [bedWidthMm, bedHeightMm],
  );

  const { image: luminaMarkImage, ready: luminaMarkReady } = useBedImage(LUMINA_BED_MARK_URL);
  const slicerLogoSource = useMemo(
    () => getSlicerLogoSource(slicerSoftware),
    [slicerSoftware],
  );
  const { image: slicerLogoImage, ready: slicerLogoReady } = useBedImage(slicerLogoSource);
  const { geometry: nativeBedGeometry, ready: nativeBedReady } = useNativeBedGeometry(
    deviceProfileId,
    bedDims.w,
    bedDims.h,
  );

  // Find current bed dimensions and its printer-specific visual palette.
  const bedColors = useMemo(() => {
    return resolveBedPlatformColors(
      theme,
      selectedBed?.printer_id,
      bed_label,
      buildPlateId,
    );
  }, [theme, selectedBed?.printer_id, bed_label, buildPlateId]);

  // Create bed geometry + material
  const bedMesh = useMemo(() => {
    const geo = nativeBedGeometry
      ? nativeBedGeometry.clone()
      : createFallbackBedGeometry(bedDims.w, bedDims.h);
    const mesh = createBedPlatformMesh(geo);
    mesh.name = "scene-build-plate";
    mesh.userData.bedGeometrySource = nativeBedGeometry
      ? "slicer-native"
      : "dimensional-fallback";
    mesh.position.set(0, 0, -0.1);
    return mesh;
  }, [bedDims, nativeBedGeometry]);

  useLayoutEffect(() => {
    onReadyChange?.(false);
    let active = true;
    const material = bedMesh.material[BED_SURFACE_MATERIAL_INDEX];
    bedMesh.material[BED_BODY_MATERIAL_INDEX].color.set(bedColors.bedBase);
    bedMesh.userData.gridVisible = gridVisible;
    const request = createBedTextureRequest({
      widthMm: bedDims.w,
      heightMm: bedDims.h,
      colors: bedColors,
      gridVisible,
      luminaMarkDataUrl: imageElementToDataUrl(luminaMarkImage),
      slicerLogoDataUrl: imageElementToDataUrl(slicerLogoImage),
      slicerLogoAspectRatio: slicerLogoImage
        ? (slicerLogoImage.naturalWidth || 1) /
          (slicerLogoImage.naturalHeight || 1)
        : 1,
    });
    const stop = stageBedTextureReplacement(
      material,
      request,
      bedColors.bedInner,
    );
    void request.ready.then(() => {
      if (!active) return;
      // Material-map changes are imperative, so demand rendering needs a frame.
      invalidate();
      onReadyChange?.(luminaMarkReady && slicerLogoReady && nativeBedReady);
    });
    return () => {
      active = false;
      stop();
    };
  }, [
    bedColors,
    bedDims.h,
    bedDims.w,
    bedMesh,
    gridVisible,
    luminaMarkImage,
    slicerLogoImage,
    luminaMarkReady,
    slicerLogoReady,
    nativeBedReady,
    invalidate,
    onReadyChange,
  ]);

  useEffect(() => {
    return () => {
      disposeMeshResources(bedMesh);
    };
  }, [bedMesh]);

  // Auto-fit camera when bed changes and no model is loaded
  useEffect(() => {
    if (modelUrl || previewGlbUrl || batchPreviewItems.length > 0 || surfaceModelActive) {
      return;
    }

    const perspCam = camera as THREE.PerspectiveCamera;
    const pose = computeBedPreviewCameraPose(
      bedDims.w,
      bedDims.h,
      perspCam.fov,
    );

    camera.position.set(...pose.position);
    camera.lookAt(...pose.target);
    camera.updateProjectionMatrix();

    if (controls) {
      const oc = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      oc.target.set(...pose.target);
      oc.maxDistance = pose.fitDistance * 5;
      oc.minDistance = pose.fitDistance * 0.1;
      oc.update();
    }
  }, [bedDims, modelUrl, previewGlbUrl, batchPreviewItems.length, surfaceModelActive, camera, controls]);

  return <primitive object={bedMesh} />;
}
