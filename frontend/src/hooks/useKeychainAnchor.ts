import { useEffect, useMemo, useState } from "react";
import { fetchKeychainAnchor } from "../api/converter";
import type { KeychainAnchorRequest } from "../api/types";
import type { PreviewSpacePoint } from "../utils/previewSpace";

export function useKeychainAnchor(
  sessionId: string | null,
  previewUrl: string | null,
  width: number,
  length: number,
  hole: number,
  angle: number,
  preset: string,
): PreviewSpacePoint | null {
  const request = useMemo<KeychainAnchorRequest | null>(() => sessionId && previewUrl ? {
    session_id: sessionId, width, length, hole, angle, preset,
  } : null, [sessionId, previewUrl, width, length, hole, angle, preset]);
  const [result, setResult] = useState<{ request: KeychainAnchorRequest; anchor: PreviewSpacePoint } | null>(null);

  useEffect(() => {
    if (!request) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void fetchKeychainAnchor(request, controller.signal).then((anchor) => {
        if (!controller.signal.aborted) setResult({ request, anchor });
      }).catch(() => {
        // A retired preview session is replaced by a new request. Until a
        // matching result arrives, keep the unsolved ring out of the scene.
      });
    }, 100);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [request]);

  return result?.request === request ? result.anchor : null;
}
