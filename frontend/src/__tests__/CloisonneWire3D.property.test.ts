import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import * as THREE from "three";
import { rasterizeColorMeshesToGrid, detectColorEdges, maskIntersection } from "../components/CloisonneWire3D";

// ========== Types ==========

/** A simple axis-aligned rectangle definition for generating test meshes. */
interface RectDef {
  x: number;
  y: number;
  w: number;
  h: number;
}

// ========== Helpers ==========

/**
 * Create a THREE.Mesh representing a flat rectangular ColorMesh with a top face.
 * The mesh is a box with the top face at z = topZ and bottom at z = 0.
 * 从简单矩形定义创建一个模拟 ColorMesh 的 THREE.Mesh。
 *
 * @param rect - Rectangle definition in world coordinates. (世界坐标中的矩形定义)
 * @param topZ - Z coordinate of the top face. (顶面 Z 坐标)
 * @returns THREE.Mesh with BufferGeometry containing the box. (包含盒体的 THREE.Mesh)
 */
function createRectMesh(rect: RectDef, topZ: number = 1.0): THREE.Mesh {
  const { x, y, w, h } = rect;
  // 8 vertices of a box: 4 bottom (z=0) + 4 top (z=topZ)
  const positions = new Float32Array([
    // Bottom face (z = 0)
    x,     y,     0,     // 0: bottom-left-bottom
    x + w, y,     0,     // 1: bottom-right-bottom
    x + w, y + h, 0,     // 2: top-right-bottom
    x,     y + h, 0,     // 3: top-left-bottom
    // Top face (z = topZ)
    x,     y,     topZ,  // 4: bottom-left-top
    x + w, y,     topZ,  // 5: bottom-right-top
    x + w, y + h, topZ,  // 6: top-right-top
    x,     y + h, topZ,  // 7: top-left-top
  ]);

  // 12 triangles (6 faces × 2 triangles each)
  const indices = new Uint16Array([
    // Bottom face (z=0)
    0, 2, 1,  0, 3, 2,
    // Top face (z=topZ) — this is what rasterizeColorMeshesToGrid scans
    4, 5, 6,  4, 6, 7,
    // Front face (y=y)
    0, 1, 5,  0, 5, 4,
    // Back face (y=y+h)
    2, 3, 7,  2, 7, 6,
    // Left face (x=x)
    0, 4, 7,  0, 7, 3,
    // Right face (x=x+w)
    1, 2, 6,  1, 6, 5,
  ]);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  return new THREE.Mesh(geometry);
}

// ========== Generators ==========

/**
 * Generate a set of non-overlapping rectangles within a bounded area.
 * Uses a grid-based placement strategy to guarantee no overlaps.
 * 生成一组不重叠的矩形，使用网格放置策略保证无重叠。
 */
function nonOverlappingRectsArb(): fc.Arbitrary<{
  rects: RectDef[];
  cellSize: number;
  gridW: number;
  gridH: number;
}> {
  return fc
    .record({
      cellSize: fc.double({ min: 0.1, max: 1.0, noNaN: true, noDefaultInfinity: true }),
      // Number of grid slots in each dimension for placing rectangles
      slotsX: fc.integer({ min: 2, max: 6 }),
      slotsY: fc.integer({ min: 2, max: 6 }),
      numRects: fc.integer({ min: 1, max: 4 }),
    })
    .chain(({ cellSize, slotsX, slotsY, numRects }) => {
      // Each slot is slotSize cells wide/tall; rectangles are placed within slots
      const slotSize = 3; // each slot is 3 cells wide
      const totalCellsX = slotsX * slotSize;
      const totalCellsY = slotsY * slotSize;

      // Generate unique slot positions for each rectangle
      const totalSlots = slotsX * slotsY;
      const actualNumRects = Math.min(numRects, totalSlots);

      return fc
        .shuffledSubarray(
          Array.from({ length: totalSlots }, (_, i) => i),
          { minLength: actualNumRects, maxLength: actualNumRects },
        )
        .map((slotIndices) => {
          const rects: RectDef[] = slotIndices.map((slotIdx) => {
            const slotCol = slotIdx % slotsX;
            const slotRow = Math.floor(slotIdx / slotsX);
            // Place a rectangle occupying the inner part of the slot (leave 0 margin)
            // Each rect is exactly slotSize cells in world coords
            const x = slotCol * slotSize * cellSize;
            const y = slotRow * slotSize * cellSize;
            const w = slotSize * cellSize;
            const h = slotSize * cellSize;
            return { x, y, w, h };
          });

          return {
            rects,
            cellSize,
            gridW: totalCellsX,
            gridH: totalCellsY,
          };
        });
    });
}

// ========== Property-Based Tests ==========

describe("CloisonneWire3D — Property-Based Tests", () => {
  /**
   * **Feature: cloisonne-3d-preview, Property 1: 光栅化颜色索引正确性**
   * **Validates: Requirements 1.1**
   *
   * For any set of non-overlapping rectangles (simulating ColorMesh top faces),
   * after rasterizing them to a ColorGrid, pixels inside each rectangle should
   * have the corresponding color index, and pixels outside all rectangles should be -1.
   */
  it("Property 1: 光栅化颜色索引正确性 — pixels inside rectangles have correct color index, outside are -1", () => {
    fc.assert(
      fc.property(nonOverlappingRectsArb(), ({ rects, cellSize, gridW, gridH }) => {
        // Build THREE.Mesh[] from rectangle definitions
        const meshes = rects.map((r) => createRectMesh(r));

        const originX = 0;
        const originY = 0;
        const grid = rasterizeColorMeshesToGrid(meshes, cellSize, originX, originY, gridW, gridH);

        // Verify grid dimensions
        expect(grid.length).toBe(gridW * gridH);

        // For each pixel, determine expected color index
        for (let gy = 0; gy < gridH; gy++) {
          for (let gx = 0; gx < gridW; gx++) {
            const idx = gy * gridW + gx;
            const actual = grid[idx];

            // Cell center in world coordinates
            const worldX = originX + (gx + 0.5) * cellSize;
            const worldY = originY + (gy + 0.5) * cellSize;

            // Find which rectangle (if any) contains this cell center
            // Last-write-wins: the highest-indexed rectangle that contains the point
            let expectedIndex = -1;
            for (let ri = 0; ri < rects.length; ri++) {
              const r = rects[ri];
              if (
                worldX >= r.x && worldX <= r.x + r.w &&
                worldY >= r.y && worldY <= r.y + r.h
              ) {
                expectedIndex = ri;
              }
            }

            if (expectedIndex >= 0) {
              // Pixel inside a rectangle should have the correct color index
              expect(actual).toBe(expectedIndex);
            } else {
              // Pixel outside all rectangles should be -1
              expect(actual).toBe(-1);
            }
          }
        }
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Feature: cloisonne-3d-preview, Property 2: 边缘检测正确性**
   * **Validates: Requirements 1.2, 1.3**
   *
   * For any ColorGrid, detectColorEdges returns an edge mask satisfying:
   * (a) Every pixel marked as edge has at least one 4-neighbor with a different solid color index
   *     (out-of-bounds and -1 neighbors do NOT trigger edges);
   * (b) Every non-edge solid pixel (value ≠ -1) has no 4-neighbor with a different solid color;
   * (c) Pixels with value -1 are never marked as edge.
   */
  it("Property 2: 边缘检测正确性 — edge mask satisfies 4-neighbor difference conditions", () => {
    // Generator: random ColorGrid with dimensions 2-20 x 2-20, values -1 to N-1 (2-5 colors)
    const colorGridArb = fc
      .record({
        gridW: fc.integer({ min: 2, max: 20 }),
        gridH: fc.integer({ min: 2, max: 20 }),
        numColors: fc.integer({ min: 2, max: 5 }),
      })
      .chain(({ gridW, gridH, numColors }) =>
        fc
          .array(fc.integer({ min: -1, max: numColors - 1 }), {
            minLength: gridW * gridH,
            maxLength: gridW * gridH,
          })
          .map((values) => ({
            gridW,
            gridH,
            colorGrid: new Int16Array(values),
          })),
      );

    fc.assert(
      fc.property(colorGridArb, ({ gridW, gridH, colorGrid }) => {
        const edges = detectColorEdges(colorGrid, gridW, gridH);

        // 4-neighbor offsets
        const dx = [1, -1, 0, 0];
        const dy = [0, 0, 1, -1];

        expect(edges.length).toBe(gridW * gridH);

        for (let y = 0; y < gridH; y++) {
          for (let x = 0; x < gridW; x++) {
            const idx = y * gridW + x;
            const color = colorGrid[idx];
            const isEdge = edges[idx] === 1;

            // (c) Pixels with value -1 are never marked as edge
            if (color === -1) {
              expect(isEdge).toBe(false);
              continue;
            }

            // Compute whether any neighbor is a different SOLID color.
            // Out-of-bounds and -1 neighbors do NOT trigger edge detection
            // (only real color boundaries between two different solid colors).
            let hasDifferentSolidNeighbor = false;
            for (let d = 0; d < 4; d++) {
              const nx = x + dx[d];
              const ny = y + dy[d];
              if (nx < 0 || nx >= gridW || ny < 0 || ny >= gridH) {
                // Out-of-bounds: not an edge trigger
                continue;
              }
              const nc = colorGrid[ny * gridW + nx];
              if (nc === -1) {
                // Empty neighbor: not an edge trigger
                continue;
              }
              if (nc !== color) {
                hasDifferentSolidNeighbor = true;
                break;
              }
            }

            if (isEdge) {
              // (a) Edge pixel must have at least one different solid neighbor
              expect(hasDifferentSolidNeighbor).toBe(true);
            } else {
              // (b) Non-edge solid pixel has no different solid neighbor
              expect(hasDifferentSolidNeighbor).toBe(false);
            }
          }
        }
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Feature: cloisonne-3d-preview, Property 3: 实体掩码交集正确性**
   * **Validates: Requirements 2.2**
   *
   * For any dilated edge mask and solid mask, the intersection result satisfies:
   * (a) Every pixel that is 1 in the result is also 1 in the solid mask;
   * (b) For all i, result[i] === (dilatedEdgeMask[i] & solidMask[i]).
   */
  it("Property 3: 实体掩码交集正确性 — intersection result is subset of solid mask and equals bitwise AND", () => {
    const maskPairArb = fc
      .record({
        gridW: fc.integer({ min: 2, max: 20 }),
        gridH: fc.integer({ min: 2, max: 20 }),
      })
      .chain(({ gridW, gridH }) => {
        const len = gridW * gridH;
        const binaryArrayArb = fc.array(fc.integer({ min: 0, max: 1 }), {
          minLength: len,
          maxLength: len,
        });
        return fc
          .tuple(binaryArrayArb, binaryArrayArb)
          .map(([dilatedVals, solidVals]) => ({
            gridW,
            gridH,
            dilatedEdgeMask: new Uint8Array(dilatedVals),
            solidMask: new Uint8Array(solidVals),
          }));
      });

    fc.assert(
      fc.property(maskPairArb, ({ gridW, gridH, dilatedEdgeMask, solidMask }) => {
        const result = maskIntersection(dilatedEdgeMask, solidMask, gridW, gridH);
        const len = gridW * gridH;

        expect(result.length).toBe(len);

        for (let i = 0; i < len; i++) {
          // (b) result equals bitwise AND of the two masks
          expect(result[i]).toBe(dilatedEdgeMask[i] & solidMask[i]);

          // (a) every 1 in result must also be 1 in solidMask
          if (result[i] === 1) {
            expect(solidMask[i]).toBe(1);
          }
        }
      }),
      { numRuns: 100 },
    );
  });
});

// ========== Property 4 imports ==========
import { createSolidMask } from "../components/CloisonneWire3D";
import {
  dilateGrid,
  greedyRectMerge,
  extrudeRectangles,
} from "../components/OutlineFrame3D";

// ========== Property 4 Generator ==========

/**
 * Generate a random ColorGrid guaranteed to contain at least 2 distinct colors (non -1).
 * Also generates positive wireWidthMm, wireHeightMm, and a matching cellSize.
 * 生成保证包含至少 2 种不同颜色的随机 ColorGrid，以及正数的 wireWidthMm 和 wireHeightMm。
 */
function fullPipelineInputArb(): fc.Arbitrary<{
  colorGrid: Int16Array;
  gridW: number;
  gridH: number;
  cellSize: number;
  wireWidthMm: number;
  wireHeightMm: number;
}> {
  return fc
    .record({
      gridW: fc.integer({ min: 3, max: 20 }),
      gridH: fc.integer({ min: 3, max: 20 }),
      numColors: fc.integer({ min: 2, max: 5 }),
      cellSize: fc.double({ min: 0.1, max: 2.0, noNaN: true, noDefaultInfinity: true }),
      wireWidthMm: fc.double({ min: 0.1, max: 2.0, noNaN: true, noDefaultInfinity: true }),
      wireHeightMm: fc.double({ min: 0.04, max: 1.0, noNaN: true, noDefaultInfinity: true }),
    })
    .chain(({ gridW, gridH, numColors, cellSize, wireWidthMm, wireHeightMm }) => {
      const len = gridW * gridH;
      // Generate grid values from 0..numColors-1 (no -1, so all pixels are solid)
      // This guarantees edges exist when at least 2 colors are present.
      return fc
        .array(fc.integer({ min: 0, max: numColors - 1 }), {
          minLength: len,
          maxLength: len,
        })
        .filter((values) => {
          // Ensure at least 2 distinct color values exist
          const unique = new Set(values);
          return unique.size >= 2;
        })
        .map((values) => ({
          colorGrid: new Int16Array(values),
          gridW,
          gridH,
          cellSize,
          wireWidthMm,
          wireHeightMm,
        }));
    });
}

// ========== Property 4 Test ==========

describe("CloisonneWire3D — Property 4", () => {
  /**
   * **Feature: cloisonne-3d-preview, Property 4: 完整管线产生有效几何体**
   * **Validates: Requirements 2.1, 3.1, 3.2**
   *
   * For any valid ColorGrid (containing at least 2 distinct colors) and positive
   * wireWidthMm, wireHeightMm, the full pipeline
   * (detectColorEdges → dilateGrid → maskWithSolid → greedyRectMerge → extrudeRectangles)
   * should produce a non-empty BufferGeometry with vertices > 0 and indices > 0.
   */
  it("Property 4: 完整管线产生有效几何体 — full pipeline produces valid geometry with vertices and indices", () => {
    fc.assert(
      fc.property(fullPipelineInputArb(), ({ colorGrid, gridW, gridH, cellSize, wireWidthMm, wireHeightMm }) => {
        // Step 1: Detect color edges
        const edgeMask = detectColorEdges(colorGrid, gridW, gridH);

        // Verify edges exist (guaranteed by having ≥2 colors in a connected grid)
        let hasEdge = false;
        for (let i = 0; i < edgeMask.length; i++) {
          if (edgeMask[i] === 1) { hasEdge = true; break; }
        }
        expect(hasEdge).toBe(true);

        // Step 2: Dilate edges by wireWidthMm converted to pixel count
        const dilatePixels = Math.max(1, Math.round(wireWidthMm / cellSize));
        const dilatedMask = dilateGrid(edgeMask, gridW, gridH, dilatePixels);

        // Step 3: Create solid mask and intersect with dilated edges
        const solidMask = createSolidMask(colorGrid, gridW, gridH);
        const wireMask = maskIntersection(dilatedMask, solidMask, gridW, gridH);

        // Verify wire mask has at least one pixel set
        let hasWire = false;
        for (let i = 0; i < wireMask.length; i++) {
          if (wireMask[i] === 1) { hasWire = true; break; }
        }
        expect(hasWire).toBe(true);

        // Step 4: Greedy rectangle merge
        const rects = greedyRectMerge(wireMask, gridW, gridH);
        expect(rects.length).toBeGreaterThan(0);

        // Step 5: Extrude rectangles into 3D geometry
        const originX = 0;
        const originY = 0;
        const pad = 0;
        const geometry = extrudeRectangles(rects, originX, originY, cellSize, wireHeightMm, pad);

        // Verify geometry is non-null with valid vertices and indices
        expect(geometry).not.toBeNull();
        const posAttr = geometry!.getAttribute("position");
        expect(posAttr).toBeDefined();
        expect(posAttr.count).toBeGreaterThan(0);

        const index = geometry!.getIndex();
        expect(index).not.toBeNull();
        expect(index!.count).toBeGreaterThan(0);
      }),
      { numRuns: 100 },
    );
  });
});
