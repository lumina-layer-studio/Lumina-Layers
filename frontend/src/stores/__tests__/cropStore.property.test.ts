import { describe, it, expect, beforeEach, vi } from 'vitest';
import * as fc from 'fast-check';
import { useConverterStore } from '../converterStore';

/**
 * Property-based tests for crop-related store behavior.
 * Feature: image-crop-refactor
 */

// ========== Mocks ==========

// Mock URL.createObjectURL / revokeObjectURL (setImageFile uses them)
const mockCreateObjectURL = vi.fn(() => 'blob:mock-preview');
const mockRevokeObjectURL = vi.fn();
globalThis.URL.createObjectURL = mockCreateObjectURL;
globalThis.URL.revokeObjectURL = mockRevokeObjectURL;

// Mock Image constructor (setImageFile creates an Image to get aspect ratio)
class MockImage {
  onload: (() => void) | null = null;
  src = '';
  naturalWidth = 100;
  naturalHeight = 100;
}
vi.stubGlobal('Image', MockImage);

// Mock localStorage
const localStorageMap = new Map<string, string>();
const mockLocalStorage = {
  getItem: vi.fn((key: string) => localStorageMap.get(key) ?? null),
  setItem: vi.fn((key: string, value: string) => localStorageMap.set(key, value)),
  removeItem: vi.fn((key: string) => localStorageMap.delete(key)),
  clear: vi.fn(() => localStorageMap.clear()),
  get length() { return localStorageMap.size; },
  key: vi.fn(() => null),
};
Object.defineProperty(globalThis, 'localStorage', { value: mockLocalStorage, writable: true });

// ========== Helpers ==========

function resetStore(): void {
  useConverterStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    aspectRatio: null,
    enableCrop: true,
    cropModalOpen: false,
    isCropping: false,
    error: null,
  });
}

// ========== Property 1 ==========

// Feature: image-crop-refactor, Property 1: enableCrop 控制裁剪弹窗行为
describe('Property 1: enableCrop 控制裁剪弹窗行为', () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
    localStorageMap.clear();
  });

  it('cropModalOpen === (enableCrop && file !== null) after setImageFile', () => {
    // **Validates: Requirements 1.1, 4.2, 4.3, 6.2**
    const arbEnableCrop = fc.boolean();
    const arbFile = fc.oneof(
      fc.constant(new File(['x'], 'test.png', { type: 'image/png' })),
      fc.constant(null),
    );

    fc.assert(
      fc.property(arbEnableCrop, arbFile, (enableCrop, file) => {
        // Reset to clean state before each check
        resetStore();

        // Set enableCrop first
        useConverterStore.getState().setEnableCrop(enableCrop);

        // Call setImageFile
        useConverterStore.getState().setImageFile(file);

        const state = useConverterStore.getState();
        const expected = enableCrop && file !== null;
        expect(state.cropModalOpen).toBe(expected);
      }),
      { numRuns: 100 },
    );
  });
});

// ========== Property 2 ==========

// Feature: image-crop-refactor, Property 2: enableCrop 持久化 round-trip
describe('Property 2: enableCrop 持久化 round-trip', () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
    localStorageMap.clear();
  });

  it('localStorage round-trip preserves enableCrop value', () => {
    // **Validates: Requirements 4.4**
    fc.assert(
      fc.property(fc.boolean(), (v) => {
        resetStore();
        localStorageMap.clear();

        // Set enableCrop to v (this persists to localStorage)
        useConverterStore.getState().setEnableCrop(v);

        // Read back from localStorage and parse
        const stored = localStorage.getItem('lumina_enableCrop');
        expect(stored).not.toBeNull();
        const parsed = stored === 'true';
        expect(parsed).toBe(v);
      }),
      { numRuns: 100 },
    );
  });
});
