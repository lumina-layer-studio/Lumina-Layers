import { describe, it, expect, beforeEach } from 'vitest';
import { useConverterStore } from '../../stores/converterStore';

/**
 * Converter_Store 单元测试
 * Validates: Requirements 9.4, 2.4, 4.3, 4.5
 */

function resetStore(): void {
  useConverterStore.setState({
    selectedColor: null,
    colorRemapMap: {},
    remapHistory: [],
    autoHeightMode: 'darker-higher',
    palette: [],
    previewGlbUrl: null,
  });
}

describe('Converter_Store 默认值', () => {
  beforeEach(() => {
    resetStore();
  });

  it('autoHeightMode 默认为 "darker-higher"', () => {
    const state = useConverterStore.getState();
    expect(state.autoHeightMode).toBe('darker-higher');
  });

  it('selectedColor 默认为 null', () => {
    const state = useConverterStore.getState();
    expect(state.selectedColor).toBeNull();
  });

  it('colorRemapMap 默认为空对象', () => {
    const state = useConverterStore.getState();
    expect(state.colorRemapMap).toEqual({});
  });

  it('remapHistory 默认为空数组', () => {
    const state = useConverterStore.getState();
    expect(state.remapHistory).toEqual([]);
  });
});

describe('setSelectedColor', () => {
  beforeEach(() => {
    resetStore();
  });

  it('设置 selectedColor 为指定 hex 值', () => {
    useConverterStore.getState().setSelectedColor('ff0000');
    expect(useConverterStore.getState().selectedColor).toBe('ff0000');
  });

  it('设置 selectedColor 为 null 清除选中', () => {
    useConverterStore.getState().setSelectedColor('ff0000');
    useConverterStore.getState().setSelectedColor(null);
    expect(useConverterStore.getState().selectedColor).toBeNull();
  });
});

describe('submitGenerate 浮雕验证', () => {
  beforeEach(() => {
    resetStore();
  });

  it('enable_relief 为 true 且 color_height_map 为空时阻止生成并提示', async () => {
    useConverterStore.setState({
      sessionId: 'test-session',
      enable_relief: true,
      color_height_map: {},
      autoHeightMode: 'darker-higher',
    });

    const result = await useConverterStore.getState().submitGenerate();

    expect(result).toBeNull();
    expect(useConverterStore.getState().error).toBe('请先设置颜色高度映射后再生成');
    expect(useConverterStore.getState().isLoading).toBe(false);
  });

  it('enable_relief 为 true 且 autoHeightMode 为 use-heightmap 且 color_height_map 为空时提示上传高度图', async () => {
    useConverterStore.setState({
      sessionId: 'test-session',
      enable_relief: true,
      color_height_map: {},
      autoHeightMode: 'use-heightmap',
    });

    const result = await useConverterStore.getState().submitGenerate();

    expect(result).toBeNull();
    expect(useConverterStore.getState().error).toBe('请先上传高度图并获取高度映射后再生成');
    expect(useConverterStore.getState().isLoading).toBe(false);
  });

  it('enable_relief 为 true 且 color_height_map 非空时不阻止', async () => {
    useConverterStore.setState({
      sessionId: 'test-session',
      enable_relief: true,
      color_height_map: { 'ff0000': 2.5 },
      autoHeightMode: 'darker-higher',
    });

    // submitGenerate will proceed past validation and hit the API call
    // which will fail since we don't mock it, but the point is it doesn't
    // return null from the validation check
    await useConverterStore.getState().submitGenerate();

    // It should have attempted the API call (error will be from network, not validation)
    const error = useConverterStore.getState().error;
    expect(error).not.toBe('请先设置颜色高度映射后再生成');
    expect(error).not.toBe('请先上传高度图并获取高度映射后再生成');
  });

  it('enable_relief 为 false 时不检查 color_height_map', async () => {
    useConverterStore.setState({
      sessionId: 'test-session',
      enable_relief: false,
      color_height_map: {},
    });

    await useConverterStore.getState().submitGenerate();

    const error = useConverterStore.getState().error;
    expect(error).not.toBe('请先设置颜色高度映射后再生成');
    expect(error).not.toBe('请先上传高度图并获取高度映射后再生成');
  });
});

describe('clearAllRemaps', () => {
  beforeEach(() => {
    resetStore();
  });

  it('执行若干替换后 clearAllRemaps 清空 map 和 history', () => {
    const store = useConverterStore.getState;

    store().applyColorRemap('ff0000', '00ff00');
    store().applyColorRemap('0000ff', 'ffff00');

    expect(Object.keys(store().colorRemapMap).length).toBeGreaterThan(0);
    expect(store().remapHistory.length).toBeGreaterThan(0);

    store().clearAllRemaps();

    expect(store().colorRemapMap).toEqual({});
    expect(store().remapHistory).toEqual([]);
  });
});


describe('setModelBounds', () => {
  beforeEach(() => {
    resetStore();
    useConverterStore.setState({ modelBounds: null });
  });

  it('stores modelBounds correctly', () => {
    const bounds = { minX: -10, maxX: 10, minY: -5, maxY: 5, maxZ: 3 };
    useConverterStore.getState().setModelBounds(bounds);
    expect(useConverterStore.getState().modelBounds).toEqual(bounds);
  });

  it('sets modelBounds to null', () => {
    useConverterStore.getState().setModelBounds({ minX: 0, maxX: 1, minY: 0, maxY: 1, maxZ: 1 });
    useConverterStore.getState().setModelBounds(null);
    expect(useConverterStore.getState().modelBounds).toBeNull();
  });
});

describe('setEnableRelief auto-initialization', () => {
  beforeEach(() => {
    resetStore();
    useConverterStore.setState({
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
      palette: [],
    });
  });

  it('auto-initializes color_height_map when palette non-empty and map empty', () => {
    useConverterStore.setState({
      palette: [
        { quantized_hex: 'ff0000', matched_hex: 'ee0000', pixel_count: 100, percentage: 50 },
        { quantized_hex: '00ff00', matched_hex: '00ee00', pixel_count: 100, percentage: 50 },
      ],
      color_height_map: {},
      heightmap_max_height: 4.0,
    });

    useConverterStore.getState().setEnableRelief(true);

    const state = useConverterStore.getState();
    expect(state.enable_relief).toBe(true);
    expect(state.color_height_map).toEqual({
      'ee0000': 2.0,  // 4.0 * 0.5
      '00ee00': 2.0,
    });
  });

  it('does NOT overwrite existing color_height_map', () => {
    useConverterStore.setState({
      palette: [
        { quantized_hex: 'ff0000', matched_hex: 'ee0000', pixel_count: 100, percentage: 50 },
        { quantized_hex: '00ff00', matched_hex: '00ee00', pixel_count: 100, percentage: 50 },
      ],
      color_height_map: { 'ee0000': 3.5 },
      heightmap_max_height: 4.0,
    });

    useConverterStore.getState().setEnableRelief(true);

    const state = useConverterStore.getState();
    expect(state.enable_relief).toBe(true);
    // Should keep the existing map untouched
    expect(state.color_height_map).toEqual({ 'ee0000': 3.5 });
  });

  it('does NOT auto-initialize when palette is empty', () => {
    useConverterStore.setState({
      palette: [],
      color_height_map: {},
      heightmap_max_height: 4.0,
    });

    useConverterStore.getState().setEnableRelief(true);

    expect(useConverterStore.getState().color_height_map).toEqual({});
  });

  it('disables cloisonne when enabling relief', () => {
    useConverterStore.setState({ enable_cloisonne: true });

    useConverterStore.getState().setEnableRelief(true);

    expect(useConverterStore.getState().enable_cloisonne).toBe(false);
  });
});
