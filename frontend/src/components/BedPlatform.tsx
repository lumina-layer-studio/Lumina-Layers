import { useMemo, useEffect } from "react";
import { useThree } from "@react-three/fiber";
import * as THREE from "three";
import { useConverterStore } from "../stores/converterStore";
import { computeFitDistance } from "./ModelViewer";
import { useThemeConfig } from "../hooks/useThemeConfig";
import type { ThemeColors } from "./themeConfig";

/**
 * Create a textured print bed mesh matching the backend's PEI dark style.
 * Uses a canvas-generated texture with grid lines.
 */
function createBedTexture(
  widthMm: number,
  heightMm: number,
  colors: Pick<ThemeColors, "bedBase" | "bedInner" | "bedFineGrid" | "bedBoldGrid" | "bedBorder">
): THREE.CanvasTexture {
  const scale = 2; // pixels per mm for texture
  const texW = widthMm * scale;
  const texH = heightMm * scale;

  const canvas = document.createElement("canvas");
  canvas.width = texW;
  canvas.height = texH;
  const ctx = canvas.getContext("2d")!;

  // Bed base
  ctx.fillStyle = colors.bedBase;
  ctx.fillRect(0, 0, texW, texH);

  // Inner area
  const margin = 4;
  const radius = 16;
  ctx.fillStyle = colors.bedInner;
  ctx.beginPath();
  ctx.roundRect(margin, margin, texW - margin * 2, texH - margin * 2, radius);
  ctx.fill();

  // Fine grid (10mm)
  ctx.strokeStyle = colors.bedFineGrid;
  ctx.lineWidth = 1;
  const step10 = 10 * scale;
  for (let x = 0; x < texW; x += step10) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, texH);
    ctx.stroke();
  }
  for (let y = 0; y < texH; y += step10) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(texW, y);
    ctx.stroke();
  }

  // Bold grid (50mm)
  ctx.strokeStyle = colors.bedBoldGrid;
  ctx.lineWidth = 2;
  const step50 = 50 * scale;
  for (let x = 0; x < texW; x += step50) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, texH);
    ctx.stroke();
  }
  for (let y = 0; y < texH; y += step50) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(texW, y);
    ctx.stroke();
  }

  // Border
  ctx.strokeStyle = colors.bedBorder;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.roundRect(margin, margin, texW - margin * 2, texH - margin * 2, radius);
  ctx.stroke();

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export default function BedPlatform() {
  const bed_label = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);
  const modelUrl = useConverterStore((s) => s.modelUrl);
  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const { camera, controls } = useThree();
  const themeColors = useThemeConfig();

  // Find current bed dimensions
  const bedDims = useMemo(() => {
    const found = bedSizes.find((b) => b.label === bed_label);
    return found ? { w: found.width_mm, h: found.height_mm } : { w: 256, h: 256 };
  }, [bed_label, bedSizes]);

  // Create bed geometry + material
  const bedMesh = useMemo(() => {
    const geo = new THREE.PlaneGeometry(bedDims.w, bedDims.h);
    const texture = createBedTexture(bedDims.w, bedDims.h, themeColors);
    const mat = new THREE.MeshStandardMaterial({ map: texture, roughness: 0.8 });
    const mesh = new THREE.Mesh(geo, mat);
    // Bed stands upright in XY plane, centered at origin, pushed slightly behind the model
    mesh.position.set(0, 0, -0.1);
    return mesh;
  }, [bedDims, themeColors]);

  // Auto-fit camera when bed changes and no model is loaded
  useEffect(() => {
    if (modelUrl || previewGlbUrl) return; // Don't override camera when any model is present

    const radius = Math.max(bedDims.w, bedDims.h) / 2;
    const perspCam = camera as THREE.PerspectiveCamera;
    const dist = computeFitDistance(radius, perspCam.fov);

    // Camera faces the upright bed from the front (along +Z)
    camera.position.set(0, 0, dist);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();

    if (controls) {
      const oc = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      oc.target.set(0, 0, 0);
      oc.maxDistance = dist * 5;
      oc.minDistance = dist * 0.1;
      oc.update();
    }
  }, [bedDims, modelUrl, previewGlbUrl, camera, controls]);

  return <primitive object={bedMesh} />;
}
