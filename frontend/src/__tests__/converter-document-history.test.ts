import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("../api/converter", async (original) => ({ ...await original<typeof import("../api/converter")>(), replacementHistory: vi.fn(), getGlbStatus: vi.fn(), convertPreview: vi.fn(), getEditorSelection: vi.fn(), getEditorCommitStatus: vi.fn() }));
vi.mock("../api/session", () => ({ closeSession: vi.fn().mockResolvedValue(undefined) }));
import { convertPreview, getEditorCommitStatus, replacementHistory } from "../api/converter";
import { closeSession } from "../api/session";
import { converterDocumentHistory as history, DEFAULT_STATE, useConverterStore as converter } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { beginDocumentGesture } from "../stores/converter/documentGestures";
import { captureConversionParameters } from "../stores/conversionPreferences";
import { captureProjectSettings } from "../stores/converter/project";
import { useProjectSessionStore as session } from "../stores/projectSessionStore";
import { startProjectTracking } from "../project/controller";
import { createProjectSnapshot } from "../project/identity";
import { rememberDerivedImageSource } from "../utils/sourceFileOrigins";

let stopTracking: (() => void) | undefined;
const selection = (revision: number) => ({ selection_revision: revision, content_revision: revision, editor_content_revision: revision, selected_pixel_count: 0, selected_component_count: 0, selected_color_hexes: [], region_ids: [], components: [], contours: [], can_undo: revision > 0, can_redo: false });
beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:${Math.random()}`);
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  converter.setState({ ...DEFAULT_STATE, target_width_mm: 100, target_height_mm: 100, imageFile: new File(["art"], "art.png"), imagePreviewUrl: "blob:source" });
  history.reset();
  session.getState().reset();
});
afterEach(() => { stopTracking?.(); stopTracking = undefined; vi.restoreAllMocks(); });

it("undoes and redoes document parameters without adding preview work to history", async () => {
  converter.getState().setTargetWidthMm(150);
  const editedPosition = history.store.getState().position;
  converter.setState({ previewGlbUrl: "/later.glb", layerImagesLoading: true });
  converter.getState().setSelectionTool("brush");
  expect(history.store.getState().position).toBe(editedPosition);
  await history.undo();
  expect(converter.getState().target_width_mm).toBe(100);
  expect(converter.getState().selectionTool).toBe("brush");
  await history.redo();
  expect(converter.getState().target_width_mm).toBe(150);
});

it("groups a slider gesture while preserving separate gestures and no-ops", async () => {
  const finish = beginDocumentGesture();
  converter.getState().setTargetWidthMm(110);
  converter.getState().setTargetWidthMm(120);
  converter.getState().setTargetWidthMm(130);
  finish();
  converter.getState().setTargetWidthMm(140);
  await history.undo();
  expect(converter.getState().target_width_mm).toBe(130);
  await history.undo();
  expect(converter.getState().target_width_mm).toBe(100);
  converter.getState().setTargetWidthMm(100);
  expect(history.store.getState().canRedo).toBe(true);
  await history.redo();
  expect(converter.getState().target_width_mm).toBe(130);
});

it("treats a multi-parameter preset as one change", async () => {
  const parameters = { ...captureConversionParameters(converter.getState()), size_mm: 180, base_spacer_thick: 2, enable_outline: true };
  useSettingsStore.setState({ conversionPreferences: { last: null, presets: [{ id: "preset", name: "Large", parameters }] } });
  converter.getState().applyConversionPreset("preset");
  expect(converter.getState()).toMatchObject({ target_width_mm: 180, base_spacer_thick: 2, enable_outline: true });
  await history.undo();
  expect(converter.getState()).toMatchObject({ target_width_mm: 100, base_spacer_thick: DEFAULT_STATE.base_spacer_thick, enable_outline: false });
  expect(history.store.getState().canUndo).toBe(false);
});

it("drops redo only for a new effective document edit", async () => {
  converter.getState().setTargetWidthMm(120);
  await history.undo();
  converter.getState().setTargetWidthMm(100);
  expect(history.store.getState().canRedo).toBe(true);
  converter.getState().setTargetHeightMm(140);
  expect(history.store.getState().canRedo).toBe(false);
});

it("undoes clearing local color replacements through the unified journal", async () => {
  converter.getState().applyColorRemap("ff0000", "00ff00");
  await converter.getState().clearAllRemaps();
  expect(converter.getState().colorRemapMap).toEqual({});
  await history.undo();
  expect(converter.getState().colorRemapMap).toEqual({ ff0000: "00ff00" });
  await history.undo();
  expect(converter.getState().colorRemapMap).toEqual({});
  await history.redo();
  expect(converter.getState().colorRemapMap).toEqual({ ff0000: "00ff00" });
  await history.redo();
  expect(converter.getState().colorRemapMap).toEqual({});
});

it("restores the source and its edited session after replacing an image", async () => {
  const original = converter.getState().imageFile;
  converter.setState({ sessionId: "edited-source", previewBaseImageUrl: "/edited.png", selectionDocument: selection(4), regionReplacementCount: 2 });
  history.reset();
  converter.getState().setImageFile(new File(["new"], "new.png"));
  expect(history.store.getState().retainedSessionIds).toContain("edited-source");
  await history.undo();
  expect(converter.getState()).toMatchObject({ imageFile: original, sessionId: "edited-source", previewBaseImageUrl: "/edited.png", regionReplacementCount: 2 });
  expect(converter.getState().imagePreviewUrl).not.toBe("blob:source");
  expect(converter.getState().selectionDocument?.editor_content_revision).toBe(4);
});

it("bounds retained image history including the original behind a crop", () => {
  const file = (name: string, mib: number) => {
    const result = new File([name], name);
    Object.defineProperty(result, "size", { value: mib * 1024 * 1024 });
    return result;
  };
  const crop = file("crop.png", 20);
  rememberDerivedImageSource(crop, file("large-original.png", 200));
  converter.setState({ enableCrop: false });
  converter.getState().setImageFile(crop);
  expect(history.store.getState().canUndo).toBe(true);
  converter.getState().setImageFile(file("second.png", 60));
  expect(history.store.getState().canUndo).toBe(false);
  expect(converter.getState().imageFile?.name).toBe("second.png");
});

it("keeps document undo separate from mutable daily device defaults", async () => {
  converter.setState({ projectSettings: captureProjectSettings({ ...DEFAULT_SETTINGS, printerModel: "bambu-h2d" }) });
  history.reset();
  converter.getState().setProjectSettings({ nozzleSize: "0.2" });
  await history.undo();
  expect(converter.getState().projectSettings?.nozzleSize).toBe(DEFAULT_SETTINGS.nozzleSize);
  expect(useSettingsStore.getState().nozzleSize).toBe(DEFAULT_SETTINGS.nozzleSize);
});

it("returns to the saved content while keeping the async edit sequence monotonic", async () => {
  stopTracking = startProjectTracking();
  const snapshot = createProjectSnapshot({ name: "Saved", workflowKinds: ["converter"], documents: [{ documentId: "converter", kind: "converter", schemaVersion: 2, payload: {}, inputRevisionIds: [], resourceRefs: [], requiredCapabilities: [] }] });
  session.getState().commitSavedSnapshot(snapshot, session.getState().changeSequence);
  const before = session.getState().changeSequence;
  converter.getState().setTargetWidthMm(140);
  expect(session.getState().dirty).toBe(true);
  await history.undo();
  expect(session.getState().dirty).toBe(false);
  expect(session.getState().changeSequence).toBeGreaterThan(before);
  expect(session.getState().commitSavedSnapshot(snapshot, before)).toBe(false);
  await history.redo();
  expect(session.getState().dirty).toBe(true);
});

it("does not mark previews, tools or unchanged parameters as unsaved edits", () => {
  stopTracking = startProjectTracking();
  converter.setState({ previewBaseImageUrl: "/new.png", previewGlbUrl: "/new.glb" });
  converter.getState().setBrushSizePx(50);
  converter.getState().setSelectionTool("brush");
  converter.getState().setTargetWidthMm(100);
  expect(session.getState().dirty).toBe(false);
});

it("advances save ownership when late source decoding changes dimensions", async () => {
  stopTracking = startProjectTracking();
  const capturedSequence = session.getState().changeSequence;
  converter.setState({ aspectRatio: 2, target_height_mm: 50 });
  expect(session.getState().dirty).toBe(true);
  expect(session.getState().changeSequence).toBeGreaterThan(capturedSequence);
  expect(history.store.getState().canUndo).toBe(false);
});

it("returns a whole drag to its starting point without leaving an empty undo step", () => {
  const position = history.store.getState().position;
  const end = beginDocumentGesture();
  converter.getState().setTargetWidthMm(140);
  converter.getState().setTargetWidthMm(100);
  end();
  expect(history.store.getState()).toMatchObject({ position, canUndo: false });
});

it("preserves history and its saved position after a project restore rolls back", async () => {
  converter.getState().setTargetWidthMm(120);
  const original = converter.getState();
  const position = history.store.getState().position;
  history.replaceRuntime(() => converter.getState().commitProjectRestore({ ...original, target_width_mm: 200 }));
  history.replaceRuntime(() => converter.getState().commitProjectRestore(original));
  expect(history.store.getState().position).toBe(position);
  await history.undo();
  expect(converter.getState().target_width_mm).toBe(100);
  await history.redo();
  expect(converter.getState().target_width_mm).toBe(120);
});

it("keeps a bounded set of edited sessions and releases it on project replacement", () => {
  for (let index = 0; index < 6; index++) {
    converter.setState({ sessionId: `history-${index}`, selectionDocument: selection(0) });
    converter.getState().setImageFile(new File([String(index)], `source-${index}.png`));
  }
  expect(history.store.getState().retainedSessionIds).toHaveLength(4);
  expect(history.store.getState().retainedSessionIds).not.toContain("history-0");
  history.reset();
  expect(history.store.getState().retainedSessionIds).toEqual([]);
});

it("blocks a document switch while a backend edit is unconfirmed", () => {
  converter.setState({ contentCommitStatus: "unknown" });
  converter.getState().setImageFile(new File(["new"], "new.png"));
  expect(converter.getState().imageFile?.name).toBe("art.png");
  expect(history.store.getState().canUndo).toBe(false);
});

it("orders backend edits with parameter edits and never restores old server revisions", async () => {
  converter.setState({ sessionId: "editor", selectionDocument: selection(10), previewBaseImageUrl: "/base.png" });
  history.reset();
  converter.getState().setTargetWidthMm(150);
  converter.setState({ selectionDocument: selection(11), historyCanUndo: true, previewBaseImageUrl: "/edited.png" });
  vi.mocked(replacementHistory).mockResolvedValue({
    status: "ok", entry_kind: "selection", can_undo: false, can_redo: true,
    editor_content_revision: 12, selection: { ...selection(12), can_undo: false, can_redo: true },
    preview_url: "/restored.png", preview_raw_url: "/restored.png", free_color_set: [], replacement_regions: [], recipe_overrides: [], region_replacement_count: 0,
  } as never);
  await history.undo();
  expect(replacementHistory).toHaveBeenCalledWith("editor", "undo", expect.any(String));
  expect(converter.getState().target_width_mm).toBe(150);
  expect(converter.getState().error).toBeNull();
  expect(history.store.getState()).toMatchObject({ busy: false, canUndo: true });
  await history.undo();
  expect(converter.getState().target_width_mm).toBe(100);
  expect(converter.getState().selectionDocument?.editor_content_revision).toBe(12);
  await history.redo();
  expect(converter.getState().target_width_mm).toBe(150);
  expect(history.store.getState().canRedo).toBe(true);
});

it("keeps an unfinished history operation reserved until its receipt resolves", async () => {
  converter.setState({ sessionId: "editor", selectionDocument: selection(1) }); history.reset();
  converter.setState({ selectionDocument: selection(2), historyCanUndo: true });
  let finish!: (value: never) => void;
  vi.mocked(replacementHistory).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const operation = history.undo();
  expect(history.store.getState().busy).toBe(true);
  await history.undo();
  expect(replacementHistory).toHaveBeenCalledOnce();
  finish({ status: "ok", entry_kind: "selection", editor_content_revision: 3, selection: { ...selection(3), can_undo: false, can_redo: true }, can_undo: false, can_redo: true, free_color_set: [], replacement_regions: [], recipe_overrides: [] } as never);
  await operation;
  expect(history.store.getState().busy).toBe(false);
  expect(history.store.getState().canRedo).toBe(true);
});

it("discards an in-flight preview that finishes after parameter undo", async () => {
  converter.setState({ source_version: "legacy", lut_name: "test", lut_names: ["test"] }); history.reset();
  converter.getState().setQuantizeColors(64);
  let complete!: (value: never) => void;
  vi.mocked(convertPreview).mockImplementation(() => new Promise(resolve => { complete = resolve; }));
  const pending = converter.getState().submitPreview();
  await vi.waitFor(() => expect(convertPreview).toHaveBeenCalledOnce());
  await history.undo();
  complete({ status: "ok", message: "done", session_id: "late-preview", preview_url: "/late.png", preview_glb_url: null, warnings: [], palette: [], dimensions: { width: 10, height: 10 } } as never);
  await pending;
  expect(converter.getState().quantize_colors).toBe(DEFAULT_STATE.quantize_colors);
  expect(converter.getState().sessionId).toBeNull();
  expect(closeSession).toHaveBeenCalledWith("late-preview");
});

it("releases history navigation after an unknown undo is confirmed failed", async () => {
  converter.setState({ sessionId: "uncertain-editor", selectionDocument: selection(1) }); history.reset();
  converter.setState({ selectionDocument: selection(2), historyCanUndo: true });
  const position = history.store.getState().position;
  vi.mocked(replacementHistory).mockRejectedValueOnce(new Error("connection lost"));
  vi.mocked(getEditorCommitStatus).mockResolvedValueOnce({ status: "unknown" } as never).mockResolvedValueOnce({ status: "failed" } as never);
  await history.undo();
  expect(history.store.getState()).toMatchObject({ position, busy: true });
  await converter.getState().reconcileUnknownContentCommit();
  expect(history.store.getState()).toMatchObject({ position, busy: false, canUndo: true, canRedo: false });
  expect(replacementHistory).toHaveBeenCalledOnce();
});
