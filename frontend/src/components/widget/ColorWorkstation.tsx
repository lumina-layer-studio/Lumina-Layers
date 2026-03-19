/**
 * ColorWorkstation — fixed bottom-center composite panel for PalettePanel + LutColorGrid.
 * ColorWorkstation — 固定在视口底部中央的复合面板，包含调色板和 LUT 颜色网格。
 *
 * Renders outside the DndContext, does not participate in drag-and-drop.
 * Uses framer-motion for smooth expand/collapse height transitions.
 * 在 DndContext 之外渲染，不参与拖拽系统。
 * 使用 framer-motion 实现平滑的展开/收起高度过渡动画。
 */

import { forwardRef } from 'react';
import { motion } from 'framer-motion';
import { useWidgetStore } from '../../stores/widgetStore';
import { useSettingsStore } from '../../stores/settingsStore';
import { useI18n } from '../../i18n/context';
import PalettePanel from '../sections/PalettePanel';
import LutColorGrid from '../sections/LutColorGrid';
import { cx } from '../ui/panelPrimitives';

/** Title bar height in pixels. (标题栏高度) */
export const COLOR_WORKSTATION_TITLE_BAR_HEIGHT = 32;
export const COLOR_WORKSTATION_WIDTH = 1500;

// Chevron icons removed in favor of iOS style drag handle

const ColorWorkstation = forwardRef<HTMLDivElement>(function ColorWorkstation(_, ref) {
  const activeTab = useWidgetStore((s) => s.activeTab);
  const collapsed = useWidgetStore((s) => s.colorWorkstationCollapsed);
  const toggle = useWidgetStore((s) => s.toggleColorWorkstation);
  const enableBlur = useSettingsStore((s) => s.enableBlur);
  const { t } = useI18n();

  // Only render on converter tab
  if (activeTab !== 'converter') return null;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 0,
        left: '50%',
        transform: 'translateX(-50%)',
        width: COLOR_WORKSTATION_WIDTH,
        zIndex: 35,
      }}
    >
      <motion.div
        ref={ref}
        data-testid="color-workstation"
        initial={false}
        animate={{
          y: collapsed ? `calc(100% - ${COLOR_WORKSTATION_TITLE_BAR_HEIGHT}px)` : 0,
        }}
        transition={{ type: 'spring', damping: 25, stiffness: 350, mass: 0.8 }}
        onAnimationComplete={() => {
          window.dispatchEvent(new CustomEvent('widget-animation-complete'));
          window.dispatchEvent(new CustomEvent('color-workstation-geometry-change'));
        }}
        className={cx(
          "overflow-hidden rounded-t-[28px] border-x border-t border-white/60 dark:border-white/10",
          "bg-white/88 shadow-[var(--shadow-panel-top)] dark:bg-slate-950/90",
          enableBlur && "backdrop-blur-md"
        )}
      >
        <div
          onClick={toggle}
          className="flex w-full cursor-pointer select-none flex-col items-center justify-center border-b border-slate-200/70 bg-white/70 transition-colors hover:bg-white/90 dark:border-slate-800/80 dark:bg-slate-950/70 dark:hover:bg-slate-950/90"
          style={{ height: COLOR_WORKSTATION_TITLE_BAR_HEIGHT }}
          aria-expanded={!collapsed}
          aria-label={t('widget.colorWorkstation')}
        >
          <div className="mb-1 mt-1 h-1.5 w-12 rounded-full bg-slate-400/60 transition-transform hover:scale-x-110 hover:bg-slate-500 dark:bg-slate-500/60 dark:hover:bg-slate-400" />
        </div>

        <div
          className="flex gap-3 px-4 pb-4 pt-3"
          style={{ height: '30vh' }}
        >
          <div className="h-full w-[45%] overflow-y-auto">
            <PalettePanel />
          </div>
          <div className="h-full w-[55%] overflow-y-auto">
            <LutColorGrid />
          </div>
        </div>
      </motion.div>
    </div>
  );
});

export default ColorWorkstation;
