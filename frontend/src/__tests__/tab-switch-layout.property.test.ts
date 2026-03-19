/**
 * Property-Based Test: TAB 切换保持 Widget 布局不变性
 * TAB switching preserves widget layout invariance.
 *
 * Feature: granular-floating-widgets, Property 2: TAB 切换保持 Widget 布局不变性
 * **Validates: Requirements 1.4**
 *
 * For any widget layout state and any TAB switching sequence (from TabId A
 * to TabId B then back to TabId A), each widget's position, collapsed,
 * visible, snapEdge, and stackOrder fields should remain unchanged.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { useWidgetStore, DEFAULT_LAYOUT } from '../stores/widgetStore';
import type { WidgetId, WidgetLayoutState, TabId } from '../types/widget';

// All valid TabIds
const ALL_TAB_IDS: TabId[] = ['converter', 'calibration', 'extractor', 'lut-manager', 'five-color', 'vectorizer', 'settings'];

// All valid WidgetIds
const ALL_WIDGET_IDS: WidgetId[] = [
  'basic-settings', 'advanced-settings', 'relief-settings',
  'outline-settings', 'cloisonne-settings', 'coating-settings',
  'keychain-loop', 'action-bar', 'calibration', 'extractor',
  'lut-manager', 'five-color',
];

// Arbitrary for a single WidgetLayoutState with randomized layout fields
const widgetLayoutArb = (id: WidgetId): fc.Arbitrary<WidgetLayoutState> =>
  fc.record({
    id: fc.constant(id),
    position: fc.record({
      x: fc.double({ min: 0, max: 5000, noNaN: true, noDefaultInfinity: true }),
      y: fc.double({ min: 0, max: 5000, noNaN: true, noDefaultInfinity: true }),
    }),
    collapsed: fc.boolean(),
    visible: fc.boolean(),
    snapEdge: fc.constantFrom('left' as const, 'right' as const, null),
    stackOrder: fc.integer({ min: -1, max: 20 }),
    expandedHeight: fc.integer({ min: 50, max: 800 }),
  });

// Arbitrary for a full widgets record with randomized layout for all 14 widgets
const allWidgetsArb: fc.Arbitrary<Record<WidgetId, WidgetLayoutState>> = fc.tuple(
  ...ALL_WIDGET_IDS.map((id) => widgetLayoutArb(id))
).map((layouts) => {
  const record = {} as Record<WidgetId, WidgetLayoutState>;
  ALL_WIDGET_IDS.forEach((id, i) => {
    record[id] = layouts[i];
  });
  return record;
});

// Arbitrary for a TAB switching sequence: [startTab, ...intermediate tabs, startTab]
// This generates a round-trip: A -> B1 -> B2 -> ... -> A
const tabSwitchSequenceArb: fc.Arbitrary<TabId[]> = fc.tuple(
  fc.constantFrom(...ALL_TAB_IDS),                                    // starting tab
  fc.array(fc.constantFrom(...ALL_TAB_IDS), { minLength: 1, maxLength: 10 }), // intermediate tabs
).map(([startTab, intermediates]) => [startTab, ...intermediates, startTab]);

describe('Granular Floating Widgets — Property-Based Tests', () => {
  beforeEach(() => {
    // Reset store to default before each test
    useWidgetStore.setState({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
      activeTab: 'converter' as TabId,
    });
  });

  // Feature: granular-floating-widgets, Property 2: TAB 切换保持 Widget 布局不变性
  describe('Property 2: TAB 切换保持 Widget 布局不变性', () => {
    it('switching tabs and returning preserves all widget layout fields', () => {
      // **Validates: Requirements 1.4**
      fc.assert(
        fc.property(
          allWidgetsArb,
          tabSwitchSequenceArb,
          (randomWidgets, tabSequence) => {
            // Set up store with random widget layout
            useWidgetStore.setState({
              widgets: randomWidgets,
              activeTab: tabSequence[0],
            });

            // Snapshot all widget layout states before switching
            const snapshotBefore: Record<string, WidgetLayoutState> = {};
            const stateBefore = useWidgetStore.getState().widgets;
            for (const id of ALL_WIDGET_IDS) {
              snapshotBefore[id] = { ...stateBefore[id], position: { ...stateBefore[id].position } };
            }

            // Execute the full TAB switching sequence
            for (const tab of tabSequence.slice(1)) {
              useWidgetStore.getState().setActiveTab(tab);
            }

            // Verify: every widget's layout fields are unchanged
            const stateAfter = useWidgetStore.getState().widgets;
            for (const id of ALL_WIDGET_IDS) {
              const before = snapshotBefore[id];
              const after = stateAfter[id];

              expect(after.position).toEqual(before.position);
              expect(after.collapsed).toBe(before.collapsed);
              expect(after.visible).toBe(before.visible);
              expect(after.snapEdge).toBe(before.snapEdge);
              expect(after.stackOrder).toBe(before.stackOrder);
            }
          }
        ),
        { numRuns: 100 }
      );
    });

    it('single tab switch A->B does not mutate any widget state', () => {
      // **Validates: Requirements 1.4**
      fc.assert(
        fc.property(
          allWidgetsArb,
          fc.constantFrom(...ALL_TAB_IDS),
          fc.constantFrom(...ALL_TAB_IDS),
          (randomWidgets, tabA, tabB) => {
            // Set up store with random widget layout on tabA
            useWidgetStore.setState({
              widgets: randomWidgets,
              activeTab: tabA,
            });

            // Snapshot before
            const snapshotBefore = JSON.parse(JSON.stringify(useWidgetStore.getState().widgets));

            // Switch to tabB
            useWidgetStore.getState().setActiveTab(tabB);

            // Verify: widget states are identical (deep equality)
            const stateAfter = useWidgetStore.getState().widgets;
            expect(stateAfter).toEqual(snapshotBefore);
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
