import { useEffect } from "react";
import { useI18n } from "../../i18n/context";
import { useEditorHistory } from "../../hooks/useEditorHistory";
import { electronAPI } from "../../integrations/electron";
import { HeaderTooltip } from "../ui/HeaderTooltip";
import { beginDocumentGesture } from "../../stores/converter/documentGestures";

function textEditorFocused() {
  return document.activeElement?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]');
}

export default function EditorHistoryControls({ disabled }: { disabled: boolean }) {
  const { t } = useI18n();
  const history = useEditorHistory();
  useEffect(() => {
    let finish: (() => void) | null = null;
    const start = () => { finish?.(); finish = beginDocumentGesture(); };
    const end = () => { const complete = finish; finish = null; queueMicrotask(() => complete?.()); };
    // Capture native canvas drags as well as DOM controls. A pointer gesture may
    // update several coupled coordinates, but remains one document command.
    window.addEventListener("pointerdown", start, true);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    window.addEventListener("blur", end);
    return () => {
      finish?.();
      window.removeEventListener("pointerdown", start, true);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      window.removeEventListener("blur", end);
    };
  }, []);
  useEffect(() => {
    const invoke = (action: "undo" | "redo") => {
      if (textEditorFocused() || document.querySelector('dialog[open], [role="dialog"][aria-modal="true"]')) return false;
      if (!disabled && (action === "undo" ? history.canUndo : history.canRedo)) void history[action]();
      return true;
    };
    const keydown = (event: KeyboardEvent) => {
      // macOS desktop routes its accelerators through the native Edit menu.
      if (electronAPI?.platform === "darwin" || event.defaultPrevented || event.repeat || event.isComposing || event.altKey || !(event.metaKey || event.ctrlKey)) return;
      const key = event.key.toLowerCase();
      const action = key === "z" ? (event.shiftKey ? "redo" : "undo") : key === "y" && event.ctrlKey && !event.shiftKey ? "redo" : null;
      if (action && invoke(action)) event.preventDefault();
    };
    const native = (event: Event) => {
      const action: unknown = (event as CustomEvent).detail;
      if ((action === "undo" || action === "redo") && invoke(action)) event.preventDefault();
    };
    window.addEventListener("keydown", keydown);
    window.addEventListener("lumina-editor-history", native);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("lumina-editor-history", native);
    };
  }, [disabled, history]);
  const modifier = electronAPI?.platform === "darwin" || /Mac/.test(navigator.platform) ? "⌘" : "Ctrl+";
  return <div role="group" aria-label={t("project_edit_history")} className="flex shrink-0 items-center gap-0.5">
    {(["undo", "redo"] as const).map((action) => <HeaderTooltip key={action} label={`${t(`project_${action}`)} · ${modifier}${action === "redo" ? "Shift+" : ""}Z`}>
      <button type="button" aria-label={t(`project_${action}`)} disabled={disabled || !(action === "undo" ? history.canUndo : history.canRedo)} onClick={() => { void history[action](); }} className="ghost-control grid h-8 w-8 place-items-center rounded-lg disabled:opacity-35 focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)]">
        <svg aria-hidden="true" className={`h-4 w-4 ${action === "redo" ? "-scale-x-100" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="m9 5-5 5 5 5" /><path d="M4 10h10a6 6 0 0 1 0 12" /></svg>
      </button>
    </HeaderTooltip>)}
  </div>;
}
