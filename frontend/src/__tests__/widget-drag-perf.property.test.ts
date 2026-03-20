/**
 * Property-Based Tests for Widget drag performance optimizations.
 * Widget 拖拽性能优化 Property-Based 测试。
 *
 * Tests pure utility functions extracted during the performance refactor.
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  computeSnap,
  computeStackPositions,
  clampPosition,
  WIDGET_WIDTH,
  COLLAPSED_HEIGHT,
  EXPANDED_HEIGHT,
  STACK_GAP,
} from '../utils/widgetUtils';
import type { WidgetId, WidgetLayoutState } from '../types/widget';

describe('Widget Drag Performance Property-Based Tests', () => {
  // Feature: slider-drag-performance, Property 1: computeSnap 始终返回有效吸附结果
  describe('Property 1: computeSnap 始终返回有效吸附结果', () => {
    /**
     * **Validates: Requirements 5.1, 5.3**
     *
     * For any valid widget left/right edge positions and container width,
     * computeSnap always returns shouldSnap: true, edge is 'left' or 'right',
     * and snappedPosition.x is 0 (left snap) or containerWidth - WIDGET_WIDTH (right snap).
     * For identical inputs, the result is always consistent (pure function).
     */
    it('always returns a valid snap result for any position and container width', () => {
      // **Validates: Requirements 5.1, 5.3**
      fc.assert(
        fc.property(
          // widgetLeft: any reasonable position (can be negative from drag overshoot)
          fc.double({ min: -2000, max: 5000, noNaN: true, noDefaultInfinity: true }),
          // containerWidth: must be positive and at least WIDGET_WIDTH for meaningful layout
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          // widgetTop: any reasonable y position
          fc.double({ min: -1000, max: 5000, noNaN: true, noDefaultInfinity: true }),
          (widgetLeft, containerWidth, widgetTop) => {
            const widgetRight = widgetLeft + WIDGET_WIDTH;
            const result = computeSnap(widgetLeft, widgetRight, containerWidth, widgetTop);

            // shouldSnap is always true — widgets are never free-floating
            expect(result.shouldSnap).toBe(true);

            // edge is always 'left' or 'right'
            expect(result.edge).not.toBeNull();
            expect(['left', 'right']).toContain(result.edge);

            // snappedPosition.x is exactly 0 (left) or containerWidth - WIDGET_WIDTH (right)
            if (result.edge === 'left') {
              expect(result.snappedPosition.x).toBe(0);
            } else {
              expect(result.snappedPosition.x).toBe(containerWidth - WIDGET_WIDTH);
            }
          }
        ),
        { numRuns: 200, verbose: true }
      );
    });

    it('is a pure function — identical inputs always produce identical outputs', () => {
      // **Validates: Requirements 5.1, 5.3**
      fc.assert(
        fc.property(
          fc.double({ min: -2000, max: 5000, noNaN: true, noDefaultInfinity: true }),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          fc.double({ min: -1000, max: 5000, noNaN: true, noDefaultInfinity: true }),
          (widgetLeft, containerWidth, widgetTop) => {
            const widgetRight = widgetLeft + WIDGET_WIDTH;

            const result1 = computeSnap(widgetLeft, widgetRight, containerWidth, widgetTop);
            const result2 = computeSnap(widgetLeft, widgetRight, containerWidth, widgetTop);

            expect(result1).toEqual(result2);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('snaps to left when widget center is in the left half of the container', () => {
      // **Validates: Requirements 5.1, 5.3**
      fc.assert(
        fc.property(
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          fc.double({ min: 0, max: 5000, noNaN: true, noDefaultInfinity: true }),
          (containerWidth, widgetTop) => {
            // Place widget so center is strictly in the left half
            // center = widgetLeft + WIDGET_WIDTH / 2 < containerWidth / 2
            // => widgetLeft < containerWidth / 2 - WIDGET_WIDTH / 2
            const maxLeft = (containerWidth - WIDGET_WIDTH) / 2 - 1;
            if (maxLeft < -2000) return; // skip degenerate cases

            const widgetLeft = fc.sample(
              fc.double({ min: -2000, max: maxLeft, noNaN: true, noDefaultInfinity: true }),
              1
            )[0];
            const widgetRight = widgetLeft + WIDGET_WIDTH;

            const result = computeSnap(widgetLeft, widgetRight, containerWidth, widgetTop);
            expect(result.edge).toBe('left');
            expect(result.snappedPosition.x).toBe(0);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('snaps to right when widget center is in the right half of the container', () => {
      // **Validates: Requirements 5.1, 5.3**
      fc.assert(
        fc.property(
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          fc.double({ min: 0, max: 5000, noNaN: true, noDefaultInfinity: true }),
          (containerWidth, widgetTop) => {
            // Place widget so center is strictly in the right half
            // center = widgetLeft + WIDGET_WIDTH / 2 > containerWidth / 2
            // => widgetLeft > containerWidth / 2 - WIDGET_WIDTH / 2
            const minLeft = (containerWidth - WIDGET_WIDTH) / 2 + 1;
            if (minLeft > 5000) return; // skip degenerate cases

            const widgetLeft = fc.sample(
              fc.double({ min: minLeft, max: 5000, noNaN: true, noDefaultInfinity: true }),
              1
            )[0];
            const widgetRight = widgetLeft + WIDGET_WIDTH;

            const result = computeSnap(widgetLeft, widgetRight, containerWidth, widgetTop);
            expect(result.edge).toBe('right');
            expect(result.snappedPosition.x).toBe(containerWidth - WIDGET_WIDTH);
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: slider-drag-performance, Property 2: computeStackPositions 产生无重叠布局
  describe('Property 2: computeStackPositions 产生无重叠布局', () => {
    // All valid WidgetId values for generating realistic widgets
    const WIDGET_IDS: WidgetId[] = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'palette-panel', 'lut-color-grid', 'outline-settings',
      'cloisonne-settings', 'coating-settings', 'keychain-loop',
      'action-bar', 'calibration', 'extractor', 'lut-manager', 'five-color',
    ];

    /**
     * Smart generator: creates a valid WidgetLayoutState with unique id and stackOrder.
     * Uses the provided index to pick a unique WidgetId and assign stackOrder.
     */
    const arbWidgetLayout = (index: number): fc.Arbitrary<WidgetLayoutState> =>
      fc.record({
        id: fc.constant(WIDGET_IDS[index % WIDGET_IDS.length]),
        position: fc.record({
          x: fc.integer({ min: 0, max: 3000 }),
          y: fc.integer({ min: 0, max: 3000 }),
        }),
        collapsed: fc.boolean(),
        visible: fc.constant(true),
        snapEdge: fc.constantFrom('left' as const, 'right' as const),
        stackOrder: fc.constant(index),
        expandedHeight: fc.integer({ min: COLLAPSED_HEIGHT + 10, max: 800 }),
      });

    /**
     * Generator for a list of 1..N widgets with unique IDs and sequential stackOrder.
     */
    const arbWidgetList = (maxCount: number = 8): fc.Arbitrary<WidgetLayoutState[]> =>
      fc.integer({ min: 1, max: Math.min(maxCount, WIDGET_IDS.length) }).chain((count) =>
        fc.tuple(...Array.from({ length: count }, (_, i) => arbWidgetLayout(i))).map(
          (widgets) => widgets
        )
      );

    /**
     * **Validates: Requirements 5.2, 5.4**
     *
     * For any valid widget list with different collapsed states and expandedHeights,
     * computeStackPositions returns positions where adjacent widgets (sorted by stackOrder)
     * satisfy: prev.y + height + STACK_GAP === next.y.
     * For identical inputs, results are always consistent (pure function).
     */
    it('produces non-overlapping layout for adjacent stacked widgets', () => {
      // **Validates: Requirements 5.2, 5.4**
      fc.assert(
        fc.property(
          arbWidgetList(),
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgets, edge, containerWidth) => {
            const positions = computeStackPositions(widgets, edge, containerWidth);

            // Sort widgets by stackOrder (same as the function does internally)
            const sorted = [...widgets].sort((a, b) => a.stackOrder - b.stackOrder);

            // Every widget should have a computed position
            expect(positions.size).toBe(widgets.length);

            // Check adjacent pairs: prev.y + height + STACK_GAP === next.y
            for (let i = 0; i < sorted.length - 1; i++) {
              const curr = sorted[i];
              const next = sorted[i + 1];
              const currPos = positions.get(curr.id)!;
              const nextPos = positions.get(next.id)!;

              const currHeight = curr.collapsed
                ? COLLAPSED_HEIGHT
                : (curr.expandedHeight ?? EXPANDED_HEIGHT);

              expect(nextPos.y).toBe(currPos.y + currHeight + STACK_GAP);
            }

            // First widget starts at y = STACK_GAP (top padding)
            if (sorted.length > 0) {
              const firstPos = positions.get(sorted[0].id)!;
              expect(firstPos.y).toBe(STACK_GAP);
            }
          }
        ),
        { numRuns: 200, verbose: true }
      );
    });

    it('is a pure function — identical inputs always produce identical outputs', () => {
      // **Validates: Requirements 5.2, 5.4**
      fc.assert(
        fc.property(
          arbWidgetList(),
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgets, edge, containerWidth) => {
            const result1 = computeStackPositions(widgets, edge, containerWidth);
            const result2 = computeStackPositions(widgets, edge, containerWidth);

            // Convert Maps to comparable objects
            const obj1 = Object.fromEntries(result1);
            const obj2 = Object.fromEntries(result2);
            expect(obj1).toEqual(obj2);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('assigns correct x position based on edge', () => {
      // **Validates: Requirements 5.2, 5.4**
      fc.assert(
        fc.property(
          arbWidgetList(),
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgets, edge, containerWidth) => {
            const positions = computeStackPositions(widgets, edge, containerWidth);
            const expectedX = edge === 'left' ? 0 : containerWidth - WIDGET_WIDTH;

            for (const [, pos] of positions) {
              expect(pos.x).toBe(expectedX);
            }
          }
        ),
        { numRuns: 100 }
      );
    });

    it('produces no overlapping y-ranges between any two widgets', () => {
      // **Validates: Requirements 5.2, 5.4**
      fc.assert(
        fc.property(
          arbWidgetList(),
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgets, edge, containerWidth) => {
            const positions = computeStackPositions(widgets, edge, containerWidth);

            // Build y-ranges for each widget
            const ranges = widgets.map((w) => {
              const pos = positions.get(w.id)!;
              const height = w.collapsed
                ? COLLAPSED_HEIGHT
                : (w.expandedHeight ?? EXPANDED_HEIGHT);
              return { id: w.id, top: pos.y, bottom: pos.y + height };
            });

            // No two widgets should overlap in y
            for (let i = 0; i < ranges.length; i++) {
              for (let j = i + 1; j < ranges.length; j++) {
                const a = ranges[i];
                const b = ranges[j];
                // Overlap exists if a.top < b.bottom AND b.top < a.bottom
                const overlaps = a.top < b.bottom && b.top < a.bottom;
                expect(overlaps).toBe(false);
              }
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: slider-drag-performance, Property 3: clampPosition 保持位置在容器边界内
  describe('Property 3: clampPosition 保持位置在容器边界内', () => {
    /**
     * **Validates: Requirements 5.5**
     *
     * For any position {x, y} and positive container dimensions {containerWidth, containerHeight},
     * clampPosition returns a position satisfying:
     *   0 <= result.x <= max(0, containerWidth - widgetWidth)
     *   0 <= result.y <= max(0, containerHeight - headerHeight)
     */

    // Smart generators: positions can be negative or very large (drag overshoot scenarios)
    const arbPosition = fc.record({
      x: fc.double({ min: -5000, max: 10000, noNaN: true, noDefaultInfinity: true }),
      y: fc.double({ min: -5000, max: 10000, noNaN: true, noDefaultInfinity: true }),
    });

    // Container dimensions must be positive
    const arbContainerWidth = fc.integer({ min: 1, max: 5000 });
    const arbContainerHeight = fc.integer({ min: 1, max: 5000 });

    // Widget dimensions: positive, can be larger than container (edge case)
    const arbWidgetWidth = fc.integer({ min: 1, max: 1000 });
    const arbHeaderHeight = fc.integer({ min: 1, max: 200 });

    it('result is always within container bounds using default dimensions', () => {
      // **Validates: Requirements 5.5**
      fc.assert(
        fc.property(
          arbPosition,
          arbContainerWidth,
          arbContainerHeight,
          (position, containerWidth, containerHeight) => {
            const result = clampPosition(position, containerWidth, containerHeight);

            const maxX = Math.max(0, containerWidth - WIDGET_WIDTH);
            const maxY = Math.max(0, containerHeight - COLLAPSED_HEIGHT);

            expect(result.x).toBeGreaterThanOrEqual(0);
            expect(result.x).toBeLessThanOrEqual(maxX);
            expect(result.y).toBeGreaterThanOrEqual(0);
            expect(result.y).toBeLessThanOrEqual(maxY);
          }
        ),
        { numRuns: 200, verbose: true }
      );
    });

    it('result is always within container bounds using custom dimensions', () => {
      // **Validates: Requirements 5.5**
      fc.assert(
        fc.property(
          arbPosition,
          arbContainerWidth,
          arbContainerHeight,
          arbWidgetWidth,
          arbHeaderHeight,
          (position, containerWidth, containerHeight, widgetWidth, headerHeight) => {
            const result = clampPosition(position, containerWidth, containerHeight, widgetWidth, headerHeight);

            const maxX = Math.max(0, containerWidth - widgetWidth);
            const maxY = Math.max(0, containerHeight - headerHeight);

            expect(result.x).toBeGreaterThanOrEqual(0);
            expect(result.x).toBeLessThanOrEqual(maxX);
            expect(result.y).toBeGreaterThanOrEqual(0);
            expect(result.y).toBeLessThanOrEqual(maxY);
          }
        ),
        { numRuns: 200, verbose: true }
      );
    });

    it('is a pure function — identical inputs always produce identical outputs', () => {
      // **Validates: Requirements 5.5**
      fc.assert(
        fc.property(
          arbPosition,
          arbContainerWidth,
          arbContainerHeight,
          arbWidgetWidth,
          arbHeaderHeight,
          (position, containerWidth, containerHeight, widgetWidth, headerHeight) => {
            const result1 = clampPosition(position, containerWidth, containerHeight, widgetWidth, headerHeight);
            const result2 = clampPosition(position, containerWidth, containerHeight, widgetWidth, headerHeight);

            expect(result1).toEqual(result2);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('returns position unchanged when already within bounds', () => {
      // **Validates: Requirements 5.5**
      fc.assert(
        fc.property(
          arbContainerWidth,
          arbContainerHeight,
          arbWidgetWidth,
          arbHeaderHeight,
          (containerWidth, containerHeight, widgetWidth, headerHeight) => {
            const maxX = Math.max(0, containerWidth - widgetWidth);
            const maxY = Math.max(0, containerHeight - headerHeight);

            // Skip if no valid interior range exists
            if (maxX <= 0 || maxY <= 0) return;

            // Generate a position strictly within bounds
            const pos = {
              x: fc.sample(fc.double({ min: 0, max: maxX, noNaN: true, noDefaultInfinity: true }), 1)[0],
              y: fc.sample(fc.double({ min: 0, max: maxY, noNaN: true, noDefaultInfinity: true }), 1)[0],
            };

            const result = clampPosition(pos, containerWidth, containerHeight, widgetWidth, headerHeight);

            expect(result.x).toBe(pos.x);
            expect(result.y).toBe(pos.y);
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
