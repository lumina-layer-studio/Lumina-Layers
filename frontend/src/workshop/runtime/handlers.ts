import { importGradientCardMaterials } from "../../api/extractor";
import type { GradientCardMaterialBulkImportResponse } from "../../api/types";
import type {
  WorkshopBackendApi,
  WorkshopBackendTaskResponse,
} from "../../api/workshop";
import type {
  WorkshopBackendSubmitRequest,
  WorkshopBackendTask,
  WorkshopImageHandoff,
  WorkshopMaterialImportRequest,
  WorkshopMaterialImportResult,
  WorkshopModuleIdentity,
  WorkshopProjectRecord as SdkWorkshopProjectRecord,
  WorkshopUiState,
} from "../contracts";
import { createBrowserWorkshopFileServices } from "../browserFiles";
import {
  readWorkshopColorLibrary,
  refreshWorkshopMaterialLibrary,
} from "../colorLibrary";
import { handoffWorkshopPayloadToConverter } from "../converterHandoff";
import type { ManagedWorkshopProjectStorage } from "../projectStorage";
import type { WorkshopDiagnosticSummary } from "../types";
import { hasControlCharacter } from "./payloadValidation";
import {
  MATERIAL_IMPORT_OUTCOME_UNKNOWN_MESSAGE,
  WorkshopRpcHandlerError,
  type WorkshopRpcHandler,
  type WorkshopRpcHandlerContext,
  type WorkshopRpcHandlers,
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
  /** Host confirmation for `material.import`; absent hosts reject it. */
  materialImport?: WorkshopMaterialImportServices;
}

/** What the host confirmation dialog shows for one import request. */
export interface WorkshopMaterialImportConfirmation {
  identity: WorkshopModuleIdentity;
  fileName: string;
  sizeBytes: number;
  /** Module-provided and untrusted; shown under its own label. */
  summary: WorkshopMaterialImportRequest["summary"] | null;
}

export interface WorkshopMaterialImportServices {
  /**
   * Ask the user in a host dialog outside the frame. Resolve `false` on
   * Cancel, and also when `signal` aborts (frame closed or request timed out).
   */
  confirm(
    request: WorkshopMaterialImportConfirmation,
    signal: AbortSignal,
  ): Promise<boolean>;
  /** Defaults to the material library page's import client. */
  importArchive?(file: File, signal: AbortSignal): Promise<GradientCardMaterialBulkImportResponse>;
  /** Defaults to reloading the host's saved-material library state. */
  refreshLibrary?(): Promise<void>;
}

const MATERIAL_IMPORT_UNAVAILABLE_MESSAGE =
  "Material import is only available on a local or desktop host.";
const MATERIAL_IMPORT_INVALID_MESSAGE = "The material archive is invalid.";
const MAX_MODULE_ERROR_MESSAGE_LENGTH = 300;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Keep the server's 422 detail only when it is short, plain, and path-free. */
function safeImportDetail(data: unknown): string {
  const detail = isPlainObject(data) ? data.detail : null;
  if (
    typeof detail !== "string" ||
    detail.trim().length === 0 ||
    detail.length > MAX_MODULE_ERROR_MESSAGE_LENGTH ||
    hasControlCharacter(detail) ||
    /(?:^|[\s'"(])(?:[A-Za-z]:[\\/]|[\\/]|~[\\/])/.test(detail)
  ) {
    return MATERIAL_IMPORT_INVALID_MESSAGE;
  }
  return detail.trim();
}

function materialImportError(error: unknown): WorkshopRpcHandlerError {
  const response =
    isPlainObject(error) && isPlainObject(error.response)
      ? error.response
      : null;
  const status = typeof response?.status === "number" ? response.status : null;
  if (status === 422) {
    return new WorkshopRpcHandlerError(
      "material-import-invalid",
      safeImportDetail(response?.data),
    );
  }
  if (status === 403) {
    return new WorkshopRpcHandlerError(
      "material-import-unavailable",
      MATERIAL_IMPORT_UNAVAILABLE_MESSAGE,
    );
  }
  return new WorkshopRpcHandlerError(
    "material-import-failed",
    MATERIAL_IMPORT_OUTCOME_UNKNOWN_MESSAGE,
  );
}

/**
 * `material.import`: the user confirms each call in a host dialog, then the
 * archive goes through the material library's own import endpoint, which
 * validates it and rolls back a failed import. One pending call per module.
 * 每次调用都由用户在宿主对话框确认，再走耗材库原有导入接口（含校验与回滚）。
 */
export function createWorkshopMaterialImportHandler(
  services: WorkshopMaterialImportServices,
): WorkshopRpcHandler {
  const importArchive =
    services.importArchive ??
    ((file: File, signal: AbortSignal) => importGradientCardMaterials([file], { signal }));
  const refreshLibrary =
    services.refreshLibrary ?? refreshWorkshopMaterialLibrary;
  const pendingModules = new Set<string>();
  return async (payload, context): Promise<WorkshopMaterialImportResult> => {
    const request = payload as WorkshopMaterialImportRequest;
    const { moduleId } = context.identity;
    if (pendingModules.has(moduleId)) {
      throw new WorkshopRpcHandlerError(
        "material-import-busy",
        "Another material import from this module is still pending.",
        true,
      );
    }
    pendingModules.add(moduleId);
    try {
      const confirmed = await services.confirm(
        {
          identity: context.identity,
          fileName: request.fileName,
          sizeBytes: request.archiveBytes.byteLength,
          summary: request.summary ?? null,
        },
        context.signal,
      );
      if (!confirmed || context.signal.aborted) {
        return { status: "cancelled" };
      }
      if (!await context.commitMaterialImport?.() || context.signal.aborted) {
        return { status: "cancelled" };
      }
      let response: GradientCardMaterialBulkImportResponse;
      try {
        response = await importArchive(
          new File([request.archiveBytes], request.fileName, {
            type: "application/zip",
          }),
          context.signal,
        );
      } catch (error) {
        throw materialImportError(error);
      }
      // The import already committed. A slow/offline refresh must not turn
      // that known result into a timeout; pages also reload when they open.
      void Promise.resolve().then(refreshLibrary).catch(() => undefined);
      return {
        status: "imported",
        materials: (response.imported_materials ?? [])
          .filter(
            (item) =>
              typeof item.directory_name === "string" &&
              item.directory_name.length > 0,
          )
          .map((item) => ({
            directoryName: item.directory_name,
            name:
              typeof item.material_name === "string"
                ? item.material_name
                : item.directory_name,
          })),
      };
    } finally {
      pendingModules.delete(moduleId);
    }
  };
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
  const progress = task.progress;
  return {
    taskId: task.task_id,
    moduleVersion: task.module_version,
    operation: task.operation,
    status: task.status,
    progress: progress && { completed: progress.completed, total: progress.total, phase: progress.phase },
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

    ...(options.materialImport === undefined
      ? {}
      : {
          "material.import": createWorkshopMaterialImportHandler(
            options.materialImport,
          ),
        }),

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
    // Never touches the host material library. 不触碰宿主耗材库。
    "material.import": (): WorkshopMaterialImportResult => ({
      status: "imported",
      materials: [
        { directoryName: "fixture-material", name: "Fixture material" },
      ],
    }),
    "ui.getState": () => createWorkshopUiState("en-US", "light"),
    "status.progress": () => undefined,
    "status.error": () => undefined,
    "status.diagnostics": () => undefined,
    "lifecycle.ready": () => undefined,
  };
}
