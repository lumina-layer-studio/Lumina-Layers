import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { DEFAULT_STATE, converterDocumentHistory, useConverterStore } from '../stores/converter';
import type { PaletteEntry, LutColorEntry, SelectionDocumentResponse } from '../api/types';
import { _clearClientLogBufferForTests } from '../utils/clientLog';
import { getEditorSelection, mutateEditorSelection, replacementHistory } from '../api/converter';

const customRecipeDialogProps = vi.hoisted(() => ({
  latest: null as null | {
    open: boolean;
    regionIds: string[];
    currentRegionColorHex?: string | null;
  },
}));

// Mock API module to prevent real network calls
vi.mock('../api/converter', async () => {
  const original = await vi.importActual<typeof import('../api/converter')>('../api/converter');
  return {
    ...original,
    fetchLutColors: vi.fn().mockResolvedValue({ colors: [] }),
    replaceColor: vi.fn().mockResolvedValue({ preview_url: '/api/files/mock' }),
    mutateEditorSelection: vi.fn(),
    getEditorSelection: vi.fn(),
    replacementHistory: vi.fn(),
  };
});

vi.mock('../components/ui/CustomRecipeDialog', () => ({
  default: (props: {
    open: boolean;
    regionIds: string[];
    currentRegionColorHex?: string | null;
  }) => {
    customRecipeDialogProps.latest = props;
    return props.open ? (
      <div data-testid="custom-recipe-dialog">{props.regionIds.join(',')}</div>
    ) : null;
  },
}));

// ========== Test Data ==========

const PALETTE: PaletteEntry[] = [
  { quantized_hex: 'ff0000', matched_hex: 'ee0000', pixel_count: 500, percentage: 50.0 },
  { quantized_hex: '00ff00', matched_hex: '00ee00', pixel_count: 300, percentage: 30.0 },
  { quantized_hex: '0000ff', matched_hex: '0000ee', pixel_count: 200, percentage: 20.0 },
];

const SIX_COLOR_PALETTE: PaletteEntry[] = [
  { quantized_hex: '111111', matched_hex: '111111', pixel_count: 100, percentage: 16.7 },
  { quantized_hex: '222222', matched_hex: '222222', pixel_count: 100, percentage: 16.7 },
  { quantized_hex: '333333', matched_hex: '333333', pixel_count: 100, percentage: 16.7 },
  { quantized_hex: '444444', matched_hex: '444444', pixel_count: 100, percentage: 16.7 },
  { quantized_hex: '555555', matched_hex: '555555', pixel_count: 100, percentage: 16.7 },
  { quantized_hex: '666666', matched_hex: '666666', pixel_count: 100, percentage: 16.5 },
];

const LUT_COLORS: LutColorEntry[] = [
  { hex: '#ee0000', rgb: [238, 0, 0] },
  { hex: '#00ee00', rgb: [0, 238, 0] },
  { hex: '#0000ee', rgb: [0, 0, 238] },
  { hex: '#ff8800', rgb: [255, 136, 0] },
  { hex: '#880088', rgb: [136, 0, 136] },
  { hex: '#008888', rgb: [0, 136, 136] },
  { hex: '#ffffff', rgb: [255, 255, 255] },
  { hex: '#000000', rgb: [0, 0, 0] },
  { hex: '#cccccc', rgb: [204, 204, 204] },
  { hex: '#ff00ff', rgb: [255, 0, 255] },
  { hex: '#ffff00', rgb: [255, 255, 0] },
  { hex: '#00ffff', rgb: [0, 255, 255] },
  { hex: '#aa0000', rgb: [170, 0, 0] },
];

function resetStore() {
  _clearClientLogBufferForTests();
  useConverterStore.setState({
    ...DEFAULT_STATE,
    source_version: 'legacy',
    palette: [],
    selectedColor: null,
    colorRemapMap: {},
    remapHistory: [],
    remapRedoHistory: [],
    replacement_regions: [],
    recipe_overrides: [],
    regionReplacementCount: 0,
    lutColors: [],
    lutColorsLoading: false,
    lutColorsLutName: '',
    enable_relief: false,
    color_height_map: {},
    heightmap_max_height: 5.0,
    replacePreviewLoading: false,
    historyCanUndo: false,
    historyCanRedo: false,
    historyBusy: false,
    originalPreviewUrl: null,
    previewImageUrl: null,
    sessionId: null,
  });
  converterDocumentHistory.reset();
  customRecipeDialogProps.latest = null;
}

const historySelection = (revision: number, canUndo: boolean, canRedo: boolean): SelectionDocumentResponse => ({
  selection_revision: revision, content_revision: 1, editor_content_revision: 1,
  selected_pixel_count: 0, selected_component_count: 0, selected_color_hexes: [],
  region_ids: [], components: [], contours: [], can_undo: canUndo, can_redo: canRedo,
});

async function hydrateFirstHistoryEntry() {
  useConverterStore.setState({ palette: PALETTE, sessionId: 'selection-session' });
  vi.mocked(getEditorSelection).mockResolvedValueOnce(historySelection(1, true, false));
  await useConverterStore.getState().hydrateSelectionDocument();
}

// ========== Lazy component imports ==========

async function importLutColorGrid() {
  const mod = await import('../components/sections/LutColorGrid');
  return mod.default;
}

async function importPalettePanel() {
  const mod = await import('../components/sections/PalettePanel');
  return mod.default;
}

// ========== 推荐排序测试 (Requirements 3.2, 3.3) ==========

describe('LutColorGrid 推荐排序', () => {
  beforeEach(resetStore);

  it('selectedColor 存在时显示推荐替换色区域', async () => {
    const LutColorGrid = await importLutColorGrid();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      lutColors: LUT_COLORS,
      colorRemapMap: {},
    });

    render(<LutColorGrid />);

    expect(screen.getByText(/推荐替换色/)).toBeInTheDocument();
  });

  it('selectedColor 为 null 时不显示推荐替换色区域', async () => {
    const LutColorGrid = await importLutColorGrid();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: null,
      lutColors: LUT_COLORS,
      colorRemapMap: {},
    });

    render(<LutColorGrid />);

    expect(screen.queryByText(/推荐替换色/)).not.toBeInTheDocument();
  });

  it('推荐区域最多显示 12 个颜色', async () => {
    const LutColorGrid = await importLutColorGrid();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      lutColors: LUT_COLORS,
      colorRemapMap: {},
    });

    render(<LutColorGrid />);

    const recText = screen.getByText(/推荐替换色/);
    expect(recText).toBeInTheDocument();
    // LUT_COLORS has 13 entries, recommendations capped at 12
    expect(recText.textContent).toContain('12');
  });

  it('取消选中颜色后推荐区域消失 (Req 3.3)', async () => {
    const LutColorGrid = await importLutColorGrid();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      lutColors: LUT_COLORS,
      colorRemapMap: {},
    });

    const { unmount } = render(<LutColorGrid />);
    expect(screen.getByText(/推荐替换色/)).toBeInTheDocument();
    unmount();

    // 取消选中
    useConverterStore.setState({ selectedColor: null });

    render(<LutColorGrid />);
    expect(screen.queryByText(/推荐替换色/)).not.toBeInTheDocument();
  });

  it.each(['none', 'text-content', 'replace-node'] as const)(
    'clears a selected color after external status mutation: %s', async (mutation) => {
    const LutColorGrid = await importLutColorGrid();
    const PalettePanel = await importPalettePanel();
    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      selectedColors: new Set(['ee0000']),
      selectionMode: 'select-all',
      selectionDocument: null,
      selectedRegions: [],
      regionData: null,
      lutColors: LUT_COLORS,
      colorRemapMap: {},
    });
    render(<><PalettePanel /><LutColorGrid /></>);
    const status = screen.getByText(/共 13 色/);
    const walker = document.createTreeWalker(status, NodeFilter.SHOW_TEXT);
    const nodes: Node[] = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    const selectedLabel = nodes.find((node) => node.textContent?.includes('已选中'));
    expect(selectedLabel).toBeTruthy();
    if (mutation === 'replace-node') {
      const wrapper = document.createElement('font');
      wrapper.textContent = selectedLabel!.textContent;
      selectedLabel!.parentNode!.replaceChild(wrapper, selectedLabel!);
    } else if (mutation === 'text-content') {
      selectedLabel!.textContent += ' (external text)';
    }

    fireEvent.click(screen.getByRole('button', { name: '全不选' }));

    expect(useConverterStore.getState().selectedColor).toBeNull();
    expect(screen.queryByText(/已选中/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '全不选' })).toBeEnabled();
    expect(status).toHaveTextContent('共 13 色');
    fireEvent.click(screen.getByRole('button', { name: /颜色 00ee00/ }));
    expect(useConverterStore.getState().selectedColor).toBe('00ee00');
    expect(status).toHaveTextContent('#00ee00');
    fireEvent.click(screen.getByRole('button', { name: '全不选' }));
    expect(status).not.toHaveTextContent('已选中');
  });

  it('lutColors 为空时不显示推荐区域', async () => {
    const LutColorGrid = await importLutColorGrid();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      lutColors: [],
      colorRemapMap: {},
    });

    render(<LutColorGrid />);

    expect(screen.queryByText(/推荐替换色/)).not.toBeInTheDocument();
  });
});

// ========== 双色显示测试 (Requirements 4.1, 4.2, 4.3) ==========

describe('PalettePanel 双色显示', () => {
  beforeEach(resetStore);

  it('keeps exact per-color relief height editing and the millimeter unit', async () => {
    const PalettePanel = await importPalettePanel();
    useConverterStore.setState({
      palette: [PALETTE[0]],
      enable_relief: true,
      color_height_map: { ee0000: 1.2 },
      heightmap_max_height: 5,
    });
    render(<PalettePanel />);
    const input = screen.getByRole('textbox', { name: 'value' });
    expect(input).toHaveValue('1.20');
    expect(screen.getByText('mm')).toBeInTheDocument();
    fireEvent.change(input, { target: { value: '4.92' } });
    fireEvent.blur(input);
    expect(useConverterStore.getState().color_height_map.ee0000).toBe(4.92);
  });

  it('selectedColor 存在时显示量化色和匹配色色块 (Req 4.1)', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    // Inline swatches use title attributes for quantized/matched labels
    expect(screen.getByTitle(/量化色.*#ff0000/)).toBeInTheDocument();
    expect(screen.getByTitle(/匹配色.*#ee0000/)).toBeInTheDocument();
  });

  it('双色显示区域显示 HEX 编码 (Req 4.2)', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    // HEX codes are encoded in inline swatch title attributes
    expect(screen.getByTitle(/量化色.*#ff0000/)).toBeInTheDocument();
    expect(screen.getByTitle(/匹配色.*#ee0000/)).toBeInTheDocument();
  });

  it('颜色已被替换时额外显示替换色色块 (Req 4.3)', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      colorRemapMap: { 'ee0000': '00ee00' },
      remapHistory: [{}],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    // Replacement swatch uses title with 替换色 label
    expect(screen.getByTitle(/替换色.*#00ee00/)).toBeInTheDocument();
  });

  it('颜色未被替换时不显示替换色色块', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    expect(screen.queryByTitle(/替换色/)).not.toBeInTheDocument();
  });

  it('selectedColor 为 null 时不显示双色显示区域', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: null,
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    expect(screen.queryByTitle(/量化色/)).not.toBeInTheDocument();
    expect(screen.queryByTitle(/匹配色/)).not.toBeInTheDocument();
  });

  it('点击调色板颜色可切换选中状态（全选模式）', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: null,
      selectionMode: 'select-all',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    const firstItem = screen.getByRole('button', { name: /颜色 ee0000/ });
    fireEvent.click(firstItem);

    expect(useConverterStore.getState().selectedColor).toBe('ee0000');

    fireEvent.click(firstItem);

    expect(useConverterStore.getState().selectedColor).toBeNull();
    expect(useConverterStore.getState().selectedColors.size).toBe(0);
  });

  it('全选模式连续选择 6 个源色时保持全部高亮且已选条不换行挤压列表', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: SIX_COLOR_PALETTE,
      selectedColor: null,
      selectedColors: new Set<string>(),
      selectionMode: 'select-all',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
      sessionId: null,
    });

    render(<PalettePanel />);

    for (const entry of SIX_COLOR_PALETTE) {
      fireEvent.click(screen.getByRole('button', { name: new RegExp(`颜色 ${entry.matched_hex}`) }));
    }

    expect(useConverterStore.getState().selectedColors.size).toBe(6);
    expect(screen.getByText(/已选 6 色/)).toBeInTheDocument();

    for (const entry of SIX_COLOR_PALETTE) {
      expect(screen.getByRole('button', { name: new RegExp(`颜色 ${entry.matched_hex}`) })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
    }

    const selectedStrip = screen.getByText(/已选 6 色/).parentElement;
    expect(selectedStrip).toHaveClass('flex-nowrap');
    expect(selectedStrip).not.toHaveClass('flex-wrap');
    expect(selectedStrip).toHaveClass('overflow-hidden');
    expect(selectedStrip?.lastElementChild).toHaveClass('overflow-x-auto');
  });

  it('全选模式选中颜色后可打开自定义配方', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      selectedColors: new Set<string>(['ee0000']),
      selectedRegions: [],
      regionData: {
        regionId: 'stale-region',
        colorHex: '#00ee00',
        pixelCount: 12,
        previewUrl: '/api/files/stale-region.png',
      },
      gradientSelection: null,
      selectionMode: 'select-all',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
      sessionId: 'session-1',
    });

    render(<PalettePanel />);

    const customRecipeButton = screen.getByRole('button', { name: '自定义配方' });
    expect(customRecipeButton).toBeEnabled();
    expect(customRecipeDialogProps.latest?.regionIds).toEqual([
      '__select_all_color__:ee0000',
    ]);
    expect(customRecipeDialogProps.latest?.currentRegionColorHex).toBe('#ee0000');

    fireEvent.click(customRecipeButton);

    expect(screen.getByTestId('custom-recipe-dialog')).toHaveTextContent(
      '__select_all_color__:ee0000',
    );
  });

  it('选择工具组在窄宽度下允许按钮换行且文字保持单行居中', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: null,
      selectionMode: 'select-all',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    const modeGroup = screen.getByRole('group', { name: '选择工具' });
    const modeControls = modeGroup.lastElementChild;

    expect(modeControls).toHaveClass('grid');
    expect(modeControls).toHaveClass('min-h-9');
    expect(modeControls).toHaveClass('grid-cols-[repeat(auto-fit,minmax(6.75rem,1fr))]');
    expect(modeControls).not.toHaveClass('h-9');

    for (const label of ['同颜色全选', '点选色块', '选区画笔', '全不选']) {
      const button = screen.getByRole('button', { name: label });
      expect(button).toHaveClass('w-full');
      expect(screen.getByText(label)).toHaveClass('whitespace-nowrap');
      expect(screen.getByText(label)).toHaveClass('leading-none');
    }
  });

  it('选择工具下方的闪烁开关只切换前端显示状态', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectionMode: 'current',
      selectionBlinkEnabled: false,
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    const blinkButton = screen.getByRole('switch', { name: '选区闪烁' });
    expect(blinkButton).toHaveAttribute('aria-checked', 'false');
    expect(useConverterStore.getState().selectionBlinkEnabled).toBe(false);

    fireEvent.click(blinkButton);
    expect(useConverterStore.getState().selectionBlinkEnabled).toBe(true);
    expect(blinkButton).toHaveAttribute('aria-checked', 'true');
    expect(blinkButton.parentElement).toHaveAttribute(
      'title',
      '让当前选区整体呼吸闪烁：浅色区块变暗，深色区块发白；仅前端显示，不重新生成预览',
    );
  });

  it('已有自定义配方覆盖时历史撤销按钮保持可用', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: null,
      selectedColors: new Set<string>(),
      selectedRegions: [],
      regionData: null,
      selectionMode: 'select-all',
      recipe_overrides: [],
      colorRemapMap: {},
      remapHistory: [],
      remapRedoHistory: [],
      regionReplacementCount: 0,
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });
    useConverterStore.getState().upsertRecipeOverrides(['region-1'], [0, 1, 2], 'Top2Bottom');

    render(<PalettePanel />);

    expect(screen.getByRole('button', { name: '撤销' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '重做' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '清空替换' })).toBeEnabled();
  });

  it('会话中的首次选区历史可直接撤销', async () => {
    const PalettePanel = await importPalettePanel();
    await hydrateFirstHistoryEntry();

    render(<PalettePanel />);

    expect(screen.getByRole('button', { name: '撤销' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '重做' })).toBeDisabled();
  });

  it('会话撤销后无需本地重做记录即可重做', async () => {
    const PalettePanel = await importPalettePanel();
    await hydrateFirstHistoryEntry();
    vi.mocked(replacementHistory).mockResolvedValueOnce({
      status: 'ok', action: 'undo', message: 'ok', entry_kind: 'selection', preview_url: '/api/files/base.png',
      can_undo: false, can_redo: true, editor_content_revision: 1,
      selection: historySelection(2, false, true), replacement_regions: [], recipe_overrides: [], recipe_override_count: 0, region_replacement_count: 0,
    });
    render(<PalettePanel />);
    fireEvent.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '重做' })).toBeEnabled());
    expect(replacementHistory).toHaveBeenCalledWith('selection-session', 'undo', expect.any(String));
    expect(useConverterStore.getState().remapRedoHistory).toEqual([]);
    expect(screen.getByRole('button', { name: '撤销' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '重做' })).toBeEnabled();
  });

  it('会话历史操作进行中时禁用撤销和重做', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      sessionId: 'selection-session',
      colorRemapMap: { ee0000: '00ee00' },
      remapHistory: [{}],
      remapRedoHistory: [{ ee0000: '00ee00' }],
      historyCanUndo: true,
      historyCanRedo: true,
      historyBusy: true,
    });

    render(<PalettePanel />);

    expect(screen.getByRole('button', { name: '撤销' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '重做' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '清空替换' })).toBeEnabled();
  });

  it('无会话时继续使用本地撤销和重做历史', async () => {
    const PalettePanel = await importPalettePanel();
    useConverterStore.setState({ palette: PALETTE });
    useConverterStore.getState().applyColorRemap('ee0000', '00ee00');
    useConverterStore.getState().applyColorRemap('0000ee', 'ee0000');
    await converterDocumentHistory.undo();
    render(<PalettePanel />);
    expect(screen.getByRole('button', { name: '撤销' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '重做' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: '重做' }));
    expect(useConverterStore.getState().colorRemapMap).toEqual({ ee0000: '00ee00', '0000ee': 'ee0000' });
  });

  it('点击统一选区里的已选色块会取消对应单块', async () => {
    const PalettePanel = await importPalettePanel();
    const mockMutateEditorSelection = vi.mocked(mutateEditorSelection);
    mockMutateEditorSelection.mockResolvedValueOnce({
      selection_revision: 6,
      content_revision: 9,
      selected_pixel_count: 20,
      selected_component_count: 1,
      selected_color_hexes: ['#00ee00'],
      region_ids: ['region-green'],
      components: [
        {
          label: 2,
          region_id: 'region-green',
          color_hex: '#00ee00',
          pixel_count: 20,
          bbox: [5, 0, 4, 5],
          anchor: [6, 2],
          contours: [[[5, 0], [9, 0], [9, 5], [5, 5]]],
        },
      ],
      contours: [
        [[5, 0], [9, 0], [9, 5], [5, 5]],
      ],
      can_undo: true,
      can_redo: false,
    });

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: '00ee00',
      selectedColors: new Set<string>(['ee0000', '00ee00']),
      selectionMode: 'multi-select',
      selectionTool: 'point',
      selectionDocument: {
        selection_revision: 5,
        content_revision: 9,
        selected_pixel_count: 30,
        selected_component_count: 2,
        selected_color_hexes: ['#ee0000', '#00ee00'],
        region_ids: ['region-red', 'region-green'],
        components: [
          {
            label: 1,
            region_id: 'region-red',
            color_hex: '#ee0000',
            pixel_count: 10,
            bbox: [0, 0, 2, 5],
            anchor: [1, 2],
            contours: [[[0, 0], [2, 0], [2, 5], [0, 5]]],
          },
          {
            label: 2,
            region_id: 'region-green',
            color_hex: '#00ee00',
            pixel_count: 20,
            bbox: [5, 0, 4, 5],
            anchor: [6, 2],
            contours: [[[5, 0], [9, 0], [9, 5], [5, 5]]],
          },
        ],
        contours: [
          [[0, 0], [2, 0], [2, 5], [0, 5]],
          [[5, 0], [9, 0], [9, 5], [5, 5]],
        ],
        can_undo: false,
        can_redo: false,
      },
      selectedRegions: [
        {
          regionId: 'region-red',
          colorHex: '#ee0000',
          pixelCount: 10,
          previewUrl: '/api/files/base.png',
          clickX: 1,
          clickY: 2,
        },
        {
          regionId: 'region-green',
          colorHex: '#00ee00',
          pixelCount: 20,
          previewUrl: '/api/files/base.png',
          clickX: 6,
          clickY: 2,
        },
      ],
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
      sessionId: 'palette-session',
      previewBaseImageUrl: '/api/files/base.png',
      previewImageUrl: '/api/files/base.png',
    });

    render(<PalettePanel />);

    await act(async () => {
      fireEvent.click(screen.getByTitle('#ee0000 (10px) — 点击取消选择'));
      await Promise.resolve();
      await Promise.resolve();
    });

    const state = useConverterStore.getState();
    expect(state.selectionDocument?.selected_component_count).toBe(1);
    expect(state.selectionDocument?.region_ids).toEqual(['region-green']);
    expect(state.selectedRegions.map((region) => region.regionId)).toEqual(['region-green']);
    expect(screen.getByRole('button', { name: '撤销' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '重做' })).toBeDisabled();
    expect(mockMutateEditorSelection).toHaveBeenCalledWith(
      expect.objectContaining({
        operation: 'point-remove',
        x: 1,
        y: 2,
        base_selection_revision: 5,
        content_revision: 9,
      }),
    );
  });

  it('当前模式下点击调色板不响应', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: null,
      selectionMode: 'current',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    const firstItem = screen.getByRole('button', { name: /颜色 ee0000/ });
    fireEvent.click(firstItem);

    expect(useConverterStore.getState().selectedColor).toBeNull();
  });

  it('全不选按钮会清空所有选择状态', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: 'ee0000',
      selectedColors: new Set<string>(['ee0000']),
      selectedRegions: [
        {
          regionId: 'region-1',
          colorHex: '#ee0000',
          pixelCount: 10,
          previewUrl: '/api/files/region-1.png',
        },
      ],
      regionData: {
        regionId: 'region-1',
        colorHex: '#ee0000',
        pixelCount: 10,
        previewUrl: '/api/files/region-1.png',
      },
      selectionMode: 'select-all',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
      previewBaseImageUrl: '/api/files/base.png',
      previewImageUrl: '/api/files/region-1.png',
    });

    render(<PalettePanel />);

    fireEvent.click(screen.getByRole('button', { name: '全不选' }));

    const state = useConverterStore.getState();
    expect(state.selectedColor).toBeNull();
    expect(state.selectedColors.size).toBe(0);
    expect(state.selectedRegions).toEqual([]);
    expect(state.regionData).toBeNull();
    expect(state.previewImageUrl).toBe('/api/files/base.png');
  });

  it('????????????', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: null,
      selectionMode: 'current',
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
      sessionId: 'session-1',
    });

    render(<PalettePanel />);

    expect(screen.queryByRole('button', { name: '??????' })).not.toBeInTheDocument();
  });

  it('palette 为空时显示提示文本', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: [],
      selectedColor: null,
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    expect(screen.getByText(/暂无调色板数据/)).toBeInTheDocument();
  });

  it('magnifier toggle keeps accessible labels without rendering a hint trigger', async () => {
    const PalettePanel = await importPalettePanel();

    useConverterStore.setState({
      palette: PALETTE,
      selectedColor: null,
      colorRemapMap: {},
      remapHistory: [],
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
    });

    render(<PalettePanel />);

    const switches = screen.getAllByRole('switch').filter((control) =>
      screen.getByRole('group', { name: '悬停显示' }).contains(control),
    );
    expect(switches).toHaveLength(2);
    expect(switches[0]).toHaveAttribute('aria-label');
    expect(switches[1]).toHaveAttribute('aria-label');
    expect(screen.queryByTestId('palette-magnifier-hint-trigger')).not.toBeInTheDocument();
  });
});
