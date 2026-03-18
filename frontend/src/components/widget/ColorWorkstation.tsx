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
      ref={ref}
      data-testid="color-workstation"
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
        initial={false}
        animate={{
          y: collapsed ? `calc(100% - ${COLOR_WORKSTATION_TITLE_BAR_HEIGHT}px)` : 0,
        }}
        transition={{ type: 'spring', damping: 25, stiffness: 350, mass: 0.8 }}
        className={`rounded-t-2xl shadow-[0_-8px_30px_rgba(0,0,0,0.12)] border-t border-l border-r border-white/40 dark:border-gray-600/50 overflow-hidden ${
          enableBlur
            ? 'backdrop-blur-2xl bg-white/70 dark:bg-gray-900/80'
            : 'bg-white/95 dark:bg-gray-900/95'
        }`}
      >
        {/* iOS-Style Drag Handle Area */}
        <div
          onClick={toggle}
          className="w-full cursor-pointer select-none flex flex-col items-center justify-center hover:bg-white/10 dark:hover:bg-gray-700/20 transition-colors"
          style={{ height: COLOR_WORKSTATION_TITLE_BAR_HEIGHT }}
          aria-expanded={!collapsed}
          aria-label={t('widget.colorWorkstation')}
        >
          {/* Subtle grab handle pill */}
          <div className="w-12 h-1.5 rounded-full bg-gray-400/50 dark:bg-gray-500/50 mt-1 mb-1 transition-transform hover:scale-x-110 hover:bg-gray-500 dark:hover:bg-gray-400" />
        </div>

        {/* Content area (Always rendered, but pushed out of bounds when collapsed) */}
        <div
          className="flex gap-2 px-3 pb-2 pt-1"
          style={{ height: '30vh' }}
        >
          {/* Left: PalettePanel ~45% */}
          <div className="w-[45%] h-full overflow-y-auto">
            <PalettePanel />
          </div>
          {/* Right: LutColorGrid ~55% */}
          <div className="w-[55%] h-full overflow-y-auto">
            <LutColorGrid />
          </div>
        </div>
      </motion.div>
    </div>
  );
});

export default ColorWorkstation;
