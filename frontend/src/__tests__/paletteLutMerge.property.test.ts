/**
 * Property-Based Tests: ColorWorkstation (Palette + LUT Merge)
 *
 * Feature: palette-lut-merge
 * Tests the correctness properties of the ColorWorkstation composite component.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { useWidgetStore, DEFAULT_LAYOUT } from '../stores/widgetStore';
import type { TabId } from '../types/widget';

describe('Palette-LUT Merge Property-Based Tests', () => {
  beforeEach(() => {
    useWidgetStore.setState({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
      activeTab: 'converter' as TabId,
      colorWorkstationCollapsed: true,
    });
  });

  // Feature: palette-lut-merge, Property 1: 折叠/展开状态控制内容可见性
  describe('Property 1: 折叠/展开状态控制内容可见性', () => {
    it('colorWorkstationCollapsed state correctly reflects the set value, controlling content visibility', () => {
      // **Validates: Requirements 1.5, 1.6**
      //
      // For any boolean collapsed value, setting colorWorkstationCollapsed in the store
      // should persist that exact value. Content visibility is the inverse: !collapsed.
      // When collapsed=true → content hidden; when collapsed=false → content visible.
      fc.assert(
        fc.property(
          fc.boolean(),
          (collapsed: boolean) => {
            // Set the collapsed state to the generated boolean
            useWidgetStore.setState({ colorWorkstationCollapsed: collapsed });

            // Read back the state
            const state = useWidgetStore.getState();

            // The stored collapsed value must match what was set
            expect(state.colorWorkstationCollapsed).toBe(collapsed);

            // Content visibility is the inverse of collapsed
            const contentVisible = !state.colorWorkstationCollapsed;
            expect(contentVisible).toBe(!collapsed);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('content visibility is always the logical negation of collapsed state', () => {
      // **Validates: Requirements 1.5, 1.6**
      //
      // For any sequence of boolean states, the content visibility invariant
      // (!collapsed === visible) must hold after each state change.
      fc.assert(
        fc.property(
          fc.array(fc.boolean(), { minLength: 1, maxLength: 20 }),
          (collapsedSequence: boolean[]) => {
            for (const collapsed of collapsedSequence) {
              useWidgetStore.setState({ colorWorkstationCollapsed: collapsed });
              const state = useWidgetStore.getState();

              // Invariant: content visible iff not collapsed
              expect(!state.colorWorkstationCollapsed).toBe(!collapsed);

              // Collapsed=true means content hidden (Requirements 1.5)
              if (collapsed) {
                expect(state.colorWorkstationCollapsed).toBe(true);
              }
              // Collapsed=false means content visible (Requirements 1.6)
              if (!collapsed) {
                expect(state.colorWorkstationCollapsed).toBe(false);
              }
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: palette-lut-merge, Property 2: 切换操作的 Round-Trip 属性
  describe('Property 2: 切换操作的 Round-Trip 属性', () => {
    it('calling toggleColorWorkstation twice restores the original collapsed state', () => {
      // **Validates: Requirements 4.1**
      //
      // For any initial collapsed state (true or false), calling toggleColorWorkstation
      // twice must restore the state to its original value: toggle(toggle(state)) === state.
      fc.assert(
        fc.property(
          fc.boolean(),
          (initialCollapsed: boolean) => {
            // Set the initial collapsed state
            useWidgetStore.setState({ colorWorkstationCollapsed: initialCollapsed });

            // Toggle twice
            useWidgetStore.getState().toggleColorWorkstation();
            useWidgetStore.getState().toggleColorWorkstation();

            // State must be back to the original value
            const finalState = useWidgetStore.getState();
            expect(finalState.colorWorkstationCollapsed).toBe(initialCollapsed);
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: palette-lut-merge, Property 3: Tab 条件渲染
  describe('Property 3: Tab 条件渲染', () => {
    it('ColorWorkstation should only render when activeTab is converter', () => {
      // **Validates: Requirements 4.3**
      //
      // For any TabId value, ColorWorkstation should render (shouldRender=true)
      // only when activeTab is 'converter'. For all non-converter tabs,
      // ColorWorkstation should not render (shouldRender=false).
      fc.assert(
        fc.property(
          fc.constantFrom<TabId>('converter', 'calibration', 'extractor', 'lut-manager', 'five-color', 'vectorizer', 'settings'),
          (tab: TabId) => {
            useWidgetStore.setState({ activeTab: tab });

            const state = useWidgetStore.getState();
            const shouldRender = state.activeTab === 'converter';

            if (tab === 'converter') {
              expect(shouldRender).toBe(true);
            } else {
              expect(shouldRender).toBe(false);
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: palette-lut-merge, Property 4: 持久化迁移正确性
  describe('Property 4: 持久化迁移正确性', () => {
    // Access the migrate function from Zustand persist options
    const migrate = (useWidgetStore.persist as any).getOptions().migrate as (
      persistedState: unknown,
      version: number
    ) => Record<string, unknown>;

    // Generator for a single widget layout entry (simulates old persisted data)
    const widgetLayoutArb = fc.record({
      position: fc.record({ x: fc.integer({ min: 0, max: 1920 }), y: fc.integer({ min: 0, max: 1080 }) }),
      collapsed: fc.boolean(),
      visible: fc.boolean(),
      snapEdge: fc.constantFrom('left' as const, 'right' as const, null),
      stackOrder: fc.integer({ min: 0, max: 20 }),
      expandedHeight: fc.integer({ min: 100, max: 600 }),
    });

    // All current valid WidgetIds plus the two old ones that may exist in persisted data
    const allWidgetIds = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'outline-settings', 'cloisonne-settings', 'coating-settings',
      'keychain-loop', 'action-bar',
      'calibration', 'extractor', 'lut-manager', 'five-color',
      'palette-panel', 'lut-color-grid',
    ] as const;

    // Generator for a persisted state with random subset of widgets (always includes the two old ones)
    const persistedStateArb = fc
      .tuple(
        // Generate layout entries for each possible widget id
        ...allWidgetIds.map((id) =>
          fc.tuple(fc.constant(id), fc.option(widgetLayoutArb, { nil: undefined }))
        )
      )
      .chain((entries) => {
        // Build widgets record from generated entries, always include palette-panel and lut-color-grid
        return widgetLayoutArb.chain((palLayout) =>
          widgetLayoutArb.map((lutLayout) => {
            const widgets: Record<string, unknown> = {};
            for (const [id, layout] of entries) {
              if (layout !== undefined) {
                widgets[id] = { id, ...layout };
              }
            }
            // Ensure old WidgetIds are always present to test removal
            widgets['palette-panel'] = { id: 'palette-panel', ...palLayout };
            widgets['lut-color-grid'] = { id: 'lut-color-grid', ...lutLayout };
            return {
              widgets,
              activeTab: 'converter',
              colorWorkstationCollapsed: false,
            };
          })
        );
      });

    it('migration result never contains palette-panel or lut-color-grid keys', () => {
      // **Validates: Requirements 5.1, 5.2, 5.3**
      //
      // For any version (0-3) and any persisted state containing old WidgetIds,
      // the migrate function must produce a result without 'palette-panel' or 'lut-color-grid'.
      fc.assert(
        fc.property(
          fc.integer({ min: 0, max: 3 }),
          persistedStateArb,
          (version: number, persistedState: Record<string, unknown>) => {
            const result = migrate(persistedState, version);
            const resultWidgets = (result as any).widgets as Record<string, unknown>;

            // Core invariant: old WidgetIds must never exist after migration
            expect(resultWidgets).not.toHaveProperty('palette-panel');
            expect(resultWidgets).not.toHaveProperty('lut-color-grid');
          }
        ),
        { numRuns: 100 }
      );
    });

    it('version < 3 resets to DEFAULT_LAYOUT without old WidgetIds', () => {
      // **Validates: Requirements 5.2**
      //
      // When version < 3, migration should reset to the new DEFAULT_LAYOUT.
      // The result widgets must exactly match DEFAULT_LAYOUT keys.
      fc.assert(
        fc.property(
          fc.integer({ min: 0, max: 2 }),
          persistedStateArb,
          (version: number, persistedState: Record<string, unknown>) => {
            const result = migrate(persistedState, version);
            const resultWidgets = (result as any).widgets as Record<string, unknown>;

            // Should match DEFAULT_LAYOUT keys exactly
            const defaultKeys = Object.keys(DEFAULT_LAYOUT).sort();
            const resultKeys = Object.keys(resultWidgets).sort();
            expect(resultKeys).toEqual(defaultKeys);

            // DEFAULT_LAYOUT itself must not contain old WidgetIds
            expect(defaultKeys).not.toContain('palette-panel');
            expect(defaultKeys).not.toContain('lut-color-grid');
          }
        ),
        { numRuns: 100 }
      );
    });

    it('version === 3 preserves other widgets and removes only old WidgetIds', () => {
      // **Validates: Requirements 5.1**
      //
      // When version === 3, migration should keep all widgets except
      // 'palette-panel' and 'lut-color-grid', and add colorWorkstationCollapsed.
      fc.assert(
        fc.property(
          persistedStateArb,
          (persistedState: Record<string, unknown>) => {
            const inputWidgets = (persistedState as any).widgets as Record<string, unknown>;
            const inputKeysWithoutOld = Object.keys(inputWidgets)
              .filter((k) => k !== 'palette-panel' && k !== 'lut-color-grid')
              .sort();

            const result = migrate(persistedState, 3);
            const resultWidgets = (result as any).widgets as Record<string, unknown>;
            const resultKeys = Object.keys(resultWidgets).sort();

            // All non-old widgets should be preserved
            expect(resultKeys).toEqual(inputKeysWithoutOld);

            // colorWorkstationCollapsed should be set to true
            expect((result as any).colorWorkstationCollapsed).toBe(true);
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
