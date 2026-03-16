/**
 * Unit tests for Palette-LUT Merge (ColorWorkstation).
 * 调色板-LUT 合并（ColorWorkstation）单元测试。
 *
 * Validates registry cleanup, translations, persist version,
 * and ColorWorkstation rendering behavior.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { I18nProvider } from '../i18n/context';
import { translations } from '../i18n/translations';
import {
  useWidgetStore,
  TAB_WIDGET_MAP,
  WIDGET_REGISTRY,
  DEFAULT_LAYOUT,
} from '../stores/widgetStore';
import type { TabId } from '../types/widget';

// Mock PalettePanel and LutColorGrid — they have complex store dependencies
vi.mock('../components/sections/PalettePanel', () => ({
  default: () => <div data-testid="palette-panel">PalettePanel</div>,
}));
vi.mock('../components/sections/LutColorGrid', () => ({
  default: () => <div data-testid="lut-color-grid">LutColorGrid</div>,
}));

// Mock framer-motion to avoid animation complexity in tests
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: any) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: any) => <>{children}</>,
}));

// Mock settingsStore for enableBlur
vi.mock('../stores/settingsStore', () => ({
  useSettingsStore: (selector: any) => {
    const state = { language: 'zh' as const, enableBlur: true };
    return selector ? selector(state) : state;
  },
}));

// Lazy import ColorWorkstation after mocks are set up
import ColorWorkstation from '../components/widget/ColorWorkstation';

function renderWithI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

describe('Palette-LUT Merge Unit Tests', () => {
  beforeEach(() => {
    useWidgetStore.setState({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
      activeTab: 'converter' as TabId,
      colorWorkstationCollapsed: true,
    });
  });

  // ===== 注册表清理验证 =====
  describe('Registry cleanup — old WidgetIds removed', () => {
    it('TAB_WIDGET_MAP does not contain palette-panel or lut-color-grid', () => {
      // Requirements 3.2
      for (const [, widgetIds] of Object.entries(TAB_WIDGET_MAP)) {
        expect(widgetIds).not.toContain('palette-panel');
        expect(widgetIds).not.toContain('lut-color-grid');
      }
    });

    it('WIDGET_REGISTRY does not contain palette-panel or lut-color-grid', () => {
      // Requirements 3.4
      const registryIds = WIDGET_REGISTRY.map((w) => w.id);
      expect(registryIds).not.toContain('palette-panel');
      expect(registryIds).not.toContain('lut-color-grid');
    });

    it('DEFAULT_LAYOUT does not contain palette-panel or lut-color-grid', () => {
      // Requirements 3.3
      const layoutIds = Object.keys(DEFAULT_LAYOUT);
      expect(layoutIds).not.toContain('palette-panel');
      expect(layoutIds).not.toContain('lut-color-grid');
    });
  });

  // ===== 翻译字典验证 =====
  describe('Translation dictionary', () => {
    it('contains widget.colorWorkstation with zh and en entries', () => {
      // Requirements 6.1, 6.2
      const entry = translations['widget.colorWorkstation'];
      expect(entry).toBeDefined();
      expect(entry.zh).toBe('颜色工作站');
      expect(entry.en).toBe('Color Workstation');
    });
  });

  // ===== Persist version 验证 =====
  describe('Persist version', () => {
    it('persist version is 4', () => {
      // Requirements 5.3
      const options = (useWidgetStore.persist as any).getOptions();
      expect(options.version).toBe(4);
    });
  });

  // ===== ColorWorkstation 渲染验证 =====
  describe('ColorWorkstation rendering', () => {
    it('renders PalettePanel and LutColorGrid when activeTab is converter and expanded', () => {
      // Requirements 2.3 — rendered outside DnD; 1.2 — left/right layout
      useWidgetStore.setState({
        activeTab: 'converter',
        colorWorkstationCollapsed: false,
      });

      renderWithI18n(<ColorWorkstation />);

      expect(screen.getByTestId('palette-panel')).toBeInTheDocument();
      expect(screen.getByTestId('lut-color-grid')).toBeInTheDocument();
    });

    it('does not render content when collapsed', () => {
      useWidgetStore.setState({
        activeTab: 'converter',
        colorWorkstationCollapsed: true,
      });

      renderWithI18n(<ColorWorkstation />);

      // Title should still be visible
      expect(screen.getByText('颜色工作站')).toBeInTheDocument();
      // Content should not be rendered
      expect(screen.queryByTestId('palette-panel')).not.toBeInTheDocument();
      expect(screen.queryByTestId('lut-color-grid')).not.toBeInTheDocument();
    });

    it('returns null when activeTab is not converter', () => {
      useWidgetStore.setState({ activeTab: 'calibration' });

      const { container } = renderWithI18n(<ColorWorkstation />);
      expect(container.innerHTML).toBe('');
    });
  });
});
