import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import {
  rgbEuclideanDistance,
  sortByColorDistance,
} from '../utils/colorUtils';
import type { LutColorEntry } from '../api/types';
import { tRuntime } from '../i18n/runtime';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useConverterDataInit } from '../hooks/useConverterDataInit';
const { mockApiFetchLutCatalog, mockApiFetchLutColors } = vi.hoisted(() => ({
  mockApiFetchLutCatalog: vi.fn(),
  mockApiFetchLutColors: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

vi.mock('../api/converter', async () => {
  const original = await vi.importActual<typeof import('../api/converter')>('../api/converter');
  return {
    ...original,
    fetchLutColors: (...args: unknown[]) => mockApiFetchLutColors(...args),
    replaceColor: vi.fn().mockResolvedValue({ preview_url: '/api/files/mock-preview' }),
  };
});

vi.mock('../api/lut', async () => {
  const original = await vi.importActual<typeof import('../api/lut')>('../api/lut');
  return {
    ...original,
    fetchLutCatalog: (...args: unknown[]) => mockApiFetchLutCatalog(...args),
  };
});

// ========== Generators ==========

/** Arbitrary RGB tuple with integer values 0-255. (0-255 整数 RGB 元组生成器) */
const arbRgb = fc.tuple(
  fc.integer({ min: 0, max: 255 }),
  fc.integer({ min: 0, max: 255 }),
  fc.integer({ min: 0, max: 255 }),
) as fc.Arbitrary<[number, number, number]>;

/** Arbitrary LutColorEntry from a random RGB. (从随机 RGB 生成 LutColorEntry) */
const arbLutColorEntry: fc.Arbitrary<LutColorEntry> = arbRgb.map((rgb) => {
  const hex =
    '#' +
    rgb
      .map((c) => c.toString(16).padStart(2, '0'))
      .join('');
  return { hex, rgb };
});

/** Non-empty array of LutColorEntry. (非空 LutColorEntry 数组) */
const arbLutColorEntries = fc.array(arbLutColorEntry, { minLength: 1, maxLength: 50 });

// ========== Property 5: 颜色距离排序单调性 ==========

// **Validates: Requirements 3.1**
describe('Feature: palette-optimization, Property 5: distance sort monotonicity', () => {
  it('sortByColorDistance returns results with monotonically non-decreasing distances', () => {
    fc.assert(
      fc.property(arbRgb, arbLutColorEntries, (baseRgb, colors) => {
        const topK = colors.length; // use full list to verify complete ordering
        const sorted = sortByColorDistance(baseRgb, colors, topK);

        for (let i = 0; i < sorted.length - 1; i++) {
          const distCurrent = rgbEuclideanDistance(baseRgb, sorted[i].rgb);
          const distNext = rgbEuclideanDistance(baseRgb, sorted[i + 1].rgb);
          expect(distCurrent).toBeLessThanOrEqual(distNext);
        }
      }),
      { numRuns: 100 },
    );
  });

  it('sortByColorDistance with topK < colors.length still maintains monotonicity', () => {
    fc.assert(
      fc.property(
        arbRgb,
        arbLutColorEntries.filter((c) => c.length >= 2),
        (baseRgb, colors) => {
          const topK = Math.max(1, Math.floor(colors.length / 2));
          const sorted = sortByColorDistance(baseRgb, colors, topK);

          expect(sorted.length).toBeLessThanOrEqual(topK);

          for (let i = 0; i < sorted.length - 1; i++) {
            const distCurrent = rgbEuclideanDistance(baseRgb, sorted[i].rgb);
            const distNext = rgbEuclideanDistance(baseRgb, sorted[i + 1].rgb);
            expect(distCurrent).toBeLessThanOrEqual(distNext);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ========== Property 1: LUT 颜色缓存命中跳过请求 ==========

// **Validates: Requirements 1.3, 5.2, 5.3**
describe('Feature: palette-optimization, Property 1: LUT 颜色缓存命中跳过请求', () => {

  // Lazy-import the store AFTER mock is set up
  let useConverterStore: typeof import('../stores/converter').useConverterStore;

  beforeAll(async () => {
    const mod = await import('../stores/converter');
    useConverterStore = mod.useConverterStore;
  });

  beforeEach(() => {
    mockApiFetchLutCatalog.mockClear();
    mockApiFetchLutColors.mockClear();
  });

  /** Alphanumeric LUT name generator (1-20 chars). (字母数字 LUT 名称生成器) */
  const arbLutName = fc.string({ minLength: 1, maxLength: 20 })
    .filter((s) => /^[a-zA-Z0-9]+$/.test(s));

  /** Random non-empty LutColorEntry array for cached data. (随机非空 LutColorEntry 数组) */
  const arbCachedColors = fc.array(
    arbLutColorEntry,
    { minLength: 1, maxLength: 30 },
  );

  it('fetchLutColors skips API call when cache matches lutName and lutColors is non-empty', async () => {
    await fc.assert(
      fc.asyncProperty(arbLutName, arbCachedColors, async (lutName, cachedColors) => {
        // Set up store state to simulate a cache hit
        useConverterStore.setState({
          lutColorsLutName: lutName,
          lutColors: cachedColors,
          lutColorsLoading: false,
        });

        mockApiFetchLutColors.mockClear();

        // Call fetchLutColors with the same lutName
        await useConverterStore.getState().fetchLutColors(lutName);

        // API should NOT have been called (cache hit)
        expect(mockApiFetchLutColors).not.toHaveBeenCalled();

        // lutColors data should remain unchanged
        const state = useConverterStore.getState();
        expect(state.lutColors).toEqual(cachedColors);
        expect(state.lutColorsLutName).toBe(lutName);
      }),
      { numRuns: 100 },
    );
  });

  it('fetchLutColors hides missing LUT backend details', async () => {
    useConverterStore.setState({
      lutColors: [],
      lutColorCards: [],
      lutColorsLoading: false,
      lutColorsLutName: '',
      error: null,
    });
    mockApiFetchLutColors.mockRejectedValueOnce({
      message: 'Request failed with status code 404',
      response: {
        status: 404,
        data: { detail: 'LUT not found: stale-lut' },
      },
    });

    await useConverterStore.getState().fetchLutColors('stale-lut');

    const state = useConverterStore.getState();
    expect(state.error).toBe(tRuntime('lut_error_missing_refresh'));
    expect(state.error).not.toMatch(/LUT not found/i);
    expect(state.lutColorsLoading).toBe(false);
  });

  it('waits for a portable draft session instead of looking up its private LUT globally', async () => {
    const { converterSourceKey } = await import('../stores/converter/project');
    const previous = useConverterStore.getState();
    useConverterStore.setState({ source_version: 'legacy', lut_name: 'Portable', lut_names: ['Portable'], projectLutFile: new File(['lut'], 'source.zip'), sessionId: null, error: null });
    useConverterStore.setState({ projectSourceKey: converterSourceKey(useConverterStore.getState()) });
    try {
      mockApiFetchLutColors.mockClear();
      await useConverterStore.getState().fetchLutColors('Portable');
      expect(mockApiFetchLutColors).not.toHaveBeenCalled();
      expect(useConverterStore.getState().error).toBeNull();
      useConverterStore.setState({ sessionId: 'private-session' });
      mockApiFetchLutColors.mockResolvedValueOnce({ colors: [] });
      await useConverterStore.getState().fetchLutColors('Portable');
      expect(mockApiFetchLutColors).toHaveBeenCalledWith('Portable', undefined, 'private-session');
    } finally { useConverterStore.setState(previous); }
  });

  it('fetchLutColors ignores an older response that arrives last', async () => {
    const firstResponse = deferred<{
      colors: LutColorEntry[];
      cards: [];
    }>();
    const secondResponse = deferred<{
      colors: LutColorEntry[];
      cards: [];
    }>();
    mockApiFetchLutColors.mockImplementation((lutName: string) =>
      lutName === 'first-lut'
        ? firstResponse.promise
        : secondResponse.promise,
    );
    useConverterStore.setState({
      lutColors: [],
      lutColorCards: [],
      lutColorsLoading: false,
      lutColorsLutName: '',
      error: null,
    });

    const first = useConverterStore
      .getState()
      .fetchLutColors('first-lut');
    const second = useConverterStore
      .getState()
      .fetchLutColors('second-lut');
    const secondColors: LutColorEntry[] = [
      { rgb: [2, 2, 2], hex: '#020202' },
    ];
    secondResponse.resolve({ colors: secondColors, cards: [] });
    await second;
    firstResponse.resolve({
      colors: [{ rgb: [1, 1, 1], hex: '#010101' }],
      cards: [],
    });
    await first;

    expect(useConverterStore.getState()).toMatchObject({
      lutColorsLutName: 'second-lut',
      lutColors: secondColors,
      lutColorsLoading: false,
    });
  });

  it('loads a restored private LUT and refreshes same-name colors across project sessions', async () => {
    const { converterSourceKey } = await import('../stores/converter/project');
    const { DEFAULT_STATE } = await import('../stores/converter');
    const previous = useConverterStore.getState();
    const colors = (hex: string): LutColorEntry[] => [{ hex, rgb: [1, 2, 3] }];
    mockApiFetchLutColors.mockReset().mockResolvedValue({ colors: colors('#112233') });
    useConverterStore.setState({ ...DEFAULT_STATE, lut_name: '', fetchLutCatalog: vi.fn().mockResolvedValue(undefined), fetchBedSizes: vi.fn().mockResolvedValue(undefined) });
    const hook = renderHook(() => useConverterDataInit());
    try {
      await act(async () => { await Promise.resolve(); });
      act(() => {
        const source = { source_version: 'legacy' as const, lut_name: 'Shared name', lut_names: ['Shared name'], projectLutFile: new File(['private'], 'source.zip'), sessionId: 'project-a' };
        useConverterStore.setState({ ...source, projectSourceKey: converterSourceKey({ ...useConverterStore.getState(), ...source }) });
      });
      await waitFor(() => expect(useConverterStore.getState().lutColors).toEqual(colors('#112233')));
      expect(mockApiFetchLutColors).toHaveBeenLastCalledWith('Shared name', expect.any(AbortSignal), 'project-a');
      mockApiFetchLutColors.mockResolvedValue({ colors: colors('#445566') });
      act(() => useConverterStore.setState({ sessionId: 'project-b' }));
      await waitFor(() => expect(useConverterStore.getState().lutColors).toEqual(colors('#445566')));
      expect(mockApiFetchLutColors).toHaveBeenLastCalledWith('Shared name', expect.any(AbortSignal), 'project-b');
      mockApiFetchLutColors.mockResolvedValue({ colors: colors('#778899') });
      act(() => useConverterStore.setState({ projectLutFile: null }));
      await waitFor(() => expect(useConverterStore.getState().lutColors).toEqual(colors('#778899')));
      expect(mockApiFetchLutColors).toHaveBeenLastCalledWith('Shared name', expect.any(AbortSignal), null);
    } finally { hook.unmount(); useConverterStore.setState(previous); }
  });

  it('fetchLutCatalog ignores an older response that arrives last', async () => {
    const firstResponse = deferred<{
      legacy_groups: Array<{
        group_name: string;
        items: Array<{
          name: string;
          path: string;
          color_mode: string;
        }>;
      }>;
      native_brand_groups: [];
    }>();
    const secondResponse = deferred<{
      legacy_groups: Array<{
        group_name: string;
        items: Array<{
          name: string;
          path: string;
          color_mode: string;
        }>;
      }>;
      native_brand_groups: [];
    }>();
    mockApiFetchLutCatalog
      .mockImplementationOnce(() => firstResponse.promise)
      .mockImplementationOnce(() => secondResponse.promise);
    useConverterStore.setState({
      lutList: [],
      lutListFull: [],
      nativeBrandGroups: [],
      nativeBrandGroupsLoading: false,
      error: null,
    });

    const first = useConverterStore.getState().fetchLutCatalog();
    const second = useConverterStore.getState().fetchLutCatalog();
    secondResponse.resolve({
      legacy_groups: [
        {
          group_name: 'new',
          items: [
            {
              name: 'new-lut',
              path: '/new.npy',
              color_mode: '4-Color (RYBW)',
            },
          ],
        },
      ],
      native_brand_groups: [],
    });
    await second;
    firstResponse.resolve({
      legacy_groups: [
        {
          group_name: 'old',
          items: [
            {
              name: 'old-lut',
              path: '/old.npy',
              color_mode: '4-Color (RYBW)',
            },
          ],
        },
      ],
      native_brand_groups: [],
    });
    await first;

    expect(useConverterStore.getState()).toMatchObject({
      lutList: ['new-lut'],
      lutListFull: [
        expect.objectContaining({
          name: 'new-lut',
        }),
      ],
      nativeBrandGroupsLoading: false,
    });
  });
});

// ========== Generators for Property 2/3/4 ==========

/** Arbitrary 6-char hex string (no # prefix). (无 # 前缀的 6 位 hex 字符串生成器) */
const hexChar = fc.constantFrom(...'0123456789abcdef'.split(''));
const arbHex6 = fc
  .tuple(hexChar, hexChar, hexChar, hexChar, hexChar, hexChar)
  .map((chars) => chars.join(''));

/** Arbitrary pair of distinct hex colors. (不同 hex 颜色对生成器) */
const arbHexPair = fc
  .tuple(arbHex6, arbHex6)
  .filter(([a, b]) => a !== b);

// ========== Property 2: applyColorRemap 正确记录映射 ==========

// **Validates: Requirements 2.2**
describe('Feature: palette-optimization, Property 2: applyColorRemap 正确记录映射', () => {
  let useConverterStore: typeof import('../stores/converter').useConverterStore;

  beforeAll(async () => {
    const mod = await import('../stores/converter');
    useConverterStore = mod.useConverterStore;
  });

  beforeEach(() => {
    // Reset remap-related state before each test
    useConverterStore.setState({
      colorRemapMap: {},
      remapHistory: [],
      remapRedoHistory: [],
      replacement_regions: [],
      recipe_overrides: [],
      regionReplacementCount: 0,
      sessionId: null,
    });
  });

  it('applyColorRemap records mapping in colorRemapMap and pushes snapshot to remapHistory', () => {
    fc.assert(
      fc.property(arbHexPair, ([origHex, newHex]) => {
        // Reset state
        useConverterStore.setState({
          colorRemapMap: {},
          remapHistory: [],
          remapRedoHistory: [],
          replacement_regions: [],
          recipe_overrides: [],
          regionReplacementCount: 0,
          sessionId: null,
        });

        const historyLenBefore = useConverterStore.getState().remapHistory.length;

        useConverterStore.getState().applyColorRemap(origHex, newHex);

        const state = useConverterStore.getState();
        // colorRemapMap should contain the mapping
        expect(state.colorRemapMap[origHex]).toBe(newHex);
        // remapHistory length should increase by 1
        expect(state.remapHistory.length).toBe(historyLenBefore + 1);
      }),
      { numRuns: 100 },
    );
  });

  it('applyColorRemap accumulates multiple mappings correctly', () => {
    fc.assert(
      fc.property(
        fc.array(arbHexPair, { minLength: 1, maxLength: 10 }),
        (pairs) => {
          // Reset state
          useConverterStore.setState({
            colorRemapMap: {},
            remapHistory: [],
            remapRedoHistory: [],
            replacement_regions: [],
            recipe_overrides: [],
            regionReplacementCount: 0,
            sessionId: null,
          });

          for (let i = 0; i < pairs.length; i++) {
            const [origHex, newHex] = pairs[i];
            useConverterStore.getState().applyColorRemap(origHex, newHex);

            const state = useConverterStore.getState();
            // Each call should increase history by 1
            expect(state.remapHistory.length).toBe(i + 1);
            // Latest mapping should be recorded
            expect(state.colorRemapMap[origHex]).toBe(newHex);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ========== Property 3: 撤销恢复上一状态（Round-Trip） ==========

// **Validates: Requirements 2.5**
describe('Feature: palette-optimization, Property 3: undo round trip', () => {
  let useConverterStore: typeof import('../stores/converter').useConverterStore;

  beforeAll(async () => {
    const mod = await import('../stores/converter');
    useConverterStore = mod.useConverterStore;
  });

  beforeEach(() => {
    useConverterStore.setState({
      colorRemapMap: {},
      remapHistory: [],
      remapRedoHistory: [],
      replacement_regions: [],
      recipe_overrides: [],
      regionReplacementCount: 0,
      sessionId: null,
      originalPreviewUrl: '/api/files/original',
      previewImageUrl: '/api/files/original',
    });
  });

  it('undoColorRemap restores previous state and reduces history length by 1', () => {
    fc.assert(
      fc.property(
        fc.array(arbHexPair, { minLength: 1, maxLength: 8 }),
        (pairs) => {
          // Reset state
          useConverterStore.setState({
            colorRemapMap: {},
            remapHistory: [],
            remapRedoHistory: [],
            replacement_regions: [],
            recipe_overrides: [],
            regionReplacementCount: 0,
            sessionId: null,
            originalPreviewUrl: '/api/files/original',
            previewImageUrl: '/api/files/original',
          });

          // Apply all remaps
          for (const [origHex, newHex] of pairs) {
            useConverterStore.getState().applyColorRemap(origHex, newHex);
          }

          // Undo one by one and verify
          for (let i = pairs.length; i > 0; i--) {
            const stateBefore = useConverterStore.getState();
            const expectedMap =
              stateBefore.remapHistory.length > 0
                ? stateBefore.remapHistory[stateBefore.remapHistory.length - 1]
                : {};
            const expectedHistoryLen = stateBefore.remapHistory.length - 1;

            useConverterStore.getState().undoColorRemap();

            const stateAfter = useConverterStore.getState();
            expect(stateAfter.colorRemapMap).toEqual(expectedMap);
            expect(stateAfter.remapHistory.length).toBe(expectedHistoryLen);
          }

          // After all undos, map should be empty
          const finalState = useConverterStore.getState();
          expect(finalState.colorRemapMap).toEqual({});
          expect(finalState.remapHistory.length).toBe(0);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('undoColorRemap is a no-op when history is empty', () => {
    fc.assert(
      fc.property(fc.constant(null), () => {
        useConverterStore.setState({
          colorRemapMap: {},
          remapHistory: [],
          remapRedoHistory: [],
          replacement_regions: [],
          recipe_overrides: [],
          regionReplacementCount: 0,
          sessionId: null,
        });

        useConverterStore.getState().undoColorRemap();

        const state = useConverterStore.getState();
        expect(state.colorRemapMap).toEqual({});
        expect(state.remapHistory.length).toBe(0);
      }),
      { numRuns: 100 },
    );
  });
});

// ========== Property 4: 清空替换归零 ==========

// **Validates: Requirements 2.6**
describe('Feature: palette-optimization, Property 4: 清空替换归零', () => {
  let useConverterStore: typeof import('../stores/converter').useConverterStore;

  beforeAll(async () => {
    const mod = await import('../stores/converter');
    useConverterStore = mod.useConverterStore;
  });

  beforeEach(() => {
    useConverterStore.setState({
      colorRemapMap: {},
      remapHistory: [],
      remapRedoHistory: [],
      replacement_regions: [],
      recipe_overrides: [],
      regionReplacementCount: 0,
      sessionId: null,
      originalPreviewUrl: '/api/files/original',
      previewImageUrl: '/api/files/original',
    });
  });

  it('clearAllRemaps empties the active map but keeps it undoable', () => {
    fc.assert(
      fc.property(
        fc.array(arbHexPair, { minLength: 0, maxLength: 10 }),
        (pairs) => {
          // Reset and apply random remaps
          useConverterStore.setState({
            colorRemapMap: {},
            remapHistory: [],
            remapRedoHistory: [],
            replacement_regions: [],
            recipe_overrides: [],
            regionReplacementCount: 0,
            sessionId: null,
            originalPreviewUrl: '/api/files/original',
            previewImageUrl: '/api/files/original',
          });

          for (const [origHex, newHex] of pairs) {
            useConverterStore.getState().applyColorRemap(origHex, newHex);
          }

          const beforeClear = useConverterStore.getState();
          const hadRemaps = Object.keys(beforeClear.colorRemapMap).length > 0;
          const historyLenBefore = beforeClear.remapHistory.length;

          // Clear all
          useConverterStore.getState().clearAllRemaps();

          const state = useConverterStore.getState();
          expect(state.colorRemapMap).toEqual({});
          // "Clear" is undoable in the local flow: a non-empty pre-clear map is
          // pushed as one extra history entry instead of the stack being wiped.
          // “清空”在本地流程中可撤销：非空的清空前映射会作为一条额外历史入栈，
          // 而不是把栈清空。
          expect(state.remapHistory).toHaveLength(
            historyLenBefore + (hadRemaps ? 1 : 0),
          );
        },
      ),
      { numRuns: 100 },
    );
  });

  it('clearAllRemaps is idempotent — calling twice yields same state', () => {
    fc.assert(
      fc.property(
        fc.array(arbHexPair, { minLength: 1, maxLength: 5 }),
        (pairs) => {
          useConverterStore.setState({
            colorRemapMap: {},
            remapHistory: [],
            remapRedoHistory: [],
            replacement_regions: [],
            recipe_overrides: [],
            regionReplacementCount: 0,
            sessionId: null,
            originalPreviewUrl: '/api/files/original',
            previewImageUrl: '/api/files/original',
          });

          for (const [origHex, newHex] of pairs) {
            useConverterStore.getState().applyColorRemap(origHex, newHex);
          }

          useConverterStore.getState().clearAllRemaps();
          const afterFirst = useConverterStore.getState();
          // Second clear: the map is already empty, so nothing new is pushed —
          // the call is a true no-op on history.
          // 第二次清空：映射已空，不再入栈，对历史是真正的无操作。
          useConverterStore.getState().clearAllRemaps();

          const state = useConverterStore.getState();
          expect(state.colorRemapMap).toEqual({});
          expect(state.remapHistory).toEqual(afterFirst.remapHistory);
        },
      ),
      { numRuns: 100 },
    );
  });
});
