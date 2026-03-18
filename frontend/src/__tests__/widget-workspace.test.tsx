/**
 * Unit tests for Widget workspace components.
 * Widget 工作区组件单元测试。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { I18nProvider } from '../i18n/context';
import { WidgetHeader } from '../components/widget/WidgetHeader';
import { useWidgetStore, DEFAULT_LAYOUT } from '../stores/widgetStore';
import { computeDockBottomInset } from '../utils/widgetUtils';

/** Render helper that wraps component in I18nProvider. */
function renderWithI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

describe('Widget Workspace Unit Tests', () => {
  beforeEach(() => {
    useWidgetStore.setState({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
    });
  });

  // ===== WidgetHeader ARIA 属性 =====
  describe('WidgetHeader ARIA attributes', () => {
    it('renders with correct ARIA role and attributes when expanded', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={false}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      expect(header).toBeInTheDocument();
      expect(header).toHaveAttribute('aria-expanded', 'true');
      expect(header).toHaveAttribute('aria-label');
      expect(header).toHaveAttribute('tabindex', '0');
    });

    it('sets aria-expanded to false when collapsed', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={true}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      expect(header).toHaveAttribute('aria-expanded', 'false');
    });
  });

  // ===== 键盘 Enter 触发折叠 =====
  describe('WidgetHeader keyboard interaction', () => {
    it('calls onToggleCollapse when Enter key is pressed', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={false}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      fireEvent.keyDown(header, { key: 'Enter' });
      expect(onToggle).toHaveBeenCalledTimes(1);
    });

    it('does not call onToggleCollapse for other keys', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={false}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      fireEvent.keyDown(header, { key: 'Space' });
      fireEvent.keyDown(header, { key: 'Escape' });
      expect(onToggle).not.toHaveBeenCalled();
    });
  });

  // ===== 双击触发折叠 =====
  describe('WidgetHeader double-click', () => {
    it('calls onToggleCollapse on double click', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={false}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      fireEvent.doubleClick(header);
      expect(onToggle).toHaveBeenCalledTimes(1);
    });
  });

  // ===== 默认布局加载 =====
  describe('Default layout loading', () => {
    it('loads default layout when store is reset', () => {
      const state = useWidgetStore.getState();
      expect(state.widgets['basic-settings'].visible).toBe(true);
      expect(state.widgets['basic-settings'].collapsed).toBe(false);
      expect(state.widgets['basic-settings'].snapEdge).toBe('left');
      expect(state.widgets.extractor.collapsed).toBe(false);
      expect(state.widgets['lut-manager'].collapsed).toBe(false);
      expect(state.widgets['five-color'].collapsed).toBe(false);
    });

    it('has all 12 widgets in default layout', () => {
      const state = useWidgetStore.getState();
      const widgetIds = Object.keys(state.widgets);
      expect(widgetIds).toHaveLength(12);
      expect(widgetIds).toContain('basic-settings');
      expect(widgetIds).toContain('calibration');
      expect(widgetIds).toContain('extractor');
      expect(widgetIds).toContain('lut-manager');
      expect(widgetIds).toContain('five-color');
      // palette-panel and lut-color-grid have been merged into ColorWorkstation
      expect(widgetIds).not.toContain('palette-panel');
      expect(widgetIds).not.toContain('lut-color-grid');
    });
  });

  // ===== 批量位置更新 =====
  describe('Widget store batched position updates', () => {
    it('updates multiple widget positions in one action', () => {
      const { setWidgetPositions } = useWidgetStore.getState();

      setWidgetPositions({
        'basic-settings': { x: 12, y: 24 },
        'action-bar': { x: 240, y: 360 },
      });

      const state = useWidgetStore.getState();
      expect(state.widgets['basic-settings'].position).toEqual({ x: 12, y: 24 });
      expect(state.widgets['action-bar'].position).toEqual({ x: 240, y: 360 });
    });

    it('keeps unrelated widget positions unchanged during batched updates', () => {
      const { widgets, setWidgetPositions } = useWidgetStore.getState();
      const originalExtractorPosition = widgets.extractor.position;

      setWidgetPositions({
        'basic-settings': { x: 64, y: 96 },
      });

      const state = useWidgetStore.getState();
      expect(state.widgets.extractor.position).toEqual(originalExtractorPosition);
      expect(state.widgets['basic-settings'].position).toEqual({ x: 64, y: 96 });
    });
  });

  describe('Dock avoidance geometry', () => {
    it('returns blocker height when workstation horizontally overlaps dock', () => {
      const inset = computeDockBottomInset(
        { left: 0, right: 366 },
        { left: 200, right: 1700, height: 212 }
      );

      expect(inset).toBe(212);
    });

    it('returns zero when workstation does not horizontally overlap dock', () => {
      const inset = computeDockBottomInset(
        { left: 0, right: 366 },
        { left: 500, right: 1800, height: 212 }
      );

      expect(inset).toBe(0);
    });
  });
});
