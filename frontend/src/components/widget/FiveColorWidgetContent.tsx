/**
 * Five-Color Query widget content wrapper.
 * 配方查询 Widget 内容包装组件。
 */

import FiveColorQueryPanel from '../FiveColorQueryPanel';

export default function FiveColorWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh]">
      <FiveColorQueryPanel />
    </div>
  );
}
