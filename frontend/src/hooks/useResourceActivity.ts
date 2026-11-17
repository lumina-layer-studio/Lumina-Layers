import { useEffect } from "react";
import type { ResourceKind } from "../api/resources";
import { useCommunityStore } from "../stores/communityStore";

export function useResourceActivity(kind: ResourceKind, ids: string[], enabled = true) {
  const epoch = useCommunityStore((state) => state.epoch);
  const subject = useCommunityStore((state) => state.connection?.subject);
  const idKey = JSON.stringify([...new Set(ids)].sort());
  useEffect(() => {
    if (!enabled) return;
    const refresh = () => { void useCommunityStore.getState().refreshConnection().then(() => {
      void useCommunityStore.getState().loadMine(kind);
      void useCommunityStore.getState().loadStats(kind, JSON.parse(idKey));
    }); };
    void useCommunityStore.getState().refreshConnection();
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [enabled, kind, idKey]);
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setTimeout(() => { void useCommunityStore.getState().loadStats(kind, JSON.parse(idKey)); }, 140);
    return () => window.clearTimeout(timer);
  }, [enabled, kind, idKey, epoch]);
  useEffect(() => { if (enabled && subject) void useCommunityStore.getState().loadMine(kind); }, [enabled, kind, subject, epoch]);
}
