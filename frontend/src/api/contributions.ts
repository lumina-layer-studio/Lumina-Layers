import apiClient from "./client";
import type { ResourceKind } from "./resources";

const config = { headers: { "X-Lumina-Contribution": "1" }, suppressErrorTicket: true };
export interface ContributionConnection {
  state: "unavailable" | "disconnected" | "pending" | "connected";
  display_name?: string;
  subject?: string;
  code?: string;
  connect_url?: string;
  web_url: string;
  persistent?: boolean;
  can_remember?: boolean;
  email_verified?: boolean;
  disconnect_incomplete?: boolean;
}
export interface ContributionProduct {
  brand: string; material_type: string; series: string; color_name: string;
  color_code: string; sku: string; purchase_url: string; market: string;
  material_id: string; revision_id: string;
  market_names?: { CN?: string; INTL?: string };
  purchase_links?: { url: string; market: string; label?: string }[];
}
export interface PreparedContribution {
  kind: ResourceKind; key: string; fingerprint: string; bytes: number;
  display: Record<string, unknown> & { filaments?: Record<string, unknown>[] };
  compatibility: Record<string, unknown>;
  origin?: {
    reference: ContributionSourceReference | null;
    modified: boolean; original_author: string; rights_basis: string; license?: string | null;
  } | null;
}
export interface ContributionAttribution {
  relationship: "original" | "adapted" | "redistributed";
  original_author?: string;
  source_url?: string;
  rights_basis?: string;
}
export interface ContributionReceipt {
  kind: ResourceKind; status: string; submission_id?: string; lut_id?: string; material_id?: string;
  revision_id?: string; display?: Record<string, unknown>;
  latest_decision?: { comment?: string };
}
export type PrintImageRole =
  | "white_card"
  | "black_card"
  | "calibration_board"
  | "finished_print";
export interface PrintImageSubmission {
  role: PrintImageRole;
  data: string;
}
export interface OwnedRevision { kind: ResourceKind; resource_id: string; revision_id: string }
export interface ContributionSourceReference extends OwnedRevision { content_hash: string }
export const checkOriginalSource = async (reference: ContributionSourceReference, account_id: string) =>
  (await apiClient.post<{ eligible: boolean }>("/contributions/original-source", { ...reference, account_id }, config)).data;
export const prepareContributionRevision = async (revision: OwnedRevision, account_id: string) =>
  (await apiClient.post<PreparedContribution>("/contributions/prepare-revision", { ...revision, account_id }, config)).data;
export const changeContributionReview = async (revision: OwnedRevision, account_id: string, action: "withdraw" | "submit") =>
  (await apiClient.post<ContributionReceipt>("/contributions/review-action", { ...revision, account_id, action }, config)).data;
export const getContributionConnection = async () =>
  (await apiClient.get<ContributionConnection>("/contributions/connection", config)).data;
export const startContributionConnection = async () =>
  (await apiClient.post<ContributionConnection>("/contributions/connection", {}, config)).data;
export const disconnectContribution = async () =>
  (await apiClient.delete<ContributionConnection>("/contributions/connection", config)).data;
export const prepareContribution = async (kind: ResourceKind, key: string) =>
  (await apiClient.post<PreparedContribution>("/contributions/prepare", { kind, key }, config)).data;
export const prepareQueuedContribution = async (id: string) =>
  (await apiClient.get<PreparedContribution>(`/contributions/queue/${encodeURIComponent(id)}/prepare`, config)).data;
export const fetchContributionHistory = async () =>
  (await apiClient.get<{ items: ContributionReceipt[] }>("/contributions/history", config)).data.items;
export const submitContribution = async (payload: {
  kind: ResourceKind; key: string; fingerprint: string; name: string; description: string;
  product: ContributionProduct; filaments: ContributionProduct[]; consent: true;
  account_id: string;
  attribution: ContributionAttribution;
  queue_id?: string;
  revision?: OwnedRevision;
  updates_resource_id?: string;
  print_images?: (string | PrintImageSubmission)[];
}) => (await apiClient.post<ContributionReceipt>("/contributions/submit", payload, config)).data;

export interface QueuedContribution {
  id: string; account: string; kind: ResourceKind; resource_key: string; name: string;
  state: "queued" | "sending" | "needs_review" | "paused" | "received" | "cancelled";
  reviewed: number; reason: string;
}
export interface ContributionQueueStatus {
  enabled: boolean; account_id: string | null; items: QueuedContribution[];
}
export const getContributionQueue = async () =>
  (await apiClient.get<ContributionQueueStatus>("/contributions/queue", config)).data;
export const configureAutomaticContributions = async (account_id: string, enabled: boolean, consent: boolean) =>
  (await apiClient.put<ContributionQueueStatus>("/contributions/automatic", { account_id, enabled, consent }, config)).data;
export const actOnContributionQueue = async (id: string, action: "retry" | "pause" | "cancel", account_id?: string) =>
  (await apiClient.post<ContributionQueueStatus>(`/contributions/queue/${encodeURIComponent(id)}`, { action, account_id }, config)).data;
