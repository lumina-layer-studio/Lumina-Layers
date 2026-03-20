/**
 * Action bar widget content wrapper.
 * 操作栏 Widget 内容包装组件。
 */

import ActionBar from '../sections/ActionBar';

export default function ActionBarWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh] p-3">
      <ActionBar />
    </div>
  );
}
