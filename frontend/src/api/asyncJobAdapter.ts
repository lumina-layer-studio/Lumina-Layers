/**
 * Axios adapter that survives reverse-proxy timeouts on long requests.
 * 让耗时请求在反向代理（Lucky、nginx、Cloudflare 等）后面也不会 504。
 *
 * Write requests carry `X-Lumina-Async: 1`. The backend answers normally if
 * the work finishes within ~10 s; otherwise it replies 202 with a job id and
 * this adapter polls `GET /jobs/{id}` (each poll is held open ≤10 s) until the
 * original response is available. The caller, interceptors and error handling
 * see one ordinary response, exactly as if the request had been synchronous.
 */
import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";

export const ASYNC_REQUEST_HEADER = "X-Lumina-Async";
const ASYNC_METHODS = new Set(["post", "put", "patch", "delete"]);
const MAX_CONSECUTIVE_POLL_FAILURES = 5;

function sleep(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener?.("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }
    signal?.addEventListener?.("abort", onAbort, { once: true });
  });
}

function wantsAsync(config: InternalAxiosRequestConfig): boolean {
  const method = (config.method ?? "get").toLowerCase();
  if (!ASYNC_METHODS.has(method)) return false;
  if (config.url?.includes("/jobs/")) return false;
  return config.responseType !== "stream";
}

function jobIdFrom(response: AxiosResponse): string | null {
  if (response.status !== 202) return null;
  const header = response.headers?.["x-lumina-job"];
  if (typeof header === "string" && header) return header;
  // The JSON body also carries it (cross-origin callers cannot read the header).
  let data: unknown = response.data;
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      return null;
    }
  }
  if (data && typeof data === "object" && "job_id" in data) {
    const id = (data as { job_id?: unknown }).job_id;
    if (typeof id === "string" && id) return id;
  }
  return null;
}

function jobConfig(
  config: InternalAxiosRequestConfig,
  jobId: string,
  method: "get" | "delete",
): InternalAxiosRequestConfig {
  return {
    ...config,
    method,
    url: `/jobs/${encodeURIComponent(jobId)}`,
    data: undefined,
    params: undefined,
    headers: new AxiosHeaders({ Accept: "application/json, text/plain, */*" }),
    onUploadProgress: undefined,
    onDownloadProgress: method === "get" ? config.onDownloadProgress : undefined,
    timeout: 60_000,
    validateStatus: () => true,
  };
}

function isCancel(error: unknown): boolean {
  return (
    axios.isCancel(error) ||
    (error instanceof DOMException && error.name === "AbortError") ||
    (error as { code?: string } | null)?.code === "ERR_CANCELED"
  );
}

/** Settle like axios would for the *original* request config. */
function settle(
  config: InternalAxiosRequestConfig,
  response: AxiosResponse,
): AxiosResponse {
  const finalResponse: AxiosResponse = { ...response, config };
  const validate = config.validateStatus;
  if (!validate || validate(finalResponse.status)) return finalResponse;
  throw new AxiosError(
    `Request failed with status code ${finalResponse.status}`,
    finalResponse.status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST,
    config,
    finalResponse.request,
    finalResponse,
  );
}

export function createAsyncJobAdapter(baseAdapter: AxiosAdapter): AxiosAdapter {
  return async (config) => {
    if (!wantsAsync(config)) return baseAdapter(config);

    config.headers.set(ASYNC_REQUEST_HEADER, "1");
    const first = await baseAdapter({ ...config, validateStatus: () => true });
    const jobId = jobIdFrom(first);
    if (jobId === null) return settle(config, first);

    const signal = config.signal as AbortSignal | undefined;
    const cancelJob = () => {
      void baseAdapter(jobConfig(config, jobId, "delete")).catch(() => undefined);
    };
    let failures = 0;
    for (;;) {
      if (signal?.aborted) {
        cancelJob();
        throw new axios.CanceledError(undefined, undefined, config);
      }
      let poll: AxiosResponse;
      try {
        poll = await baseAdapter(jobConfig(config, jobId, "get"));
      } catch (error) {
        if (isCancel(error) || signal?.aborted) {
          cancelJob();
          throw new axios.CanceledError(undefined, undefined, config);
        }
        // A dropped poll (Wi-Fi blip, proxy restart) is retried; the job keeps running.
        failures += 1;
        if (failures >= MAX_CONSECUTIVE_POLL_FAILURES) throw error;
        try {
          await sleep(1_000 * failures, signal);
        } catch {
          cancelJob();
          throw new axios.CanceledError(undefined, undefined, config);
        }
        continue;
      }
      if (poll.status === 202 && jobIdFrom(poll) === jobId) {
        failures = 0;
        continue; // still running; the server already held this poll open
      }
      if (poll.status >= 502 && poll.status <= 504) {
        // Proxy hiccup on the poll itself; try again.
        failures += 1;
        if (failures >= MAX_CONSECUTIVE_POLL_FAILURES) return settle(config, poll);
        await sleep(1_000 * failures, signal).catch(() => undefined);
        continue;
      }
      return settle(config, poll);
    }
  };
}
