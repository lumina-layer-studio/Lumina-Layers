import { describe, it, expect, beforeEach, vi } from "vitest";
import * as fc from "fast-check";
import { useSlicerStore } from "../slicerStore";

/**
 * Property: setSelectedSlicerId 对任意字符串正确更新状态
 * **Validates: Requirements 4.4**
 *
 * Feature: slicer-integration, Property: setSelectedSlicerId idempotent
 *
 * For any string or null value passed to setSelectedSlicerId,
 * the store's selectedSlicerId state should equal that value immediately after the call.
 */

vi.mock("../../api/slicer", () => ({
  detectSlicers: vi.fn(),
  launchSlicer: vi.fn(),
}));

// ========== Helpers ==========

function resetStore(): void {
  useSlicerStore.setState({
    slicers: [],
    selectedSlicerId: null,
    isDetecting: false,
    isLaunching: false,
    launchMessage: null,
    error: null,
  });
}

// ========== Arbitraries ==========

/** Arbitrary: string or null, matching the setSelectedSlicerId parameter type */
const arbSlicerId = fc.oneof(fc.string(), fc.constant(null));

// ========== Tests ==========

describe("Property: setSelectedSlicerId 对任意字符串正确更新状态", () => {
  beforeEach(() => {
    resetStore();
  });

  it("setSelectedSlicerId(value) 后 getState().selectedSlicerId === value", () => {
    fc.assert(
      fc.property(arbSlicerId, (value) => {
        resetStore();

        useSlicerStore.getState().setSelectedSlicerId(value);

        expect(useSlicerStore.getState().selectedSlicerId).toBe(value);
      }),
      { numRuns: 100 },
    );
  });

  it("连续调用 setSelectedSlicerId 最终状态等于最后一次调用的值", () => {
    fc.assert(
      fc.property(
        fc.array(arbSlicerId, { minLength: 1, maxLength: 20 }),
        (values) => {
          resetStore();

          for (const v of values) {
            useSlicerStore.getState().setSelectedSlicerId(v);
          }

          const last = values[values.length - 1];
          expect(useSlicerStore.getState().selectedSlicerId).toBe(last);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("setSelectedSlicerId 不影响其他状态字段", () => {
    fc.assert(
      fc.property(arbSlicerId, (value) => {
        resetStore();

        const before = useSlicerStore.getState();
        const snapshotBefore = {
          slicers: before.slicers,
          isDetecting: before.isDetecting,
          isLaunching: before.isLaunching,
          launchMessage: before.launchMessage,
          error: before.error,
        };

        useSlicerStore.getState().setSelectedSlicerId(value);

        const after = useSlicerStore.getState();
        expect(after.slicers).toEqual(snapshotBefore.slicers);
        expect(after.isDetecting).toBe(snapshotBefore.isDetecting);
        expect(after.isLaunching).toBe(snapshotBefore.isLaunching);
        expect(after.launchMessage).toBe(snapshotBefore.launchMessage);
        expect(after.error).toBe(snapshotBefore.error);
      }),
      { numRuns: 100 },
    );
  });
});
