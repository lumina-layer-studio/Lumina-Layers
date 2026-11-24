import { create } from "zustand";
import type { WorkshopModuleIdentity } from "../workshop/contracts";
import {
  WorkshopProjectDisconnectedError,
  type CurrentWorkshopProject,
  type WorkshopProjectChannel,
} from "../workshop/runtime/projectChannel";
import { useWorkshopStore, type ActiveWorkshopModule } from "../workshop/store";

export interface RetainedWorkshopProject { module: ActiveWorkshopModule; value: CurrentWorkshopProject }
interface WorkshopProjectRuntime {
  current: WorkshopProjectChannel | null;
  retained: RetainedWorkshopProject | null;
  /** Keep track of a lost live editor even if the user returns to the manager. */
  disconnected: WorkshopModuleIdentity | null;
  mounted: boolean;
  change: number;
}

export const useWorkshopProjectRuntime = create<WorkshopProjectRuntime>(() => ({
  current: null, retained: null, disconnected: null, mounted: false, change: 0,
}));

function matchesModule(identity: WorkshopModuleIdentity | null, module: ActiveWorkshopModule): boolean {
  return identity?.moduleId === module.moduleId && identity.moduleVersion === module.version;
}

export function liveWorkshopProject(module: ActiveWorkshopModule): WorkshopProjectChannel | null {
  const { current } = useWorkshopProjectRuntime.getState();
  return current && !current.isClosed && matchesModule(current.identity, module) ? current : null;
}

export function isWorkshopProjectDisconnected(module: ActiveWorkshopModule): boolean {
  return matchesModule(useWorkshopProjectRuntime.getState().disconnected, module);
}

export function workshopProjectDisconnected(identity: WorkshopModuleIdentity): void {
  useWorkshopProjectRuntime.setState({ disconnected: identity });
}

export async function retainWorkshopProject() {
  const module = useWorkshopStore.getState().activeModule;
  if (!module) return;
  const current = liveWorkshopProject(module);
  if (!current) return;
  const value = await current.capture();
  if (useWorkshopStore.getState().activeModule !== module || liveWorkshopProject(module) !== current) {
    throw new WorkshopProjectDisconnectedError();
  }
  useWorkshopProjectRuntime.setState({ retained: { module, value } });
}
export function workshopProjectChanged() {
  useWorkshopProjectRuntime.setState(({ change }) => ({ change: change + 1 }));
}
export function registerWorkshopProject(channel: WorkshopProjectChannel) {
  if (channel.isClosed) return () => undefined;
  channel.onClose(() => {
    if (useWorkshopProjectRuntime.getState().current === channel) {
      useWorkshopProjectRuntime.setState({ current: null, disconnected: channel.identity });
    }
  });
  useWorkshopProjectRuntime.setState({ current: channel, disconnected: null });
  return () => {
    // An intentional detach ends this registration before it closes the channel.
    if (useWorkshopProjectRuntime.getState().current === channel) useWorkshopProjectRuntime.setState({ current: null });
    channel.close();
  };
}
export function waitForWorkshopProject(moduleId: string, version: string): Promise<WorkshopProjectChannel> {
  const module = { moduleId, version };
  return new Promise((resolve, reject) => {
    const finish = () => {
      clearTimeout(timeout);
      stop();
    };
    const fail = () => {
      finish();
      reject(new WorkshopProjectDisconnectedError());
    };
    const check = () => {
      const channel = liveWorkshopProject(module);
      if (channel) {
        finish();
        resolve(channel);
      }
    };
    const stop = useWorkshopProjectRuntime.subscribe((next, previous) => {
      if (next.disconnected !== previous.disconnected && matchesModule(next.disconnected, module)) {
        fail();
      } else if (next.current !== previous.current) {
        queueMicrotask(check);
      }
    });
    const timeout = setTimeout(fail, 30_000);
    // Read after synchronous registration or teardown has finished.
    queueMicrotask(check);
  });
}
