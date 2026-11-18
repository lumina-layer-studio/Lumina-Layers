import { useEffect } from "react";

import { useConverterStore } from "../../stores/converter";
import {
  comboFromConverter,
  selectConverterMaterialSnapshot,
  useMaterialWorkbenchStore,
} from "../../stores/materialWorkbenchStore";

/**
 * Seed the shared combination from the converter the first time a tab opens.
 * Later converter edits never overwrite what the user picked here.
 *
 * 标签页首次打开时用转换器的组合初始化；之后转换器的修改不会覆盖用户在此处的选择。
 */
export function useSeedWorkbenchFromConverter(): void {
  useEffect(() => {
    const snapshot = selectConverterMaterialSnapshot(useConverterStore.getState());
    useMaterialWorkbenchStore.getState().ensureInitialized(comboFromConverter(snapshot));
  }, []);
}
