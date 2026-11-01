/* eslint-disable react-refresh/only-export-components */
import { useMemo, useEffect, useRef } from "react";
import { useGLTF } from "@react-three/drei";
import { configureGltfTransport } from "../utils/gltfTransport";
import * as THREE from "three";
import { useConverterStore } from "../stores/converter";
import {
  cloneObjectTreeWithOwnedResources,
  disposeMaterial,
  disposeMeshResources,
  disposeObjectTree,
} from "../utils/threeDisposal";
import OutlineFrame3D from "./OutlineFrame3D";
import CloisonneWire3D from "./CloisonneWire3D";
import {
  debugThreeLog,
  getLatestResourceTiming,
  summarizeMeshList,
  summarizeObjectTree,
} from "../utils/threeDebug";
import { postClientLog } from "../utils/clientLog";
import { createMatteMaterialFromStandard } from "../utils/threeMatteMaterial";
import PuzzleOverlay3D from "./PuzzleOverlay3D";
import { useGltfCacheLifecycle } from "./useGltfCacheLifecycle";
import { materializePositionAttributeForGeometryBake } from "../utils/threeQuantizedGeometry";
import type { PuzzleOverlayBounds } from "./puzzleOverlay3DUtils";
import { createPreviewSpace } from "../utils/previewSpace";
import HeightmapReliefSurface3D from "./HeightmapReliefSurface3D";
import CoatingPreview3D from "./CoatingPreview3D";

type LuminaWindow = Window & { __luminaPreviewStart?: number };

function _getPreviewStartTime(): number | null {
  return (window as LuminaWindow).__luminaPreviewStart ?? null;
}

// ========== Exported pure utility functions (testable without Three.js) ==========

/**
 * Extract hex color string from a mesh name with "color_" prefix.
 * 从带有 "color_" 前缀的网格名称中提取 hex 颜色字符串。
 *
 * @param meshName - The mesh name, e.g. "color_ff0000". (网格名称)
 * @returns The hex string without prefix, e.g. "ff0000". (不含前缀的 hex 字符串)
 */
export function extractHexFromMeshName(meshName: string): string {
  return meshName.slice(6, 12);
}

/** Resolve stable relief identity, with legacy mesh names as a safe fallback. */
export function resolvePreviewMeshHeightKey(
  meshName: string,
  userData: Record<string, unknown>,
): string {
  const metadataKey = userData.height_key;
  if (
    typeof metadataKey === "string" &&
    /^[0-9a-fA-F]{6}$/.test(metadataKey)
  ) {
    return metadataKey.toLowerCase();
  }
  return extractHexFromMeshName(meshName).toLowerCase();
}

// ========== Component ==========

export interface InteractiveModelViewerProps {
  url: string;
  sourceRole: InteractiveModelSourceRole;
  colorRemapMap: Record<string, string>;
  colorHeightMap: Record<string, number>;
  baseHeight: number;
  enableRelief: boolean;
  scaleX?: number;  // X 方向缩放比例，默认 1.0
  scaleY?: number;  // Y 方向缩放比例，默认 1.0
  spacerThick?: number;    // 底板厚度 (mm)，默认 1.2
  structureMode?: string;  // "Double-sided" | "Single-sided"
  enableOutline?: boolean;   // 是否启用外轮廓预览，默认 false
  outlineWidth?: number;     // 外轮廓厚度 (mm)，默认 2.0
  enableCloisonne?: boolean;   // 是否启用景泰蓝预览，默认 false
  wireWidthMm?: number;        // 金丝宽度 (mm)，默认 0.4
  wireHeightMm?: number;       // 金丝高度 (mm)，默认 0.1
  enableFridgeMagnet?: boolean;
  rasterCellSize?: number;
  puzzleOverlayEnabled?: boolean;
  puzzleOverlayUrl?: string | null;
  colorLayerHeightMm?: number;
  onPreviewCanvasBoundsChange?: (
    sourceUrl: string,
    bounds: PuzzleOverlayBounds | null,
  ) => void;
  heightmapReliefUrl?: string | null;
  heightmapArtworkUrl?: string | null;
  heightmapReliefMaxHeightMm?: number;
  enableCoating?: boolean;
  coatingHeightMm?: number;
  printingLayerHeightMm?: number;
}

export type InteractiveModelSourceRole = "quick-preview" | "generated" | "batch";

export function shouldApplyQuickPreviewGeometry(
  sourceRole: InteractiveModelSourceRole,
): boolean {
  return sourceRole === "quick-preview";
}

export interface PreparedInteractiveModelScene {
  clone: THREE.Object3D;
  sceneCenter: THREE.Vector3;
}

/** Default color layer thickness in mm (5 layers x 0.08mm). */
export const DEFAULT_COLOR_LAYER_HEIGHT_MM = 0.4;
const PREVIEW_CANVAS_BOUNDS_NODE_NAME = "preview_canvas_bounds";
const EMBEDDED_OUTLINE_NODE_NAME = "Outline";
const PREVIEW_LAYER_Z_EPSILON_MM = 0.002;

export function applyInteractiveModelPreviewMaterials(
  root: THREE.Object3D,
  sourceRole: InteractiveModelSourceRole,
): void {
  if (!shouldApplyQuickPreviewGeometry(sourceRole)) return;

  root.traverse((child) => {
    if (
      !(child instanceof THREE.Mesh) ||
      !child.material ||
      child.name === "backing_plate" ||
      child.name === PREVIEW_CANVAS_BOUNDS_NODE_NAME
    ) {
      return;
    }
    const previousMaterial = child.material;
    const materials = Array.isArray(previousMaterial)
      ? previousMaterial
      : [previousMaterial];
    const replacedMaterials: THREE.Material[] = [];
    const previewMaterials = materials.map((material: THREE.Material) => {
      if (material instanceof THREE.MeshStandardMaterial) {
        replacedMaterials.push(material);
        return createMatteMaterialFromStandard(material);
      }
      return material;
    });
    if (replacedMaterials.length === 0) return;

    for (const material of replacedMaterials) {
      disposeMaterial(material);
    }
    child.material = Array.isArray(previousMaterial)
      ? previewMaterials
      : previewMaterials[0];
  });
}

function hasDiscardedAncestor(
  object: THREE.Object3D,
  root: THREE.Object3D,
  shouldDiscard: (candidate: THREE.Object3D) => boolean,
): boolean {
  let parent = object.parent;
  while (parent && parent !== root) {
    if (shouldDiscard(parent)) {
      return true;
    }
    parent = parent.parent;
  }
  return false;
}

/**
 * Clone and center a model after removing role-specific non-model nodes.
 * 克隆模型，并在移除当前来源不应参与预览的节点后计算居中位置。
 */
export function prepareInteractiveModelSceneClone(
  sourceScene: THREE.Object3D,
  sourceRole: InteractiveModelSourceRole,
): PreparedInteractiveModelScene {
  const clone = cloneObjectTreeWithOwnedResources(sourceScene);
  const shouldDiscard = (candidate: THREE.Object3D): boolean => (
    candidate.name.toLowerCase() === "bed"
    || (
      sourceRole === "quick-preview"
      && candidate.name === EMBEDDED_OUTLINE_NODE_NAME
    )
  );
  const discardedRoots: THREE.Object3D[] = [];
  clone.traverse((candidate) => {
    if (
      candidate !== clone
      && shouldDiscard(candidate)
      && !hasDiscardedAncestor(candidate, clone, shouldDiscard)
    ) {
      discardedRoots.push(candidate);
    }
  });
  for (const discardedRoot of discardedRoots) {
    discardedRoot.removeFromParent();
    disposeObjectTree(discardedRoot);
  }

  clone.updateMatrixWorld(true);
  const box = new THREE.Box3();
  const childBox = new THREE.Box3();
  clone.traverse((child) => {
    if (
      child instanceof THREE.Mesh
      && child.name !== PREVIEW_CANVAS_BOUNDS_NODE_NAME
    ) {
      childBox.setFromObject(child);
      box.union(childBox);
    }
  });
  if (box.isEmpty()) {
    box.setFromObject(clone);
  }

  const sceneCenter = new THREE.Vector3();
  box.getCenter(sceneCenter);
  clone.position.set(-sceneCenter.x, -sceneCenter.y, -box.min.z);
  clone.updateMatrixWorld(true);

  return { clone, sceneCenter };
}

export function computePreviewLayerZPositions(spacerThick: number): {
  frontColorZ: number;
  mirrorColorZ: number;
} {
  const safeSpacerThick = Number.isFinite(spacerThick)
    ? Math.max(0, spacerThick)
    : 0;
  return {
    frontColorZ: safeSpacerThick + PREVIEW_LAYER_Z_EPSILON_MM,
    mirrorColorZ: -PREVIEW_LAYER_Z_EPSILON_MM,
  };
}

const MATERIAL_LAYER_MESH_RE = /^color_([0-9a-fA-F]{6})_m(\d+)_l(\d+)$/;
const BATCHED_MATERIAL_APPEARANCE_MESH_RE =
  /^color_layered_appearance_l000$/;
const BATCHED_MATERIAL_PHYSICAL_MESH_RE =
  /^color_layered_physical_l(\d+)$/;

export interface BatchedHeightSegment {
  height_key: string;
  display_hex: string;
  vertex_start: number;
  vertex_count: number;
}

export interface BatchedPaletteSegment {
  display_hex: string;
  vertex_start: number;
  vertex_count: number;
}

export interface BatchedPaletteUvEncoding {
  valid: boolean;
  paletteHex: string[];
  uvData: Uint8Array | Uint16Array | null;
  componentBits: 8 | 16 | null;
  error?: string;
}

export function isBatchedMaterialAppearanceMeshName(
  meshName: string,
): boolean {
  return BATCHED_MATERIAL_APPEARANCE_MESH_RE.test(meshName);
}

export function isBatchedMaterialPhysicalMeshName(
  meshName: string,
): boolean {
  return BATCHED_MATERIAL_PHYSICAL_MESH_RE.test(meshName);
}

export function resolvePreviewColorLayerHeightMm(
  colorLayerHeightMm?: number,
): number {
  const value = typeof colorLayerHeightMm === "number" ? colorLayerHeightMm : NaN;
  return Number.isFinite(value) && value > 0
    ? value
    : DEFAULT_COLOR_LAYER_HEIGHT_MM;
}

export function isLayeredMaterialColorMeshName(meshName: string): boolean {
  return (
    MATERIAL_LAYER_MESH_RE.test(meshName) ||
    isBatchedMaterialAppearanceMeshName(meshName) ||
    isBatchedMaterialPhysicalMeshName(meshName)
  );
}

function normalizePaletteHex(rawHex: unknown): string | null {
  const normalized = String(rawHex ?? "")
    .replace(/^#/, "")
    .toLowerCase();
  return /^[0-9a-f]{6}$/.test(normalized) ? normalized : null;
}

/** Build compact palette UVs while proving every vertex is covered exactly once. */
export function buildBatchedPaletteUvEncoding(
  vertexCount: number,
  segments: BatchedPaletteSegment[],
): BatchedPaletteUvEncoding {
  if (!Number.isInteger(vertexCount) || vertexCount <= 0) {
    return {
      valid: false,
      paletteHex: [],
      uvData: null,
      componentBits: null,
      error: "invalid_vertex_count",
    };
  }

  const coverage = new Uint8Array(vertexCount);
  const paletteHex: string[] = [];
  const paletteIndexes = new Map<string, number>();
  const normalizedSegments: Array<{
    start: number;
    end: number;
    paletteIndex: number;
  }> = [];

  for (const segment of segments) {
    const displayHex = normalizePaletteHex(segment.display_hex);
    const start = Number(segment.vertex_start);
    const count = Number(segment.vertex_count);
    const end = start + count;
    if (
      displayHex === null
      || !Number.isInteger(start)
      || !Number.isInteger(count)
      || count <= 0
      || start < 0
      || end > vertexCount
    ) {
      return {
        valid: false,
        paletteHex: [],
        uvData: null,
        componentBits: null,
        error: "invalid_palette_segment",
      };
    }
    let paletteIndex = paletteIndexes.get(displayHex);
    if (paletteIndex === undefined) {
      paletteIndex = paletteHex.length;
      paletteIndexes.set(displayHex, paletteIndex);
      paletteHex.push(displayHex);
    }
    for (let vertexIndex = start; vertexIndex < end; vertexIndex += 1) {
      if (coverage[vertexIndex] !== 0) {
        return {
          valid: false,
          paletteHex: [],
          uvData: null,
          componentBits: null,
          error: "overlapping_palette_segments",
        };
      }
      coverage[vertexIndex] = 1;
    }
    normalizedSegments.push({ start, end, paletteIndex });
  }

  if (paletteHex.length === 0 || coverage.some((value) => value !== 1)) {
    return {
      valid: false,
      paletteHex: [],
      uvData: null,
      componentBits: null,
      error: "incomplete_palette_segments",
    };
  }

  const componentBits: 8 | 16 = paletteHex.length <= 128 ? 8 : 16;
  const componentMax = componentBits === 8 ? 0xff : 0xffff;
  const uvData = componentBits === 8
    ? new Uint8Array(vertexCount * 2)
    : new Uint16Array(vertexCount * 2);
  const encodedV = Math.round(0.5 * componentMax);
  for (const segment of normalizedSegments) {
    const encodedU = Math.round(
      ((segment.paletteIndex + 0.5) / paletteHex.length) * componentMax,
    );
    for (
      let vertexIndex = segment.start;
      vertexIndex < segment.end;
      vertexIndex += 1
    ) {
      uvData[vertexIndex * 2] = encodedU;
      uvData[vertexIndex * 2 + 1] = encodedV;
    }
  }
  return { valid: true, paletteHex, uvData, componentBits };
}

/** Attach an exact-sRGB palette texture without persistent GLB vertex colours. */
export function configureBatchedPaletteTexture(mesh: THREE.Mesh): boolean {
  const material = mesh.material as
    | THREE.MeshBasicMaterial
    | THREE.MeshStandardMaterial;
  const geometry = mesh.geometry;
  const rawSegments = isBatchedMaterialAppearanceMeshName(mesh.name)
    ? mesh.userData.height_segments
    : mesh.userData.material_segments;
  const segments = Array.isArray(rawSegments)
    ? (rawSegments as BatchedPaletteSegment[])
    : [];
  const encoding = buildBatchedPaletteUvEncoding(
    geometry.getAttribute("position")?.count ?? 0,
    segments,
  );

  geometry.deleteAttribute("color");
  if (material.map) {
    material.map.dispose();
    material.map = null;
  }
  material.vertexColors = false;
  material.color.setRGB(1, 1, 1);

  if (!encoding.valid || !encoding.uvData || !encoding.componentBits) {
    geometry.deleteAttribute("uv");
    geometry.userData.luminaPaletteError = encoding.error ?? "invalid_metadata";
    material.needsUpdate = true;
    return false;
  }

  const uvAttribute = encoding.componentBits === 8
    ? new THREE.Uint8BufferAttribute(encoding.uvData as Uint8Array, 2, true)
    : new THREE.Uint16BufferAttribute(encoding.uvData as Uint16Array, 2, true);
  geometry.setAttribute("uv", uvAttribute);

  const textureData = new Uint8Array(encoding.paletteHex.length * 4);
  for (let index = 0; index < encoding.paletteHex.length; index += 1) {
    const hex = encoding.paletteHex[index];
    const offset = index * 4;
    textureData[offset] = Number.parseInt(hex.slice(0, 2), 16);
    textureData[offset + 1] = Number.parseInt(hex.slice(2, 4), 16);
    textureData[offset + 2] = Number.parseInt(hex.slice(4, 6), 16);
    textureData[offset + 3] = 255;
  }
  const paletteTexture = new THREE.DataTexture(
    textureData,
    encoding.paletteHex.length,
    1,
    THREE.RGBAFormat,
    THREE.UnsignedByteType,
  );
  paletteTexture.name = `${mesh.name}_palette`;
  paletteTexture.colorSpace = THREE.SRGBColorSpace;
  paletteTexture.minFilter = THREE.NearestFilter;
  paletteTexture.magFilter = THREE.NearestFilter;
  paletteTexture.wrapS = THREE.ClampToEdgeWrapping;
  paletteTexture.wrapT = THREE.ClampToEdgeWrapping;
  paletteTexture.generateMipmaps = false;
  paletteTexture.needsUpdate = true;
  material.map = paletteTexture;
  material.needsUpdate = true;
  geometry.userData.luminaPaletteHex = encoding.paletteHex;
  delete geometry.userData.luminaPaletteError;
  return true;
}

export function buildBatchedReliefPositionArray({
  originalPositions,
  heightSegments,
  nativeMinZ,
  nativeMaxZ,
  colorHeightMap,
  fallbackHeightMm,
}: {
  originalPositions: Float32Array;
  heightSegments: BatchedHeightSegment[];
  nativeMinZ: number;
  nativeMaxZ: number;
  colorHeightMap: Record<string, number>;
  fallbackHeightMm: number;
}): Float32Array {
  const output = originalPositions.slice();
  const nativeHeight = nativeMaxZ - nativeMinZ;
  if (!Number.isFinite(nativeHeight) || nativeHeight <= 0) return output;
  const safeFallback = resolvePreviewColorLayerHeightMm(fallbackHeightMm);

  for (const segment of heightSegments) {
    const start = Math.max(0, Math.trunc(segment.vertex_start));
    const end = Math.min(
      originalPositions.length / 3,
      start + Math.max(0, Math.trunc(segment.vertex_count)),
    );
    const heightKey = String(segment.height_key || "").toLowerCase();
    const requestedHeight = resolveReliefHeightForHex(
      colorHeightMap,
      heightKey,
    );
    const targetHeight = requestedHeight ?? safeFallback;
    for (let vertexIndex = start; vertexIndex < end; vertexIndex += 1) {
      const zOffset = vertexIndex * 3 + 2;
      const normalizedZ = Math.min(
        1,
        Math.max(0, (originalPositions[zOffset] - nativeMinZ) / nativeHeight),
      );
      output[zOffset] = normalizedZ * targetHeight;
    }
  }
  return output;
}

/** Return whether the colour stack should be mirrored below the backing. */
export function shouldMirrorPreview(
  structureMode: string,
  enableRelief: boolean,
): boolean {
  // Relief generation is single-sided. Fail safe here too because imported
  // recipes can momentarily restore an inconsistent double-sided state.
  // 浮雕生成固定为单面；导入配方可能短暂恢复不一致的双面状态，因此此处也兜底。
  return structureMode === "Double-sided" && !enableRelief;
}

function resolveReliefHeightForHex(
  colorHeightMap: Record<string, number>,
  displayHex: string,
): number | undefined {
  const directValue = colorHeightMap[displayHex] ?? colorHeightMap[`#${displayHex}`];
  if (Number.isFinite(directValue) && directValue > 0) {
    return directValue;
  }

  for (const [key, value] of Object.entries(colorHeightMap)) {
    if (
      key.replace(/^#/, "").toLowerCase() === displayHex
      && Number.isFinite(value)
      && value > 0
    ) {
      return value;
    }
  }
  return undefined;
}

export function resolvePreviewMeshReliefHeightMm({
  meshName,
  userData,
  colorHeightMap,
  fallbackHeightMm,
}: {
  meshName: string;
  userData: Record<string, unknown>;
  colorHeightMap: Record<string, number>;
  fallbackHeightMm: number;
}): number {
  const heightKey = resolvePreviewMeshHeightKey(meshName, userData);
  return (
    resolveReliefHeightForHex(colorHeightMap, heightKey) ??
    resolvePreviewColorLayerHeightMm(fallbackHeightMm)
  );
}

/**
 * Resolve visibility and Z placement for one material-archive layer mesh.
 * 计算耗材档案单个分层网格在普通或浮雕预览中的可见性与 Z 轴变换。
 *
 * Normal previews keep the native physical slices. Relief previews use only
 * the solver-coloured outward slice (l000) as a lightweight appearance column:
 * the real 3MF still shifts the complete optical stack and fills below it with
 * backing material, while the browser preserves the same top height and colour
 * without multiplying GLB geometry.
 * 普通预览保留真实物理分层；浮雕预览只把带模拟色的最外层（l000）作为轻量
 * 外观柱。真实 3MF 仍会整体抬升光学层并用底色填充，浏览器则在不增加 GLB
 * 几何量的前提下保持相同的顶面高度和颜色。
 *
 * @param options - Mesh bounds and live preview settings. (网格边界与实时预览设置)
 * @returns Visibility, Z scale, and Z translation. (可见性、Z 缩放与 Z 位移)
 */
export function resolveLayeredMaterialPreviewTransform({
  meshName,
  nativeMinZ,
  nativeMaxZ,
  spacerThick,
  enableRelief,
  colorHeightMap,
  colorLayerHeightMm,
}: {
  meshName: string;
  nativeMinZ: number;
  nativeMaxZ: number;
  spacerThick: number;
  enableRelief: boolean;
  colorHeightMap: Record<string, number>;
  colorLayerHeightMm: number;
}): { visible: boolean; scaleZ: number; positionZ: number } {
  const safeSpacerThick = Number.isFinite(spacerThick)
    ? Math.max(0, spacerThick)
    : 0;
  const match = meshName.match(MATERIAL_LAYER_MESH_RE);
  if (!enableRelief || !match) {
    return { visible: true, scaleZ: 1, positionZ: safeSpacerThick };
  }

  const layerIndex = Number.parseInt(match[3], 10);
  if (layerIndex !== 0) {
    return { visible: false, scaleZ: 1, positionZ: safeSpacerThick };
  }

  const nativeHeight = nativeMaxZ - nativeMinZ;
  if (!Number.isFinite(nativeHeight) || nativeHeight <= 0) {
    return { visible: true, scaleZ: 1, positionZ: safeSpacerThick };
  }

  const displayHex = match[1].toLowerCase();
  const requestedHeight = resolveReliefHeightForHex(colorHeightMap, displayHex);
  const reliefExtraHeight = requestedHeight !== undefined
    ? requestedHeight
    : resolvePreviewColorLayerHeightMm(colorLayerHeightMm);
  const scaleZ = reliefExtraHeight / nativeHeight;

  return {
    visible: true,
    scaleZ,
    positionZ: safeSpacerThick - nativeMinZ * scaleZ,
  };
}

export function shouldApplyColorRemapToMeshName(meshName: string): boolean {
  return !isLayeredMaterialColorMeshName(meshName);
}

export function applyPreviewMeshDisplayColor(
  material: THREE.MeshBasicMaterial | THREE.MeshStandardMaterial,
  meshName: string,
  colorRemapMap: Record<string, string>,
): void {
  if (
    isBatchedMaterialAppearanceMeshName(meshName) ||
    isBatchedMaterialPhysicalMeshName(meshName)
  ) {
    material.vertexColors = false;
    material.color.setRGB(1, 1, 1);
    return;
  }
  const originalHex = extractHexFromMeshName(meshName);
  const displayHex = shouldApplyColorRemapToMeshName(meshName)
    ? colorRemapMap[originalHex] || originalHex
    : originalHex;

  // GLTFLoader exposes baseColorFactor values in Three's linear working
  // space. Trimesh writes our byte RGB values directly, so keeping the loaded
  // numbers would apply linear->sRGB a second time and wash every material
  // archive colour out (for example D24854 became EA919B). Setting the encoded
  // hex explicitly performs the required sRGB->linear conversion once.
  material.vertexColors = false;
  material.color.set(`#${displayHex}`);
}

export function computeOutlinePreviewHeight(
  spacerThick: number,
  structureMode: string,
  enableRelief: boolean,
  colorHeightMap: Record<string, number>,
  fallbackModelMaxZ: number,
  colorLayerHeightMm: number = DEFAULT_COLOR_LAYER_HEIGHT_MM,
): number {
  const safeSpacerThick = Number.isFinite(spacerThick)
    ? Math.max(0, spacerThick)
    : 0;
  const resolvedColorLayerHeight = resolvePreviewColorLayerHeightMm(colorLayerHeightMm);
  const reliefHeights = Object.values(colorHeightMap).filter(
    (height) => Number.isFinite(height) && height > 0,
  );
  const colorLayerHeight = enableRelief
    ? reliefHeights.length > 0
      ? Math.max(...reliefHeights)
      : resolvedColorLayerHeight
    : resolvedColorLayerHeight * (structureMode.includes("Double") ? 2 : 1);
  const livePreviewHeight = safeSpacerThick + colorLayerHeight;
  if (livePreviewHeight > 0) {
    return livePreviewHeight;
  }
  return Number.isFinite(fallbackModelMaxZ) ? Math.max(0, fallbackModelMaxZ) : 0;
}

function InteractiveModelViewer({
  url,
  sourceRole,
  colorRemapMap,
  colorHeightMap,
  baseHeight,
  enableRelief,
  scaleX = 1,
  scaleY = 1,
  spacerThick = 1.2,
  structureMode = "Double-sided",
  enableOutline = false,
  outlineWidth = 2.0,
  enableCloisonne = false,
  wireWidthMm = 0.4,
  wireHeightMm = 0.1,
  enableFridgeMagnet = false,
  rasterCellSize,
  puzzleOverlayEnabled = false,
  puzzleOverlayUrl = null,
  colorLayerHeightMm = DEFAULT_COLOR_LAYER_HEIGHT_MM,
  onPreviewCanvasBoundsChange,
  heightmapReliefUrl = null,
  heightmapArtworkUrl = null,
  heightmapReliefMaxHeightMm = 3.0,
  enableCoating = false,
  coatingHeightMm = 0.08,
  printingLayerHeightMm = 0.08,
}: InteractiveModelViewerProps) {
  const { scene } = useGLTF(url, true, true, configureGltfTransport);
  const groupRef = useRef<THREE.Group>(null);
  useGltfCacheLifecycle(url, useGLTF.clear);
  const applyQuickPreviewGeometry = shouldApplyQuickPreviewGeometry(sourceRole);
  const previewColorLayerHeightMm = resolvePreviewColorLayerHeightMm(colorLayerHeightMm);
  const spatialHeightmapEnabled = Boolean(
    applyQuickPreviewGeometry
    && enableRelief
    && heightmapReliefUrl
    && heightmapArtworkUrl,
  );
  const previewReliefHeightMap = useMemo(
    () => spatialHeightmapEnabled
      ? { __heightmap: Math.max(0.08, heightmapReliefMaxHeightMm) }
      : colorHeightMap,
    [colorHeightMap, heightmapReliefMaxHeightMm, spatialHeightmapEnabled],
  );

  useEffect(() => {
    debugThreeLog("InteractiveModelViewer.lifecycle", {
      event: "mount",
      url,
    });
    return () => {
      debugThreeLog("InteractiveModelViewer.lifecycle", {
        event: "unmount",
        url,
      });
    };
  }, [url]);

  useEffect(() => {
    const resourceTiming = getLatestResourceTiming(url);
    const sourceScene = summarizeObjectTree(scene);
    postClientLog("preview: GLB loaded (useGLTF resolved)", {
      startTime: _getPreviewStartTime(),
      scope: "preview-viewer",
      phase: "gltf-loaded",
      dedupeMs: 250,
      details: {
        url,
        resource_timing: resourceTiming,
        source_scene: sourceScene,
      },
    });
    debugThreeLog("InteractiveModelViewer.gltf", {
      url,
      resource_timing: resourceTiming,
      source_scene: sourceScene,
    });
  }, [scene, url]);

  // Clone scene once per URL load, apply rotation/centering,
  // and clone each color mesh's material to avoid shared-material mutations.
  // Also separate color_ meshes from non-color children for individual JSX rendering.
  const {
    nonColorObject,
    colorMeshes,
    modelBounds,
    sceneCenter,
    backingPlateMesh,
    puzzleOverlayBounds,
    buildSummary,
  } = useMemo(() => {
    const buildStart = performance.now();
    const {
      clone,
      sceneCenter: center,
    } = prepareInteractiveModelSceneClone(scene, sourceRole);

    // Segmented quick previews use unlit materials so displayed chip colours
    // stay exact. Generated and batch GLBs keep every embedded material.
    applyInteractiveModelPreviewMaterials(clone, sourceRole);

    // --- Extract full preview-canvas bounds anchor from GLB scene ---
    let extractedPreviewCanvasBounds: THREE.Mesh | null = null;
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.name === PREVIEW_CANVAS_BOUNDS_NODE_NAME) {
        extractedPreviewCanvasBounds = child;
      }
    });
    let resolvedPuzzleOverlayBounds: PuzzleOverlayBounds | null = null;
    if (extractedPreviewCanvasBounds !== null) {
      const canvasBoundsMesh = extractedPreviewCanvasBounds as THREE.Mesh;
      canvasBoundsMesh.updateWorldMatrix(true, false);
      materializePositionAttributeForGeometryBake(canvasBoundsMesh.geometry);
      canvasBoundsMesh.geometry.applyMatrix4(canvasBoundsMesh.matrixWorld);
      canvasBoundsMesh.position.set(0, 0, 0);
      canvasBoundsMesh.rotation.set(0, 0, 0);
      canvasBoundsMesh.scale.set(1, 1, 1);
      canvasBoundsMesh.updateMatrixWorld(true);
      canvasBoundsMesh.removeFromParent();

      canvasBoundsMesh.geometry.computeBoundingBox();
      const canvasBox = canvasBoundsMesh.geometry.boundingBox;
      if (canvasBox && !canvasBox.isEmpty()) {
        resolvedPuzzleOverlayBounds = {
          minX: canvasBox.min.x,
          maxX: canvasBox.max.x,
          minY: canvasBox.min.y,
          maxY: canvasBox.max.y,
          maxZ: canvasBox.max.z,
        };
      }
      disposeMeshResources(canvasBoundsMesh);
    }

    // --- Extract backing_plate mesh from GLB scene ---
    let extractedBackingPlate: THREE.Mesh | null = null;
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.name === "backing_plate") {
        extractedBackingPlate = child;
      }
    });

    if (extractedBackingPlate !== null) {
      const bp = extractedBackingPlate as THREE.Mesh;
      // Bake world matrix so geometry is in centered world space
      bp.updateWorldMatrix(true, false);
      materializePositionAttributeForGeometryBake(bp.geometry);
      bp.geometry.applyMatrix4(bp.matrixWorld);
      bp.position.set(0, 0, 0);
      bp.rotation.set(0, 0, 0);
      bp.scale.set(1, 1, 1);
      bp.updateMatrixWorld(true);

      // Detach from clone tree
      bp.removeFromParent();

      if (applyQuickPreviewGeometry) {
        // Quick previews use a neutral backing regardless of LUT appearance.
        const previousBackingMaterial = bp.material;
        const backingMat = new THREE.MeshLambertMaterial({
          color: 0xf5f5f5,
          side: THREE.DoubleSide,
          toneMapped: true,
        });
        bp.material = backingMat;
        disposeMaterial(previousBackingMaterial);
      }
    }

    // Separate color_ meshes from the rest (excluding backing_plate)
    const colorMeshList: THREE.Mesh[] = [];
    const colorMeshParents: { mesh: THREE.Mesh; parent: THREE.Object3D }[] = [];

    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.name.startsWith("color_")) {
        colorMeshList.push(child);
        if (child.parent) {
          colorMeshParents.push({ mesh: child, parent: child.parent });
        }
      }
    });

    // Bake the parent's centering offset into each color mesh's geometry
    // so they remain centered after detachment from the clone tree.
    for (const mesh of colorMeshList) {
      materializePositionAttributeForGeometryBake(mesh.geometry);
      mesh.geometry.applyMatrix4(mesh.matrixWorld);
      mesh.position.set(0, 0, 0);
      mesh.rotation.set(0, 0, 0);
      mesh.scale.set(1, 1, 1);
      mesh.updateMatrixWorld(true);
      if (
        isBatchedMaterialAppearanceMeshName(mesh.name) ||
        isBatchedMaterialPhysicalMeshName(mesh.name)
      ) {
        configureBatchedPaletteTexture(mesh);
      }
      if (isBatchedMaterialAppearanceMeshName(mesh.name)) {
        const positions = mesh.geometry.getAttribute("position");
        mesh.userData.luminaOriginalPositions = new Float32Array(
          positions.array as ArrayLike<number>,
        );
      }
    }

    // Detach color meshes from the clone tree so they can be rendered as individual JSX
    for (const { mesh, parent } of colorMeshParents) {
      parent.remove(mesh);
    }

    // Compute model bounding box from color meshes only (after centering).
    // Do NOT include the clone — it may be empty or contain stale transforms
    // that pollute the bounds and cause pixel coordinate offsets.
    const boundsBox = new THREE.Box3();
    for (const mesh of colorMeshList) {
      mesh.geometry.computeBoundingBox();
      if (mesh.geometry.boundingBox) {
        boundsBox.union(mesh.geometry.boundingBox);
      }
    }
    // Include backing plate in bounds calculation
    if (extractedBackingPlate !== null) {
      const bp = extractedBackingPlate as THREE.Mesh;
      bp.geometry.computeBoundingBox();
      if (bp.geometry.boundingBox) {
        boundsBox.union(bp.geometry.boundingBox);
      }
    }

    const bounds = boundsBox.isEmpty()
      ? null
      : {
          minX: boundsBox.min.x,
          maxX: boundsBox.max.x,
          minY: boundsBox.min.y,
          maxY: boundsBox.max.y,
          maxZ: boundsBox.max.z, // thickness direction (toward camera)
        };

    const buildSummary = {
      url,
      source_role: sourceRole,
      build_ms: +(performance.now() - buildStart).toFixed(2),
      source_scene: summarizeObjectTree(scene),
      non_color_scene: summarizeObjectTree(clone),
      color_meshes: summarizeMeshList(colorMeshList),
      backing_plate: summarizeMeshList(
        extractedBackingPlate ? [extractedBackingPlate as THREE.Mesh] : [],
      ),
      puzzle_overlay_bounds: resolvedPuzzleOverlayBounds,
      model_bounds: bounds,
      scene_center: {
        x: +center.x.toFixed(3),
        y: +center.y.toFixed(3),
        z: +center.z.toFixed(3),
      },
    };
    debugThreeLog("InteractiveModelViewer.build", buildSummary);

    return {
      nonColorObject: clone,
      colorMeshes: colorMeshList,
      modelBounds: bounds,
      sceneCenter: center,
      backingPlateMesh: extractedBackingPlate as THREE.Mesh | null,
      puzzleOverlayBounds: resolvedPuzzleOverlayBounds,
      buildSummary,
    };
  }, [applyQuickPreviewGeometry, scene, sourceRole, url]);

  const previewSpace = useMemo(
    () =>
      applyQuickPreviewGeometry && modelBounds
        ? createPreviewSpace(modelBounds, scaleX, scaleY)
        : null,
    [applyQuickPreviewGeometry, modelBounds, scaleX, scaleY],
  );

  useEffect(() => {
    postClientLog("preview: GLB scene processed (useMemo done)", {
      startTime: _getPreviewStartTime(),
      scope: "preview-viewer",
      phase: "scene-processed",
      dedupeMs: 250,
      details: buildSummary,
    });
  }, [buildSummary]);

  // Expose model bounds to store for KeychainRing3D positioning
  useEffect(() => {
    useConverterStore.getState().setModelBounds(modelBounds);
  }, [modelBounds]);

  useEffect(() => {
    onPreviewCanvasBoundsChange?.(url, puzzleOverlayBounds);
    return () => onPreviewCanvasBoundsChange?.(url, null);
  }, [onPreviewCanvasBoundsChange, puzzleOverlayBounds, url]);

  useEffect(() => {
    return () => {
      debugThreeLog("InteractiveModelViewer.dispose", {
        url,
        non_color_scene: summarizeObjectTree(nonColorObject),
        color_meshes: summarizeMeshList(colorMeshes),
        backing_plate: summarizeMeshList(backingPlateMesh ? [backingPlateMesh] : []),
      });
      disposeObjectTree(nonColorObject);
      for (const mesh of colorMeshes) {
        disposeMeshResources(mesh);
      }
      if (backingPlateMesh) {
        disposeMeshResources(backingPlateMesh);
      }
    };
  }, [nonColorObject, colorMeshes, backingPlateMesh, url]);

  const outlinePreviewHeight = computeOutlinePreviewHeight(
    spacerThick,
    structureMode,
    enableRelief,
    previewReliefHeightMap,
    modelBounds?.maxZ ?? 0,
    previewColorLayerHeightMm,
  );
  const visibleColorHeightMm = spatialHeightmapEnabled
    ? Math.max(0.08, heightmapReliefMaxHeightMm)
    : Math.max(0, outlinePreviewHeight - Math.max(0, spacerThick));

  // ---- White backing plate mesh ----
  const isDoubleSided =
    applyQuickPreviewGeometry && shouldMirrorPreview(structureMode, enableRelief);
  const backingMesh = useMemo(() => {
    // When GLB contains backing_plate: use it directly (Requirement 2.2, 2.4)
    if (backingPlateMesh) {
      return backingPlateMesh;
    }

    if (!applyQuickPreviewGeometry) return null;

    // Fallback: create rectangular BoxGeometry when GLB has no backing_plate (Requirement 2.3)
    if (!modelBounds) return null;
    const w = modelBounds.maxX - modelBounds.minX;
    const h = modelBounds.maxY - modelBounds.minY;
    if (w <= 0 || h <= 0) return null;

    const geo = new THREE.BoxGeometry(w, h, spacerThick);
    const mat = new THREE.MeshLambertMaterial({
      color: 0xf5f5f5,
      side: THREE.DoubleSide,
      toneMapped: true,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = "__backing_plate_fallback";

    const cx = (modelBounds.minX + modelBounds.maxX) / 2;
    const cy = (modelBounds.minY + modelBounds.maxY) / 2;
    mesh.position.set(cx, cy, spacerThick / 2);
    return mesh;
  }, [applyQuickPreviewGeometry, backingPlateMesh, modelBounds, spacerThick]);

  useEffect(() => {
    return () => {
      if (backingMesh && backingMesh !== backingPlateMesh) {
        disposeMeshResources(backingMesh);
      }
    };
  }, [backingMesh, backingPlateMesh]);

  // Camera is managed by BedPlatform's default view — skip auto-fit here
  // so the viewport stays stable when a preview model loads.

  // Double-sided mirror meshes: pre-create clones that share the same material
  // so color remap mutations apply to both sides automatically.
  const mirrorMeshes = useMemo(() => {
    if (!isDoubleSided) return [];
    return colorMeshes.map((mesh) => {
      const mirror = mesh.clone(true);
      // Share the same material instance so color remap applies to both
      mirror.material = mesh.material;
      mirror.name = `mirror_${mesh.name}`;
      return mirror;
    });
  }, [colorMeshes, isDoubleSided]);


  // Imperative Three.js mutations: color remap, relief scaling.
  useEffect(() => {
    if (!applyQuickPreviewGeometry) return;

    const layerZ = computePreviewLayerZPositions(spacerThick);

    // ---- Backing plate Z positioning and scaling (Requirements 3.1, 3.2, 3.3, 3.4) ----
    // XY scale is inherited from parent group via scaleX/scaleY (Requirement 3.4)
    if (backingMesh) {
      if (backingPlateMesh && backingMesh === backingPlateMesh) {
        // GLB-extracted backing plate: scale Z to match spacerThick
        // The native mesh has Z height = 1 voxel layer × LAYER_HEIGHT
        backingMesh.geometry.computeBoundingBox();
        const backingBBox = backingMesh.geometry.boundingBox;
        const nativeH = backingBBox
          ? backingBBox.max.z - backingBBox.min.z
          : 1;
        backingMesh.scale.z = nativeH > 0 ? spacerThick / nativeH : 1;
        // Bottom-aligned at Z=0; top face at Z=spacerThick (Requirement 3.1, 3.2)
        backingMesh.position.z = 0;
      }
      // Fallback BoxGeometry already has correct size and position from useMemo
    }

    for (const mesh of colorMeshes) {
      const isLayeredMaterialMesh = isLayeredMaterialColorMeshName(mesh.name);
      const isBatchedAppearance = isBatchedMaterialAppearanceMeshName(
        mesh.name,
      );
      const isBatchedPhysical = isBatchedMaterialPhysicalMeshName(mesh.name);
      const mat = mesh.material as THREE.MeshBasicMaterial;

      // Drive the colour solely from the mesh-name hex for both GLB contracts.
      // Legacy matched-colour meshes still accept optimistic remaps; physical
      // layered meshes wait for their rebuilt GLB and keep the encoded colour.
      applyPreviewMeshDisplayColor(mat, mesh.name, colorRemapMap);

      // Keep all meshes fully opaque and unchanged
      mat.opacity = 1.0;
      mat.transparent = false;
      mat.side = THREE.DoubleSide;
      mat.depthTest = true;
      mat.depthWrite = true;
      mat.toneMapped = false;
      mat.needsUpdate = true;

      if (isBatchedAppearance) {
        const originalPositions = mesh.userData
          .luminaOriginalPositions as Float32Array | undefined;
        const rawSegments = mesh.userData.height_segments;
        const heightSegments = Array.isArray(rawSegments)
          ? (rawSegments as BatchedHeightSegment[])
          : [];
        if (originalPositions) {
          let nativeMinZ = Number.POSITIVE_INFINITY;
          let nativeMaxZ = Number.NEGATIVE_INFINITY;
          for (let offset = 2; offset < originalPositions.length; offset += 3) {
            nativeMinZ = Math.min(nativeMinZ, originalPositions[offset]);
            nativeMaxZ = Math.max(nativeMaxZ, originalPositions[offset]);
          }
          const nextPositions = enableRelief
            ? buildBatchedReliefPositionArray({
                originalPositions,
                heightSegments,
                nativeMinZ,
                nativeMaxZ,
                colorHeightMap: spatialHeightmapEnabled ? {} : colorHeightMap,
                fallbackHeightMm: spatialHeightmapEnabled
                  ? 0.08
                  : previewColorLayerHeightMm,
              })
            : originalPositions;
          const positionAttribute = mesh.geometry.getAttribute("position");
          (positionAttribute.array as Float32Array).set(nextPositions);
          positionAttribute.needsUpdate = true;
          mesh.geometry.computeBoundingBox();
          mesh.geometry.computeBoundingSphere();
        }
        mesh.visible = true;
        mesh.scale.z = 1;
        mesh.position.z = spacerThick;
        continue;
      }

      if (isBatchedPhysical) {
        mesh.visible = !enableRelief;
        mesh.scale.z = 1;
        mesh.position.z = spacerThick;
        continue;
      }

      // Compute Z scale: map the GLB's native color height to the target height
      // GLB color meshes span [0, nativeH] where nativeH ≈ 2.0mm (25 layers × 0.08)
      mesh.geometry.computeBoundingBox();
      const nativeH = mesh.geometry.boundingBox
        ? mesh.geometry.boundingBox.max.z - mesh.geometry.boundingBox.min.z
        : 1;

      if (isLayeredMaterialMesh) {
        const nativeMinZ = mesh.geometry.boundingBox?.min.z ?? 0;
        const nativeMaxZ = mesh.geometry.boundingBox?.max.z ?? nativeMinZ;
        const transform = resolveLayeredMaterialPreviewTransform({
          meshName: mesh.name,
          nativeMinZ,
          nativeMaxZ,
          spacerThick,
          enableRelief,
          colorHeightMap: spatialHeightmapEnabled ? {} : colorHeightMap,
          colorLayerHeightMm: spatialHeightmapEnabled
            ? 0.08
            : previewColorLayerHeightMm,
        });
        mesh.visible = transform.visible;
        mesh.scale.z = transform.scaleZ;
        mesh.position.z = transform.positionZ;
      } else if (enableRelief && baseHeight > 0) {
        mesh.visible = true;
        // Relief mode: each color gets its own height from colorHeightMap
        const heightMm = spatialHeightmapEnabled
          ? 0.08
          : resolvePreviewMeshReliefHeightMm({
              meshName: mesh.name,
              userData: mesh.userData,
              colorHeightMap,
              fallbackHeightMm: previewColorLayerHeightMm,
            });
        mesh.scale.z = nativeH > 0 ? heightMm / nativeH : 1;
        mesh.position.z = spacerThick;
      } else {
        mesh.visible = true;
        // Normal mode: scale to the active preview color-layer height.
        mesh.scale.z = nativeH > 0 ? previewColorLayerHeightMm / nativeH : 1;
        mesh.position.z = spacerThick;
      }
      // Position color layer on top of the backing plate (top face at Z=spacerThick)
      // Keep a tiny preview-only gap so the color layer's bottom face does not
      // fight with the backing plate's top face when the preview is scaled up.
      mesh.position.z = layerZ.frontColorZ;
    }

    // Update mirror meshes for double-sided mode
    for (const mirror of mirrorMeshes) {
      const origName = mirror.name.replace("mirror_", "");
      const origMesh = colorMeshes.find((m) => m.name === origName);
      if (origMesh) {
        mirror.visible = origMesh.visible;
        mirror.scale.z = -origMesh.scale.z; // flip Z direction
        mirror.position.z = layerZ.mirrorColorZ; // grow downward from bottom of backing plate
      }
    }
  }, [applyQuickPreviewGeometry, colorMeshes, mirrorMeshes, colorRemapMap, colorHeightMap, enableRelief, baseHeight, modelBounds, sceneCenter, spacerThick, isDoubleSided, backingMesh, backingPlateMesh, previewColorLayerHeightMm, spatialHeightmapEnabled]);

  // Double-sided mirror meshes are defined above (before useEffect).

  return (
    <group ref={groupRef}>
      <group
        name="preview-asset-space"
        position={previewSpace
          ? [previewSpace.assetGroupPosition.x, previewSpace.assetGroupPosition.y, 0]
          : [0, 0, 0]}
        scale={previewSpace
          ? [previewSpace.scaleX, previewSpace.scaleY, 1]
          : [1, 1, 1]}
      >
        <primitive object={nonColorObject} />
        {/* Double-sided: mirror color layers below the backing plate (Z < 0) */}
        {mirrorMeshes.map((mesh) => (
          <primitive key={mesh.uuid} object={mesh} />
        ))}
        {/* White backing plate — GLB-extracted shape or rectangular fallback (Z ∈ [0, spacerThick]) */}
        {backingMesh && <primitive object={backingMesh} />}
        {/* Color layers on top of backing plate (Z ≥ spacerThick) */}
        {colorMeshes.map((mesh) => (
          <primitive key={mesh.uuid} object={mesh} />
        ))}
        <HeightmapReliefSurface3D
          enabled={spatialHeightmapEnabled}
          heightmapUrl={heightmapReliefUrl}
          artworkUrl={heightmapArtworkUrl}
          modelBounds={puzzleOverlayBounds ?? modelBounds}
          spacerThickMm={spacerThick}
          maximumHeightMm={heightmapReliefMaxHeightMm}
        />
        <CoatingPreview3D
          enabled={applyQuickPreviewGeometry && enableCoating}
          backingMesh={backingMesh}
          coatingHeightMm={coatingHeightMm}
          layerHeightMm={printingLayerHeightMm}
          structureMode={structureMode}
          enableRelief={enableRelief}
          spacerThickMm={spacerThick}
          visibleColorHeightMm={visibleColorHeightMm}
          enableOutline={enableOutline}
          outlineWidthMm={outlineWidth}
          displayScale={previewSpace?.scaleX ?? 1}
          rasterCellSize={rasterCellSize}
        />
        <PuzzleOverlay3D
          enabled={puzzleOverlayEnabled}
          overlayUrl={puzzleOverlayUrl}
          modelBounds={modelBounds}
          previewCanvasBounds={puzzleOverlayBounds}
          spacerThick={spacerThick}
          enableRelief={enableRelief}
          colorHeightMap={previewReliefHeightMap}
          enableOutline={enableOutline}
          enableCloisonne={enableCloisonne}
          wireHeightMm={wireHeightMm}
        />
      </group>
      {/* 外轮廓预览 */}
      <OutlineFrame3D
        enabled={applyQuickPreviewGeometry && enableOutline}
        outlineWidth={outlineWidth}
        backingPlateMesh={backingMesh}
        sourceMeshes={colorMeshes.length > 0 ? colorMeshes : undefined}
        modelMaxZ={outlinePreviewHeight}
        rasterCellSize={rasterCellSize}
        fillInteriorHoles={enableFridgeMagnet}
        previewSpace={previewSpace}
      />
      {/* 景泰蓝金色线条预览 */}
      <CloisonneWire3D
        enabled={applyQuickPreviewGeometry && enableCloisonne}
        wireWidthMm={wireWidthMm}
        wireHeightMm={wireHeightMm}
        colorMeshes={colorMeshes}
        backingPlateMesh={backingMesh}
        spacerThick={spacerThick}
        colorLayerHeightMm={previewColorLayerHeightMm}
        rasterCellSize={rasterCellSize}
        previewSpace={previewSpace}
      />
    </group>
  );
}

export default InteractiveModelViewer;
