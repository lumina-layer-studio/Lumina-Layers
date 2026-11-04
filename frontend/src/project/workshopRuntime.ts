import { create } from "zustand";
import type { CurrentWorkshopProject, WorkshopProjectChannel } from "../workshop/runtime/projectChannel";
import { useWorkshopStore, type ActiveWorkshopModule } from "../workshop/store";

export interface RetainedWorkshopProject { module: ActiveWorkshopModule; value: CurrentWorkshopProject }
export const useWorkshopProjectRuntime = create<{ current: WorkshopProjectChannel | null; retained: RetainedWorkshopProject | null; mounted: boolean; change: number }>(() => ({ current: null, retained: null, mounted: false, change: 0 }));
export async function retainWorkshopProject() {
  const { current } = useWorkshopProjectRuntime.getState();
  const module = useWorkshopStore.getState().activeModule;
  if (!module || !current) return;
  const value = await current.capture();
  if (useWorkshopProjectRuntime.getState().current === current) useWorkshopProjectRuntime.setState({ retained: { module, value } });
}
export function workshopProjectChanged() {
  useWorkshopProjectRuntime.setState(({ change }) => ({ change: change + 1 }));
}
export function registerWorkshopProject(channel: WorkshopProjectChannel) {
  useWorkshopProjectRuntime.setState({ current: channel });
  return () => {
    if (useWorkshopProjectRuntime.getState().current === channel) useWorkshopProjectRuntime.setState({ current: null });
    channel.close();
  };
}
export function waitForWorkshopProject(moduleId: string, version: string): Promise<WorkshopProjectChannel> {
  const match = () => {
    const current = useWorkshopProjectRuntime.getState().current;
    return current?.identity.moduleId === moduleId && current.identity.moduleVersion === version ? current : null;
  };
  const current = match();
  if (current) return Promise.resolve(current);
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { stop(); reject(new Error("The installed Workshop module did not become ready for project restore")); }, 30_000);
    const stop = useWorkshopProjectRuntime.subscribe(() => {
      const channel = match();
      if (channel) { clearTimeout(timeout); stop(); resolve(channel); }
    });
  });
}
