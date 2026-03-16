import { useEffect } from 'react';
import { useConverterStore } from '../stores/converterStore';

/**
 * Initialize converter data on app startup.
 * 应用启动时初始化转换器数据（LUT 列表、打印床尺寸、记忆的 LUT 颜色）。
 *
 * Migrated from LeftPanel's useEffect initialization logic.
 * 从 LeftPanel 的 useEffect 初始化逻辑迁移而来。
 */
export function useConverterDataInit() {
  const fetchLutList = useConverterStore((s) => s.fetchLutList);
  const fetchBedSizes = useConverterStore((s) => s.fetchBedSizes);
  const fetchLutColors = useConverterStore((s) => s.fetchLutColors);

  useEffect(() => {
    void fetchLutList().then(() => {
      // After LUT list loads, if a remembered LUT is set, also load its colors
      const { lut_name, lutColorsLutName, lutColors } = useConverterStore.getState();
      if (lut_name && (lutColorsLutName !== lut_name || lutColors.length === 0)) {
        void fetchLutColors(lut_name);
      }
    });
    void fetchBedSizes();
  }, [fetchLutList, fetchBedSizes, fetchLutColors]);
}
