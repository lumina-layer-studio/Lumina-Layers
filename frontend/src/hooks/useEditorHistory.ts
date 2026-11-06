import { useShallow } from "zustand/react/shallow";
import { useStore } from "zustand";
import { converterDocumentHistory, useConverterStore } from "../stores/converter";

/** One availability rule for every entry into the existing editor history. */
export function useEditorHistory() {
  const history = useStore(converterDocumentHistory.store);
  const busy = useConverterStore(useShallow((state) =>
    state.isGenerating || state.batchLoading || state.isCropping || state.historyBusy || state.replacePreviewLoading || state.pendingSelectionMutations.length > 0
      || state.contentCommitStatus === "pending" || state.contentCommitStatus === "unknown"
  ));
  return {
    canUndo: !busy && !history.busy && history.canUndo,
    canRedo: !busy && !history.busy && history.canRedo,
    undo: converterDocumentHistory.undo,
    redo: converterDocumentHistory.redo,
  };
}
