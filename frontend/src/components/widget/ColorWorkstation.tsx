/**
 * ColorWorkstation — fixed bottom-center composite panel for PalettePanel + LutColorGrid.
 * ColorWorkstation — 固定在视口底部中央的复合面板，包含调色板和 LUT 颜色网格。
 *
 * Renders outside the DndContext, does not participate in drag-and-drop.
 * Uses framer-motion for smooth expand/collapse height transitions.
 * 在 DndContext 之外渲染，不参与拖拽系统。
 * 使用 framer-motion 实现平滑的展开/收起高度过渡动画。
 */

import { motion, AnimatePresence } from 'framer-motion';
import { useWidgetStore } from '../../stores/widgetStore';
import { useSettingsStore } from '../../stores/settingsStore';
import { useI18n } from '../../i18n/context';
import PalettePanel from '../sections/PalettePanel';
import LutColorGrid from '../sections/LutColorGrid';

/** Title bar height in pixels. (标题栏高度) */
const TITLE_BAR_HEIGHT = 32;

/** ChevronUp SVG icon. (向上箭头图标) */
function ChevronUp() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="18 15 12 9 6 15" />
    </svg>
  );
}

/** ChevronDown SVG icon. (向下箭头图标) */
function ChevronDown() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

export default function ColorWorkstation() {
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
        width: 1500,
        zIndex: 35,
      }}
    >
      <div
        className={`rounded-t-xl shadow-lg border border-white/20 dark:border-gray-700/50 overflow-hidden ${
          enableBlur
            ? 'backdrop-blur-xl bg-white/70 dark:bg-gray-900/70'
            : 'bg-gray-100/95 dark:bg-gray-900/95'
        }`}
      >
        {/* Title bar */}
        <button
          type="button"
          onClick={toggle}
          className="flex items-center justify-between w-full px-4 cursor-pointer select-none text-gray-700 dark:text-gray-200 hover:bg-white/20 dark:hover:bg-gray-700/30 transition-colors"
          style={{ height: TITLE_BAR_HEIGHT }}
          aria-expanded={!collapsed}
          aria-label={t('widget.colorWorkstation')}
        >
          <span className="text-sm font-medium">{t('widget.colorWorkstation')}</span>
          {collapsed ? <ChevronUp /> : <ChevronDown />}
        </button>

        {/* Content area with animated height */}
        <AnimatePresence initial={false}>
          {!collapsed && (
            <motion.div
              key="content"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: 'easeInOut' }}
              style={{ overflow: 'hidden' }}
            >
              <div
                className="flex gap-2 px-3 pb-2 pt-1"
                style={{ maxHeight: '30vh', overflow: 'hidden' }}
              >
                {/* Left: PalettePanel ~45% */}
                <div className="w-[45%] overflow-y-auto" style={{ maxHeight: '30vh' }}>
                  <PalettePanel />
                </div>
                {/* Right: LutColorGrid ~55% */}
                <div className="w-[55%] overflow-y-auto" style={{ maxHeight: '30vh' }}>
                  <LutColorGrid />
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
