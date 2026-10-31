/**
 * TabNavBar - Top navigation bar for switching between TAB pages.
 * 顶部导航栏，用于切换不同 TAB 页面。
 *
 * Only renders the primary tab row. Secondary/sub tabs are rendered by
 * SubTabBar inside the main content area so that the header height stays
 * constant and never causes layout shifts.
 * 仅渲染一级标签行。二级标签由 SubTabBar 在主内容区渲染，
 * 使顶栏高度恒定，不会引起布局位移。
 */
import type { Ref } from 'react';
import { useI18n } from '../../i18n/context';
import type { TabId } from '../../types/widget';
import { motion } from 'framer-motion';
import NavTabStrip from './NavTabStrip';
import {
  NAV_TAB_INDICATOR_CLASS,
  NAV_TAB_INDICATOR_TRANSITION,
  primaryNavTabClass,
} from './navTabStyles';

type PrimaryTabId = 'converter' | 'lut-management' | 'material-management' | 'vectorizer' | 'workshop' | 'settings';
type LutSubTabId = 'lut-library' | 'calibration' | 'extractor' | 'lut-manager' | 'lut-cloud-sync' | 'lut-details' | 'lut-compare' | 'five-color';
type MaterialSubTabId =
  | 'gradient-card-generate'
  | 'gradient-card-extract'
  | 'material-library'
  | 'material-cloud-sync'
  | 'material-recipe';

const LUT_SUB_TAB_IDS: LutSubTabId[] = ['lut-library', 'calibration', 'extractor', 'lut-manager', 'lut-cloud-sync', 'lut-details', 'lut-compare', 'five-color'];
const MATERIAL_SUB_TAB_IDS: MaterialSubTabId[] = ['material-library', 'material-cloud-sync', 'gradient-card-generate', 'gradient-card-extract', 'material-recipe'];

const PRIMARY_TAB_ICONS: Record<PrimaryTabId, React.ReactNode> = {
  'converter': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  'lut-management': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
    </svg>
  ),
  'material-management': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 7h10M7 12h10M7 17h6M5 4h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z" />
    </svg>
  ),
  'vectorizer': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 20C4 20 8 4 12 4C16 4 20 20 20 20" />
      <circle cx="4" cy="20" r="1.5" fill="currentColor" />
      <circle cx="20" cy="20" r="1.5" fill="currentColor" />
      <circle cx="12" cy="4" r="1.5" fill="currentColor" />
    </svg>
  ),
  'workshop': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <rect x="4" y="4" width="6" height="6" rx="1.5" />
      <rect x="14" y="4" width="6" height="6" rx="1.5" />
      <rect x="4" y="14" width="6" height="6" rx="1.5" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M17 14v6m-3-3h6" />
    </svg>
  ),
  'settings': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
};

const PRIMARY_TAB_LIST: { id: PrimaryTabId; titleKey: string }[] = [
  { id: 'converter', titleKey: 'tab.converter' },
  { id: 'lut-management', titleKey: 'tab.lutManagement' },
  { id: 'material-management', titleKey: 'tab.materialManagement' },
  { id: 'vectorizer', titleKey: 'tab.vectorizer' },
  { id: 'workshop', titleKey: 'tab.workshop' },
  { id: 'settings', titleKey: 'tab.settings' },
];

export function isLutSubTab(tab: TabId): tab is LutSubTabId {
  return LUT_SUB_TAB_IDS.includes(tab as LutSubTabId);
}

export function isMaterialSubTab(tab: TabId): tab is MaterialSubTabId {
  return MATERIAL_SUB_TAB_IDS.includes(tab as MaterialSubTabId);
}

export function resolvePrimaryTab(activeTab: TabId): PrimaryTabId {
  if (isLutSubTab(activeTab)) return 'lut-management';
  if (isMaterialSubTab(activeTab)) return 'material-management';
  return activeTab;
}

export function hasSubTabs(activeTab: TabId): boolean {
  const primary = resolvePrimaryTab(activeTab);
  return primary === 'converter' || primary === 'lut-management' || primary === 'material-management';
}

interface TabNavBarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  onIndicatorAnimationComplete?: (tab: TabId) => void;
  compact?: boolean;
  /** Exposes the tab strip so the header can measure its full width. */
  navRef?: Ref<HTMLElement>;
}

export default function TabNavBar({ activeTab, onTabChange, onIndicatorAnimationComplete, compact = false, navRef }: TabNavBarProps) {
  const { t } = useI18n();
  const activePrimaryTab = resolvePrimaryTab(activeTab);

  return (
    // Only the strip is no-drag, so the empty title bar around it still moves the window.
    <NavTabStrip navRef={navRef} tutorialAnchor="primary-tabs" className="desktop-titlebar-controls">
      {PRIMARY_TAB_LIST.map(({ id, titleKey }) => {
        const isActive = id === activePrimaryTab;
        return (
          <button
            key={id}
            data-testid={`tab-${id}`}
            onClick={() => {
              if (id === 'lut-management') {
                onTabChange(isLutSubTab(activeTab) ? activeTab : 'lut-library');
                return;
              }
              if (id === 'material-management') {
                onTabChange(isMaterialSubTab(activeTab) ? activeTab : 'material-library');
                return;
              }
              onTabChange(id);
            }}
            className={primaryNavTabClass(isActive, compact)}
            style={{ WebkitTapHighlightColor: 'transparent' }}
          >
            {isActive && (
              // Animate only when the selected tab changes; header layout
              // changes must not replay the slide from the old position.
              <motion.div
                layoutId="active-primary-tab-indicator"
                layoutDependency={id}
                className={NAV_TAB_INDICATOR_CLASS}
                transition={NAV_TAB_INDICATOR_TRANSITION}
                onLayoutAnimationComplete={() => onIndicatorAnimationComplete?.(activeTab)}
                style={{ zIndex: -1 }}
              />
            )}
            <span className="relative z-10 flex items-center gap-2">
              <span className="flex items-center justify-center">{PRIMARY_TAB_ICONS[id]}</span>
              <span className={`whitespace-nowrap ${compact ? "hidden sm:inline" : ""}`}>{t(titleKey)}</span>
            </span>
          </button>
        );
      })}
    </NavTabStrip>
  );
}
