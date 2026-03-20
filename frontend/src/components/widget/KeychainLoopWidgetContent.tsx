/**
 * Keychain loop settings widget content wrapper.
 * 挂件环设置 Widget 内容包装组件。
 */

import KeychainLoopSettings from '../sections/KeychainLoopSettings';

export default function KeychainLoopWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh] p-3">
      <KeychainLoopSettings />
    </div>
  );
}
