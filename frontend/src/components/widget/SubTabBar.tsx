/**
 * SubTabBar - Secondary tab bar rendered inside the main content area.
 * 二级标签栏，在主内容区内部渲染。
 *
 * Placed below the header so its height changes never affect the header,
 * eliminating layout shifts / bouncing at the top of the viewport.
 * 放在顶栏下方，其高度变化不影响顶栏，消除画面抖动。
 */
import { useI18n } from '../../i18n/context';
import type { TabId, ConverterSubTabId } from '../../types/widget';
import { resolvePrimaryTab } from './TabNavBar';
import { useWidgetStore } from '../../stores/widgetStore';
import { motion } from 'framer-motion';
import NavTabStrip from './NavTabStrip';
import {
  NAV_TAB_INDICATOR_CLASS,
  NAV_TAB_INDICATOR_TRANSITION,
  SECONDARY_NAV_TAB_ICON_CLASS,
  secondaryNavTabClass,
} from './navTabStyles';

type LutSubTabId = 'lut-library' | 'calibration' | 'extractor' | 'lut-manager' | 'lut-cloud-sync' | 'lut-details' | 'lut-compare' | 'five-color';
type MaterialSubTabId =
  | 'gradient-card-generate'
  | 'gradient-card-extract'
  | 'material-library'
  | 'material-cloud-sync'
  | 'material-recipe'
  | 'material-gamut'
  | 'material-cache';

const CONVERTER_SUB_TAB_ICONS: Record<ConverterSubTabId, React.ReactNode> = {
  core: (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
  color: (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
    </svg>
  ),
  advanced: (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
    </svg>
  ),
};

const SECONDARY_TAB_ICONS: Record<LutSubTabId | MaterialSubTabId, React.ReactNode> = {
  'lut-library': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 7.5A2.5 2.5 0 015.5 5H9l1.5 2H18.5A2.5 2.5 0 0121 9.5v7A2.5 2.5 0 0118.5 19h-13A2.5 2.5 0 013 16.5v-9z" />
    </svg>
  ),
  'calibration': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
    </svg>
  ),
  'extractor': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758a3 3 0 10-4.243-4.243 3 3 0 004.243 4.243z" />
    </svg>
  ),
  'lut-manager': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
    </svg>
  ),
  'lut-cloud-sync': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M4 17.5A3.5 3.5 0 017.5 14H8a5 5 0 019.7-1.7A3.5 3.5 0 0117.5 21h-10A3.5 3.5 0 014 17.5z" />
    </svg>
  ),
  'lut-details': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10 6h8m-8 6h8m-8 6h8M6 6h.01M6 12h.01M6 18h.01" />
    </svg>
  ),
  'lut-compare': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h8M8 17h8M5 7l-2 2m0 0l2 2m-2-2h10M19 17l2-2m0 0l-2-2m2 2H11" />
    </svg>
  ),
  'five-color': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
    </svg>
  ),
  'gradient-card-generate': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m6-6H6m12-7H6a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2z" />
    </svg>
  ),
  'gradient-card-extract': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 16V4m0 12l-4-4m4 4l4-4M6 20h12" />
    </svg>
  ),
  'material-library': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 7.5A2.5 2.5 0 015.5 5H9l1.5 2H18.5A2.5 2.5 0 0121 9.5v7A2.5 2.5 0 0118.5 19h-13A2.5 2.5 0 013 16.5v-9z" />
    </svg>
  ),
  'material-cloud-sync': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M4 17.5A3.5 3.5 0 017.5 14H8a5 5 0 019.7-1.7A3.5 3.5 0 0117.5 21h-10A3.5 3.5 0 014 17.5z" />
    </svg>
  ),
  'material-recipe': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h10" />
      <circle cx="18" cy="18" r="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  'material-gamut': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l8.5 15h-17L12 3z" />
      <circle cx="12" cy="13" r="2.5" />
    </svg>
  ),
  'material-cache': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <ellipse cx="12" cy="6" rx="7" ry="3" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 6v6c0 1.66 3.13 3 7 3s7-1.34 7-3V6M5 12v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6" />
    </svg>
  ),
};

const CONVERTER_SUB_TAB_LIST: { id: ConverterSubTabId; titleKey: string }[] = [
  { id: 'core', titleKey: 'tab.converterCore' },
  { id: 'color', titleKey: 'tab.converterColor' },
  { id: 'advanced', titleKey: 'tab.converterAdvanced' },
];

const LUT_SECONDARY_TAB_LIST: { id: LutSubTabId; titleKey: string }[] = [
  { id: 'lut-library', titleKey: 'tab.lutLibrary' },
  { id: 'lut-cloud-sync', titleKey: 'tab.lutCloudSync' },
  { id: 'calibration', titleKey: 'tab.calibration' },
  { id: 'extractor', titleKey: 'tab.extractor' },
  { id: 'lut-details', titleKey: 'tab.lutDetails' },
  { id: 'lut-compare', titleKey: 'tab.lutCompare' },
  { id: 'five-color', titleKey: 'tab.fiveColor' },
];

const MATERIAL_SECONDARY_TAB_LIST: { id: MaterialSubTabId; titleKey: string }[] = [
  { id: 'material-library', titleKey: 'tab.materialLibrary' },
  { id: 'material-cloud-sync', titleKey: 'tab.materialCloudSync' },
  { id: 'gradient-card-generate', titleKey: 'tab.gradientCardGenerate' },
  { id: 'gradient-card-extract', titleKey: 'tab.gradientCardExtract' },
  { id: 'material-recipe', titleKey: 'tab.materialRecipe' },
  { id: 'material-gamut', titleKey: 'tab.materialGamut' },
  { id: 'material-cache', titleKey: 'tab.materialCache' },
];

interface SubTabBarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  compact?: boolean;
}

export default function SubTabBar({ activeTab, onTabChange, compact = false }: SubTabBarProps) {
  const { t } = useI18n();
  const primaryTab = resolvePrimaryTab(activeTab);
  const activeConverterSubTab = useWidgetStore((s) => s.activeConverterSubTab);
  const setActiveConverterSubTab = useWidgetStore((s) => s.setActiveConverterSubTab);

  const showConverterSecondary = primaryTab === 'converter';
  const showLutSubTabs = primaryTab === 'lut-management';
  const showMaterialSubTabs = primaryTab === 'material-management';

  if (!showConverterSecondary && !showLutSubTabs && !showMaterialSubTabs) {
    return null;
  }

  const secondaryTabList = showLutSubTabs
    ? LUT_SECONDARY_TAB_LIST
    : showMaterialSubTabs
      ? MATERIAL_SECONDARY_TAB_LIST
      : null;

  return (
    <NavTabStrip role="tablist">
      {showConverterSecondary
        ? CONVERTER_SUB_TAB_LIST.map(({ id, titleKey }) => (
            <SubTabButton
              key={id}
              testId={`subtab-converter-${id}`}
              label={t(titleKey)}
              icon={CONVERTER_SUB_TAB_ICONS[id]}
              isActive={id === activeConverterSubTab}
              indicatorLayoutId="active-converter-sub-tab-indicator"
              compact={compact}
              onSelect={() => setActiveConverterSubTab(id)}
            />
          ))
        : secondaryTabList?.map(({ id, titleKey }) => (
            <SubTabButton
              key={id}
              testId={`subtab-${id}`}
              label={t(titleKey)}
              icon={SECONDARY_TAB_ICONS[id]}
              isActive={id === activeTab}
              indicatorLayoutId="active-secondary-tab-indicator"
              compact={compact}
              onSelect={() => onTabChange(id)}
            />
          ))}
    </NavTabStrip>
  );
}

interface SubTabButtonProps {
  testId: string;
  label: string;
  icon: React.ReactNode;
  isActive: boolean;
  indicatorLayoutId: string;
  compact: boolean;
  onSelect: () => void;
}

function SubTabButton({
  testId,
  label,
  icon,
  isActive,
  indicatorLayoutId,
  compact,
  onSelect,
}: SubTabButtonProps) {
  return (
    <button
      role="tab"
      aria-selected={isActive}
      data-testid={testId}
      onClick={onSelect}
      className={secondaryNavTabClass(isActive, compact)}
      style={{ WebkitTapHighlightColor: 'transparent' }}
    >
      {isActive && (
        // Animate only when the selected tab changes; header layout changes
        // must not replay the slide from the old position.
        <motion.div
          layoutId={indicatorLayoutId}
          layoutDependency={testId}
          className={NAV_TAB_INDICATOR_CLASS}
          transition={NAV_TAB_INDICATOR_TRANSITION}
          style={{ zIndex: -1 }}
        />
      )}
      <span className="relative z-10 flex items-center gap-1.5">
        <span className={SECONDARY_NAV_TAB_ICON_CLASS}>{icon}</span>
        <span className={`whitespace-nowrap ${compact ? "hidden sm:inline" : ""}`}>{label}</span>
      </span>
    </button>
  );
}
