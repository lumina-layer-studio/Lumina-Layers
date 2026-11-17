import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useI18n } from "../../i18n/context";
import { electronAPI } from "../../integrations/electron";
import { useApplicationMenuCommand } from "../../integrations/applicationMenu";
import { useProjectSessionStore } from "../../stores/projectSessionStore";
import { useWidgetStore } from "../../stores/widgetStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { subTabRowJustifyClass } from "../widget/headerNavLayout";
import { projectAdapterRegistry } from "../../project/adapters/registry";
import { parseProject } from "../../project/archive";
import { activeWorkflow, exportCurrentProject, markProjectChanged, newProject, openProjectFile, PROJECT_TABS, recoverProject, refreshProjects, saveCurrentProject, startProjectTracking, useProjectUi } from "../../project/controller";
import { nativeOpenedFile, nativeProjects, openProjectEntry, pickProject, updateProjectFile, type OpenedProjectFile } from "../../project/files";
import type { ProjectSnapshot } from "../../project/types";
import Button from "../ui/Button";
import { ProjectResourceLeases } from "./ProjectResourceLeases";
import { workstationInputClass } from "../ui/panelPrimitives";
import ProjectToolbar from "./ProjectToolbar";
import { useProjectShareCard } from "./useProjectShareCard";
import TransientBanner from "../ui/TransientBanner";
import EditorHistoryControls from "./EditorHistoryControls";
import ProjectDeviceDialog from "./ProjectDeviceDialog";
import { availableRecoveries } from "../../project/recentProjects";
import { projectErrorMessage } from "../../project/errors";

type Choice = "save" | "discard" | "cancel";
const DEV_RELOAD_ENTRY = "lumina-dev-reload-entry";
export default function ProjectWorkspace({ children, className = "px-4", style }: { children?: ReactNode; className?: string; style?: CSSProperties }) {
  const { t } = useI18n();
  const ui = useProjectUi();
  const activeTab = useWidgetStore((state) => state.activeTab);
  const alignment = useSettingsStore((state) => state.headerNavAlignment);
  const session = useProjectSessionStore();
  const [deviceKind, setDeviceKind] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState(activeWorkflow);
  const [confirmation, setConfirmation] = useState<((choice: Choice) => void) | null>(null);
  const pendingGuard = useRef(false);
  const pendingChoice = useRef<((choice: Choice) => void) | null>(null);
  const [inspection, setInspection] = useState<{ opened: OpenedProjectFile; snapshot: ProjectSnapshot; unavailable: string[]; resolve: () => void } | null>(null);
  const [inspectionPreview, setInspectionPreview] = useState<string | null>(null);
  const center = useRef<HTMLDialogElement>(null);
  const confirm = useRef<HTMLDialogElement>(null);
  const inspect = useRef<HTMLDialogElement>(null);
  const toolbarRow = useRef<HTMLDivElement>(null);
  const toolbarActions = useRef<HTMLDivElement>(null);
  const projectBusy = session.status === "opening" || session.status === "saving";
  const sharing = useProjectShareCard(projectBusy);
  const busy = projectBusy || sharing.busy;
  const busyRef = useRef(busy);
  busyRef.current = busy;
  useLayoutEffect(() => {
    const row = toolbarRow.current;
    const actions = toolbarActions.current;
    if (!row || !actions) return;
    const measure = () => row.style.setProperty("--project-actions-width", `${actions.getBoundingClientRect().width + 16}px`);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(actions);
    return () => observer.disconnect();
  }, []);
  const error = (cause: unknown) => useProjectSessionStore.getState().setStatus("error", cause instanceof Error ? cause.message : String(cause));
  const perform = useCallback((action: () => Promise<unknown> | void) => { void Promise.resolve().then(action).catch(error); }, []);
  const guard = useCallback(async (action: () => Promise<unknown> | void, opened?: OpenedProjectFile) => {
    const cancel = async () => {
      if (opened?.requestId) await nativeProjects?.complete(opened.requestId, "cancelled");
      return false;
    };
    if (pendingGuard.current || busyRef.current) return cancel();
    pendingGuard.current = true;
    try {
      if (useProjectSessionStore.getState().dirty) {
        const choice = await new Promise<Choice>((resolve) => { pendingChoice.current = resolve; setConfirmation(() => resolve); });
        pendingChoice.current = null;
        if (choice === "cancel" || (choice === "save" && !await saveCurrentProject())) return cancel();
      }
      await action();
      return true;
    } finally { pendingGuard.current = false; }
  }, []);
  useEffect(() => () => pendingChoice.current?.("cancel"), []);
  const acceptFile = useCallback(async (opened: OpenedProjectFile | null) => {
    if (!opened) return;
    if (opened.requestId) await nativeProjects?.progress(opened.requestId, "awaiting-user");
    try { await guard(async () => {
      const snapshot = await parseProject(opened.bytes);
      const unavailable = (await projectAdapterRegistry.unavailable(snapshot)).map((doc) => doc.kind);
      if (unavailable.length) await new Promise<void>((resolve) => setInspection({ opened, snapshot, unavailable, resolve }));
      else await openProjectFile(opened);
    }, opened); } catch (cause) {
      if (opened.requestId) await nativeProjects?.complete(opened.requestId, "failed");
      throw cause;
    }
  }, [guard]);
  const open = useCallback(() => perform(async () => acceptFile(await pickProject())), [acceptFile, perform]);
  const save = useCallback(() => perform(() => saveCurrentProject()), [perform]);
  const saveAs = useCallback(() => perform(() => saveCurrentProject(true)), [perform]);
  const showCenter = useCallback(() => { setCreating(false); useProjectUi.setState({ centerOpen: true }); perform(refreshProjects); }, [perform]);
  const showNew = useCallback(() => {
    setNewName("");
    setNewKind(activeWorkflow());
    setCreating(true);
    useProjectUi.setState({ centerOpen: true });
  }, []);
  useApplicationMenuCommand("projectOpen", open, !busy);
  useApplicationMenuCommand("projectSave", save, !busy);
  useApplicationMenuCommand("projectSaveAs", saveAs, !busy);
  useApplicationMenuCommand("projectNew", showNew, !busy);

  useEffect(() => startProjectTracking(), []);
  useEffect(() => { void nativeProjects?.setDirty(session.dirty).catch(error); }, [session.dirty]);
  useEffect(() => nativeProjects?.onClose((id) => {
    void guard(() => undefined).then((accepted) => nativeProjects?.closeAnswer(id, accepted)).catch((cause) => {
      error(cause);
      void nativeProjects?.closeAnswer(id, false);
    });
  }), [guard]);
  useEffect(() => {
    const dialog = center.current;
    if (ui.centerOpen && !dialog?.open) dialog?.showModal();
    else if (!ui.centerOpen && dialog?.open) dialog.close();
  }, [ui.centerOpen]);
  useEffect(() => { if (confirmation) confirm.current?.showModal(); else confirm.current?.close(); }, [confirmation]);
  useEffect(() => { if (inspection) inspect.current?.showModal(); else inspect.current?.close(); }, [inspection]);
  useEffect(() => {
    const thumbnail = inspection?.snapshot.thumbnail;
    const url = thumbnail ? URL.createObjectURL(new Blob([thumbnail.data], { type: "image/png" })) : null;
    setInspectionPreview(url);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [inspection]);
  useEffect(() => {
    let queue = Promise.resolve();
    let disposed = false;
    let receivedOpen = false;
    const unsubscribe = nativeProjects?.onOpen((value) => {
      receivedOpen = true;
      queue = queue.then(() => acceptFile(nativeOpenedFile(value))).catch(error);
    });
    void nativeProjects?.ready().then(async () => {
      if (!import.meta.env.DEV || disposed) return;
      // A development reload returns through the normal parser/restore path.
      // The native file capability remains owned by the desktop host.
      const entryId = sessionStorage.getItem(DEV_RELOAD_ENTRY);
      sessionStorage.removeItem(DEV_RELOAD_ENTRY);
      if (entryId && !receivedOpen) queue = queue.then(async () => acceptFile(nativeOpenedFile(await nativeProjects!.openEntry(entryId)))).catch(error);
    }).catch(error);
    return () => { disposed = true; unsubscribe?.(); };
  }, [acceptFile]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.repeat || busy || electronAPI?.platform === "darwin") return;
      if (event.key.toLowerCase() === "s") { event.preventDefault(); if (event.shiftKey) saveAs(); else save(); }
      if (event.key.toLowerCase() === "o") { event.preventDefault(); open(); }
      if (event.key.toLowerCase() === "n") { event.preventDefault(); showNew(); }
    };
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (useProjectSessionStore.getState().dirty) { event.preventDefault(); event.returnValue = ""; }
      if (import.meta.env.DEV && nativeProjects) {
        const id = useProjectUi.getState().entry?.fileEntryId;
        try {
          if (id) sessionStorage.setItem(DEV_RELOAD_ENTRY, id);
          else sessionStorage.removeItem(DEV_RELOAD_ENTRY);
        } catch { /* Development resume is optional; the unsaved-edit guard is not. */ }
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", beforeUnload);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("beforeunload", beforeUnload); };
  }, [busy, open, save, saveAs, showNew]);
  const choose = (choice: Choice) => { confirmation?.(choice); setConfirmation(null); };
  const closeInspection = () => {
    if (inspection?.opened.requestId) void nativeProjects?.complete(inspection.opened.requestId, "cancelled");
    inspection?.resolve(); setInspection(null);
  };
  const recoveries = availableRecoveries(ui.recoveries, ui.entries);
  const projectError = session.lastError || ui.recoveryError;
  const filtered = ui.entries.filter((entry) => `${entry.name} ${entry.path ?? ""} ${entry.workflowKinds?.join(" ") ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  const panel = "m-auto rounded-2xl border panel-divider bg-[var(--surface-panel-strong)] p-6 text-slate-900 dark:text-slate-100 backdrop:bg-slate-950/50";
  return <>
    <ProjectResourceLeases />
    {deviceKind && <ProjectDeviceDialog kind={deviceKind} onClose={() => setDeviceKind(null)} />}
    <div ref={toolbarRow} data-testid="workspace-toolbar" style={style} className={`relative z-40 flex min-h-11 shrink-0 items-center gap-4 border-b panel-divider bg-slate-200 py-1 dark:bg-slate-950 ${className}`}>
      <div data-testid="sub-tab-row" className={`flex min-w-0 flex-1 items-center ${subTabRowJustifyClass(alignment)}`}>{children}</div>
      <div ref={toolbarActions} className="flex shrink-0 items-center gap-2">
        {activeTab === "converter" && <EditorHistoryControls disabled={busy} />}
        <ProjectToolbar name={ui.name} dirty={session.dirty} busy={busy} saving={session.status === "saving"} status={busy ? t("project_working") : session.dirty ? t("project_unsaved") : session.savedRevisionId ? t("project_saved") : t("project_draft")} notice={ui.notice && (!session.dirty || ui.notice !== "project_saved") ? t(ui.notice) : null} onCenter={showCenter} onNew={showNew} onOpen={open} onSave={save} onSaveAs={saveAs} onExport={() => perform(exportCurrentProject)} shareCard={sharing.available ? { onExport: () => { void sharing.exportCard(); }, disabledReason: sharing.disabledReason } : undefined} />
      </div>
    </div>
    {(sharing.error || session.lastError || ui.recoveryError) && <div role="alert" className="flex items-center gap-3 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"><span className="flex-1">{sharing.error || (projectError && <>{projectErrorMessage(projectError, t)}<details className="mt-1 text-xs"><summary className="cursor-pointer">{t("project_error_details")}</summary><p className="mt-1 break-words">{projectError}</p></details></>)}</span><Button label={t("common_close")} size="sm" variant="ghost" onClick={() => { sharing.dismissError(); useProjectSessionStore.getState().setStatus("idle"); useProjectUi.setState({ recoveryError: null }); }} /></div>}
    <TransientBanner message={sharing.notice} onDismiss={sharing.dismissNotice} />
    <dialog ref={center} aria-label={t(creating ? "project_new" : "project_center")} className={`${panel} ${creating ? "w-[min(28rem,92vw)]" : "w-[min(60rem,92vw)]"} max-h-[88vh]`} onCancel={() => useProjectUi.setState({ centerOpen: false })}>
      <div className="mb-6 flex items-start justify-between gap-4"><div className="min-w-0"><h2 className="text-2xl font-semibold tracking-tight">{t(creating ? "project_new" : "project_center")}</h2>{!creating && <p className="mt-2 text-sm text-[var(--surface-text-muted)]">{t("project_center_detail")}</p>}</div><Button label={t("common_close")} className="shrink-0" variant="ghost" onClick={() => useProjectUi.setState({ centerOpen: false })} /></div>
      {creating ? <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (!busy) perform(() => guard(() => newProject(newKind, newName || t("project_untitled")))); }}>
        <label className="block space-y-2 text-sm"><span>{t("project_name")}</span><input autoFocus value={newName} onChange={(event) => setNewName(event.target.value)} className={`${workstationInputClass} w-full`} disabled={busy} /></label>
        <label className="block space-y-2 text-sm"><span>{t("project_workflow")}</span><select value={newKind} onChange={(event) => setNewKind(event.target.value)} className={`${workstationInputClass} w-full`} disabled={busy}>{Object.keys(PROJECT_TABS).filter((kind) => projectAdapterRegistry.get(kind)).map((kind) => <option key={kind} value={kind}>{t(`project_kind_${kind}`)}</option>)}</select></label>
        <Button label={t("project_create")} type="submit" variant="primary" className="w-full" disabled={busy} />
      </form> : <div className="grid gap-6 md:grid-cols-[15rem_1fr]">
        <div className="space-y-5 border-b panel-divider pb-5 md:border-b-0 md:border-r md:pr-5">
          <section className="space-y-3">
            <h3 className="font-semibold">{t("project_current")}</h3>
            <input aria-label={t("project_name")} value={ui.name} onChange={(event) => { useProjectUi.setState({ name: event.target.value }); markProjectChanged(); }} className={`${workstationInputClass} w-full`} disabled={busy} />
            <Button label={t("project_export_bundle")} className="w-full" disabled={busy} onClick={() => perform(exportCurrentProject)} />
            <p className="break-all text-xs text-[var(--surface-text-muted)]">{ui.entry?.path ?? (ui.entry?.handle?.name || t("project_location_unsaved"))}</p>
            <Button label={t("project_device_settings")} className="w-full" disabled={busy} onClick={() => { useProjectUi.setState({ centerOpen: false }); setDeviceKind(activeWorkflow()); }} />
          </section>
          <div className="border-t panel-divider pt-5"><Button label={t("project_new")} className="w-full" disabled={busy} onClick={showNew} /></div>
        </div>
        <section className="min-w-0"><div className="mb-4 flex items-center justify-between gap-4"><h3 className="font-semibold">{t("project_recent")}</h3><Button label={t("project_open")} size="sm" onClick={open} disabled={busy} /></div><input type="search" placeholder={t("project_search")} aria-label={t("project_search")} className={`${workstationInputClass} mb-3 w-full`} value={query} onChange={(event) => setQuery(event.target.value)} />
          <div className="max-h-[40vh] overflow-auto">
            {filtered.length ? filtered.map((entry) => <article key={entry.fileEntryId} className="flex items-center gap-3 border-b panel-divider py-3">
              {entry.thumbnailDataUrl && <img src={entry.thumbnailDataUrl} alt="" className="h-16 w-24 shrink-0 rounded-lg object-cover" />}
              <button className="min-w-0 flex-1 rounded-lg text-left focus-visible:outline focus-visible:outline-2" onClick={() => perform(async () => acceptFile(await openProjectEntry(entry)))} disabled={busy}>
                <div className="truncate text-sm font-medium">{entry.pinned ? "★ " : ""}{entry.name}</div>
                <div className="mt-1 truncate text-xs text-[var(--surface-text-muted)]">{entry.path ?? entry.workflowKinds?.map((kind) => t(`project_kind_${kind}`)).join(" · ")}</div>
                <time className="mt-1 block text-xs text-[var(--surface-text-muted)]">{new Date(entry.lastOpenedAt).toLocaleString()}</time>
              </button>
              <div className="flex flex-col items-end">
                <Button label={t(entry.pinned ? "project_unpin" : "project_pin")} variant="ghost" size="sm" onClick={() => perform(async () => { await updateProjectFile(entry, "pin"); await refreshProjects(); })} />
                {entry.path && <Button label={t("project_locate")} variant="ghost" size="sm" onClick={() => perform(() => updateProjectFile(entry, "locate"))} />}
                <Button label={t("project_remove")} variant="ghost" size="sm" onClick={() => perform(async () => { await updateProjectFile(entry, "remove"); await refreshProjects(); })} />
              </div>
            </article>) : <div className="rounded-xl border border-dashed panel-divider px-6 py-10 text-center text-sm text-[var(--surface-text-muted)]">{t(query ? "project_no_matches" : "project_no_recent")}</div>}
          </div>
          {recoveries.length > 0 && <section className="mt-5 border-t panel-divider pt-4">
            <h3 className="text-sm font-semibold">{t("project_recovery_available")}</h3>
            {recoveries.slice(0, 5).map((record) => <div key={record.key} className="flex items-center justify-between gap-3 py-3 text-sm"><div className="min-w-0"><div className="truncate">{record.snapshot.manifest.name}</div><time className="text-xs text-[var(--surface-text-muted)]">{new Date(record.savedAt).toLocaleString()}</time></div><Button label={t("project_restore")} size="sm" disabled={busy} onClick={() => perform(() => guard(() => recoverProject(record)))} /></div>)}
          </section>}

        </section>
      </div>}
    </dialog>
    <dialog ref={confirm} className={`${panel} max-w-md`} onCancel={(event) => { event.preventDefault(); choose("cancel"); }}><h2 className="text-lg font-semibold">{t("project_unsaved_title")}</h2><p className="my-4 text-sm text-[var(--surface-text-muted)]">{t("project_unsaved_detail")}</p><div className="flex flex-wrap justify-end gap-2"><Button label={t("project_cancel")} onClick={() => choose("cancel")} /><Button label={t("project_discard")} onClick={() => choose("discard")} /><Button label={t("project_save")} variant="primary" onClick={() => choose("save")} /></div></dialog>
    <dialog ref={inspect} className={`${panel} max-w-lg`} onCancel={closeInspection}>
      <h2 className="text-lg font-semibold">{inspection?.snapshot.manifest.name}</h2>
      {inspectionPreview && <img src={inspectionPreview} alt="" className="mt-4 w-full rounded-lg object-contain" />}
      <p className="my-4 text-sm">{t("project_limited_detail")}</p>
      <p className="mb-5 text-sm text-[var(--surface-text-muted)]">{inspection?.snapshot.manifest.workflowKinds.join(" · ")}</p>
      <div className="flex justify-end gap-2">
        <Button label={t("common_close")} onClick={closeInspection} />
        <Button label={t("project_open_supported")} variant="primary" disabled={!inspection || Object.values(inspection.snapshot.documents).every((doc) => inspection.unavailable.includes(doc.kind))} onClick={() => {
          if (inspection) perform(async () => { try { await openProjectFile(inspection.opened, true); } finally { inspection.resolve(); setInspection(null); } });
        }} />
      </div>
    </dialog>
    {session.status === "opening" && <div role="status" className="fixed inset-0 z-[200] grid place-items-center bg-slate-950/40 text-white"><p className="rounded-xl bg-slate-900 px-6 py-4">{t("project_opening")}</p></div>}
  </>;
}
