import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useConverterStore } from '../stores/converterStore';
import type { PaletteEntry, LutColorEntry } from '../api/types';

// Mock API module to prevent real network calls
vi.mock('../api/converter', async () => {
  const original = await vi.importActual<typeof import('../api/converter')>('../api/converter');
  return {
    ...original,
    fetchLutColors: vi.fn().mockResolvedValue({ colors: [] }),
    replaceColor: vi.fn().mockResolvedValue({ preview_url: '/api/files/mock' }),
  };
});

// ========== Test Data ==========

const PALETTE: PaletteEntry[] = [
  { quantized_hex: 'ff0000', matched_hex: 'ee0000', pixel_count: 500, percentage: 50.0 },
  { quantized_hex: '00ff00', matched_hex: '00ee00', pixel_count: 300, percentage: 30.0 },
  { quantized_hex: '0000ff', matched_hex: '0000ee', pixel_count: 200, percentage: 20.0 },
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
  useConverterStore.setState({
    palette: [],
    selectedColor: null,
    colorRemapMap: {},
    remapHistory: [],
    lutColors: [],
    lutColorsLoading: false,
    lutColorsLutName: '',
    enable_relief: false,
    color_height_map: {},
    heightmap_max_height: 5.0,
    replacePreviewLoading: false,
    originalPreviewUrl: null,
    previewImageUrl: null,
    sessionId: null,
  });
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

    expect(screen.getByText('量化色')).toBeInTheDocument();
    expect(screen.getByText('匹配色')).toBeInTheDocument();
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

    // The detail area uses text-[10px] font-mono class for hex codes
    // quantized_hex='ff0000' only appears once (in detail area), matched_hex='ee0000' appears in both detail and list
    expect(screen.getByText('#ff0000')).toBeInTheDocument();
    // matched_hex appears in both SelectedColorDetail and PaletteItem, so use getAllByText
    const matchedHexElements = screen.getAllByText('#ee0000');
    expect(matchedHexElements.length).toBeGreaterThanOrEqual(2); // detail area + palette list
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

    expect(screen.getByText('替换色')).toBeInTheDocument();
    // replacement hex '00ee00' appears in detail area, palette list item, and also as matched_hex of second palette entry
    const replacementHexElements = screen.getAllByText('#00ee00');
    expect(replacementHexElements.length).toBeGreaterThanOrEqual(2);
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

    expect(screen.queryByText('替换色')).not.toBeInTheDocument();
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

    expect(screen.queryByText('量化色')).not.toBeInTheDocument();
    expect(screen.queryByText('匹配色')).not.toBeInTheDocument();
  });

  it('点击调色板颜色可切换选中状态', async () => {
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

    const firstItem = screen.getByRole('button', { name: /颜色 #ee0000/ });
    fireEvent.click(firstItem);

    expect(useConverterStore.getState().selectedColor).toBe('ee0000');
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
});
