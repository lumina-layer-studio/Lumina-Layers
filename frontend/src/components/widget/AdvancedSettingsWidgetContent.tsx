/**
 * Advanced settings widget content wrapper.
 * 高级设置 Widget 内容包装组件。
 */

import AdvancedSettings from '../sections/AdvancedSettings';

export default function AdvancedSettingsWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh] p-3">
      <AdvancedSettings />
    </div>
  );
}
