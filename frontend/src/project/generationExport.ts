import { create } from "zustand";
import apiClient from "../api/client";
import { useProjectSessionStore } from "../stores/projectSessionStore";
import { serializeProject } from "./archive";

/** A deliberate per-session choice; normal exports carry no project data. */
export const useProjectExportStore = create<{ embed: boolean }>(() => ({ embed: false }));

export async function freezeGenerationProject(expectedSequence: number): Promise<string | undefined> {
  if (!useProjectExportStore.getState().embed) return undefined;
  const assertCurrent = () => {
    if (useProjectSessionStore.getState().changeSequence !== expectedSequence) throw new Error("Project edits changed before generation. Generate again to include them.");
  };
  assertCurrent();
  const { captureCurrentProject } = await import("./controller");
  const { snapshot } = await captureCurrentProject({ allowGenerating: true });
  assertCurrent();
  const bytes = await serializeProject(snapshot);
  const form = new FormData();
  form.append("project", new File([bytes], "revision.lum", { type: "application/zip" }));
  const result = await apiClient.post<{ file_id: string; revision_id: string }>("/projects/revisions", form);
  assertCurrent();
  if (result.data.revision_id !== snapshot.project.revisionId) throw new Error("Project export revision was not confirmed");
  return result.data.file_id;
}
