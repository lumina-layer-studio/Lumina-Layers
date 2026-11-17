import { workshopApi } from "../../api/workshop";
import { useWidgetStore } from "../../stores/widgetStore";
import { useWorkshopStore, type ActiveWorkshopModule } from "../../workshop/store";
import type { CurrentWorkshopProject, WorkshopProjectChannel } from "../../workshop/runtime/projectChannel";
import { fileAsset, projectFile } from "../assets";
import { decodeWorkshopState, encodeWorkshopState } from "../workshopState";
import { useWorkshopProjectRuntime, waitForWorkshopProject, type RetainedWorkshopProject } from "../workshopRuntime";
import type { JsonObject, WorkflowDocument } from "../types";
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
}
function validate(document: WorkflowDocument): WorkshopPayload {
  if (document.kind !== "workshop" || document.schemaVersion !== 2) throw new Error("Unsupported Workshop project version");
  const payload = document.payload as unknown as WorkshopPayload;
  if (payload.module === null && payload.state === null && payload.schema === null) return payload;
  if (!payload.module || !/^[a-z0-9][a-z0-9.-]{1,127}$/.test(payload.module.moduleId) || typeof payload.module.version !== "string" || payload.module.version.length > 128 || !payload.schema || typeof payload.state !== "string" || !document.resourceRefs.includes(payload.state)) throw new Error("Invalid Workshop project identity or state");
  return payload;
}
async function selectModule(module: ActiveWorkshopModule): Promise<WorkshopProjectChannel> {
  useWorkshopProjectRuntime.setState({ mounted: true });
  useWorkshopStore.getState().openModule(module.moduleId, module.version);
  return waitForWorkshopProject(module.moduleId, module.version);
}
async function restorePrevious(prepared: PreparedWorkshop) {
  if (prepared.rolledBack) return;
  if (prepared.previousModule && prepared.previousSnapshot) {
    const current = useWorkshopProjectRuntime.getState().current;
    const channel = current?.identity.moduleId === prepared.previousModule.moduleId && current.identity.moduleVersion === prepared.previousModule.version ? current : await selectModule(prepared.previousModule);
    const token = await channel.prepare(prepared.previousSnapshot);
    await channel.request("commit", token);
  } else if (prepared.switched) useWorkshopStore.getState().returnHome();
  useWidgetStore.getState().setActiveTab(prepared.previousTab);
  useWorkshopProjectRuntime.setState({ retained: prepared.previousRetained });
  prepared.rolledBack = true;
}
export function createWorkshopProjectAdapter(): ProjectAdapter {
  return {
    kind: "workshop", validate,
    subscribe: (listener) => useWorkshopProjectRuntime.subscribe((next, previous) => { if (next.change !== previous.change) listener(); }),
    reset: () => { useWorkshopStore.getState().returnHome(); useWorkshopProjectRuntime.setState({ retained: null }); },
    async unavailable(document) {
      if (document.schemaVersion !== 2) return true;
      const payload = validate(document);
      if (!payload.module) return false;
      const modules = await workshopApi.listModules();
      const module = modules.modules.find((item) => item.module_id === payload.module!.moduleId && item.enabled);
      const version = module?.version_details.find((item) => item.version === payload.module!.version);
      return version?.project_snapshot_protocol !== 1 || !version.project_snapshot_schemas?.includes(payload.schema!);
    },
    async capture() {
      const active = useWorkshopStore.getState().activeModule;
      const retained = useWorkshopProjectRuntime.getState().retained;
      const module = active ?? retained?.module ?? null;
      const channel = useWorkshopProjectRuntime.getState().current;
      if (active && (!channel || channel.identity.moduleId !== active.moduleId || channel.identity.moduleVersion !== active.version)) throw new Error("This Workshop module does not support live project snapshots. Install a compatible module version before saving it.");
      const value = active && channel ? await channel.capture() : retained?.value ?? null;
      const encoded = value ? await encodeWorkshopState(value.state) : null;
      const stateAsset = encoded ? await fileAsset("workshop.state", new File([JSON.stringify(encoded.state)], "workshop-state.json", { type: "application/vnd.lumina.workshop-state+json" }), "resource") : null;
      const assets = stateAsset ? [stateAsset, ...encoded!.assets] : [];
      const payload: WorkshopPayload = { module, schema: value?.schemaVersion ?? null, state: stateAsset?.assetId ?? null };
      return { document: { documentId: "workshop.main", kind: "workshop", schemaVersion: 2, payload: payload as unknown as JsonObject, inputRevisionIds: [], resourceRefs: assets.map((asset) => asset.assetId), requiredCapabilities: ["workflow.workshop-v2"] }, assets };
    },
    async prepareRestore(snapshot, context) {
      const document = Object.values(snapshot.documents).find((doc) => doc.kind === "workshop")!;
      const payload = validate(document);
      const previousModule = useWorkshopStore.getState().activeModule;
      const previousChannel = useWorkshopProjectRuntime.getState().current;
      const prepared: PreparedWorkshop = { snapshot, document, previousModule, previousSnapshot: null, previousRetained: useWorkshopProjectRuntime.getState().retained, previousTab: useWidgetStore.getState().activeTab, channel: previousChannel, token: null, switched: false };
      if (previousModule) {
        if (!previousChannel) throw new Error("Close or save the current Workshop editor before opening a project");
        prepared.previousSnapshot = await previousChannel.capture();
      }
      if (!payload.module) return prepared;
      const file = projectFile(snapshot, payload.state)!;
      if (file.size > 128 * 1024 * 1024) throw new Error("Workshop snapshot exceeds its size limit");
      const state = await decodeWorkshopState(JSON.parse(await file.text()), snapshot, document.resourceRefs);
      assertRestoreIsCurrent(context);
      try {
        if (!previousModule || previousModule.moduleId !== payload.module.moduleId || previousModule.version !== payload.module.version) {
          prepared.switched = true;
          prepared.channel = await selectModule(payload.module);
        }
        prepared.token = await prepared.channel!.prepare({ schemaVersion: payload.schema!, state });
        assertRestoreIsCurrent(context);
        return prepared;
      } catch (error) {
        if (prepared.switched) await restorePrevious(prepared);
        throw error;
      }
    },
    async commitRestore(value, context) {
      assertRestoreIsCurrent(context);
      const prepared = value as PreparedWorkshop;
      if (prepared.token) await prepared.channel!.request("commit", prepared.token);
      else useWorkshopStore.getState().returnHome();
      useWorkshopProjectRuntime.setState({ retained: null });
    },
    rollbackRestore: (value) => restorePrevious(value as PreparedWorkshop),
    async discardRestore(value) {
      const prepared = value as PreparedWorkshop;
      if (prepared.token) await prepared.channel?.request("discard", prepared.token).catch(() => undefined);
      if (prepared.switched) await restorePrevious(prepared);
    },
  };
}
