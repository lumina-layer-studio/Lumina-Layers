/**
 * Relief settings widget content wrapper.
 * 浮雕设置 Widget 内容包装组件。
 */

import ReliefSettings from '../sections/ReliefSettings';

export default function ReliefSettingsWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh] p-3">
      <ReliefSettings />
    </div>
  );
}
