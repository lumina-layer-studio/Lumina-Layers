import apiClient from "./client";

const SESSION_API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";
const closeRequestedSessionIds = new Set<string>();

export function isSessionCloseRequested(sessionId: string): boolean {
  return closeRequestedSessionIds.has(sessionId);
}

function markSessionCloseRequested(sessionId: string): void {
  closeRequestedSessionIds.add(sessionId);
}

/**
 * Renew an active frontend session lease.
 */
export async function heartbeatSession(sessionId: string, signal?: AbortSignal): Promise<void> {
  await apiClient.post(
    "/session/heartbeat",
    { session_id: sessionId },
    { timeout: 15_000, signal, suppressErrorTicket: true },
  );
}

/**
 * Best-effort close for an active frontend session lease.
 */
export async function closeSession(
  sessionId: string,
  keepFileIds: string[] = [],
): Promise<void> {
  markSessionCloseRequested(sessionId);
  await apiClient
    .post(
      "/session/close",
      { session_id: sessionId, keep_file_ids: keepFileIds },
      { timeout: 3_600_000 },
    )
    .catch(() => {
      /* fire-and-forget: ignore close failures */
    });
}

/**
 * Use sendBeacon to close the active session during page unload.
 */
export function beaconCloseSession(
  sessionId: string,
  keepFileIds: string[] = [],
): void {
  markSessionCloseRequested(sessionId);
  const body = JSON.stringify({
    session_id: sessionId,
    keep_file_ids: keepFileIds,
  });
  const beaconUrl = `${SESSION_API_BASE}/session/close`;

  if (
    typeof navigator !== "undefined" &&
    typeof navigator.sendBeacon === "function"
  ) {
    const queued = navigator.sendBeacon(
      beaconUrl,
      new Blob([body], { type: "application/json" }),
    );
    if (queued) {
      markSessionCloseRequested(sessionId);
      return;
    }
  }

  void closeSession(sessionId, keepFileIds);
}
