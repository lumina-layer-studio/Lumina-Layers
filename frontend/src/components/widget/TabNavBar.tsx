/**
 * TabNavBar - Top navigation bar for switching between TAB pages.
 * 顶部导航栏组件，用于在大 TAB 页面之间切换。
 */
import { useI18n } from '../../i18n/context';
import type { TabId } from '../../types/widget';

interface TabNavBarProps {
  activeTab: TabId;
  modalTab?: TabId | null;
  onTabChange: (tab: TabId) => void;
}

const TAB_LIST: { id: TabId; titleKey: string }[] = [
  { id: 'converter',   titleKey: 'tab.converter' },
  { id: 'calibration', titleKey: 'tab.calibration' },
  { id: 'extractor',   titleKey: 'tab.extractor' },
  { id: 'lut-manager', titleKey: 'tab.lutManager' },
  { id: 'five-color',  titleKey: 'tab.fiveColor' },
];

export default function TabNavBar({ activeTab, modalTab, onTabChange }: TabNavBarProps) {
  const { t } = useI18n();

  return (
    <nav className="flex items-center gap-1 px-2 py-1">
      {TAB_LIST.map(({ id, titleKey }) => {
        const isActive = id === activeTab || id === modalTab;
        return (
          <button
            key={id}
            data-testid={`tab-${id}`}
            onClick={() => onTabChange(id)}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              isActive
                ? 'bg-blue-600 text-white shadow-sm'
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
            }`}
          >
            {t(titleKey)}
          </button>
        );
      })}
    </nav>
  );
}
