import { workshopApi } from "../../api/workshop";
import { useWidgetStore } from "../../stores/widgetStore";
import type { WorkshopModuleIdentity } from "../../workshop/contracts";
import {
  WorkshopProjectDisconnectedError,
  type CurrentWorkshopProject,
  type WorkshopProjectChannel,
} from "../../workshop/runtime/projectChannel";
import { useWorkshopStore, type ActiveWorkshopModule } from "../../workshop/store";
import { fileAsset, projectFile } from "../assets";
import { workshopProjectError } from "../errors";
import type { JsonObject, WorkflowDocument } from "../types";
import {
  isWorkshopProjectDisconnected,
  liveWorkshopProject,
  useWorkshopProjectRuntime,
  waitForWorkshopProject,
  type RetainedWorkshopProject,
} from "../workshopRuntime";
import { decodeWorkshopState, encodeWorkshopState } from "../workshopState";
import { assertRestoreIsCurrent, type PreparedProjectRestore, type ProjectAdapter } from "./types";

interface WorkshopPayload { module: ActiveWorkshopModule | null; schema: string | null; state: string | null }
interface PreparedWorkshop extends PreparedProjectRestore {
  channel: WorkshopProjectChannel | null;
  token: { token: string } | null;
  previousModule: ActiveWorkshopModule | null;
  previousSnapshot: CurrentWorkshopProject | null;
  previousTab: ReturnType<typeof useWidgetStore.getState>["activeTab"];
  switched: boolean;
  rolledBack?: boolean;
  previousRetained: RetainedWorkshopProject | null;
  previousDisconnected: WorkshopModuleIdentity | null;
  commitStarted: boolean;
}
function validate(document: WorkflowDocument): WorkshopPayload {
  if (document.kind !== "workshop" || document.schemaVersion !== 2) throw new Error("Unsupported Workshop project version");
  const payload = document.payload as unknown as WorkshopPayload;
  if (payload.module === null && payload.state === null && payload.schema === null) return payload;
  if (!payload.module || !/^[a-z0-9][a-z0-9.-]{1,127}$/.test(payload.module.moduleId) || typeof payload.module.version !== "string" || payload.module.version.length > 128 || !payload.schema || typeof payload.state !== "string" || !document.resourceRefs.includes(payload.state)) throw new Error("Invalid Workshop project identity or state");
  return payload;
}

async function installedSnapshotSupport(module: ActiveWorkshopModule) {
  const { modules } = await workshopApi.listModules();
  const installed = modules.find((item) => item.module_id === module.moduleId);
  const version = installed?.version_details.find((item) => item.version === module.version);
  const schemas = version?.project_snapshot_protocol === 1 && version.permissions.some((permission) => permission.name === "project.storage")
    ? version.project_snapshot_schemas ?? []
    : [];
  return { enabled: installed?.enabled === true, schemas };
}

async function requireLiveWorkshopProject(module: ActiveWorkshopModule): Promise<WorkshopProjectChannel> {
  const live = liveWorkshopProject(module);
  if (live) return live;
  if (isWorkshopProjectDisconnected(module)) throw new WorkshopProjectDisconnectedError();
  const { schemas } = await installedSnapshotSupport(module);
  const connected = liveWorkshopProject(module);
  if (connected) return connected;
  if (!schemas.length && !isWorkshopProjectDisconnected(module)) throw workshopProjectError("workshop_project_snapshots_unsupported");
  throw new WorkshopProjectDisconnectedError();
}

function assertLiveWorkshopProject(
  module: ActiveWorkshopModule | null,
  channel: WorkshopProjectChannel | null,
): asserts channel is WorkshopProjectChannel {
  if (!module || !channel || useWorkshopStore.getState().activeModule !== module || liveWorkshopProject(module) !== channel) {
    throw new WorkshopProjectDisconnectedError();
  }
}

function restoreError(error: unknown): unknown {
  return error instanceof WorkshopProjectDisconnectedError
    ? workshopProjectError("workshop_project_restore_disconnected", error)
    : error;
}

async function selectModule(module: ActiveWorkshopModule): Promise<WorkshopProjectChannel> {
  useWorkshopProjectRuntime.setState({ mounted: true });
  useWorkshopStore.getState().openModule(module.moduleId, module.version);
  return waitForWorkshopProject(module.moduleId, module.version);
}
async function restorePrevious(prepared: PreparedWorkshop) {
  if (prepared.rolledBack) return;
  if (prepared.previousModule && prepared.previousSnapshot) {
    const active = useWorkshopStore.getState().activeModule;
    const current = active?.moduleId === prepared.previousModule.moduleId && active.version === prepared.previousModule.version
      ? liveWorkshopProject(prepared.previousModule) : null;
    const channel = current ?? await selectModule(prepared.previousModule);
    const selected = useWorkshopStore.getState().activeModule;
    assertLiveWorkshopProject(selected, channel);
    const token = await channel.prepare(prepared.previousSnapshot);
    await channel.request("commit", token);
    assertLiveWorkshopProject(selected, channel);
  } else if (prepared.switched) useWorkshopStore.getState().returnHome();
  useWidgetStore.getState().setActiveTab(prepared.previousTab);
  useWorkshopProjectRuntime.setState({ retained: prepared.previousRetained, disconnected: prepared.previousDisconnected });
  prepared.rolledBack = true;
}
export function createWorkshopProjectAdapter(): ProjectAdapter {
  return {
    kind: "workshop", validate,
    subscribe: (listener) => useWorkshopProjectRuntime.subscribe((next, previous) => { if (next.change !== previous.change) listener(); }),
    reset: () => {
      useWorkshopStore.getState().returnHome();
      useWorkshopProjectRuntime.setState({ retained: null, disconnected: null });
    },
    async unavailable(document) {
      if (document.schemaVersion !== 2) return true;
      const payload = validate(document);
      if (!payload.module) return false;
      const support = await installedSnapshotSupport(payload.module);
      return !support.enabled || !support.schemas.includes(payload.schema!);
    },
    async capture() {
      const active = useWorkshopStore.getState().activeModule;
      const { retained, disconnected } = useWorkshopProjectRuntime.getState();
      const module = active ?? retained?.module ?? null;
      try {
        if (!active && disconnected) throw new WorkshopProjectDisconnectedError();
        const channel = active ? await requireLiveWorkshopProject(active) : null;
        if (active) assertLiveWorkshopProject(active, channel);
        const value = channel ? await channel.capture() : retained?.value ?? null;
        const encoded = value ? await encodeWorkshopState(value.state) : null;
        const stateAsset = encoded ? await fileAsset("workshop.state", new File([JSON.stringify(encoded.state)], "workshop-state.json", { type: "application/vnd.lumina.workshop-state+json" }), "resource") : null;
        if (active) {
          assertLiveWorkshopProject(active, channel);
        } else {
          const runtime = useWorkshopProjectRuntime.getState();
          if (runtime.disconnected) throw new WorkshopProjectDisconnectedError();
          if (useWorkshopStore.getState().activeModule !== null || runtime.retained !== retained) {
            throw new Error("The Workshop project changed while it was being captured. Save again to include the latest edits.");
          }
        }
        const assets = stateAsset ? [stateAsset, ...encoded!.assets] : [];
        const payload: WorkshopPayload = { module, schema: value?.schemaVersion ?? null, state: stateAsset?.assetId ?? null };
        return { document: { documentId: "workshop.main", kind: "workshop", schemaVersion: 2, payload: payload as unknown as JsonObject, inputRevisionIds: [], resourceRefs: assets.map((asset) => asset.assetId), requiredCapabilities: ["workflow.workshop-v2"] }, assets };
      } catch (error) {
        if (error instanceof WorkshopProjectDisconnectedError) throw workshopProjectError("workshop_project_save_disconnected", error);
        throw error;
      }
    },
    async prepareRestore(snapshot, context) {
      const document = Object.values(snapshot.documents).find((doc) => doc.kind === "workshop")!;
      const payload = validate(document);
      const previousModule = useWorkshopStore.getState().activeModule;
      const { retained, disconnected } = useWorkshopProjectRuntime.getState();
      const prepared: PreparedWorkshop = {
        snapshot, document, previousModule, previousSnapshot: null,
        previousRetained: retained, previousDisconnected: disconnected, previousTab: useWidgetStore.getState().activeTab,
        channel: null, token: null, switched: false, commitStarted: false,
      };
      try {
        if (previousModule) {
          const previousChannel = await requireLiveWorkshopProject(previousModule);
          assertLiveWorkshopProject(previousModule, previousChannel);
          prepared.previousSnapshot = await previousChannel.capture();
          assertLiveWorkshopProject(previousModule, previousChannel);
          prepared.channel = previousChannel;
        }
        if (!payload.module) return prepared;
        const file = projectFile(snapshot, payload.state)!;
        if (file.size > 128 * 1024 * 1024) throw new Error("Workshop snapshot exceeds its size limit");
        const state = await decodeWorkshopState(JSON.parse(await file.text()), snapshot, document.resourceRefs);
        assertRestoreIsCurrent(context);
        if (previousModule) assertLiveWorkshopProject(previousModule, prepared.channel);
        if (!previousModule || previousModule.moduleId !== payload.module.moduleId || previousModule.version !== payload.module.version) {
          prepared.switched = true;
          prepared.channel = await selectModule(payload.module);
        }
        const active = useWorkshopStore.getState().activeModule;
        const channel = prepared.channel;
        assertLiveWorkshopProject(active, channel);
        prepared.token = await channel.prepare({ schemaVersion: payload.schema!, state });
        assertLiveWorkshopProject(active, channel);
        assertRestoreIsCurrent(context);
        return prepared;
      } catch (error) {
        try {
          if (prepared.switched) await restorePrevious(prepared);
        } catch (rollbackError) {
          throw new AggregateError([error, rollbackError], "Project open failed during rollback");
        }
        throw restoreError(error);
      }
    },
    async commitRestore(value, context) {
      assertRestoreIsCurrent(context);
      const prepared = value as PreparedWorkshop;
      if (prepared.token) {
        try {
          const active = useWorkshopStore.getState().activeModule;
          const channel = prepared.channel;
          assertLiveWorkshopProject(active, channel);
          prepared.commitStarted = true;
          await channel.request("commit", prepared.token);
          assertLiveWorkshopProject(active, channel);
        } catch (error) {
          throw restoreError(error);
        }
      } else {
        prepared.commitStarted = true;
        useWorkshopStore.getState().returnHome();
      }
      useWorkshopProjectRuntime.setState({ retained: null, disconnected: null });
    },
    async rollbackRestore(value) {
      const prepared = value as PreparedWorkshop;
      if (prepared.commitStarted || prepared.switched) await restorePrevious(prepared);
    },
    async discardRestore(value) {
      const prepared = value as PreparedWorkshop;
      if (prepared.token) await prepared.channel?.request("discard", prepared.token).catch(() => undefined);
      if (prepared.switched) await restorePrevious(prepared);
    },
  };
}
