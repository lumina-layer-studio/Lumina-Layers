import { create } from "zustand";
import type { LutInfo } from "../api/types";
import { useSettingsStore } from "../stores/settingsStore";
import type { ProjectConverterSettings } from "../stores/converter/project";

export interface WorkflowRuntime {
  contextId: string | null;
  lutFiles: Record<string, File>;
  settings: ProjectConverterSettings | null;
  sessionIds?: string[];
  urls?: string[];
  colorcheckerIds?: string[];
}
export const useWorkflowRuntime = create<{ workflows: Record<string, WorkflowRuntime> }>(() => ({ workflows: {} }));
export function workflowRuntime(kind: string): WorkflowRuntime | undefined {
  return useWorkflowRuntime.getState().workflows[kind];
}
export function setWorkflowRuntime(kind: string, runtime: WorkflowRuntime | undefined) {
  useWorkflowRuntime.setState(({ workflows }) => {
    const next = { ...workflows };
    if (runtime) next[kind] = runtime;
    else delete next[kind];
    return { workflows: next };
  });
}
export function workflowHeaders(kind: string): Record<string, string> | undefined {
  const id = workflowRuntime(kind)?.contextId;
  return id ? { "X-Lumina-Project-Context": id } : undefined;
}
export function workflowSettings(kind: string) {
  return { ...useSettingsStore.getState(), ...workflowRuntime(kind)?.settings };
}
export function includeProjectLuts(kind: string, luts: LutInfo[], previous: LutInfo[]): LutInfo[] {
  const names = Object.keys(workflowRuntime(kind)?.lutFiles ?? {});
  return [...luts.filter((item) => !names.includes(item.name)), ...previous.filter((item) => names.includes(item.name))];
}
