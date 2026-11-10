import type {
  WorkshopBackendApi,
  WorkshopBackendTaskResponse,
} from "../../api/workshop";
import type {
  WorkshopBackendSubmitRequest,
  WorkshopBackendTask,
  WorkshopImageHandoff,
  WorkshopProjectRecord as SdkWorkshopProjectRecord,
  WorkshopUiState,
} from "../contracts";
import { createBrowserWorkshopFileServices } from "../browserFiles";
import { readWorkshopColorLibrary } from "../colorLibrary";
import { handoffWorkshopPayloadToConverter } from "../converterHandoff";
import type { ManagedWorkshopProjectStorage } from "../projectStorage";
import type { WorkshopDiagnosticSummary } from "../types";
import type {
  WorkshopRpcHandlerContext,
  WorkshopRpcHandlers,
} from "./rpcHost";

const MAX_PICKED_IMAGE_BYTES = 64 * 1024 * 1024;
const MAX_PICKED_IMAGE_EDGE = 16_384;
const MAX_PICKED_IMAGE_PIXELS = 64_000_000;

interface CreateManagerHandlersOptions {
  storage: ManagedWorkshopProjectStorage;
  locale(): "zh-CN" | "en-US";
  theme(): "light" | "dark";
  onDiagnostics(summary: WorkshopDiagnosticSummary | null): void;
  /** Host-owned backend task API; absent hosts reject backend methods. */
  backend?: WorkshopBackendApi;
}

interface BackendTaskIdPayload {
  taskId: string;
}

interface BackendOutputPayload {
  taskId: string;
  name: string;
}

/** Map one host task to the public RPC shape (camelCase, no paths). */
export function publicBackendTask(
  task: WorkshopBackendTaskResponse,
): WorkshopBackendTask {
  return {
    taskId: task.task_id,
    moduleVersion: task.module_version,
    operation: task.operation,
    status: task.status,
    progress: task.progress,
    error: task.error,
    outputs: task.outputs.map((output) => ({
      name: output.name,
      fileName: output.file_name,
      mimeType: output.mime_type,
      bytes: output.size_bytes,
    })),
    variant: task.variant,
    createdAt: task.created_at,
    updatedAt: task.updated_at,
    finishedAt: task.finished_at,
  };
}

/**
 * Backend RPC handlers. Tasks belong to the host: closing the frame aborts
 * only the frame's waits, never a submitted task, so these handlers ignore
 * the request abort signal and never call cancel on their own.
 * 后端任务归宿主所有：关闭模块页面只结束前端等待，不会取消已提交的任务。
 */
export function createWorkshopBackendHandlers(
  backend: WorkshopBackendApi,
): WorkshopRpcHandlers {
  const operationTask = async (
    context: WorkshopRpcHandlerContext,
    taskId: string,
  ): Promise<WorkshopBackendTaskResponse> => {
    const task = await backend.task(context.identity.moduleId, taskId);
    if (task.kind !== "operation") {
      throw new Error("Workshop backend task is not available to modules.");
    }
    return task;
  };
  return {
    "backend.status": async (_payload, context) => {
      const status = await backend.status(
        context.identity.moduleId,
        context.identity.moduleVersion,
      );
      return {
        prepared: status.preparation === "prepared",
        authorized: status.authorization !== "required",
        state: status.runtime.state,
        acceleration: status.acceleration,
        variant: status.runtime.variant,
      };
    },
    "backend.submit": async (payload, context) => {
      const request = payload as WorkshopBackendSubmitRequest;
      return publicBackendTask(
        await backend.submit(
          context.identity.moduleId,
          context.identity.moduleVersion,
          request,
        ),
      );
    },
    "backend.get": async (payload, context) =>
      publicBackendTask(
        await operationTask(context, (payload as BackendTaskIdPayload).taskId),
      ),
    "backend.list": async (_payload, context) =>
      (await backend.tasks(context.identity.moduleId))
        .filter((task) => task.kind === "operation")
        .slice(0, 100)
        .map(publicBackendTask),
    "backend.cancel": async (payload, context) => {
      const { taskId } = payload as BackendTaskIdPayload;
      await operationTask(context, taskId);
      return publicBackendTask(
        await backend.cancel(context.identity.moduleId, taskId),
      );
    },
    "backend.readOutput": async (payload, context) => {
      const { taskId, name } = payload as BackendOutputPayload;
      const task = await operationTask(context, taskId);
      const output = task.outputs.find((item) => item.name === name);
      if (output === undefined) {
        throw new Error("Workshop backend output does not exist.");
      }
      return {
        name: output.name,
        fileName: output.file_name,
        mimeType: output.mime_type,
        bytes: await backend.output(context.identity.moduleId, taskId, name),
      };
    },
    "backend.remove": async (payload, context) => {
      const { taskId } = payload as BackendTaskIdPayload;
      await operationTask(context, taskId);
      await backend.remove(context.identity.moduleId, taskId);
    },
  };
}

interface ProjectSavePayload {
  record: SdkWorkshopProjectRecord<unknown>;
}

interface ProjectIdPayload {
  projectId: string;
}

export function createWorkshopUiState(
  locale: "zh-CN" | "en-US",
  theme: "light" | "dark",
): WorkshopUiState {
  return {
    locale,
    theme,
    tokens: {
      "--lumina-surface": theme === "dark" ? "#111827" : "#ffffff",
      "--lumina-surface-muted":
        theme === "dark" ? "#1f2937" : "#f5f5f7",
      "--lumina-text": theme === "dark" ? "#f8fafc" : "#1d1d1f",
      "--lumina-text-muted":
        theme === "dark" ? "#cbd5e1" : "#6e6e73",
      "--lumina-accent": "#0071e3",
      "--lumina-border": theme === "dark" ? "#475569" : "#d2d2d7",
    },
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value as Record<string, unknown>;
}

function publicProjectRecord<T>(
  value: {
    projectId: string;
    schemaVersion: string;
    createdAt: string;
    updatedAt: string;
    project: T;
  } | null,
): SdkWorkshopProjectRecord<T> | null {
  if (value === null) {
    return null;
  }
  return {
    projectId: value.projectId,
    schemaVersion: value.schemaVersion,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
    project: value.project,
  };
}

function diagnosticValue(
  payload: Record<string, unknown>,
  key: string,
): string | number | null {
  const value = payload[key];
  return typeof value === "string" || typeof value === "number"
    ? value
    : null;
}

function diagnosticSummary(
  payload: unknown,
): WorkshopDiagnosticSummary {
  const value = asRecord(payload);
  return {
    projectSchemaVersion:
      (diagnosticValue(value, "projectSchemaVersion") as string | null) ??
      (diagnosticValue(value, "project_schema_version") as
        | string
        | null) ??
      "unknown",
    inputMode:
      (diagnosticValue(value, "inputMode") as string | null) ??
      (diagnosticValue(value, "input_mode") as string | null),
    rows:
      (diagnosticValue(value, "rows") as number | null),
    columns:
      (diagnosticValue(value, "columns") as number | null),
    compression:
      (diagnosticValue(value, "compression") as number | null),
    errorCode:
      (diagnosticValue(value, "errorCode") as string | null) ??
      (diagnosticValue(value, "error_code") as string | null),
  };
}

function moduleProjectRecord(
  context: WorkshopRpcHandlerContext,
  record: SdkWorkshopProjectRecord<unknown>,
) {
  return {
    moduleId: context.identity.moduleId,
    ...record,
  };
}

export function createWorkshopManagerHandlers(
  options: CreateManagerHandlersOptions,
): WorkshopRpcHandlers {
  const files = createBrowserWorkshopFileServices();
  let pendingReplacement:
    | { moduleId: string; projectId: string }
    | null = null;

  return {
    "image.pick": async () => {
      const selected = await files.pickImage();
      if (selected === null) {
        return null;
      }
      const bytes = await selected.file.arrayBuffer();
      const { width, height } = selected.raster;
      if (
        bytes.byteLength === 0 ||
        bytes.byteLength > MAX_PICKED_IMAGE_BYTES ||
        width > MAX_PICKED_IMAGE_EDGE ||
        height > MAX_PICKED_IMAGE_EDGE ||
        width * height > MAX_PICKED_IMAGE_PIXELS
      ) {
        throw new Error("Selected Workshop image exceeds its limits.");
      }
      return {
        name: selected.file.name,
        mimeType: selected.file.type,
        bytes,
        raster: selected.raster,
      };
    },

    "project.save": async (payload, context) => {
      const { record } = payload as ProjectSavePayload;
      await options.storage.save(
        moduleProjectRecord(context, record),
      );
    },

    "project.load": async (payload, context) => {
      const { projectId } = payload as ProjectIdPayload;
      return publicProjectRecord(
        await options.storage.load(
          context.identity.moduleId,
          projectId,
        ),
      );
    },

    "project.latest": async (_payload, context) =>
      publicProjectRecord(
        await options.storage.latest(context.identity.moduleId),
      ),

    "project.remove": async (payload, context) => {
      const { projectId } = payload as ProjectIdPayload;
      await options.storage.remove(
        context.identity.moduleId,
        projectId,
      );
    },

    "colorLibrary.read": (_payload, context) =>
      readWorkshopColorLibrary({ signal: context.signal }),

    "handoff.image": async (payload, context) => {
      const handoff = payload as WorkshopImageHandoff;
      const isConfirmedRetry =
        pendingReplacement?.moduleId === context.identity.moduleId &&
        pendingReplacement.projectId === handoff.projectId;
      const result = await handoffWorkshopPayloadToConverter(handoff, {
        replaceExisting: isConfirmedRetry,
      });
      pendingReplacement =
        result.status === "needs-confirmation"
          ? {
              moduleId: context.identity.moduleId,
              projectId: handoff.projectId,
            }
          : null;
      return result;
    },

    "ui.getState": () =>
      createWorkshopUiState(options.locale(), options.theme()),

    "status.progress": () => undefined,

    "status.error": (payload) => {
      if (payload === null) {
        options.onDiagnostics(null);
        return;
      }
      const value = asRecord(payload);
      options.onDiagnostics({
        projectSchemaVersion: "unknown",
        inputMode: null,
        rows: null,
        columns: null,
        compression: null,
        errorCode:
          typeof value.code === "string" ? value.code : "module-error",
      });
    },

    "status.diagnostics": (payload) => {
      options.onDiagnostics(diagnosticSummary(payload));
    },

    "lifecycle.ready": () => undefined,

    ...(options.backend === undefined
      ? {}
      : createWorkshopBackendHandlers(options.backend)),
  };
}

const SYNTHETIC_PNG = new Uint8Array([
  137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68,
  82, 0, 0, 0, 1, 0, 0, 0, 1, 8, 4, 0, 0, 0, 181, 28, 12,
  2, 0, 0, 0, 11, 73, 68, 65, 84, 120, 218, 99, 96, 254, 15,
  0, 2, 3, 1, 128, 173, 242, 83, 135, 0, 0, 0, 0, 73, 69,
  78, 68, 174, 66, 96, 130,
]);

/**
 * Return isolated fixture-only handlers for explicit browser development.
 * These handlers never read host images, stores, projects, or color choices.
 */
export function createSyntheticWorkshopHandlers(): WorkshopRpcHandlers {
  const projects = new Map<
    string,
    SdkWorkshopProjectRecord<unknown>
  >();
  const key = (
    context: WorkshopRpcHandlerContext,
    projectId: string,
  ) => `${context.identity.moduleId}:${projectId}`;

  return {
    "image.pick": () => ({
      name: "synthetic-workshop-fixture.png",
      mimeType: "image/png",
      bytes: SYNTHETIC_PNG.slice().buffer,
      raster: {
        width: 1,
        height: 1,
        data: new Uint8ClampedArray([0, 113, 227, 255]),
      },
    }),
    "project.save": (payload, context) => {
      const { record } = payload as ProjectSavePayload;
      projects.set(key(context, record.projectId), structuredClone(record));
    },
    "project.load": (payload, context) => {
      const { projectId } = payload as ProjectIdPayload;
      return (
        structuredClone(projects.get(key(context, projectId))) ?? null
      );
    },
    "project.latest": (_payload, context) => {
      const prefix = `${context.identity.moduleId}:`;
      const records = [...projects.entries()]
        .filter(([recordKey]) => recordKey.startsWith(prefix))
        .map(([, record]) => record)
        .sort((left, right) =>
          right.updatedAt.localeCompare(left.updatedAt),
        );
      return structuredClone(records[0] ?? null);
    },
    "project.remove": (payload, context) => {
      const { projectId } = payload as ProjectIdPayload;
      projects.delete(key(context, projectId));
    },
    "colorLibrary.read": () => ({
      id: "fixture:synthetic",
      label: "Synthetic Workshop fixture",
      sourceKind: "lut",
      colors: [
        {
          id: "fixture-blue",
          label: "Fixture blue",
          hex: "#0071E3",
          materialId: null,
        },
      ],
    }),
    "handoff.image": () => ({ status: "completed" }),
    "ui.getState": () => createWorkshopUiState("en-US", "light"),
    "status.progress": () => undefined,
    "status.error": () => undefined,
    "status.diagnostics": () => undefined,
    "lifecycle.ready": () => undefined,
  };
}
