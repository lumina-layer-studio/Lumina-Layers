import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

// ========== Constants ==========

/** Animation speed: hue cycles per second. */
const ANIM_SPEED = 0.001;

// ========== Exported pure utility functions (testable without React) ==========

/**
 * Rasterize the top face of a backing plate mesh onto a 2D occupancy grid.
 * Returns the grid, dimensions, origin, and cell size.
 * 将底板网格的顶面光栅化到 2D 占用网格上。
 *
 * @param geometry - BufferGeometry of the backing plate mesh. (底板网格的 BufferGeometry)
 * @returns Grid info object, or null if geometry is invalid. (网格信息对象，或 null)
 */
export function rasterizeMeshToGrid(geometry: THREE.BufferGeometry): {
  grid: Uint8Array;
  gridW: number;
  gridH: number;
  originX: number;
  originY: number;
  cellSize: number;
  maxZ: number;
} | null {
  const posAttr = geometry.getAttribute("position");
  const index = geometry.getIndex();
  if (!posAttr || !index) return null;

  // 1. Find Z range
  let maxZ = -Infinity;
  let minZ = Infinity;
  for (let i = 0; i < posAttr.count; i++) {
    const z = posAttr.getZ(i);
    if (z > maxZ) maxZ = z;
    if (z < minZ) minZ = z;
  }
  if (maxZ <= minZ) return null;

  // 2. Collect top-face vertex XY coordinates
  const tolerance = (maxZ - minZ) * 0.01 + 1e-6;
  const topPoints: [number, number][] = [];
  for (let i = 0; i < posAttr.count; i++) {
    if (Math.abs(posAttr.getZ(i) - maxZ) < tolerance) {
      topPoints.push([posAttr.getX(i), posAttr.getY(i)]);
    }
  }
  if (topPoints.length < 3) return null;

  // 3. Compute bounding box
  let bMinX = Infinity, bMaxX = -Infinity, bMinY = Infinity, bMaxY = -Infinity;
  for (const [x, y] of topPoints) {
    if (x < bMinX) bMinX = x;
    if (x > bMaxX) bMaxX = x;
    if (y < bMinY) bMinY = y;
    if (y > bMaxY) bMaxY = y;
  }
  const rangeX = bMaxX - bMinX;
  const rangeY = bMaxY - bMinY;
  if (rangeX < 1e-6 || rangeY < 1e-6) return null;

  // Cell size: derive pixel_scale from mesh vertex spacing.
  // Backend voxels are at [(x+shrink)*ps, (x+1-shrink)*ps] where ps=pixel_scale, shrink=0.05.
  // Sorted unique X coords have alternating gaps: shrink_gap (~0.1*ps) and voxel_width (~0.9*ps).
  // pixel_scale = shrink_gap + voxel_width. We detect this by clustering gaps into two groups.
  const uniqueXs = Array.from(new Set(topPoints.map(p => Math.round(p[0] * 1e4) / 1e4))).sort((a, b) => a - b);
  let cellSize: number;
  if (uniqueXs.length >= 4) {
    // Collect all positive gaps between consecutive unique X values
    const gaps: number[] = [];
    for (let i = 1; i < uniqueXs.length; i++) {
      const gap = uniqueXs[i] - uniqueXs[i - 1];
      if (gap > 1e-6) gaps.push(gap);
    }
    if (gaps.length >= 2) {
      gaps.sort((a, b) => a - b);
      // Split into two clusters: small gaps (shrink) and large gaps (voxel width).
      // The boundary is at the largest jump between consecutive sorted gaps.
      let maxJump = 0, splitIdx = 0;
      for (let i = 1; i < gaps.length; i++) {
        const jump = gaps[i] - gaps[i - 1];
        if (jump > maxJump) { maxJump = jump; splitIdx = i; }
      }
      // Average of small cluster + average of large cluster = pixel_scale
      if (splitIdx > 0 && splitIdx < gaps.length) {
        let sumSmall = 0;
        for (let i = 0; i < splitIdx; i++) sumSmall += gaps[i];
        const avgSmall = sumSmall / splitIdx;
        let sumLarge = 0;
        for (let i = splitIdx; i < gaps.length; i++) sumLarge += gaps[i];
        const avgLarge = sumLarge / (gaps.length - splitIdx);
        cellSize = avgSmall + avgLarge;
      } else {
        // All gaps are similar — likely no shrink gap, use median gap directly
        cellSize = gaps[Math.floor(gaps.length / 2)];
      }
    } else {
      cellSize = gaps.length > 0 ? gaps[0] : rangeX;
    }
  } else {
    // Too few unique X values — fallback: cap grid to reasonable resolution
    cellSize = Math.max(rangeX, rangeY) / Math.min(Math.max(rangeX, rangeY), 512);
    if (cellSize < 1e-6) cellSize = 1.0;
  }
  const gridW = Math.ceil(rangeX / cellSize) + 2; // +2 for padding
  const gridH = Math.ceil(rangeY / cellSize) + 2;

  // 4. Fill occupancy grid from top-face triangles
  const grid = new Uint8Array(gridW * gridH);

  // Mark cells that contain top-face vertices
  for (const [x, y] of topPoints) {
    const gx = Math.min(gridW - 2, Math.max(0, Math.floor((x - bMinX) / cellSize))) + 1;
    const gy = Math.min(gridH - 2, Math.max(0, Math.floor((y - bMinY) / cellSize))) + 1;
    grid[gy * gridW + gx] = 1;
  }

  // Also fill cells covered by top-face triangles (scan triangle interiors)
  const topVertexSet = new Set<number>();
  for (let i = 0; i < posAttr.count; i++) {
    if (Math.abs(posAttr.getZ(i) - maxZ) < tolerance) {
      topVertexSet.add(i);
    }
  }
  for (let i = 0; i < index.count; i += 3) {
    const a = index.getX(i), b = index.getX(i + 1), c = index.getX(i + 2);
    if (topVertexSet.has(a) && topVertexSet.has(b) && topVertexSet.has(c)) {
      fillTriangleInGrid(
        posAttr.getX(a), posAttr.getY(a),
        posAttr.getX(b), posAttr.getY(b),
        posAttr.getX(c), posAttr.getY(c),
        grid, gridW, gridH, bMinX, bMinY, cellSize,
      );
    }
  }

  return { grid, gridW, gridH, originX: bMinX, originY: bMinY, cellSize, maxZ };
}


/**
 * Rasterize a triangle into the occupancy grid.
 * 将三角形光栅化到占用网格中。
 */
function fillTriangleInGrid(
  x0: number, y0: number,
  x1: number, y1: number,
  x2: number, y2: number,
  grid: Uint8Array, gridW: number, gridH: number,
  originX: number, originY: number, cellSize: number,
): void {
  const gx0 = (x0 - originX) / cellSize + 1;
  const gy0 = (y0 - originY) / cellSize + 1;
  const gx1 = (x1 - originX) / cellSize + 1;
  const gy1 = (y1 - originY) / cellSize + 1;
  const gx2 = (x2 - originX) / cellSize + 1;
  const gy2 = (y2 - originY) / cellSize + 1;

  const minGY = Math.max(1, Math.floor(Math.min(gy0, gy1, gy2)));
  const maxGY = Math.min(gridH - 2, Math.ceil(Math.max(gy0, gy1, gy2)));
  const minGX = Math.max(1, Math.floor(Math.min(gx0, gx1, gx2)));
  const maxGX = Math.min(gridW - 2, Math.ceil(Math.max(gx0, gx1, gx2)));

  for (let gy = minGY; gy <= maxGY; gy++) {
    for (let gx = minGX; gx <= maxGX; gx++) {
      if (pointInTriangle(gx + 0.5, gy + 0.5, gx0, gy0, gx1, gy1, gx2, gy2)) {
        grid[gy * gridW + gx] = 1;
      }
    }
  }
}

/** Point-in-triangle test using barycentric coordinates. */
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
 * Dilate a binary grid using a 3x3 kernel for N iterations.
 * Equivalent to cv2.dilate(mask, np.ones((3,3)), iterations=N).
 * 使用 3x3 核对二值网格进行 N 次膨胀（等效于 cv2.dilate）。
 *
 * @param grid - Input binary grid (1 = occupied). (输入二值网格)
 * @param gridW - Grid width. (网格宽度)
 * @param gridH - Grid height. (网格高度)
 * @param iterations - Number of dilation iterations. (膨胀迭代次数)
 * @returns New dilated grid. (膨胀后的新网格)
 */
export function dilateGrid(
  grid: Uint8Array,
  gridW: number,
  gridH: number,
  iterations: number,
): Uint8Array {
  let current = grid;
  for (let iter = 0; iter < iterations; iter++) {
    const next = new Uint8Array(gridW * gridH);
    for (let y = 0; y < gridH; y++) {
      for (let x = 0; x < gridW; x++) {
        // 3x3 kernel: if any neighbor (including self) is 1, output is 1
        let found = false;
        for (let dy = -1; dy <= 1 && !found; dy++) {
          for (let dx = -1; dx <= 1 && !found; dx++) {
            const ny = y + dy;
            const nx = x + dx;
            if (ny >= 0 && ny < gridH && nx >= 0 && nx < gridW) {
              if (current[ny * gridW + nx] === 1) {
                found = true;
              }
            }
          }
        }
        if (found) next[y * gridW + x] = 1;
      }
    }
    current = next;
  }
  return current;
}

/**
 * Create ring mask by subtracting original grid from dilated grid.
 * Ring = dilated AND NOT original.
 * 通过从膨胀网格中减去原始网格来创建环形掩码。
 *
 * @param dilated - Dilated grid. (膨胀后的网格)
 * @param original - Original grid. (原始网格)
 * @param gridW - Grid width. (网格宽度)
 * @param gridH - Grid height. (网格高度)
 * @returns Ring mask grid. (环形掩码网格)
 */
export function createRingMask(
  dilated: Uint8Array,
  original: Uint8Array,
  gridW: number,
  gridH: number,
): Uint8Array {
  const ring = new Uint8Array(gridW * gridH);
  for (let i = 0; i < gridW * gridH; i++) {
    ring[i] = (dilated[i] === 1 && original[i] === 0) ? 1 : 0;
  }
  return ring;
}


/**
 * Greedy rectangle merge on a binary ring mask.
 * Scans row by row, finds horizontal runs, then extends downward.
 * Returns an array of rectangles [x0, y0, x1, y1] in grid coordinates.
 * Equivalent to the backend _greedy_rect_merge algorithm.
 * 对二值环形掩码进行贪心矩形合并。
 *
 * @param ring - Ring mask grid. (环形掩码网格)
 * @param gridW - Grid width. (网格宽度)
 * @param gridH - Grid height. (网格高度)
 * @returns Array of rectangles [x0, y0, x1, y1]. (矩形数组)
 */
export function greedyRectMerge(
  ring: Uint8Array,
  gridW: number,
  gridH: number,
): [number, number, number, number][] {
  const processed = new Uint8Array(gridW * gridH);
  const rects: [number, number, number, number][] = [];

  for (let y = 0; y < gridH; y++) {
    for (let x = 0; x < gridW; x++) {
      if (ring[y * gridW + x] !== 1 || processed[y * gridW + x] === 1) continue;

      // Find horizontal run starting at (x, y)
      let xEnd = x + 1;
      while (xEnd < gridW && ring[y * gridW + xEnd] === 1 && processed[y * gridW + xEnd] === 0) {
        xEnd++;
      }

      // Extend downward
      let yEnd = y + 1;
      while (yEnd < gridH) {
        let rowOk = true;
        for (let xi = x; xi < xEnd; xi++) {
          if (ring[yEnd * gridW + xi] !== 1 || processed[yEnd * gridW + xi] === 1) {
            rowOk = false;
            break;
          }
        }
        if (!rowOk) break;
        yEnd++;
      }

      // Mark as processed
      for (let ry = y; ry < yEnd; ry++) {
        for (let rx = x; rx < xEnd; rx++) {
          processed[ry * gridW + rx] = 1;
        }
      }

      rects.push([x, y, xEnd, yEnd]);
    }
  }

  return rects;
}

/**
 * Extrude rectangles into 3D box geometries and merge into a single BufferGeometry.
 * Each rectangle becomes a box with 8 vertices and 12 faces.
 * 将矩形挤出为 3D 盒体几何体并合并为单个 BufferGeometry。
 *
 * @param rects - Array of rectangles [x0, y0, x1, y1] in grid coords. (网格坐标中的矩形数组)
 * @param originX - World X origin of the grid. (网格的世界 X 原点)
 * @param originY - World Y origin of the grid. (网格的世界 Y 原点)
 * @param cellSize - Size of each grid cell in world units. (每个网格单元的世界单位大小)
 * @param height - Extrusion height (Z). (挤出高度)
 * @param pad - Padding offset applied to grid coords. (应用于网格坐标的填充偏移)
 * @returns Merged BufferGeometry, or null if no rectangles. (合并的 BufferGeometry，或 null)
 */
export function extrudeRectangles(
  rects: [number, number, number, number][],
  originX: number,
  originY: number,
  cellSize: number,
  height: number,
  pad: number,
): THREE.BufferGeometry | null {
  if (rects.length === 0 || height <= 0) return null;

  const vertices: number[] = [];
  const indices: number[] = [];

  for (const [x0, y0, x1, y1] of rects) {
    // Convert grid coords to world coords, subtracting pad offset
    const wx0 = originX + (x0 - pad) * cellSize;
    const wx1 = originX + (x1 - pad) * cellSize;
    const wy0 = originY + (y0 - pad) * cellSize;
    const wy1 = originY + (y1 - pad) * cellSize;

    const baseIdx = vertices.length / 3;

    // 8 vertices per box: bottom 4 + top 4
    vertices.push(
      wx0, wy0, 0,    // 0: bottom-front-left
      wx1, wy0, 0,    // 1: bottom-front-right
      wx1, wy1, 0,    // 2: bottom-back-right
      wx0, wy1, 0,    // 3: bottom-back-left
      wx0, wy0, height, // 4: top-front-left
      wx1, wy0, height, // 5: top-front-right
      wx1, wy1, height, // 6: top-back-right
      wx0, wy1, height, // 7: top-back-left
    );

    // 12 faces (same winding as backend)
    const cubeFaces = [
      [0, 2, 1], [0, 3, 2], // bottom
      [4, 5, 6], [4, 6, 7], // top
      [0, 1, 5], [0, 5, 4], // front
      [1, 2, 6], [1, 6, 5], // right
      [2, 3, 7], [2, 7, 6], // back
      [3, 0, 4], [3, 4, 7], // left
    ];

    for (const face of cubeFaces) {
      indices.push(face[0] + baseIdx, face[1] + baseIdx, face[2] + baseIdx);
    }
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
  geo.setIndex(indices);
  geo.computeVertexNormals();
  return geo;
}

// ========== Legacy exports for test compatibility ==========

/**
 * Offset a 2D contour outward by the given distance using miter joins.
 * 使用 miter 连接将 2D 轮廓向外偏移指定距离。
 * @deprecated Use dilateGrid + createRingMask + greedyRectMerge instead.
 */
export function offsetContour(
  contour: [number, number][],
  offset: number,
): [number, number][] {
  const n = contour.length;
  if (n < 3) return contour;
  const MAX_MITER_RATIO = 2.0;
  const result: [number, number][] = [];
  for (let i = 0; i < n; i++) {
    const prev = contour[(i - 1 + n) % n];
    const curr = contour[i];
    const next = contour[(i + 1) % n];
    const dx_prev = curr[0] - prev[0];
    const dy_prev = curr[1] - prev[1];
    const dx_next = next[0] - curr[0];
    const dy_next = next[1] - curr[1];
    const len_prev = Math.sqrt(dx_prev * dx_prev + dy_prev * dy_prev) || 1e-10;
    const nx_prev = -dy_prev / len_prev;
    const ny_prev = dx_prev / len_prev;
    const len_next = Math.sqrt(dx_next * dx_next + dy_next * dy_next) || 1e-10;
    const nx_next = -dy_next / len_next;
    const ny_next = dx_next / len_next;
    let nx_avg = nx_prev + nx_next;
    let ny_avg = ny_prev + ny_next;
    const len_avg = Math.sqrt(nx_avg * nx_avg + ny_avg * ny_avg) || 1e-10;
    nx_avg /= len_avg;
    ny_avg /= len_avg;
    const dot = nx_avg * nx_prev + ny_avg * ny_prev;
    const absDot = Math.abs(dot);
    let miterScale: number;
    if (absDot < 1e-6) {
      miterScale = offset;
    } else {
      miterScale = offset / absDot;
      if (miterScale > MAX_MITER_RATIO * offset) {
        miterScale = MAX_MITER_RATIO * offset;
      }
    }
    result.push([curr[0] + nx_avg * miterScale, curr[1] + ny_avg * miterScale]);
  }
  return result;
}

/**
 * Create a ring-shaped outline geometry from inner and outer contours.
 * @deprecated Use dilateGrid + createRingMask + greedyRectMerge + extrudeRectangles instead.
 */
export function createOutlineRingGeometry(
  innerContour: [number, number][],
  outerContour: [number, number][],
  height: number,
): THREE.BufferGeometry | null {
  const n = innerContour.length;
  if (n < 3 || outerContour.length !== n || height <= 0) return null;
  const vertices: number[] = [];
  const indices: number[] = [];
  for (let i = 0; i < n; i++) {
    const [ix, iy] = innerContour[i];
    const [ox, oy] = outerContour[i];
    vertices.push(ix, iy, 0, ix, iy, height, ox, oy, 0, ox, oy, height);
  }
  for (let i = 0; i < n; i++) {
    const next = (i + 1) % n;
    const ci = i * 4, cn = next * 4;
    indices.push(ci+1, ci+3, cn+3, ci+1, cn+3, cn+1);
    indices.push(ci+0, cn+0, cn+2, ci+0, cn+2, ci+2);
    indices.push(ci+2, cn+2, cn+3, ci+2, cn+3, ci+3);
    indices.push(cn+0, ci+0, ci+1, cn+0, ci+1, cn+1);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
  geo.setIndex(indices);
  geo.computeVertexNormals();
  return geo;
}

/**
 * Extract boundary contour from backing plate mesh (legacy wrapper).
 * @deprecated Use rasterizeMeshToGrid instead.
 */
export function extractBoundaryContour(
  geometry: THREE.BufferGeometry,
): [number, number][] | null {
  const result = rasterizeMeshToGrid(geometry);
  if (!result) return null;
  // Return the occupied cell centers as a simple contour (for legacy test compat)
  const { grid, gridW, gridH, originX, originY, cellSize } = result;
  const points: [number, number][] = [];
  for (let y = 0; y < gridH; y++) {
    for (let x = 0; x < gridW; x++) {
      if (grid[y * gridW + x] === 1) {
        // Check if boundary cell (has at least one empty 4-neighbor)
        const hasEmpty =
          x === 0 || grid[y * gridW + (x - 1)] === 0 ||
          x === gridW - 1 || grid[y * gridW + (x + 1)] === 0 ||
          y === 0 || grid[(y - 1) * gridW + x] === 0 ||
          y === gridH - 1 || grid[(y + 1) * gridW + x] === 0;
        if (hasEmpty) {
          points.push([originX + (x - 0.5) * cellSize, originY + (y - 0.5) * cellSize]);
        }
      }
    }
  }
  return points.length >= 3 ? points : null;
}

// ========== Component ==========

export interface OutlineFrame3DProps {
  enabled: boolean;
  outlineWidth: number;
  backingPlateMesh: THREE.Mesh | null;
  modelMaxZ: number;
}

/**
 * 3D outline frame component with flowing RGB rainbow animation.
 * Algorithm: rasterize mesh → pad → dilate → subtract → greedy rect merge → extrude boxes.
 * Color: per-vertex HSL hue based on angle from center, animated each frame.
 * 使用与后端一致的算法渲染外轮廓，并添加 RGB 炫彩灯带动画效果。
 */
export default function OutlineFrame3D({
  enabled,
  outlineWidth,
  backingPlateMesh,
  modelMaxZ,
}: OutlineFrame3DProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const tmpColor = useRef(new THREE.Color());

  const geometry = useMemo(() => {
    if (!enabled || !backingPlateMesh || outlineWidth <= 0 || modelMaxZ <= 0) {
      return null;
    }

    // 1. Rasterize backing plate mesh to occupancy grid
    const rasterResult = rasterizeMeshToGrid(backingPlateMesh.geometry);
    if (!rasterResult) return null;

    const { grid: originalGrid, gridW: origW, gridH: origH, originX, originY, cellSize } = rasterResult;

    // 2. Convert outlineWidth (mm) to grid pixels
    const outlineWidthPx = Math.max(1, Math.round(outlineWidth / cellSize));

    // 3. Pad the grid (same as backend: pad = outlineWidthPx + 1)
    const pad = outlineWidthPx + 1;
    const paddedW = origW + 2 * pad;
    const paddedH = origH + 2 * pad;
    const paddedGrid = new Uint8Array(paddedW * paddedH);

    // Copy original grid into padded grid
    for (let y = 0; y < origH; y++) {
      for (let x = 0; x < origW; x++) {
        if (originalGrid[y * origW + x] === 1) {
          paddedGrid[(y + pad) * paddedW + (x + pad)] = 1;
        }
      }
    }

    // 4. Dilate the padded grid by outlineWidthPx
    const dilated = dilateGrid(paddedGrid, paddedW, paddedH, outlineWidthPx);

    // 5. Create ring mask = dilated - original (in padded space)
    const ring = createRingMask(dilated, paddedGrid, paddedW, paddedH);

    // 6. Greedy rectangle merge
    const rects = greedyRectMerge(ring, paddedW, paddedH);
    if (rects.length === 0) return null;

    // 7. Extrude rectangles to 3D boxes
    const geo = extrudeRectangles(rects, originX - cellSize, originY - cellSize, cellSize, modelMaxZ, pad);
    if (!geo) return null;

    // 8. Compute per-vertex hue parameter based on angle from geometry center.
    //    This creates a smooth rainbow gradient around the outline ring.
    //    使用顶点相对于几何中心的角度计算色相参数，形成环绕彩虹渐变。
    const posAttr = geo.getAttribute("position");
    const vertCount = posAttr.count;

    // Find XY center of the geometry
    let cx = 0, cy = 0;
    for (let i = 0; i < vertCount; i++) {
      cx += posAttr.getX(i);
      cy += posAttr.getY(i);
    }
    cx /= vertCount;
    cy /= vertCount;

    // Assign hue = atan2(y-cy, x-cx) normalized to [0, 1]
    const colorArr = new Float32Array(vertCount * 3);
    for (let i = 0; i < vertCount; i++) {
      const angle = Math.atan2(posAttr.getY(i) - cy, posAttr.getX(i) - cx);
      const hue = (angle / (2 * Math.PI) + 1) % 1; // normalize to [0, 1]
      tmpColor.current.setHSL(hue, 1.0, 0.5);
      colorArr[i * 3] = tmpColor.current.r;
      colorArr[i * 3 + 1] = tmpColor.current.g;
      colorArr[i * 3 + 2] = tmpColor.current.b;
    }
    geo.setAttribute("color", new THREE.BufferAttribute(colorArr, 3));

    // Store the per-vertex angle ratios as userData for animation
    const hueParams = new Float32Array(vertCount);
    for (let i = 0; i < vertCount; i++) {
      const angle = Math.atan2(posAttr.getY(i) - cy, posAttr.getX(i) - cx);
      hueParams[i] = (angle / (2 * Math.PI) + 1) % 1;
    }
    geo.userData.hueParams = hueParams;

    return geo;
  }, [enabled, backingPlateMesh, outlineWidth, modelMaxZ]);

  // Flowing RGB animation with brightness pulse for visibility.
  // RGB 炫彩灯带动画 + 亮度脉动，提高选区可见性。
  const birthTime = useRef(0);
  useFrame(() => {
    if (!meshRef.current || !geometry) return;
    const colorAttr = geometry.getAttribute("color") as THREE.BufferAttribute;
    const hueParams = geometry.userData.hueParams as Float32Array | undefined;
    if (!colorAttr || !hueParams) return;

    const now = performance.now();
    if (birthTime.current === 0) birthTime.current = now;
    const age = now - birthTime.current;
    const time = now * ANIM_SPEED;

    // Flash twice on first appearance (0-600ms), then steady pulse
    let lightness: number;
    if (age < 600) {
      const phase = (age / 150) * Math.PI;
      lightness = 0.5 + 0.35 * Math.abs(Math.sin(phase));
    } else {
      lightness = 0.45 + 0.1 * Math.sin(now * 0.004);
    }

    const arr = colorAttr.array as Float32Array;
    const c = tmpColor.current;

    for (let i = 0; i < hueParams.length; i++) {
      c.setHSL((hueParams[i] + time) % 1.0, 1.0, lightness);
      arr[i * 3] = c.r;
      arr[i * 3 + 1] = c.g;
      arr[i * 3 + 2] = c.b;
    }
    colorAttr.needsUpdate = true;
  });

  if (!geometry) return null;

  return (
    <mesh ref={meshRef} geometry={geometry} position={[0, 0, 0]}>
      <meshBasicMaterial
        vertexColors
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}
