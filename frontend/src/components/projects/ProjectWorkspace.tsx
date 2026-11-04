import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n/context";
import { electronAPI } from "../../integrations/electron";
import { useApplicationMenuCommand } from "../../integrations/applicationMenu";
import { useProjectSessionStore } from "../../stores/projectSessionStore";
import { useConverterStore } from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import { captureProjectSettings } from "../../stores/converter/project";
import { projectAdapterRegistry } from "../../project/adapters/registry";
import { parseProject } from "../../project/archive";
import { activeWorkflow, exportCurrentProject, markProjectChanged, newProject, openProjectFile, PROJECT_TABS, recoverProject, refreshProjects, saveCurrentProject, startProjectTracking, useProjectUi } from "../../project/controller";
import { nativeOpenedFile, nativeProjects, openProjectEntry, pickProject, updateProjectFile, type OpenedProjectFile } from "../../project/files";
import { setWorkflowRuntime, workflowRuntime } from "../../project/workflowRuntime";
import { useProjectExportStore } from "../../project/generationExport";
import type { ProjectSnapshot } from "../../project/types";
import Button from "../ui/Button";
import { ProjectResourceLeases } from "./ProjectResourceLeases";
import { workstationInputClass } from "../ui/panelPrimitives";

type Choice = "save" | "discard" | "cancel";
export default function ProjectWorkspace() {
  const { t } = useI18n();
  const ui = useProjectUi();
  const session = useProjectSessionStore();
  const embed = useProjectExportStore((state) => state.embed);
  const [query, setQuery] = useState("");
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState(activeWorkflow);
  const [confirmation, setConfirmation] = useState<((choice: Choice) => void) | null>(null);
  const [inspection, setInspection] = useState<{ opened: OpenedProjectFile; snapshot: ProjectSnapshot; unavailable: string[]; resolve: () => void } | null>(null);
  const [inspectionPreview, setInspectionPreview] = useState<string | null>(null);
  const center = useRef<HTMLDialogElement>(null);
  const confirm = useRef<HTMLDialogElement>(null);
  const inspect = useRef<HTMLDialogElement>(null);
  const busy = session.status === "opening" || session.status === "saving";
  const error = (cause: unknown) => useProjectSessionStore.getState().setStatus("error", cause instanceof Error ? cause.message : String(cause));
  const perform = useCallback((action: () => Promise<unknown> | void) => { void Promise.resolve().then(action).catch(error); }, []);
  const guard = useCallback(async (action: () => Promise<unknown> | void, opened?: OpenedProjectFile) => {
    if (useProjectSessionStore.getState().dirty) {
      const choice = await new Promise<Choice>((resolve) => setConfirmation(() => resolve));
      if (choice === "cancel" || (choice === "save" && !await saveCurrentProject())) {
        if (opened?.requestId) await nativeProjects?.complete(opened.requestId, "cancelled");
        return false;
      }
    }
    await action();
    return true;
  }, []);
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
  const showCenter = useCallback(() => { useProjectUi.setState({ centerOpen: true }); perform(refreshProjects); }, [perform]);
  useApplicationMenuCommand("projectOpen", open, !busy);
  useApplicationMenuCommand("projectSave", save, !busy);
  useApplicationMenuCommand("projectSaveAs", saveAs, !busy);
  useApplicationMenuCommand("projectNew", showCenter, !busy);

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
    const unsubscribe = nativeProjects?.onOpen((value) => {
      queue = queue.then(() => acceptFile(nativeOpenedFile(value))).catch(error);
    });
    void nativeProjects?.ready().catch(error);
    return unsubscribe;
  }, [acceptFile]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.repeat || busy || electronAPI?.platform === "darwin") return;
      if (event.key.toLowerCase() === "s") { event.preventDefault(); if (event.shiftKey) saveAs(); else save(); }
      if (event.key.toLowerCase() === "o") { event.preventDefault(); open(); }
      if (event.key.toLowerCase() === "n") { event.preventDefault(); showCenter(); }
    };
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!nativeProjects && useProjectSessionStore.getState().dirty) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", beforeUnload);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("beforeunload", beforeUnload); };
  }, [busy, open, save, saveAs, showCenter]);
  const choose = (choice: Choice) => { confirmation?.(choice); setConfirmation(null); };
  const closeInspection = () => {
    if (inspection?.opened.requestId) void nativeProjects?.complete(inspection.opened.requestId, "cancelled");
    inspection?.resolve(); setInspection(null);
  };
  const useDeviceSettings = () => {
    const settings = captureProjectSettings(useSettingsStore.getState());
    const kind = activeWorkflow();
    if (kind === "converter") useConverterStore.setState({ projectSettings: settings });
    else setWorkflowRuntime(kind, { contextId: null, lutFiles: {}, ...workflowRuntime(kind), settings });
  };
  const filtered = ui.entries.filter((entry) => `${entry.name} ${entry.path ?? ""} ${entry.workflowKinds?.join(" ") ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  const panel = "m-auto rounded-2xl border panel-divider bg-[var(--surface-panel-strong)] p-6 text-slate-900 dark:text-slate-100 backdrop:bg-slate-950/50";
  return <>
    <ProjectResourceLeases />
    <div data-testid="project-bar" className="flex min-h-10 shrink-0 items-center gap-3 border-b panel-divider bg-[var(--surface-panel)] px-4 py-1.5 text-xs">
      <Button label={t("project_center")} size="sm" variant="ghost" onClick={showCenter} />
      <span className="min-w-0 flex-1 truncate font-medium" title={ui.entry?.path}>{ui.name}{session.dirty ? " ·" : ""}</span>
      <span role="status" className="hidden text-[var(--surface-text-muted)] sm:inline">{busy ? t("project_working") : ui.notice ? t(ui.notice) : session.dirty ? t("project_unsaved") : session.savedRevisionId ? t("project_saved") : t("project_draft")}</span>
      <Button label={t("project_open")} size="sm" onClick={open} disabled={busy} />
      <Button label={t("project_save")} size="sm" variant="primary" onClick={save} disabled={busy} />
      <Button label={t("project_save_as")} size="sm" onClick={saveAs} disabled={busy} />
      <label className="hidden items-center gap-2 lg:flex" title={t("project_embed_detail")}><input type="checkbox" checked={embed} onChange={(event) => useProjectExportStore.setState({ embed: event.target.checked })} />{t("project_embed")}</label>
    </div>
    {(session.lastError || ui.recoveryError) && <div role="alert" className="flex items-center gap-3 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"><span className="flex-1">{session.lastError || `${t("project_recovery_failed")}: ${ui.recoveryError}`}</span><Button label={t("common_close")} size="sm" variant="ghost" onClick={() => { useProjectSessionStore.getState().setStatus("idle"); useProjectUi.setState({ recoveryError: null }); }} /></div>}
    <dialog ref={center} className={`${panel} w-[min(60rem,92vw)] max-h-[88vh]`} onCancel={() => useProjectUi.setState({ centerOpen: false })}>
      <div className="mb-6 flex items-start justify-between gap-4"><div className="min-w-0"><h2 className="text-2xl font-semibold tracking-tight">{t("project_center")}</h2><p className="mt-2 text-sm text-[var(--surface-text-muted)]">{t("project_center_detail")}</p></div><Button label={t("common_close")} className="shrink-0" variant="ghost" onClick={() => useProjectUi.setState({ centerOpen: false })} /></div>
      <div className="grid gap-6 md:grid-cols-[15rem_1fr]">
        <div className="space-y-5 border-b panel-divider pb-5 md:border-b-0 md:border-r md:pr-5">
          <section className="space-y-3"><h3 className="font-semibold">{t("project_new")}</h3><input aria-label={t("project_name")} placeholder={t("project_name")} value={newName} onChange={(event) => setNewName(event.target.value)} className={`${workstationInputClass} w-full`} /><select aria-label={t("project_workflow")} value={newKind} onChange={(event) => setNewKind(event.target.value)} className={`${workstationInputClass} w-full`}>{Object.keys(PROJECT_TABS).filter((kind) => projectAdapterRegistry.get(kind)).map((kind) => <option key={kind} value={kind}>{t(`project_kind_${kind}`)}</option>)}</select><Button label={t("project_create")} variant="primary" className="w-full" disabled={busy} onClick={() => perform(() => guard(() => newProject(newKind, newName || t("project_untitled"))))} /></section>
          <section className="space-y-3 border-t panel-divider pt-5">
            <h3 className="font-semibold">{t("project_current")}</h3>
            <input aria-label={t("project_name")} value={ui.name} onChange={(event) => { useProjectUi.setState({ name: event.target.value }); markProjectChanged(); }} className={`${workstationInputClass} w-full`} />
            <Button label={t("project_export_bundle")} className="w-full" disabled={busy} onClick={() => perform(exportCurrentProject)} />
            <Button label={t("project_use_device_settings")} className="w-full" onClick={useDeviceSettings} />
            <label className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={embed} onChange={(event) => useProjectExportStore.setState({ embed: event.target.checked })} /><span>{t("project_embed")}<span className="mt-1 block text-xs text-[var(--surface-text-muted)]">{t("project_embed_detail")}</span></span></label>
          </section>
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
          {ui.recoveries.filter((record) => record.revisionId !== ui.entries.find((entry) => entry.projectId === record.projectId)?.revisionId).slice(0, 5).map((record) => <div key={record.key} className="mt-3 flex items-center justify-between gap-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"><div>{record.snapshot.manifest.name}<div className="text-xs">{t("project_recovery")} · {new Date(record.savedAt).toLocaleString()}</div></div><Button label={t("project_restore")} size="sm" onClick={() => perform(() => guard(() => recoverProject(record)))} /></div>)}
        </section>
      </div>
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
