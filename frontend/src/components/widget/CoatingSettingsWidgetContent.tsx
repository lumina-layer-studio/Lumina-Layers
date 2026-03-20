/**
 * Coating settings widget content wrapper.
 * 涂层设置 Widget 内容包装组件。
 */

import CoatingSettings from '../sections/CoatingSettings';

export default function CoatingSettingsWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh] p-3">
      <CoatingSettings />
    </div>
  );
}
