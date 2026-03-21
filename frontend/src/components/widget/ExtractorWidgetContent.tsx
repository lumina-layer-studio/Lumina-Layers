/**
 * Extractor widget content wrapper.
 * 提取器 Widget 内容包装组件。
 */

import ExtractorPanel from '../ExtractorPanel';

export default function ExtractorWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh]">
      <ExtractorPanel />
    </div>
  );
}
