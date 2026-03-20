/**
 * Outline settings widget content wrapper.
 * 轮廓设置 Widget 内容包装组件。
 */

import OutlineSettings from '../sections/OutlineSettings';

export default function OutlineSettingsWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh] p-3">
      <OutlineSettings />
    </div>
  );
}
