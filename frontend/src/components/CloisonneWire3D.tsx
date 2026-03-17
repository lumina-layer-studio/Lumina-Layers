import { useMemo } from "react";
import * as THREE from "three";
import {
  rasterizeMeshToGrid,
  dilateGrid,
  greedyRectMerge,
  extrudeRectangles,
} from "./OutlineFrame3D";

// ========== Exported pure utility functions (testable without React) ==========

/**
 * Rasterize the top faces of multiple ColorMesh objects onto a shared 2D color grid.
 * Each pixel stores the color index (0-based) of the mesh that covers it, or -1 if uncovered.
 * Later meshes overwrite earlier ones (last-write-wins).
 * 将多个 ColorMesh 的顶面三角形光栅化到共享的 2D 颜色网格上。
 * 每个像素存储覆盖它的 mesh 的颜色索引（0-based），未覆盖区域为 -1。
 * 后写入的颜色覆盖先写入的（最后一个覆盖的 mesh 获胜）。
 *
 * @param colorMeshes - Array of color meshes from GLB model. (GLB 模型中的颜色网格数组)
 * @param cellSize - Size of each grid cell in world units. (每个网格单元的世界单位大小)
 * @param originX - World X origin of the grid. (网格的世界 X 原点)
 * @param originY - World Y origin of the grid. (网格的世界 Y 原点)
 * @param gridW - Grid width in cells. (网格宽度，单位为单元格)
 * @param gridH - Grid height in cells. (网格高度，单位为单元格)
 * @returns Int16Array of size gridW*gridH, row-major, values -1..N-1. (Int16Array，行优先，值域 -1..N-1)
 */
export function rasterizeColorMeshesToGrid(
  colorMeshes: THREE.Mesh[],
  cellSize: number,
  originX: number,
  originY: number,
  gridW: number,
  gridH: number,
): Int16Array {
  const grid = new Int16Array(gridW * gridH);
  grid.fill(-1);

  for (let i = 0; i < colorMeshes.length; i++) {
    const mesh = colorMeshes[i];
    const geometry = mesh.geometry;
    const posAttr = geometry.getAttribute("position") as THREE.BufferAttribute;
    const index = geometry.getIndex();
    if (!posAttr || !index) continue;

    // Find maxZ for this mesh to identify top-face vertices
    let maxZ = -Infinity;
    let minZ = Infinity;
    for (let v = 0; v < posAttr.count; v++) {
      const z = posAttr.getZ(v);
      if (z > maxZ) maxZ = z;
      if (z < minZ) minZ = z;
    }
    if (maxZ <= minZ) continue;

    const tolerance = (maxZ - minZ) * 0.01 + 1e-6;

    // Build set of top-face vertex indices
    const topVertexSet = new Set<number>();
    for (let v = 0; v < posAttr.count; v++) {
      if (Math.abs(posAttr.getZ(v) - maxZ) < tolerance) {
        topVertexSet.add(v);
      }
    }

    // Rasterize top-face triangles into the grid with color index i
    for (let t = 0; t < index.count; t += 3) {
      const a = index.getX(t);
      const b = index.getX(t + 1);
      const c = index.getX(t + 2);
      if (topVertexSet.has(a) && topVertexSet.has(b) && topVertexSet.has(c)) {
        fillTriangleInColorGrid(
          posAttr.getX(a), posAttr.getY(a),
          posAttr.getX(b), posAttr.getY(b),
          posAttr.getX(c), posAttr.getY(c),
          grid, gridW, gridH,
          originX, originY, cellSize, i,
        );
      }
    }
  }

  return grid;
}


// ========== Internal helpers ==========

/**
 * Rasterize a single triangle into the color grid, writing the given color index.
 * Uses scanline approach: iterate over bounding box cells, test point-in-triangle.
 * 将单个三角形光栅化到颜色网格中，写入指定的颜色索引。
 *
 * @param x0 - Triangle vertex A x. (三角形顶点 A 的 x 坐标)
 * @param y0 - Triangle vertex A y. (三角形顶点 A 的 y 坐标)
 * @param x1 - Triangle vertex B x. (三角形顶点 B 的 x 坐标)
 * @param y1 - Triangle vertex B y. (三角形顶点 B 的 y 坐标)
 * @param x2 - Triangle vertex C x. (三角形顶点 C 的 x 坐标)
 * @param y2 - Triangle vertex C y. (三角形顶点 C 的 y 坐标)
 * @param grid - Target color grid (Int16Array). (目标颜色网格)
 * @param gridW - Grid width. (网格宽度)
 * @param gridH - Grid height. (网格高度)
 * @param originX - World X origin. (世界 X 原点)
 * @param originY - World Y origin. (世界 Y 原点)
 * @param cellSize - Cell size in world units. (单元格大小)
 * @param colorIndex - Color index to write. (要写入的颜色索引)
 */
function fillTriangleInColorGrid(
  x0: number, y0: number,
  x1: number, y1: number,
  x2: number, y2: number,
  grid: Int16Array, gridW: number, gridH: number,
  originX: number, originY: number, cellSize: number,
  colorIndex: number,
): void {
  // Convert world coords to grid coords
  const gx0 = (x0 - originX) / cellSize;
  const gy0 = (y0 - originY) / cellSize;
  const gx1 = (x1 - originX) / cellSize;
  const gy1 = (y1 - originY) / cellSize;
  const gx2 = (x2 - originX) / cellSize;
  const gy2 = (y2 - originY) / cellSize;

  // Bounding box in grid coords, clamped to grid bounds
  const minGX = Math.max(0, Math.floor(Math.min(gx0, gx1, gx2)));
  const maxGX = Math.min(gridW - 1, Math.ceil(Math.max(gx0, gx1, gx2)));
  const minGY = Math.max(0, Math.floor(Math.min(gy0, gy1, gy2)));
  const maxGY = Math.min(gridH - 1, Math.ceil(Math.max(gy0, gy1, gy2)));

  for (let gy = minGY; gy <= maxGY; gy++) {
    for (let gx = minGX; gx <= maxGX; gx++) {
      // Test cell center against triangle
      if (pointInTriangle(gx + 0.5, gy + 0.5, gx0, gy0, gx1, gy1, gx2, gy2)) {
        grid[gy * gridW + gx] = colorIndex;
      }
    }
  }
}

/**
 * Point-in-triangle test using barycentric coordinates.
 * 使用重心坐标进行点在三角形内的测试。
 */
function pointInTriangle(
  px: number, py: number,
  x0: number, y0: number,
  x1: number, y1: number,
  x2: number, y2: number,
): boolean {
  const d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2);
  if (Math.abs(d) < 1e-10) return false;
  const a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / d;
  const b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / d;
  const c = 1 - a - b;
  return a >= -0.01 && b >= -0.01 && c >= -0.01;
}


/**
 * Detect color edges via 4-neighbor comparison on a ColorGrid.
 * Returns a binary edge mask where 1 = edge pixel, 0 = non-edge.
 * Pixels with value -1 (outside model solid area) are excluded from edge detection.
 * 通过 4-邻域比较检测 ColorGrid 上的颜色边缘。
 * 返回二值边缘掩码，1 = 边缘像素，0 = 非边缘。
 * 值为 -1 的像素（模型实体区域之外）被排除在边缘检测之外。
 *
 * @param colorGrid - Int16Array of size gridW*gridH, row-major, values -1..N-1. (颜色网格，行优先)
 * @param gridW - Grid width in cells. (网格宽度)
 * @param gridH - Grid height in cells. (网格高度)
 * @returns Uint8Array of size gridW*gridH, 0 or 1. (边缘掩码，0 或 1)
 */
export function detectColorEdges(
  colorGrid: Int16Array,
  gridW: number,
  gridH: number,
): Uint8Array {
  const edges = new Uint8Array(gridW * gridH);

  // 4-neighbor offsets: right, left, down, up
  const dx = [1, -1, 0, 0];
  const dy = [0, 0, 1, -1];

  for (let y = 0; y < gridH; y++) {
    for (let x = 0; x < gridW; x++) {
      const idx = y * gridW + x;
      const color = colorGrid[idx];

      // Skip non-solid pixels
      if (color === -1) continue;

      // Check 4 neighbors — only mark edge when a neighbor is a DIFFERENT solid color.
      // Out-of-bounds or -1 neighbors are NOT treated as different (avoids
      // marking the entire model outline as edge, which causes the gold wire
      // to flood the whole surface on complex images after dilation).
      for (let d = 0; d < 4; d++) {
        const nx = x + dx[d];
        const ny = y + dy[d];

        // Out-of-bounds neighbors: skip (not an edge trigger)
        if (nx < 0 || nx >= gridW || ny < 0 || ny >= gridH) {
          continue;
        }

        const neighborColor = colorGrid[ny * gridW + nx];
        // Empty (-1) neighbors: skip (not a color boundary)
        if (neighborColor === -1) {
          continue;
        }

        // Different solid color → this is a real color boundary edge
        if (neighborColor !== color) {
          edges[idx] = 1;
          break;
        }
      }
    }
  }

  return edges;
}


/**
 * Create a solid mask from a ColorGrid: pixels with colorIndex >= 0 become 1, others become 0.
 * 从 ColorGrid 生成实体掩码：颜色索引 >= 0 的像素为 1，其余为 0。
 *
 * @param colorGrid - Int16Array of size gridW*gridH, row-major, values -1..N-1. (颜色网格，行优先)
 * @param gridW - Grid width in cells. (网格宽度)
 * @param gridH - Grid height in cells. (网格高度)
 * @returns Uint8Array of size gridW*gridH, 0 or 1. (实体掩码，0 或 1)
 */
export function createSolidMask(
  colorGrid: Int16Array,
  gridW: number,
  gridH: number,
): Uint8Array {
  const len = gridW * gridH;
  const mask = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    mask[i] = colorGrid[i] >= 0 ? 1 : 0;
  }
  return mask;
}


/**
 * Compute the intersection of a dilated edge mask and a solid mask.
 * A pixel is 1 in the result only if it is 1 in both inputs.
 * 计算膨胀后边缘掩码与实体掩码的交集。
 * 结果中像素为 1 当且仅当两个输入中该像素均为 1。
 *
 * @param dilatedEdgeMask - Uint8Array of size gridW*gridH, 0 or 1. (膨胀后的边缘掩码)
 * @param solidMask - Uint8Array of size gridW*gridH, 0 or 1. (实体掩码)
 * @param gridW - Grid width in cells. (网格宽度)
 * @param gridH - Grid height in cells. (网格高度)
 * @returns Uint8Array of size gridW*gridH, 0 or 1. (交集结果掩码)
 */
export function maskIntersection(
  dilatedEdgeMask: Uint8Array,
  solidMask: Uint8Array,
  gridW: number,
  gridH: number,
): Uint8Array {
  const len = gridW * gridH;
  const result = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    result[i] = dilatedEdgeMask[i] & solidMask[i];
  }
  return result;
}

// ========== React Component ==========

/** Color layer thickness in mm (5 layers × 0.08mm), consistent with InteractiveModelViewer. */
export const COLOR_LAYER_HEIGHT = 0.4;

/** Gold color for cloisonné wires. */
export const WIRE_COLOR = 0xdaa520;

/** Metalness for gold wire material. */
export const WIRE_METALNESS = 0.6;

/** Roughness for gold wire material. */
export const WIRE_ROUGHNESS = 0.3;

/**
 * Props for the CloisonneWire3D component.
 * CloisonneWire3D 组件的属性接口。
 */
export interface CloisonneWire3DProps {
  enabled: boolean;
  wireWidthMm: number;
  wireHeightMm: number;
  colorMeshes: THREE.Mesh[];
  backingPlateMesh: THREE.Mesh | null;
  spacerThick: number;
}

/**
 * Derive cellSize, origin, and grid dimensions from a backing plate mesh or color meshes.
 * Reuses the same vertex-spacing logic as OutlineFrame3D's rasterizeMeshToGrid.
 * 从底板网格或颜色网格推导 cellSize、原点和网格尺寸。
 *
 * @param backingPlateMesh - Backing plate mesh (preferred source). (底板网格，优先来源)
 * @param colorMeshes - Color meshes (fallback source). (颜色网格，备选来源)
 * @returns Grid parameters or null if derivation fails. (网格参数或 null)
 */
function deriveGridParams(
  backingPlateMesh: THREE.Mesh | null,
  colorMeshes: THREE.Mesh[],
): {
  cellSize: number;
  originX: number;
  originY: number;
  gridW: number;
  gridH: number;
} | null {
  // Try backing plate first (preferred — matches OutlineFrame3D behavior)
  if (backingPlateMesh) {
    const result = rasterizeMeshToGrid(backingPlateMesh.geometry);
    if (result) {
      return {
        cellSize: result.cellSize,
        originX: result.originX,
        originY: result.originY,
        gridW: result.gridW,
        gridH: result.gridH,
      };
    }
  }

  // Fallback: derive from colorMeshes vertices
  if (colorMeshes.length === 0) return null;

  // Collect all top-face XY points from all color meshes
  const allTopPoints: [number, number][] = [];
  for (const mesh of colorMeshes) {
    const posAttr = mesh.geometry.getAttribute("position") as THREE.BufferAttribute;
    const index = mesh.geometry.getIndex();
    if (!posAttr || !index) continue;

    let maxZ = -Infinity;
    let minZ = Infinity;
    for (let v = 0; v < posAttr.count; v++) {
      const z = posAttr.getZ(v);
      if (z > maxZ) maxZ = z;
      if (z < minZ) minZ = z;
    }
    if (maxZ <= minZ) continue;

    const tolerance = (maxZ - minZ) * 0.01 + 1e-6;
    for (let v = 0; v < posAttr.count; v++) {
      if (Math.abs(posAttr.getZ(v) - maxZ) < tolerance) {
        allTopPoints.push([posAttr.getX(v), posAttr.getY(v)]);
      }
    }
  }

  if (allTopPoints.length < 3) return null;

  // Bounding box
  let bMinX = Infinity, bMaxX = -Infinity, bMinY = Infinity, bMaxY = -Infinity;
  for (const [x, y] of allTopPoints) {
    if (x < bMinX) bMinX = x;
    if (x > bMaxX) bMaxX = x;
    if (y < bMinY) bMinY = y;
    if (y > bMaxY) bMaxY = y;
  }
  const rangeX = bMaxX - bMinX;
  const rangeY = bMaxY - bMinY;
  if (rangeX < 1e-6 || rangeY < 1e-6) return null;

  // Derive cellSize from vertex spacing (same algorithm as rasterizeMeshToGrid)
  const uniqueXs = Array.from(
    new Set(allTopPoints.map((p) => Math.round(p[0] * 1e4) / 1e4)),
  ).sort((a, b) => a - b);

  let cellSize: number;
  if (uniqueXs.length >= 4) {
    const gaps: number[] = [];
    for (let i = 1; i < uniqueXs.length; i++) {
      const gap = uniqueXs[i] - uniqueXs[i - 1];
      if (gap > 1e-6) gaps.push(gap);
    }
    if (gaps.length >= 2) {
      gaps.sort((a, b) => a - b);
      let maxJump = 0, splitIdx = 0;
      for (let i = 1; i < gaps.length; i++) {
        const jump = gaps[i] - gaps[i - 1];
        if (jump > maxJump) { maxJump = jump; splitIdx = i; }
      }
      if (splitIdx > 0 && splitIdx < gaps.length) {
        let sumSmall = 0;
        for (let i = 0; i < splitIdx; i++) sumSmall += gaps[i];
        const avgSmall = sumSmall / splitIdx;
        let sumLarge = 0;
        for (let i = splitIdx; i < gaps.length; i++) sumLarge += gaps[i];
        const avgLarge = sumLarge / (gaps.length - splitIdx);
        cellSize = avgSmall + avgLarge;
      } else {
        cellSize = gaps[Math.floor(gaps.length / 2)];
      }
    } else {
      cellSize = gaps.length > 0 ? gaps[0] : rangeX;
    }
  } else {
    cellSize = Math.max(rangeX, rangeY) / Math.min(Math.max(rangeX, rangeY), 512);
    if (cellSize < 1e-6) cellSize = 1.0;
  }

  const gridW = Math.ceil(rangeX / cellSize) + 2;
  const gridH = Math.ceil(rangeY / cellSize) + 2;

  return { cellSize, originX: bMinX, originY: bMinY, gridW, gridH };
}

/**
 * Cloisonné (掐丝珐琅) gold wire 3D preview component.
 * Renders gold-colored raised wires along color boundaries in the 3D scene.
 * Pipeline: rasterize → detectEdges → dilate → maskIntersection → greedyRectMerge → extrude.
 * 景泰蓝金色线条 3D 预览组件，沿颜色边界渲染凸起的金色线条。
 */
export default function CloisonneWire3D({
  enabled,
  wireWidthMm,
  wireHeightMm,
  colorMeshes,
  backingPlateMesh,
  spacerThick,
}: CloisonneWire3DProps) {
  const geometry = useMemo(() => {
    // Guard: early returns for invalid states
    if (!enabled) return null;
    if (colorMeshes.length === 0) return null;
    if (wireWidthMm <= 0 || wireHeightMm <= 0) return null;

    // 1. Derive grid parameters (cellSize, origin, dimensions)
    const gridParams = deriveGridParams(backingPlateMesh, colorMeshes);
    if (!gridParams) return null;

    const { cellSize, originX, originY, gridW, gridH } = gridParams;

    // 2. Rasterize all color meshes to a shared color grid
    const colorGrid = rasterizeColorMeshesToGrid(
      colorMeshes, cellSize, originX, originY, gridW, gridH,
    );

    // 3. Detect color edges via 4-neighbor comparison
    const edgeMask = detectColorEdges(colorGrid, gridW, gridH);

    // Check if any edges were found (all same color → no edges)
    let hasEdge = false;
    for (let i = 0; i < edgeMask.length; i++) {
      if (edgeMask[i] === 1) { hasEdge = true; break; }
    }
    if (!hasEdge) return null;

    // 4. Dilate edges by wireWidthMm converted to pixel count
    const dilatePixels = Math.max(1, Math.round(wireWidthMm / cellSize));
    const dilatedMask = dilateGrid(edgeMask, gridW, gridH, dilatePixels);

    // 5. Create solid mask and intersect with dilated edges
    const solidMask = createSolidMask(colorGrid, gridW, gridH);
    const wireMask = maskIntersection(dilatedMask, solidMask, gridW, gridH);

    // 6. Greedy rectangle merge to reduce draw calls
    const rects = greedyRectMerge(wireMask, gridW, gridH);
    if (rects.length === 0) return null;

    // 7. Extrude rectangles into 3D geometry
    //    Bottom at Z = spacerThick + COLOR_LAYER_HEIGHT
    //    pad = 0 since our grid has no extra padding (unlike OutlineFrame3D)
    const geo = extrudeRectangles(
      rects, originX, originY, cellSize, wireHeightMm, 0,
    );
    if (!geo) return null;

    // 8. Translate geometry so bottom sits at Z = spacerThick + COLOR_LAYER_HEIGHT
    const baseZ = spacerThick + COLOR_LAYER_HEIGHT;
    geo.translate(0, 0, baseZ);

    return geo;
  }, [enabled, wireWidthMm, wireHeightMm, colorMeshes, backingPlateMesh, spacerThick]);

  if (!geometry) return null;

  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial
        color={WIRE_COLOR}
        metalness={WIRE_METALNESS}
        roughness={WIRE_ROUGHNESS}
      />
    </mesh>
  );
}
