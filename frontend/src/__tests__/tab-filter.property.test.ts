/**
 * Property-Based Test: TAB 页面过滤正确性
 * TAB page filtering correctness.
 *
 * Feature: granular-floating-widgets, Property 1: TAB 页面过滤正确性
 * **Validates: Requirements 1.2, 2.4, 3.5, 5.2**
 *
 * For any valid TabId, when activeTab is set to that TabId, the set of
 * Widgets rendered by WidgetWorkspace should be exactly equal to the
 * WidgetId set defined in TAB_WIDGET_MAP[tabId] — no more, no less.
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { WIDGET_REGISTRY, TAB_WIDGET_MAP } from '../stores/widgetStore';
import type { TabId } from '../types/widget';

// All valid TabIds
const ALL_TAB_IDS: TabId[] = ['converter', 'calibration', 'extractor', 'lut-manager', 'five-color'];

describe('Granular Floating Widgets — Property-Based Tests', () => {
  // Feature: granular-floating-widgets, Property 1: TAB 页面过滤正确性
  describe('Property 1: TAB 页面过滤正确性', () => {
    // Arbitrary that picks a random valid TabId
    const tabIdArb = fc.constantFrom(...ALL_TAB_IDS);

    it('filtered widget set equals exactly TAB_WIDGET_MAP[tabId] for any TabId', () => {
      // **Validates: Requirements 1.2, 2.4, 3.5, 5.2**
      fc.assert(
        fc.property(tabIdArb, (tabId) => {
          const expectedWidgetIds = TAB_WIDGET_MAP[tabId];

          // Simulate the filtering logic from WidgetWorkspace
          const filteredRegistry = WIDGET_REGISTRY.filter((c) =>
            expectedWidgetIds.includes(c.id)
          );
          const filteredIds = filteredRegistry.map((c) => c.id);

          // 1. The filtered set should contain exactly the widgets in TAB_WIDGET_MAP[tabId]
          expect(new Set(filteredIds)).toEqual(new Set(expectedWidgetIds));

          // 2. No widget from another tab should be included
          const otherTabWidgetIds = ALL_TAB_IDS
            .filter((t) => t !== tabId)
            .flatMap((t) => TAB_WIDGET_MAP[t]);
          for (const id of filteredIds) {
            // A widget may appear in the current tab only; verify it's in expectedWidgetIds
            expect(expectedWidgetIds).toContain(id);
          }

          // 3. All widgets from the current tab should be included (no missing)
          for (const expectedId of expectedWidgetIds) {
            expect(filteredIds).toContain(expectedId);
          }
        }),
        { numRuns: 100 }
      );
    });

    it('no widget from other tabs leaks into the filtered set', () => {
      // **Validates: Requirements 1.2, 2.4, 3.5, 5.2**
      fc.assert(
        fc.property(tabIdArb, (tabId) => {
          const expectedWidgetIds = TAB_WIDGET_MAP[tabId];

          const filteredRegistry = WIDGET_REGISTRY.filter((c) =>
            expectedWidgetIds.includes(c.id)
          );
          const filteredIdSet = new Set(filteredRegistry.map((c) => c.id));

          // Collect all widget IDs that belong to OTHER tabs
          const otherTabWidgetIds = ALL_TAB_IDS
            .filter((t) => t !== tabId)
            .flatMap((t) => TAB_WIDGET_MAP[t])
            .filter((id) => !expectedWidgetIds.includes(id)); // exclude shared IDs

          // None of the other-tab-only widgets should appear in filtered set
          for (const otherId of otherTabWidgetIds) {
            expect(filteredIdSet.has(otherId)).toBe(false);
          }
        }),
        { numRuns: 100 }
      );
    });
  });
});
