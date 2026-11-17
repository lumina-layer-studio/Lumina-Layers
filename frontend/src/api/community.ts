import apiClient from "./client";
import type { ResourceKind } from "./resources";

const config = { headers: { "X-Lumina-Contribution": "1" }, suppressErrorTicket: true };
export interface ResourceReference {
  resource_id: string;
  revision_id: string;
  content_hash: string;
}
export interface ResourceActivity {
  resource_id: string;
  liked: boolean;
  saved: boolean;
  downloaded: boolean;
}
export interface ResourceStats extends ResourceActivity {
  stats_source?: "snapshot";
  snapshot_at?: string;
  likes: number | null;
  saves: number | null;
  downloads: number | null;
  revisions: { revision_id: string; content_hash: string }[];
}
export type PersonalFilter = "all" | "liked" | "saved" | "downloaded";
export const fetchResourceStats = async (kind: ResourceKind, ids: string[]) =>
  (await apiClient.get<{ items: ResourceStats[]; subject: string | null }>(`/community/${kind}/activity`, {
    ...config, params: { resource_id: ids }, paramsSerializer: { indexes: null },
  })).data;
export const fetchMyResourceActivity = async (kind: ResourceKind) =>
  (await apiClient.get<{ items: ResourceActivity[]; subject: string }>(`/community/${kind}/mine`, config)).data;
export const setResourceActivity = async (kind: ResourceKind, resource: ResourceReference,
  action: "liked" | "saved", enabled: boolean, accountId: string) =>
  (await apiClient.put<{ item: ResourceStats; subject: string }>(`/community/${kind}/activity`,
    { ...resource, action, enabled, account_id: accountId }, config)).data;
export const fetchLocalResourceReferences = async (kind: ResourceKind) =>
  (await apiClient.get<{ items: Record<string, ResourceReference> }>(`/community/${kind}/local-references`, config)).data.items;

export interface ResourceContributor { id: string; display_name: string }
export interface ResourceReportImage { image_id: string; width: number; height: number; bytes: number }
export interface ResourceReport extends ResourceReference {
  report_id: string; kind: ResourceKind;
  category: "attribution" | "incorrect_data" | "unsafe_link" | "other";
  message: string; evidence_url: string;
  status: "open" | "resolved" | "dismissed"; decision: string;
  created_at: string; decided_at: string | null;
  images?: ResourceReportImage[];
}
export const fetchResourceContributor = async (kind: ResourceKind, resource: ResourceReference) =>
  (await apiClient.post<{ contributor: ResourceContributor | null }>(`/community/${kind}/contributor`, resource, config)).data;
export const fetchMyResourceReports = async (kind: ResourceKind, resource: ResourceReference) =>
  (await apiClient.post<{ items: ResourceReport[]; subject: string }>(`/community/${kind}/reports/mine`, resource, config)).data;
export const submitResourceReport = async (kind: ResourceKind, resource: ResourceReference, payload: {
  account_id: string; request_id: string; category: ResourceReport["category"]; message: string; evidence_url: string; images?: string[];
}) => (await apiClient.post<{ item: ResourceReport; subject: string }>(`/community/${kind}/reports`, { ...resource, ...payload }, { ...config, suppressClientLog: true })).data;
export const fetchResourceReportHistory = async (offset = 0) =>
  (await apiClient.get<{ items: ResourceReport[]; subject: string; has_more: boolean }>("/community/reports", { ...config, params: { offset } })).data;
export const fetchResourceReportImage = async (reportId: string, imageId: string, accountId: string) =>
  (await apiClient.post<{ data_url: string; subject: string }>(`/community/reports/${encodeURIComponent(reportId)}/image`,
    { image_id: imageId, account_id: accountId }, { ...config, suppressClientLog: true })).data;
