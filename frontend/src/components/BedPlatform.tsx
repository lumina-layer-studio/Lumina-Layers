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

/**
 * Create a rounded-rectangle ShapeGeometry matching the bed texture corners.
 * 创建与热床纹理圆角匹配的圆角矩形几何体。
 */
function createRoundedBedGeometry(
  widthMm: number,
  heightMm: number,
  radius: number = 8
): THREE.ShapeGeometry {
  const hw = widthMm / 2;
  const hh = heightMm / 2;
  const r = Math.min(radius, hw, hh);

  const shape = new THREE.Shape();
  shape.moveTo(-hw + r, -hh);
  shape.lineTo(hw - r, -hh);
  shape.quadraticCurveTo(hw, -hh, hw, -hh + r);
  shape.lineTo(hw, hh - r);
  shape.quadraticCurveTo(hw, hh, hw - r, hh);
  shape.lineTo(-hw + r, hh);
  shape.quadraticCurveTo(-hw, hh, -hw, hh - r);
  shape.lineTo(-hw, -hh + r);
  shape.quadraticCurveTo(-hw, -hh, -hw + r, -hh);

  const geo = new THREE.ShapeGeometry(shape, 16);

  // Remap UV from shape coords to [0,1] range
  const pos = geo.attributes.position;
  const uvAttr = geo.attributes.uv;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    uvAttr.setXY(i, (x + hw) / widthMm, 1 - (y + hh) / heightMm);
  }
  uvAttr.needsUpdate = true;

  return geo;
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
    const geo = createRoundedBedGeometry(bedDims.w, bedDims.h, 8);
    const texture = createBedTexture(bedDims.w, bedDims.h, themeColors);
    const mat = new THREE.MeshStandardMaterial({ map: texture, roughness: 0.8 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(0, 0, -0.1);
    return mesh;
  }, [bedDims, themeColors]);

  // Auto-fit camera when bed changes and no model is loaded
  useEffect(() => {
    if (modelUrl || previewGlbUrl) return; // Don't override camera when any model is present

    const radius = Math.max(bedDims.w, bedDims.h) / 2;
    const perspCam = camera as THREE.PerspectiveCamera;
    // Use user-tuned default camera position & orbit target so the bed
    // renders in the upper portion of the viewport, clear of the bottom
    // ColorWorkstation panel.
    const dist = computeFitDistance(radius, perspCam.fov) * 1.45;

    camera.position.set(1.3, -129.08, 465.36);
    camera.lookAt(1.3, -71.74, -8.68);
    camera.updateProjectionMatrix();

    if (controls) {
      const oc = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      oc.target.set(1.3, -71.74, -8.68);
      oc.maxDistance = dist * 5;
      oc.minDistance = dist * 0.1;
      oc.update();
    }
  }, [bedDims, modelUrl, previewGlbUrl, camera, controls]);

  return <primitive object={bedMesh} />;
}
