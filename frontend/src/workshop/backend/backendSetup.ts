import type {
  WorkshopBackendApi,
  WorkshopBackendStatus,
  WorkshopBackendTaskResponse,
} from "../../api/workshop";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "interrupted"]);

export class BackendSetupError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(`Workshop backend setup failed: ${code}`);
    this.name = "BackendSetupError";
    this.code = code;
  }
}

export interface WaitOptions {
  intervalMs?: number;
  onProgress?(task: WorkshopBackendTaskResponse): void;
  isCancelled?(): boolean;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

/** Poll one host task until it reaches a terminal state. */
export async function waitForBackendTask(
  api: WorkshopBackendApi,
  moduleId: string,
  taskId: string,
  options: WaitOptions = {},
): Promise<WorkshopBackendTaskResponse> {
  const interval = options.intervalMs ?? 500;
  for (;;) {
    const task = await api.task(moduleId, taskId);
    options.onProgress?.(task);
    if (TERMINAL.has(task.status)) {
      return task;
    }
    if (options.isCancelled?.()) {
      return task;
    }
    await delay(interval);
  }
}

/**
 * Record consent (when needed), then run the cancellable preparation task.
 * Consent is bound by the host to exact package bytes and declaration.
 * 记录授权（如需要）后执行可取消的准备任务；授权由宿主绑定到精确包与声明。
 */
export async function authorizeAndPrepare(
  api: WorkshopBackendApi,
  moduleId: string,
  version: string,
  acknowledgeUnreviewed: boolean,
  options: WaitOptions & { onTask?(taskId: string): void } = {},
): Promise<WorkshopBackendStatus> {
  let status = await api.status(moduleId, version);
  if (status.authorization === "required") {
    status = await api.authorize(moduleId, version, acknowledgeUnreviewed);
  }
  if (status.preparation === "prepared" && status.preparation_task_id === null) {
    return status;
  }
  const task =
    status.preparation_task_id !== null
      ? await api.task(moduleId, status.preparation_task_id)
      : await api.prepare(moduleId, version);
  options.onTask?.(task.task_id);
  const finished = await waitForBackendTask(api, moduleId, task.task_id, options);
  if (finished.status !== "succeeded") {
    throw new BackendSetupError(finished.error?.code ?? finished.status);
  }
  return api.status(moduleId, version);
}

export function backendNeedsSetup(status: WorkshopBackendStatus): boolean {
  return status.authorization === "required" || status.preparation !== "prepared";
}

export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const formatted =
    unit === 0 ? String(Math.round(value)) : value.toFixed(value >= 10 ? 0 : 1);
  return `${formatted} ${units[unit]}`;
}
