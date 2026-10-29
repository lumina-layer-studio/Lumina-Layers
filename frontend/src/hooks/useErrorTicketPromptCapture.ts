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

export function useErrorTicketPromptCapture(enabled: boolean): void {
  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    const { reportClientError } = useErrorTicketPromptStore.getState();

    const handleError = (event: ErrorEvent) => {
      if (isHandledSceneError(event.error)) return;
      reportClientError(describeThrownValue(event.error, event.message ?? ""));
    };
    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
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
