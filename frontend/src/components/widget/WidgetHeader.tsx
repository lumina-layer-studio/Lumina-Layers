/**
 * Widget header component with drag handle, collapse toggle, and ARIA support.
 * Widget 标题栏组件，支持拖拽手柄、折叠切换和 ARIA 无障碍。
 */

import type { DraggableSyntheticListeners, DraggableAttributes } from '@dnd-kit/core';
import { useI18n } from '../../i18n/context';
import type { WidgetId } from '../../types/widget';

interface WidgetHeaderProps {
  widgetId: WidgetId;
  titleKey: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
  dragListeners?: DraggableSyntheticListeners;
  dragAttributes?: DraggableAttributes;
}

export function WidgetHeader({
  widgetId,
  titleKey,
  collapsed,
  onToggleCollapse,
  dragListeners,
  dragAttributes,
}: WidgetHeaderProps) {
  const { t } = useI18n();

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      onToggleCollapse();
    }
  };

  return (
    <div
      role="heading"
      aria-level={2}
      aria-expanded={!collapsed}
      aria-label={t(titleKey)}
      tabIndex={0}
      className="flex items-center justify-between px-3 py-1.5 cursor-grab active:cursor-grabbing select-none"
      onDoubleClick={onToggleCollapse}
      onKeyDown={handleKeyDown}
      {...dragListeners}
      {...dragAttributes}
    >
      <span className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">
        {t(titleKey)}
      </span>
      <button
        type="button"
        aria-label={collapsed ? t('widget_expand') : t('widget_collapse')}
        onClick={(e) => {
          e.stopPropagation();
          onToggleCollapse();
        }}
        onPointerDown={(e) => e.stopPropagation()}
        className="ml-1 flex-shrink-0 w-7 h-7 flex items-center justify-center rounded hover:bg-gray-200/60 dark:hover:bg-gray-700/60 transition-colors text-gray-500 dark:text-gray-400"
      >
        <span className="text-xs">{collapsed ? '\u25B6' : '\u25BC'}</span>
      </button>
    </div>
  );
}
