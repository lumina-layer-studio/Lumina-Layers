/**
 * Listen for uncaught frontend errors and forward them to the error ticket
 * prompt store. API failures are reported separately from `api/client.ts`.
 * 监听前端未捕获异常并转交给错误工单提示 Store；接口错误由 `api/client.ts` 单独上报。
 */

import { useEffect } from "react";

import { useErrorTicketPromptStore } from "../stores/errorTicketPromptStore";
import { isHandledSceneError } from "../utils/handledSceneErrors";

/**
 * Extract a short, human-readable message from an unknown thrown value.
 * 从任意抛出值中提取简短可读的错误信息。
 */
export function describeThrownValue(value: unknown, fallback = ""): string {
  if (value instanceof Error) {
    return value.message || value.name || fallback;
  }
  if (typeof value === "string") {
    return value;
  }
  return fallback;
}

function isInlineDocumentFetchFailure(error: unknown): boolean {
  if (!(error instanceof TypeError) || error.message !== "Failed to fetch") return false;

  // Lumina runs as modules. A Fetch failure from an inline page script stays
  // in the global diagnostic log.
  const firstFrame = error.stack?.split("\n", 2)[1]?.trim();
  const source = firstFrame?.match(/^at (?:.+? \()?(.+?):\d+:\d+\)?$/)?.[1];
  return source === window.location.href;
}

export function useErrorTicketPromptCapture(enabled: boolean): void {
  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    const { reportClientError } = useErrorTicketPromptStore.getState();

    const handleError = (event: ErrorEvent) => {
      if (isHandledSceneError(event.error)) return;
      reportClientError(describeThrownValue(event.error, event.message ?? ""));
    };
    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
      if (isInlineDocumentFetchFailure(event.reason)) return;
      reportClientError(describeThrownValue(event.reason));
    };

    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleUnhandledRejection);
    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleUnhandledRejection);
    };
  }, [enabled]);
}
