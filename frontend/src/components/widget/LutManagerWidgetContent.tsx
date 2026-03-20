/**
 * LUT Manager widget content wrapper.
 * LUT 管理器 Widget 内容包装组件。
 */

import LutManagerPanel from '../LutManagerPanel';

export default function LutManagerWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh]">
      <LutManagerPanel />
    </div>
  );
}
