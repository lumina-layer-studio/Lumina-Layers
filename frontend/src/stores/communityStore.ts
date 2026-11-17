import { create } from "zustand";
import { apiErrorToVisibleMessage } from "../api/client";
import { getContributionConnection, startContributionConnection, disconnectContribution, type ContributionConnection } from "../api/contributions";
import { fetchResourceStats, fetchMyResourceActivity, setResourceActivity, fetchLocalResourceReferences,
  type ResourceReference, type ResourceActivity, type ResourceStats } from "../api/community";
import type { ResourceKind } from "../api/resources";
import { tRuntime } from "../i18n/runtime";

export const activityKey = (kind: ResourceKind, id: string) => `${kind}:${id}`;
type CachedStats = { value: ResourceStats | null; time: number };
interface CommunityState {
  connection: ContributionConnection | null;
  epoch: number;
  activityVersion: number;
  stats: Record<string, CachedStats>;
  mine: Record<ResourceKind, Record<string, ResourceActivity>>;
  mineLoaded: Record<ResourceKind, boolean>;
  references: Record<ResourceKind, Record<string, ResourceReference>>;
  pending: Record<string, boolean>;
  error: string;
  connectionError: string;
  resetActivity: () => void;
  acceptConnection: (connection: ContributionConnection) => void;
  refreshConnection: () => Promise<void>;
  start: () => Promise<void>;
  disconnect: () => Promise<void>;
  loadStats: (kind: ResourceKind, ids: string[], force?: boolean) => Promise<void>;
  loadMine: (kind: ResourceKind) => Promise<void>;
  loadReferences: (kind: ResourceKind) => Promise<void>;
  toggle: (kind: ResourceKind, resource: ResourceReference, action: "liked" | "saved") => Promise<void>;
  downloaded: (kind: ResourceKind, id: string, subject: string | undefined, recorded: boolean | null | undefined) => void;
}

let connectionRequest: Promise<void> | null = null;
const statsRequests = new Map<string, Promise<void>>();
const mineRequests = new Map<string, Promise<void>>();
export const useCommunityStore = create<CommunityState>((set, get) => {
  const fail = (error: unknown) => {
    const status = (error as { response?: { status: number } })?.response?.status;
    if (status === 401 && get().connection) {
      get().acceptConnection({ ...get().connection!, state: "disconnected", subject: undefined, display_name: undefined });
    }
    set({ error: apiErrorToVisibleMessage(error, tRuntime("community_failed")) });
  };
  return {
    connection: null, epoch: 0, activityVersion: 0, stats: {}, mine: { materials: {}, luts: {} },
    mineLoaded: { materials: false, luts: false }, references: { materials: {}, luts: {} }, pending: {}, error: "", connectionError: "",
    resetActivity: () => set(state => ({ epoch: state.epoch + 1, stats: {}, pending: {}, error: "", mineLoaded: { materials: false, luts: false } })),
    acceptConnection: (next) => {
      const previous = get().connection;
      const changed = previous?.subject !== next.subject || previous?.web_url !== next.web_url
        || (previous?.state === "connected") !== (next.state === "connected");
      set({ connection: next, ...(changed ? {
        epoch: get().epoch + 1, stats: {}, mine: { materials: {}, luts: {} },
        mineLoaded: { materials: false, luts: false }, pending: {}, error: "",
      } : {}) });
    },
    refreshConnection: () => {
      const epoch = get().epoch;
      if (!connectionRequest) connectionRequest = getContributionConnection()
        .then((value) => {
          if (get().epoch === epoch) {
            const connectionError = get().connectionError;
            get().acceptConnection(value);
            set(state => ({ connectionError: "", ...(connectionError && state.error === connectionError ? { error: "" } : {}) }));
          }
        })
        .catch((error) => {
          if (get().epoch === epoch) {
            fail(error);
            set({ connectionError: apiErrorToVisibleMessage(error, tRuntime("community_failed")) });
          }
        })
        .finally(() => { connectionRequest = null; });
      return connectionRequest;
    },
    start: async () => {
      set({ error: "", connectionError: "", epoch: get().epoch + 1 });
      try { get().acceptConnection(await startContributionConnection()); } catch (error) {
        fail(error); set({ connectionError: apiErrorToVisibleMessage(error, tRuntime("community_failed")) });
      }
    },
    disconnect: async () => {
      set({ error: "", connectionError: "", epoch: get().epoch + 1 });
      try { get().acceptConnection(await disconnectContribution()); } catch (error) {
        fail(error); set({ connectionError: apiErrorToVisibleMessage(error, tRuntime("community_failed")) });
      }
    },
    loadStats: async (kind, ids, force = false) => {
      const epoch = get().epoch;
      const version = get().activityVersion;
      const missing = [...new Set(ids)].filter((id) => force || !get().stats[activityKey(kind, id)]
        || Date.now() - get().stats[activityKey(kind, id)].time > 30_000).sort();
      if (!missing.length) return;
      const requestKey = JSON.stringify([epoch, kind, missing]);
      if (statsRequests.has(requestKey)) return statsRequests.get(requestKey)!;
      const promise = (async () => {
        try {
          const rows: ResourceStats[] = [];
          for (let offset = 0; offset < missing.length; offset += 100) {
            const page = await fetchResourceStats(kind, missing.slice(offset, offset + 100));
            if (get().epoch !== epoch) return;
            if ((get().connection?.subject ?? null) !== page.subject) {
              await get().refreshConnection();
              return;
            }
            rows.push(...page.items);
          }
          if (get().epoch !== epoch) return;
          const byId = new Map(rows.map((row) => [row.resource_id, row]));
          set((state) => {
            const stats = { ...state.stats };
            for (const id of missing) {
              const key = activityKey(kind, id);
              if (get().activityVersion !== version && stats[key]) continue;
              stats[key] = { value: byId.get(id) ?? null, time: Date.now() };
            }
            // Keep the cache bounded and entirely in memory.
            for (const key of Object.keys(stats).slice(0, Math.max(0, Object.keys(stats).length - 1000))) delete stats[key];
            return { stats };
          });
        } catch (error) { if (get().epoch === epoch) fail(error); }
        finally { statsRequests.delete(requestKey); }
      })();
      statsRequests.set(requestKey, promise);
      return promise;
    },
    loadMine: async (kind) => {
      if (get().connection?.state !== "connected") return;
      const epoch = get().epoch;
      const version = get().activityVersion;
      const key = `${epoch}:${kind}`;
      if (mineRequests.has(key)) return mineRequests.get(key)!;
      const promise = fetchMyResourceActivity(kind).then((value) => {
        if (get().epoch !== epoch || get().connection?.subject !== value.subject) return;
        set((state) => ({ mine: { ...state.mine, [kind]: {
          ...Object.fromEntries(value.items.map((row) => [row.resource_id, row])),
          ...(state.activityVersion !== version ? state.mine[kind] : {}),
        } }, mineLoaded: { ...state.mineLoaded, [kind]: true } }));
      }).catch((error) => { if (get().epoch === epoch) fail(error); }).finally(() => { mineRequests.delete(key); });
      mineRequests.set(key, promise);
      return promise;
    },
    loadReferences: async (kind) => {
      try {
        const references = await fetchLocalResourceReferences(kind);
        set((state) => ({ references: { ...state.references, [kind]: references } }));
      } catch (error) { fail(error); }
    },
    toggle: async (kind, resource, action) => {
      const subject = get().connection?.subject;
      if (!subject) return;
      const key = activityKey(kind, resource.resource_id);
      if (get().pending[key]) return;
      const epoch = get().epoch;
      set((state) => ({ pending: { ...state.pending, [key]: true }, error: "" }));
      try {
        if (!get().mineLoaded[kind]) await get().loadMine(kind);
        if (get().epoch !== epoch || !get().mineLoaded[kind]) return;
        const current = get().mine[kind][resource.resource_id];
        const enabled = !current?.[action];
        const result = await setResourceActivity(kind, resource, action, enabled, subject);
        if (get().epoch !== epoch || result.subject !== subject) return;
        set((state) => ({ activityVersion: state.activityVersion + 1, stats: { ...state.stats, [key]: { value: result.item, time: Date.now() } },
          mine: { ...state.mine, [kind]: { ...state.mine[kind], [resource.resource_id]: result.item } } }));
      } catch (error) { if (get().epoch === epoch) fail(error); }
      finally { if (get().epoch === epoch) set((state) => ({ pending: { ...state.pending, [key]: false } })); }
    },
    downloaded: (kind, id, subject, recorded) => {
      if (!subject || get().connection?.subject !== subject) return;
      if (recorded === false) { set({ error: tRuntime("community_download_sync_failed") }); return; }
      if (recorded) { void get().loadMine(kind); void get().loadStats(kind, [id], true); }
    },
  };
});
