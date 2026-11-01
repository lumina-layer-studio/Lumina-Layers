import axios, { type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import { retryAsync } from "../utils/retryAsync";

function hasBatchCommitIdentity(config: InternalAxiosRequestConfig): boolean {
  if (config.method?.toLowerCase() !== "post" || config.url !== "/convert/replace-colors-batch") return false;
  try {
    const data = typeof config.data === "string" ? JSON.parse(config.data) : config.data;
    return typeof data?.session_id === "string" && data.session_id.trim().length > 0
      && typeof data?.operation_id === "string" && data.operation_id.trim().length > 0;
  } catch {
    return false;
  }
}

function isInterruptedRequest(error: unknown): boolean {
  if (!axios.isAxiosError(error) || axios.isCancel(error)) return false;
  if (error.response) return [502, 503, 504].includes(error.response.status);
  return ["ERR_NETWORK", "ECONNRESET", "ECONNABORTED", "ETIMEDOUT"].includes(error.code ?? "");
}

export function createEditorRetryAdapter(baseAdapter: AxiosAdapter): AxiosAdapter {
  return (config) => {
    if (!hasBatchCommitIdentity(config)) return baseAdapter(config);
    // Preserve the exact body/operation id. The backend rejects duplicate
    // commits before mutation; a 409 uses the store's receipt reconciliation.
    return retryAsync(() => {
      config.cancelToken?.throwIfRequested();
      if (config.signal?.aborted) throw new axios.CanceledError(undefined, config);
      return baseAdapter(config);
    }, { attempts: 2, delayMs: 500, shouldRetry: isInterruptedRequest });
  };
}
