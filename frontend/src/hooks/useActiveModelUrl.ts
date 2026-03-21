import { useConverterStore } from "../stores/converterStore";
import { useCalibrationStore } from "../stores/calibrationStore";

/**
 * 根据当前激活的标签页，返回应显示的 3D 模型 URL。
 *
 * 规则：
 * - 当 activeTab 为 "calibration" 且 calibrationModelUrl 非空时，返回 calibrationModelUrl
 * - 否则返回 converterModelUrl（热床由 BedPlatform 组件独立渲染）
 */
export function useActiveModelUrl(
  activeTab: "converter" | "calibration" | "extractor" | "lut-manager" | "five-color" | "about"
): string | null {
  const converterModelUrl = useConverterStore((s) => s.modelUrl);
  const calibrationModelUrl = useCalibrationStore((s) => s.modelUrl);

  if (activeTab === "calibration" && calibrationModelUrl !== null) {
    return calibrationModelUrl;
  }
  return converterModelUrl;
}
