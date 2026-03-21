/**
 * Property-Based Test: computeStackPositions 非重叠性
 * Stack positions computed by computeStackPositions never overlap.
 *
 * Feature: granular-floating-widgets, Property 4: 堆叠位置不重叠
 * **Validates: Requirements 9.1**
 *
 * For any set of widgets (1-14) snapped to the same edge with random
 * collapsed states, computeStackPositions should return positions where
 * each widget's y + height + STACK_GAP <= next widget's y.
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  computeStackPositions,
  COLLAPSED_HEIGHT,
  EXPANDED_HEIGHT,
  STACK_GAP,
} from '../utils/widgetUtils';
import type { WidgetId, WidgetLayoutState } from '../types/widget';

// All 14 valid WidgetIds
const ALL_WIDGET_IDS: WidgetId[] = [
  'basic-settings', 'advanced-settings', 'relief-settings',
  'palette-panel', 'lut-color-grid', 'outline-settings',
  'cloisonne-settings', 'coating-settings', 'keychain-loop', 'action-bar',
  'calibration', 'extractor', 'lut-manager', 'five-color',
];

/**
 * Arbitrary: generate a random subset of 1-14 widgets with random collapsed states,
 * all snapped to the given edge, with sequential stackOrder.
 */
const stackWidgetsArb = (edge: 'left' | 'right'): fc.Arbitrary<WidgetLayoutState[]> =>
  fc.tuple(
    fc.integer({ min: 1, max: 14 }),
    fc.shuffledSubarray(ALL_WIDGET_IDS, { minLength: 1, maxLength: 14 }),
    fc.array(fc.boolean(), { minLength: 14, maxLength: 14 }),
  ).chain(([count, shuffledIds, collapsedStates]) => {
    const actualCount = Math.min(count, shuffledIds.length);
    const ids = shuffledIds.slice(0, actualCount);
    return fc.constant(
      ids.map((id, i) => ({
        id,
        position: { x: 0, y: 0 },
        collapsed: collapsedStates[i],
        visible: true,
        snapEdge: edge,
        stackOrder: i,
      }))
    );
  });

describe('Granular Floating Widgets — Property-Based Tests', () => {
  // Feature: granular-floating-widgets, Property 4: 堆叠位置不重叠
  describe('Property 4: 堆叠位置不重叠', () => {
    it('stacked widgets never overlap vertically (left edge)', () => {
      // **Validates: Requirements 9.1**
      fc.assert(
        fc.property(
          stackWidgetsArb('left'),
          fc.integer({ min: 500, max: 5000 }), // containerWidth
          (widgets, containerWidth) => {
            const positions = computeStackPositions(widgets, 'left', containerWidth);
            assertNoOverlap(widgets, positions);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('stacked widgets never overlap vertically (right edge)', () => {
      // **Validates: Requirements 9.1**
      fc.assert(
        fc.property(
          stackWidgetsArb('right'),
          fc.integer({ min: 500, max: 5000 }), // containerWidth
          (widgets, containerWidth) => {
            const positions = computeStackPositions(widgets, 'right', containerWidth);
            assertNoOverlap(widgets, positions);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('stacked widgets never overlap with random edge', () => {
      // **Validates: Requirements 9.1**
      fc.assert(
        fc.property(
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: 500, max: 5000 }),
          fc.integer({ min: 1, max: 14 }),
          fc.array(fc.boolean(), { minLength: 14, maxLength: 14 }),
          (edge, containerWidth, count, collapsedStates) => {
            const ids = ALL_WIDGET_IDS.slice(0, count);
            const widgets: WidgetLayoutState[] = ids.map((id, i) => ({
              id,
              position: { x: 0, y: 0 },
              collapsed: collapsedStates[i],
              visible: true,
              snapEdge: edge,
              stackOrder: i,
            }));

            const positions = computeStackPositions(widgets, edge, containerWidth);
            assertNoOverlap(widgets, positions);
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});

/**
 * Assert that consecutive widgets in the stack do not overlap.
 * For each pair of consecutive widgets (sorted by stackOrder):
 *   widget[i].y + widget[i].height + STACK_GAP <= widget[i+1].y
 */
function assertNoOverlap(
  widgets: WidgetLayoutState[],
  positions: Map<WidgetId, { x: number; y: number }>
) {
  // Sort widgets by stackOrder (same order computeStackPositions uses)
  const sorted = [...widgets].sort((a, b) => a.stackOrder - b.stackOrder);
  const entries = sorted.map((w) => ({
    id: w.id,
    y: positions.get(w.id)!.y,
    collapsed: w.collapsed,
  }));

  // Verify monotonically increasing y
  for (let i = 1; i < entries.length; i++) {
    expect(entries[i].y).toBeGreaterThan(entries[i - 1].y);
  }

  // Verify no overlap: prev.y + prevHeight + STACK_GAP <= current.y
  for (let i = 1; i < entries.length; i++) {
    const prev = entries[i - 1];
    const curr = entries[i];
    const prevHeight = prev.collapsed ? COLLAPSED_HEIGHT : EXPANDED_HEIGHT;
    const minNextY = prev.y + prevHeight + STACK_GAP;
    expect(curr.y).toBeGreaterThanOrEqual(minNextY);
  }
}
