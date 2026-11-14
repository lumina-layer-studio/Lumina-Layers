import { useEffect, useRef } from "react";

import {
  beaconCloseSession,
  closeSession,
  heartbeatSession,
  isSessionCloseRequested,
} from "../api/session";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import type { Workstream } from "../types/actionHistory";

const HEARTBEAT_INTERVAL_MS = 2 * 60 * 1000;
const HEARTBEAT_RETRY_MS = 10_000;
const SESSION_CLOSE_DELAY_MS = 30_000;
const EMPTY_KEEP_FILE_IDS: readonly string[] = [];
const pendingSessionCloseTimers = new Map<string, number>();
const activeSessionLeases = new Map<string, number>();
const leaseFileRefs = new Map<string, Set<{ current: string[] }>>();
const releasedKeepFileIds = new Map<string, Set<string>>();
function retainedFileIds(sessionId: string, extra: readonly string[] = []): string[] {
  return [...new Set([...extra, ...(releasedKeepFileIds.get(sessionId) ?? []),
    ...[...(leaseFileRefs.get(sessionId) ?? [])].flatMap(ref => ref.current)])];
}

function cancelPendingSessionClose(sessionId: string): void {
  const pendingTimer = pendingSessionCloseTimers.get(sessionId);
  if (pendingTimer === undefined) {
    return;
  }

  window.clearTimeout(pendingTimer);
  pendingSessionCloseTimers.delete(sessionId);
}

function normalizeKeepFileIds(keepFileIds: readonly string[]): string[] {
  return Array.from(new Set(keepFileIds));
}

function isMissingSessionHeartbeat(error: unknown): boolean {
  if (typeof error !== "object" || error === null) {
    return false;
  }
  const response = (error as { response?: { status?: unknown } }).response;
  return response?.status === 404;
}

function isTransientHeartbeatFailure(error: unknown): boolean {
  const status = (error as { response?: { status?: number } } | null)?.response?.status;
  return status == null || status === 408 || status === 429 || status >= 500;
}

function scheduleSessionClose(
  sessionId: string,
  keepFileIds: readonly string[] = EMPTY_KEEP_FILE_IDS,
): void {
  cancelPendingSessionClose(sessionId);
  if (activeSessionLeases.has(sessionId)) return;
  if (isSessionCloseRequested(sessionId)) {
    return;
  }
  const keepFileIdsSnapshot = retainedFileIds(sessionId, keepFileIds);
  const timerId = window.setTimeout(() => {
    pendingSessionCloseTimers.delete(sessionId);
    if (isSessionCloseRequested(sessionId)) {
      return;
    }
    void closeSession(sessionId, keepFileIdsSnapshot);
    releasedKeepFileIds.delete(sessionId);
  }, SESSION_CLOSE_DELAY_MS);
  pendingSessionCloseTimers.set(sessionId, timerId);
}

export function useSessionLease(
  sessionId: string | null | undefined,
  workstream: Workstream | null = "converter",
  keepFileIds: readonly string[] = EMPTY_KEEP_FILE_IDS,
  onExpired?: (sessionId: string) => void,
): void {
  const keepFileIdsRef = useRef<string[]>([]);
  keepFileIdsRef.current = normalizeKeepFileIds(keepFileIds);
  const onExpiredRef = useRef(onExpired);
  onExpiredRef.current = onExpired;

  useEffect(() => {
    if (!sessionId) {
      return;
    }

    cancelPendingSessionClose(sessionId);
    activeSessionLeases.set(sessionId, (activeSessionLeases.get(sessionId) ?? 0) + 1);
    const refs = leaseFileRefs.get(sessionId) ?? new Set();
    refs.add(keepFileIdsRef); leaseFileRefs.set(sessionId, refs);

    // Record this session id into the action-history session ring so the
    // bug-report bundle can reference recent sessions even after the source
    // session has been cleaned up on the backend.
    // TODO(task 1.4): callers in App.tsx should pass an explicit workstream
    // argument ('converter' vs 'single_stage') so the ring is accurately
    // labelled; this wiring only provides the plumbing.
    // 把会话 id 登记到操作历史的会话环中，便于反馈复现包在后端 session 已清理
    // 后仍能追溯近期会话。工作流分类的精细化由后续任务 1.4 处理。
    if (workstream) useActionHistoryStore.getState().observeSession(workstream, sessionId);

    const controller = new AbortController();
    let retryPending = false;
    let renewing = false;
    let expired = false;
    let timerId: number;
    const renew = async (): Promise<void> => {
      if (controller.signal.aborted || renewing || expired) return;
      window.clearTimeout(timerId);
      renewing = true;
      let nextDelay = HEARTBEAT_INTERVAL_MS;
      try {
        await heartbeatSession(sessionId, controller.signal);
        retryPending = false;
      } catch (error: unknown) {
        if (isMissingSessionHeartbeat(error)) {
          expired = true;
          if (!controller.signal.aborted) onExpiredRef.current?.(sessionId);
          return;
        }
        // One prompt retry per cycle; prolonged outages keep the normal cadence.
        if (!retryPending && isTransientHeartbeatFailure(error)) {
          retryPending = true;
          nextDelay = HEARTBEAT_RETRY_MS;
        } else {
          retryPending = false;
        }
      } finally {
        renewing = false;
      }
      if (!controller.signal.aborted) {
        timerId = window.setTimeout(() => void renew(), nextDelay);
      }
    };
    timerId = window.setTimeout(() => void renew(), HEARTBEAT_INTERVAL_MS);
    const renewOnResume = (): void => {
      if (document.visibilityState === "visible") void renew();
    };

    const handleBeforeUnload = () => {
      if (isSessionCloseRequested(sessionId)) {
        return;
      }
      beaconCloseSession(sessionId, retainedFileIds(sessionId));
    };

    window.addEventListener("pagehide", handleBeforeUnload);
    window.addEventListener("focus", renewOnResume);
    window.addEventListener("online", renewOnResume);
    document.addEventListener("visibilitychange", renewOnResume);

    return () => {
      controller.abort();
      window.clearTimeout(timerId);
      window.removeEventListener("pagehide", handleBeforeUnload);
      window.removeEventListener("focus", renewOnResume);
      window.removeEventListener("online", renewOnResume);
      document.removeEventListener("visibilitychange", renewOnResume);
      if (!expired) releasedKeepFileIds.set(sessionId, new Set(retainedFileIds(sessionId, keepFileIdsRef.current)));
      refs.delete(keepFileIdsRef);
      if (!refs.size) leaseFileRefs.delete(sessionId);
      const remaining = (activeSessionLeases.get(sessionId) ?? 1) - 1;
      if (remaining > 0) activeSessionLeases.set(sessionId, remaining);
      else activeSessionLeases.delete(sessionId);
      if (!expired) scheduleSessionClose(sessionId, keepFileIdsRef.current);
      else if (!remaining) releasedKeepFileIds.delete(sessionId);
    };
  }, [sessionId, workstream]);
}
