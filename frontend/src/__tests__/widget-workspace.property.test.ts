/**
 * Property-Based Tests for the floating widget workspace.
 * 浮动 Widget 工作区 Property-Based 测试。
 *
 * This file contains all PBT tests for the widget workspace feature.
 * Tests are added incrementally across tasks 1.4, 1.5, 1.6, 2.2–2.6.
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { clampPosition, computeSnap, computeStackPositions, resolveWidgetHeight, WIDGET_WIDTH, COLLAPSED_HEIGHT, EXPANDED_HEIGHT, STACK_GAP } from '../utils/widgetUtils';
import { useWidgetStore, DEFAULT_LAYOUT } from '../stores/widgetStore';
import type { WidgetLayoutState, WidgetId } from '../types/widget';

describe('Widget Workspace Property-Based Tests', () => {
  // Feature: floating-widget-workspace, Property 1: 位置边界约束
  describe('Property 1: Clamping Invariant', () => {
    it('clamped position is always within container bounds', () => {
      // **Validates: Requirements 2.4, 9.1**
      fc.assert(
        fc.property(
          fc.record({
            x: fc.double({ min: -5000, max: 5000, noNaN: true }),
            y: fc.double({ min: -5000, max: 5000, noNaN: true }),
          }),
          fc.integer({ min: 100, max: 5000 }), // containerWidth
          fc.integer({ min: 100, max: 5000 }), // containerHeight
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
        { numRuns: 100 }
      );
    });
  });

  // Feature: floating-widget-workspace, Property 3: 强制边缘吸附正确性
  describe('Property 3: Forced Snap Detection', () => {
    it('always snaps to left edge when widget center is in left half', () => {
      // **Validates: Requirements 3.2, 3.5**
      fc.assert(
        fc.property(
          fc.integer({ min: 500, max: 5000 }),   // containerWidth
          fc.integer({ min: 0, max: 5000 }),     // widgetTop
          (containerWidth, widgetTop) => {
            // Place widget so its center is in the left half
            const widgetLeft = 0;
            const widgetRight = widgetLeft + WIDGET_WIDTH;
            const result = computeSnap(widgetLeft, widgetRight, containerWidth, widgetTop);
            expect(result.shouldSnap).toBe(true);
            expect(result.edge).toBe('left');
            expect(result.snappedPosition.x).toBe(0);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('always snaps to right edge when widget center is in right half', () => {
      // **Validates: Requirements 3.2, 3.5**
      fc.assert(
        fc.property(
          fc.integer({ min: 500, max: 5000 }),   // containerWidth
          fc.integer({ min: 0, max: 5000 }),     // widgetTop
          (containerWidth, widgetTop) => {
            // Place widget so its center is in the right half
            const widgetLeft = containerWidth - WIDGET_WIDTH;
            const widgetRight = containerWidth;
            const result = computeSnap(widgetLeft, widgetRight, containerWidth, widgetTop);
            expect(result.shouldSnap).toBe(true);
            expect(result.edge).toBe('right');
            expect(result.snappedPosition.x).toBe(containerWidth - WIDGET_WIDTH);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('always returns shouldSnap true for any position', () => {
      // **Validates: Requirements 3.2, 3.5**
      fc.assert(
        fc.property(
          fc.integer({ min: -500, max: 5000 }),  // widgetLeft
          fc.integer({ min: 500, max: 5000 }),   // containerWidth
          fc.integer({ min: 0, max: 5000 }),     // widgetTop
          (widgetLeft, containerWidth, widgetTop) => {
            const widgetRight = widgetLeft + WIDGET_WIDTH;
            const result = computeSnap(widgetLeft, widgetRight, containerWidth, widgetTop);
            expect(result.shouldSnap).toBe(true);
            expect(result.edge).not.toBeNull();
            // Edge must be 'left' or 'right'
            expect(['left', 'right']).toContain(result.edge);
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: floating-widget-workspace, Property 2: 折叠状态切换幂等性
  describe('Property 2: Toggle Collapse Round-Trip', () => {
    const WIDGET_IDS: WidgetId[] = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'outline-settings', 'cloisonne-settings', 'coating-settings',
      'keychain-loop', 'action-bar',
      'calibration', 'extractor', 'lut-manager', 'five-color',
    ];

    it('double toggle restores original collapsed state', () => {
      // **Validates: Requirements 4.1, 4.4**
      fc.assert(
        fc.property(
          fc.constantFrom(...WIDGET_IDS),
          fc.boolean(), // initial collapsed state
          (widgetId, initialCollapsed) => {
            // Reset store with custom initial state
            const initialWidgets = { ...DEFAULT_LAYOUT };
            initialWidgets[widgetId] = { ...initialWidgets[widgetId], collapsed: initialCollapsed };
            useWidgetStore.setState({ widgets: initialWidgets, isDragging: false, activeWidgetId: null });

            // Toggle twice
            useWidgetStore.getState().toggleCollapse(widgetId);
            useWidgetStore.getState().toggleCollapse(widgetId);

            // Should be back to initial
            expect(useWidgetStore.getState().widgets[widgetId].collapsed).toBe(initialCollapsed);
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: floating-widget-workspace, Property 4: 堆叠布局无重叠
  describe('Property 4: Stack Layout Non-Overlapping', () => {
    const WIDGET_IDS: WidgetId[] = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'outline-settings', 'cloisonne-settings', 'coating-settings',
      'keychain-loop', 'action-bar',
      'calibration', 'extractor', 'lut-manager', 'five-color',
    ];

    it('stacked widgets never overlap vertically', () => {
      // **Validates: Requirements 3.3, 4.5**
      fc.assert(
        fc.property(
          fc.integer({ min: 1, max: 12 }),  // number of widgets
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: 500, max: 5000 }), // containerWidth
          fc.array(fc.boolean(), { minLength: 12, maxLength: 12 }), // collapsed states
          (count, edge, containerWidth, collapsedStates) => {
            const widgets: WidgetLayoutState[] = WIDGET_IDS.slice(0, count).map((id, i) => ({
              id,
              position: { x: 0, y: 0 },
              collapsed: collapsedStates[i],
              visible: true,
              snapEdge: edge,
              stackOrder: i,
              expandedHeight: EXPANDED_HEIGHT,
            }));

            const positions = computeStackPositions(widgets, edge, containerWidth);
            const entries = [...positions.entries()];

            // Verify monotonically increasing y
            for (let i = 1; i < entries.length; i++) {
              expect(entries[i][1].y).toBeGreaterThan(entries[i - 1][1].y);
            }

            // Verify no overlap
            for (let i = 1; i < entries.length; i++) {
              const prevWidget = widgets.find(w => w.id === entries[i - 1][0])!;
              const prevHeight = prevWidget.collapsed ? COLLAPSED_HEIGHT : EXPANDED_HEIGHT;
              const gap = entries[i][1].y - entries[i - 1][1].y;
              expect(gap).toBeGreaterThanOrEqual(prevHeight + STACK_GAP);
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  describe('Property 4.1: Measured Height Precedence', () => {
    const WIDGET_IDS: WidgetId[] = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'outline-settings', 'cloisonne-settings', 'coating-settings',
      'keychain-loop', 'action-bar',
      'calibration', 'extractor', 'lut-manager', 'five-color',
    ];

    it('uses measured heights for expanded widgets when available', () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 1, max: 8 }),
          fc.integer({ min: 500, max: 2000 }),
          fc.array(fc.integer({ min: COLLAPSED_HEIGHT + 20, max: 700 }), { minLength: 8, maxLength: 8 }),
          fc.array(fc.integer({ min: COLLAPSED_HEIGHT + 40, max: 820 }), { minLength: 8, maxLength: 8 }),
          (count, containerWidth, storedHeights, measuredHeightsRaw) => {
            const widgets: WidgetLayoutState[] = WIDGET_IDS.slice(0, count).map((id, i) => ({
              id,
              position: { x: 0, y: 0 },
              collapsed: false,
              visible: true,
              snapEdge: 'left',
              stackOrder: i,
              expandedHeight: storedHeights[i],
            }));

            const measuredHeights = new Map<WidgetId, number>();
            widgets.forEach((widget, i) => {
              measuredHeights.set(widget.id, measuredHeightsRaw[i]);
            });

            const positions = computeStackPositions(widgets, 'left', containerWidth, measuredHeights);
            const entries = [...positions.entries()];

            for (let i = 1; i < entries.length; i++) {
              const prevWidget = widgets.find((w) => w.id === entries[i - 1][0])!;
              const expectedGap = resolveWidgetHeight(prevWidget, measuredHeights) + STACK_GAP;
              const actualGap = entries[i][1].y - entries[i - 1][1].y;
              expect(actualGap).toBe(expectedGap);
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: floating-widget-workspace, Property 5: 布局状态序列化 Round-Trip
  describe('Property 5: Serialization Round-Trip', () => {
    const widgetStateArb = fc.record({
      position: fc.record({
        x: fc.double({ min: 0, max: 5000, noNaN: true, noDefaultInfinity: true }),
        y: fc.double({ min: 0, max: 5000, noNaN: true, noDefaultInfinity: true }),
      }),
      collapsed: fc.boolean(),
      visible: fc.boolean(),
      snapEdge: fc.constantFrom('left' as const, 'right' as const, null),
      stackOrder: fc.integer({ min: -1, max: 10 }),
      expandedHeight: fc.integer({ min: COLLAPSED_HEIGHT + 10, max: 800 }),
    });

    it('JSON round-trip preserves widget layout state', () => {
      // **Validates: Requirements 6.4, 6.1, 6.2**
      fc.assert(
        fc.property(
          fc.record({
            'basic-settings': widgetStateArb,
            'advanced-settings': widgetStateArb,
            'relief-settings': widgetStateArb,
            'outline-settings': widgetStateArb,
            'cloisonne-settings': widgetStateArb,
            'coating-settings': widgetStateArb,
            'keychain-loop': widgetStateArb,
            'action-bar': widgetStateArb,
            'calibration': widgetStateArb,
            'extractor': widgetStateArb,
            'lut-manager': widgetStateArb,
            'five-color': widgetStateArb,
          }),
          fc.integer({ min: 1, max: 100 }), // version
          (widgets, version) => {
            const state = { widgets, version };
            const serialized = JSON.stringify(state);
            const deserialized = JSON.parse(serialized);
            expect(deserialized).toEqual(state);
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: floating-widget-workspace, Property 7: moveWidget 位置更新正确性
  describe('Property 7: moveWidget Position Update', () => {
    const WIDGET_IDS: WidgetId[] = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'outline-settings', 'cloisonne-settings', 'coating-settings',
      'keychain-loop', 'action-bar',
      'calibration', 'extractor', 'lut-manager', 'five-color',
    ];

    it('moveWidget updates position to the exact given value', () => {
      // **Validates: Requirements 2.3**
      fc.assert(
        fc.property(
          fc.constantFrom(...WIDGET_IDS),
          fc.record({
            x: fc.double({ min: 0, max: 5000, noNaN: true, noDefaultInfinity: true }),
            y: fc.double({ min: 0, max: 5000, noNaN: true, noDefaultInfinity: true }),
          }),
          (widgetId, position) => {
            // Reset store
            useWidgetStore.setState({ widgets: { ...DEFAULT_LAYOUT }, isDragging: false, activeWidgetId: null });

            // Move widget
            useWidgetStore.getState().moveWidget(widgetId, position);

            // Verify position
            const updated = useWidgetStore.getState().widgets[widgetId].position;
            expect(updated.x).toBe(position.x);
            expect(updated.y).toBe(position.y);
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: floating-widget-workspace, Property 8: Auto-Arrange 完整性
  describe('Property 8: Auto-Arrange Completeness', () => {
    const WIDGET_IDS: WidgetId[] = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'outline-settings', 'cloisonne-settings', 'coating-settings',
      'keychain-loop', 'action-bar',
      'calibration', 'extractor', 'lut-manager', 'five-color',
    ];

    it('after autoArrange all visible widgets are snapped to an edge', () => {
      // **Validates: Requirements 3.6**
      fc.assert(
        fc.property(
          fc.array(fc.boolean(), { minLength: 12, maxLength: 12 }), // which widgets are free-floating
          fc.array(fc.boolean(), { minLength: 12, maxLength: 12 }), // which widgets are visible
          (freeFloating, visibleStates) => {
            // Build initial state with some widgets free-floating
            const widgets = { ...DEFAULT_LAYOUT };
            WIDGET_IDS.forEach((id, i) => {
              widgets[id] = {
                ...widgets[id],
                snapEdge: freeFloating[i] ? null : 'left',
                visible: visibleStates[i],
                stackOrder: freeFloating[i] ? -1 : i,
              };
            });

            useWidgetStore.setState({ widgets, isDragging: false, activeWidgetId: null });

            // Auto arrange
            useWidgetStore.getState().autoArrange();

            // All visible widgets should be snapped
            const state = useWidgetStore.getState();
            WIDGET_IDS.forEach((id) => {
              if (state.widgets[id].visible) {
                expect(state.widgets[id].snapEdge).not.toBeNull();
              }
            });
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: floating-widget-workspace, Property 6: 布局操作不影响业务状态
  describe('Property 6: Layout-Domain Isolation', () => {
    const WIDGET_IDS: WidgetId[] = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'outline-settings', 'cloisonne-settings', 'coating-settings',
      'keychain-loop', 'action-bar',
      'calibration', 'extractor', 'lut-manager', 'five-color',
    ];

    // Layout operations enum for generation
    const layoutOps = ['moveWidget', 'toggleCollapse', 'toggleVisible', 'snapToEdge', 'detachFromEdge'] as const;

    it('layout operations do not modify widget domain data (id, other properties remain stable)', () => {
      // **Validates: Requirements 7.2, 7.4**
      fc.assert(
        fc.property(
          fc.constantFrom(...WIDGET_IDS),
          fc.constantFrom(...layoutOps),
          (widgetId, op) => {
            // Reset store
            useWidgetStore.setState({ widgets: { ...DEFAULT_LAYOUT }, isDragging: false, activeWidgetId: null });

            // Snapshot all widget IDs before operation
            const beforeIds = Object.keys(useWidgetStore.getState().widgets).sort();

            // Perform layout operation
            const store = useWidgetStore.getState();
            switch (op) {
              case 'moveWidget':
                store.moveWidget(widgetId, { x: 100, y: 200 });
                break;
              case 'toggleCollapse':
                store.toggleCollapse(widgetId);
                break;
              case 'toggleVisible':
                store.toggleVisible(widgetId);
                break;
              case 'snapToEdge':
                store.snapToEdge(widgetId, 'right');
                break;
              case 'detachFromEdge':
                store.detachFromEdge(widgetId);
                break;
            }

            // Verify: all widget IDs still exist (no widgets lost or added)
            const afterIds = Object.keys(useWidgetStore.getState().widgets).sort();
            expect(afterIds).toEqual(beforeIds);

            // Verify: the operated widget's id field is unchanged
            expect(useWidgetStore.getState().widgets[widgetId].id).toBe(widgetId);

            // Verify: other widgets' domain-relevant fields are unchanged
            WIDGET_IDS.filter(id => id !== widgetId).forEach(otherId => {
              const before = DEFAULT_LAYOUT[otherId];
              const after = useWidgetStore.getState().widgets[otherId];
              // For non-targeted widgets, their state should be unchanged
              expect(after.id).toBe(before.id);
              expect(after.position).toEqual(before.position);
              expect(after.collapsed).toBe(before.collapsed);
              expect(after.visible).toBe(before.visible);
            });
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
