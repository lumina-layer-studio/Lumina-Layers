/**
 * Basic settings widget content wrapper.
 * 基础设置 Widget 内容包装组件。
 */

import BasicSettings from '../sections/BasicSettings';

export default function BasicSettingsWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh] p-3">
      <BasicSettings />
    </div>
  );
}
