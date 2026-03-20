/**
 * ColorWorkstation — fixed bottom-center composite panel for PalettePanel + LutColorGrid.
 * ColorWorkstation — 固定在视口底部中央的复合面板，包含调色板和 LUT 颜色网格。
 *
 * Renders outside the DndContext, does not participate in drag-and-drop.
 * Uses framer-motion for smooth expand/collapse height transitions.
 * 在 DndContext 之外渲染，不参与拖拽系统。
 * 使用 framer-motion 实现平滑的展开/收起高度过渡动画。
 */

import { forwardRef, useMemo } from 'react';
import { motion } from 'framer-motion';
import { useWidgetStore } from '../../stores/widgetStore';
import { useSettingsStore } from '../../stores/settingsStore';
import { useI18n } from '../../i18n/context';
import PalettePanel from '../sections/PalettePanel';
import LutColorGrid from '../sections/LutColorGrid';
import { cx, workstationShellClass } from '../ui/panelPrimitives';
import type { WorkspaceMode } from '../../types/workspace';

/** Title bar height in pixels. (标题栏高度) */
export const COLOR_WORKSTATION_TITLE_BAR_HEIGHT = 32;
export const COLOR_WORKSTATION_WIDTH = 1500;
const COLOR_WORKSTATION_BODY_HEIGHT = 'clamp(12rem, 24vh, 22rem)';

interface ColorWorkstationProps {
  workspaceWidth?: number;
  dockWidth?: number;
  mode?: WorkspaceMode;
}

// Chevron icons removed in favor of iOS style drag handle

const ColorWorkstation = forwardRef<HTMLDivElement, ColorWorkstationProps>(function ColorWorkstation({
  workspaceWidth,
  dockWidth = 0,
  mode = 'standard',
}, ref) {
  const activeTab = useWidgetStore((s) => s.activeTab);
  const collapsed = useWidgetStore((s) => s.colorWorkstationCollapsed);
  const toggle = useWidgetStore((s) => s.toggleColorWorkstation);
  const enableBlur = useSettingsStore((s) => s.enableBlur);
  const { t } = useI18n();

  const panelWidth = useMemo(() => {
    if (!workspaceWidth || workspaceWidth <= 0) {
      return `min(${COLOR_WORKSTATION_WIDTH}px, calc(100vw - 24px))`;
    }

    const sideClearance = dockWidth > 0 ? dockWidth * 2 + 32 : 24;
    const modeFloor = mode === 'compact' ? 560 : 720;
    const modeMax = mode === 'compact' ? 1040 : COLOR_WORKSTATION_WIDTH;
    const safeWidth = Math.max(modeFloor, workspaceWidth - sideClearance);
    return `${Math.min(modeMax, safeWidth)}px`;
  }, [dockWidth, mode, workspaceWidth]);

  // Only render on converter tab
  if (activeTab !== 'converter') return null;

  return (
    <motion.div
      ref={ref}
      data-testid="color-workstation"
      initial={false}
      animate={{
        height: collapsed
          ? COLOR_WORKSTATION_TITLE_BAR_HEIGHT
          : `calc(${mode === 'compact' ? 'clamp(10rem, 20vh, 18rem)' : COLOR_WORKSTATION_BODY_HEIGHT} + ${COLOR_WORKSTATION_TITLE_BAR_HEIGHT}px)`,
      }}
      transition={{ type: 'spring', damping: 25, stiffness: 350, mass: 0.8 }}
      onAnimationComplete={() => {
        window.dispatchEvent(new CustomEvent('widget-animation-complete'));
        window.dispatchEvent(new CustomEvent('color-workstation-geometry-change'));
      }}
      style={{
        position: 'fixed',
        bottom: 0,
        left: '50%',
        transform: 'translateX(-50%)',
        width: panelWidth,
        maxWidth: 'calc(100vw - 24px)',
        zIndex: 35,
        overflow: 'hidden',
      }}
      className={cx(
        workstationShellClass,
        "border-x border-t border-slate-200/80 dark:border-slate-800/80",
        "bg-slate-50/98 shadow-[var(--shadow-panel-top)] dark:bg-slate-950/98",
        enableBlur && "backdrop-blur-[2px]"
      )}
    >
      {/* iOS-Style Drag Handle Area */}
      <div
        onClick={toggle}
        className="flex w-full cursor-pointer select-none items-center justify-center border-b border-slate-200/70 bg-slate-50 transition-colors hover:bg-white dark:border-slate-800/80 dark:bg-slate-950 dark:hover:bg-slate-900"
        style={{ height: COLOR_WORKSTATION_TITLE_BAR_HEIGHT }}
        aria-expanded={!collapsed}
        aria-label={t('widget.colorWorkstation')}
      >
        <div className="h-1.5 w-12 rounded-full bg-slate-400/60 transition-transform hover:scale-x-110 hover:bg-slate-500 dark:bg-slate-500/60 dark:hover:bg-slate-400" />
        {collapsed && (
          <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">{t('widget.colorWorkstation')}</span>
        )}
      </div>

      {/* Content area (only rendered when expanded) */}
      {!collapsed && (
        <div
          className={cx(
            "px-3 pb-3 pt-2",
            mode === 'compact' ? "grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-2" : "flex gap-3"
          )}
          style={{ height: mode === 'compact' ? 'clamp(10rem, 20vh, 18rem)' : COLOR_WORKSTATION_BODY_HEIGHT }}
        >
          <div className={cx("min-w-0 overflow-y-auto", mode === 'compact' ? "" : "basis-[42%]")}>
            <PalettePanel />
          </div>
          <div className={cx("min-w-0 overflow-y-auto", mode === 'compact' ? "" : "basis-[58%]")}>
            <LutColorGrid />
          </div>
        </div>
      )}
    </motion.div>
  );
});

export default ColorWorkstation;
