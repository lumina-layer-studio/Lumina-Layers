import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { converterDocumentHistory, DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { useProjectSessionStore } from "../stores/projectSessionStore";
import { projectAdapterRegistry } from "../project/adapters/registry";
import { newProject, startProjectTracking, useProjectUi } from "../project/controller";
import * as storage from "../project/recoveryStore";

let stop: () => void;
beforeEach(() => {
  vi.useFakeTimers();
  useConverterStore.setState({ ...DEFAULT_STATE });
  newProject("converter", "Recovery");
  useConverterStore.setState({ imageFile: new File(["art"], "art.png"), target_width_mm: 100, target_height_mm: 100 });
  converterDocumentHistory.reset();
  useProjectUi.setState({ recoveryError: null });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  vi.spyOn(projectAdapterRegistry, "capture").mockResolvedValue({ document: { documentId: "converter", kind: "converter", schemaVersion: 2, payload: {}, inputRevisionIds: [], resourceRefs: [], requiredCapabilities: [] }, assets: [] });
  vi.spyOn(storage, "saveRecoverySnapshot").mockResolvedValue();
  vi.spyOn(storage, "listRecoverySnapshots").mockResolvedValue([]);
  stop = startProjectTracking();
});
afterEach(() => { stop(); vi.restoreAllMocks(); vi.useRealTimers(); });

it("resumes recovery after generation finishes with no additional edit", async () => {
  useConverterStore.getState().setTargetWidthMm(120);
  useConverterStore.setState({ isGenerating: true });
  await vi.advanceTimersByTimeAsync(5000);
  expect(storage.saveRecoverySnapshot).not.toHaveBeenCalled();
  useConverterStore.setState({ isGenerating: false });
  await vi.advanceTimersByTimeAsync(2000);
  expect(storage.saveRecoverySnapshot).toHaveBeenCalledOnce();
  expect(useProjectSessionStore.getState().recoveryRevisionId).toBeTruthy();
});

it("clears the visible error after a retry succeeds", async () => {
  vi.mocked(storage.saveRecoverySnapshot).mockRejectedValueOnce(new Error("temporary write failure"));
  useConverterStore.getState().setTargetWidthMm(120);
  await vi.advanceTimersByTimeAsync(5000);
  expect(useProjectUi.getState().recoveryError).toBe("temporary write failure");
  await vi.advanceTimersByTimeAsync(2000);
  expect(storage.saveRecoverySnapshot).toHaveBeenCalledTimes(2);
  expect(useProjectUi.getState().recoveryError).toBeNull();
});

it("does not let an old recovery write claim the newly opened draft", async () => {
  let finish!: () => void;
  vi.mocked(storage.saveRecoverySnapshot).mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
  useConverterStore.getState().setTargetWidthMm(120);
  await vi.advanceTimersByTimeAsync(5000);
  expect(storage.saveRecoverySnapshot).toHaveBeenCalledOnce();
  newProject("converter", "Next");
  finish();
  await vi.advanceTimersByTimeAsync(0);
  expect(useProjectSessionStore.getState().recoveryRevisionId).toBeNull();
  expect(useProjectUi.getState().name).toBe("Next");
});

it("cancels pending recovery when undo returns to the saved baseline", async () => {
  useProjectSessionStore.getState().setDocumentBaseline({ converter: converterDocumentHistory.store.getState().position });
  useConverterStore.getState().setTargetWidthMm(120);
  await converterDocumentHistory.undo();
  expect(useProjectSessionStore.getState().dirty).toBe(false);
  await vi.advanceTimersByTimeAsync(5000);
  expect(storage.saveRecoverySnapshot).not.toHaveBeenCalled();
});
