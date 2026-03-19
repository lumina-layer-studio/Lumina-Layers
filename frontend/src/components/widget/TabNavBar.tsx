/**
 * TabNavBar - Top navigation bar for switching between TAB pages.
 * 顶部导航栏组件，用于在大 TAB 页面之间切换。
 * Fully redesigned with framer-motion for smooth sliding pills and glassmorphism.
 */
import { useI18n } from '../../i18n/context';
import type { TabId } from '../../types/widget';
import { motion } from 'framer-motion';

interface TabNavBarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
}

const TAB_ICONS: Record<TabId, React.ReactNode> = {
  'converter': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  'calibration': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
    </svg>
  ),
  'extractor': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758a3 3 0 10-4.243-4.243 3 3 0 004.243 4.243z" />
    </svg>
  ),
  'lut-manager': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
    </svg>
  ),
  'five-color': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
    </svg>
  ),
  'vectorizer': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 20C4 20 8 4 12 4C16 4 20 20 20 20" />
      <circle cx="4" cy="20" r="1.5" fill="currentColor" />
      <circle cx="20" cy="20" r="1.5" fill="currentColor" />
      <circle cx="12" cy="4" r="1.5" fill="currentColor" />
    </svg>
  ),
  'settings': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
};

const TAB_LIST: { id: TabId; titleKey: string }[] = [
  { id: 'converter',   titleKey: 'tab.converter' },
  { id: 'calibration', titleKey: 'tab.calibration' },
  { id: 'extractor',   titleKey: 'tab.extractor' },
  { id: 'lut-manager', titleKey: 'tab.lutManager' },
  { id: 'five-color',  titleKey: 'tab.fiveColor' },
  { id: 'vectorizer',  titleKey: 'tab.vectorizer' },
  { id: 'settings',    titleKey: 'tab.settings' },
];

export default function TabNavBar({ activeTab, onTabChange }: TabNavBarProps) {
  const { t } = useI18n();

  return (
    <nav className="relative flex items-center p-1.5 bg-gray-200/60 dark:bg-gray-800/60 backdrop-blur-xl rounded-2xl shadow-[inset_0_1px_4px_rgba(0,0,0,0.05)] dark:shadow-[inset_0_1px_4px_rgba(0,0,0,0.4)] border border-white/40 dark:border-white/5 mx-2 xl:mx-8">
      {TAB_LIST.map(({ id, titleKey }) => {
        const isActive = id === activeTab;
        
        return (
          <button
            key={id}
            data-testid={`tab-${id}`}
            onClick={() => onTabChange(id)}
            className={`
              relative flex items-center gap-2
              px-4 py-2 text-sm font-semibold tracking-wide transition-colors duration-300 rounded-xl outline-none z-10
              ${isActive ? 'text-blue-700 dark:text-blue-400' : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200'}
            `}
            style={{
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            {isActive && (
              <motion.div
                layoutId="active-tab-indicator"
                className="absolute inset-0 bg-white dark:bg-gray-700 rounded-xl shadow-[0_2px_10px_rgba(0,0,0,0.06)] dark:shadow-[0_2px_10px_rgba(0,0,0,0.5)] border border-gray-100 dark:border-gray-600/50"
                transition={{ type: 'spring', bounce: 0.2, duration: 0.5 }}
                style={{ zIndex: -1 }}
              />
            )}
            <span className="relative z-10 flex items-center justify-center">
              {TAB_ICONS[id]}
            </span>
            <span className="relative z-10">{t(titleKey)}</span>
          </button>
        );
      })}
    </nav>
  );
}
