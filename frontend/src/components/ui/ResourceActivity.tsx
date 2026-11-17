import { useEffect, useState } from "react";
import { HeartIcon, StarIcon, ArrowDownTrayIcon } from "@heroicons/react/24/outline";
import { HeartIcon as HeartFilled, StarIcon as StarFilled } from "@heroicons/react/24/solid";
import type { ResourceKind } from "../../api/resources";
import type { ResourceReference, PersonalFilter } from "../../api/community";
import { useCommunityStore, activityKey } from "../../stores/communityStore";
import { useI18n } from "../../i18n/context";
import { CommunityAccountDialog } from "../CommunityAccount";
import Button from "./Button";
import Dropdown from "./Dropdown";
import { StatusBanner } from "./panelPrimitives";

export function ResourceActivityActions({ kind, resource, favoriteOnly = false }: {
  kind: ResourceKind; resource: ResourceReference; favoriteOnly?: boolean;
}) {
  const { t, lang } = useI18n();
  const key = activityKey(kind, resource.resource_id);
  const cached = useCommunityStore((state) => state.stats[key]);
  const received = cached?.value;
  const stats = received?.revisions.some((row) => row.revision_id === resource.revision_id
    && row.content_hash.replace(/^sha256:/, "") === resource.content_hash.replace(/^sha256:/, "")) ? received : undefined;
  const mine = useCommunityStore((state) => state.mine[kind][resource.resource_id]);
  const pending = useCommunityStore((state) => state.pending[key]);
  const connected = useCommunityStore((state) => state.connection?.state === "connected");
  const unavailable = Boolean(cached && !stats);
  const [accountOpen, setAccountOpen] = useState(false);
  const format = (value: number | null | undefined) => value == null ? "—" : new Intl.NumberFormat(lang, { notation: "compact", maximumFractionDigits: 1 }).format(value);
  const snapshotDate = stats?.snapshot_at ? new Date(stats.snapshot_at) : null;
  const snapshotHint = stats?.stats_source === "snapshot"
    ? `${t("community_snapshot_counts")}${snapshotDate && !Number.isNaN(snapshotDate.getTime()) ? ` · ${snapshotDate.toLocaleString(lang)}` : ""}` : "";
  const action = (field: "liked" | "saved") => {
    if (!connected) setAccountOpen(true);
    else void useCommunityStore.getState().toggle(kind, resource, field);
  };
  const saved = connected && Boolean(stats && (mine?.saved ?? stats.saved));
  const liked = connected && Boolean(stats && (mine?.liked ?? stats.liked));
  const controls = [
    ...(!favoriteOnly ? [{ field: "liked" as const, selected: liked, Icon: liked ? HeartFilled : HeartIcon, count: stats?.likes, label: t(liked ? "community_unlike" : "community_like") }] : []),
    { field: "saved" as const, selected: saved, Icon: saved ? StarFilled : StarIcon, count: stats?.saves, label: t(saved ? "community_unsave" : "community_save") },
  ];
  return <div className="flex min-w-0 flex-wrap items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
    {controls.map(({ field, selected, Icon, count, label }) => <button key={field} type="button"
      aria-label={label} aria-pressed={selected} disabled={pending || (connected && !stats)}
      title={unavailable ? t("community_resource_unavailable") : [label, snapshotHint].filter(Boolean).join(" · ")}
      aria-description={snapshotHint || undefined}
      onClick={(event) => { event.stopPropagation(); action(field); }}
      className={`inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50 ${selected ? "bg-slate-200 text-slate-900 dark:bg-slate-700 dark:text-slate-100" : "hover:bg-slate-200 dark:hover:bg-slate-700"}`}>
      <Icon aria-hidden="true" className="h-4 w-4" />{!favoriteOnly && <span className="tabular-nums">{format(count)}</span>}
    </button>)}
    {!favoriteOnly && <span className="ml-auto inline-flex min-h-9 items-center gap-1.5 px-1" title={[t("community_download_count_hint"), snapshotHint].filter(Boolean).join(" · ")}
      aria-label={`${t("community_downloaders")} ${format(stats?.downloads)}`}>
      <ArrowDownTrayIcon aria-hidden="true" className="h-4 w-4" /><span className="tabular-nums">{format(stats?.downloads)}</span>
    </span>}
    {accountOpen && <CommunityAccountDialog onClose={() => setAccountOpen(false)} />}
  </div>;
}

export function CommunityFilter({ value, onChange }: { value: PersonalFilter; onChange: (value: PersonalFilter) => void }) {
  const { t } = useI18n();
  const connection = useCommunityStore((state) => state.connection);
  const connected = connection?.state === "connected";
  const [open, setOpen] = useState(false);
  const [requested, setRequested] = useState<PersonalFilter | null>(null);
  useEffect(() => { if (connection && !connected && value !== "all") onChange("all"); }, [connection, connected, value, onChange]);
  useEffect(() => {
    if (connected && requested) { onChange(requested); setRequested(null); setOpen(false); }
  }, [connected, requested, onChange]);
  return <>
    <Dropdown label={t("community_filter")} value={value} variant="filter"
      options={(["all", "liked", "saved", "downloaded"] as const).map((key) => ({ value: key, label: t(`community_filter_${key}`) }))}
      onChange={(nextValue) => {
        const next = nextValue as PersonalFilter;
        if (!connected && next !== "all") { setRequested(next); setOpen(true); } else onChange(next);
      }} />
    {open && <CommunityAccountDialog onClose={() => { setRequested(null); setOpen(false); }} />}
  </>;
}

export function CommunityNotice({ kind, ids }: { kind: ResourceKind; ids: string[] }) {
  const { t } = useI18n();
  const error = useCommunityStore((state) => state.error);
  return error ? <StatusBanner tone="warning" action={<Button label={t("resources_retry")} onClick={() => {
    useCommunityStore.setState({ error: "" });
    void useCommunityStore.getState().refreshConnection().then(() => {
      void useCommunityStore.getState().loadStats(kind, ids, true);
      void useCommunityStore.getState().loadMine(kind);
    });
  }} />}>{error}</StatusBanner> : null;
}
