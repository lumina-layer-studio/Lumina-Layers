/**
 * Calibration widget content wrapper.
 * 校准 Widget 内容包装组件。
 */

import CalibrationPanel from '../CalibrationPanel';

export default function CalibrationWidgetContent() {
  return (
    <div className="overflow-y-auto max-h-[60vh]">
      <CalibrationPanel />
    </div>
  );
}
