import { useEffect } from 'react';
import { useConverterStore } from '../stores/converter';
import { boundProjectResources } from '../stores/converter/project';

/**
 * Initialize converter data on app startup.
 * 应用启动时初始化转换器数据（LUT 列表、打印床尺寸、记忆的 LUT 颜色）。
 *
 * Migrated from LeftPanel's useEffect initialization logic.
 * 从 LeftPanel 的 useEffect 初始化逻辑迁移而来。
 */
export function useConverterDataInit() {
  const fetchLutCatalog = useConverterStore((s) => s.fetchLutCatalog);
  const fetchBedSizes = useConverterStore((s) => s.fetchBedSizes);
  const fetchLutColors = useConverterStore((s) => s.fetchLutColors);
  const lutName = useConverterStore((s) => s.lut_name);
  const portableLut = useConverterStore((s) => boundProjectResources(s).lut);
  const lutSessionId = useConverterStore((s) => boundProjectResources(s).lut ? s.sessionId : null);

  useEffect(() => {
    void fetchLutCatalog();
    void fetchBedSizes();
  }, [fetchLutCatalog, fetchBedSizes]);

  useEffect(() => {
    // Restore and undo bypass source pickers. Rebind the palette when the
    // private session changes, even if its LUT has the same display name.
    const controller = new AbortController();
    void fetchLutColors(lutName, controller.signal);
    return () => controller.abort();
  }, [lutName, portableLut, lutSessionId, fetchLutColors]);
}
