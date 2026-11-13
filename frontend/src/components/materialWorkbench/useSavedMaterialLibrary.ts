import { useCallback, useEffect, useState } from "react";

import { listGradientCardMaterials } from "../../api/extractor";
import type { SavedMaterialLibraryItem } from "../../api/types";

interface SavedMaterialLibraryState {
  materials: SavedMaterialLibraryItem[];
  loading: boolean;
  loadError: boolean;
  retry: () => void;
}

/**
 * Load the saved material library once per mount, with a retry action.
 * 每次挂载加载一次已保存耗材库，并提供重试操作。
 */
export function useSavedMaterialLibrary(): SavedMaterialLibraryState {
  const [materials, setMaterials] = useState<SavedMaterialLibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(false);
    listGradientCardMaterials({ signal: controller.signal })
      .then((response) => setMaterials(response.materials ?? []))
      .catch(() => {
        if (!controller.signal.aborted) setLoadError(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { materials, loading, loadError, retry };
}
