import apiClient from "./client";
import type {
  ActionEntry,
  AdvancedParams,
  SessionRingEntry,
} from "../types/actionHistory";
import type { ClientLogEntry } from "../utils/clientLog";

export interface FinalArtifactRef {
  session_id: string | null;
  /** Backend-provided download URL (often ``/api/files/<file_id>``). */
  download_url: string | null;
  /** Artifact classification, best-effort. */
  artifact_type: "3mf" | "zip" | "share_card" | null;
  /** Legacy clients may still send this; new payloads should omit it. */
  disk_path?: string | null;
  /** Which workstream originated the artifact. */
  source: "converter" | "single_stage" | "puzzle" | "vector" | "batch" | null;
}

export interface OriginalImageRef {
  session_id: string | null;
  /** Best-known filename shown to the user when they uploaded the image. */
  filename: string | null;
  source: "converter" | "single_stage" | null;
}

export interface WorkshopBugReportContext {
  module_id: string;
  module_version: string;
  install_source: "registry" | "github" | "local" | "seed" | "unknown";
  audit_status:
    | "official"
    | "verified"
    | "deprecated"
    | "blocked"
    | "unreviewed"
    | "unknown";
  runtime_mode:
    | "desktop-secure"
    | "browser-restricted"
    | "unsafe-development";
  error_code: string | null;
}

export interface BugReportContextPayload {
  url: string;
  user_agent: string;
  screen_width: number;
  screen_height: number;
  device_pixel_ratio: number;
  app_version: string;
  language: "zh" | "en";
  theme: "light" | "dark";
  active_tab: string;
  active_session_ids: {
    converter: string | null;
    single_stage: string | null;
    extractor?: string | null;
  };
  printer_id?: string;
  slicer?: string;
  nozzle_size?: string;
  device_profile_id?: string;
  build_plate_id?: string;
  external_spool_material?: string;
  custom_3mf_template_id?: string | null;
  color_mode: string | null;
  lut_name: string | null;
  lut_names?: string[];
  source_version: "legacy" | "native" | "material" | null;
  selected_native_brand_key: string | null;
  selected_native_db_names: string[];
  selected_material_dir_names: string[];
  material_layer_count: number | null;
  material_dynamic_layer_count_enabled?: boolean | null;
  material_min_layer_count?: number | null;
  material_max_layer_count?: number | null;
  material_delta_e00_tolerance?: number | null;
  material_layer_height_mm: number | null;
  material_backing_material_dir_name: string | null;
  /** Client-local preference used to name ordinary single-item 3MF downloads. */
  preserve_upload_filename_for_3mf?: boolean;
  /** 3MF export preference controlling automatic model/tower layout. */
  enable_wipe_tower_auto_placement?: boolean;
  /** Personal browser preference; never part of print or share-card state. */
  enable_smooth_vector_preview?: boolean;
  /** Lightweight renderer selected for the active native SVG session. */
  vector_preview_renderer?: "vector_analytic" | "segmented" | null;
  recent_client_logs: ReadonlyArray<ClientLogEntry>;
  /**
   * Recent user actions with workflow snapshots; populated by the
   * reproducible-bug-reports pipeline (Req 5.x). Backwards compatible:
   * omitting the field is legal for older clients.
   */
  action_history?: ReadonlyArray<ActionEntry>;
  /**
   * Recent session ids seen by the frontend (Req 6.x). Lets developers grep
   * structured server logs even after the live sessions were cleaned up.
   */
  session_history?: ReadonlyArray<SessionRingEntry>;
  /**
   * JSON-only reference to the user's original image (Req 2.x). Exact bytes
   * may travel separately as multipart; ``session_id`` remains the fallback.
   */
  active_original_image_ref?: OriginalImageRef | null;
  /**
   * Reference to the most recent generation artifact (Req 3.x). No file
   * bytes; the backend resolves the artifact through FileRegistry.
   */
  active_final_artifact_ref?: FinalArtifactRef | null;
  /**
   * Advanced generation parameters grouped by feature (Req 3.1). Present
   * only when the active tab is "converter"; ``null`` otherwise. Optional
   * for backward compatibility with clients that predate this field.
   *
   * 高级生成参数，按特性分组（Req 3.1）。仅在 converter Tab 激活时有值，
   * 其它情况为 ``null``。为兼容旧客户端保留 optional 语义。
   */
  advanced_params?: AdvancedParams | null;
  /**
   * Complete workflow store snapshots; binary source bytes travel separately
   * in multipart attachments.
   *
   * 完整工作流状态快照；源文件二进制字节通过 multipart 附件发送。
   */
  workflow_state?: Record<string, unknown>;
  source_file_ids?: string[];
  source_lut_names?: string[];
  source_material_dir_names?: string[];
  /** Compact Workshop summary; workflow_state also preserves the full store. */
  workshop?: WorkshopBugReportContext | null;
}

export interface BugReportRequestPayload {
  description: string;
  user_email: string | null;
  context: BugReportContextPayload;
  screenshot_data_url: string | null;
}

/**
 * Upload state of a local ticket on the official feedback server.
 *
 * - ``pending``: the background task is still assembling or uploading.
 * - ``submitted``: the server stored the ticket and its attachments.
 * - ``failed``: the upload failed; the ticket stays on this device and can
 *   be retried.
 * - ``disabled``: uploads are switched off on this installation.
 *
 * 工单在官方反馈服务上的上传状态：``pending`` 后台仍在装配或上传；
 * ``submitted`` 服务器已保存；``failed`` 上传失败，工单保留在本机可重试；
 * ``disabled`` 本机已关闭上传。
 */
export type BugReportSubmissionStatus =
  | "pending"
  | "submitted"
  | "failed"
  | "disabled";

export interface BugReportResponse {
  ticket_id: string;
  dump_path: string;
  submission_status: BugReportSubmissionStatus;
  /**
   * Assembly status of the ticket directory. The synchronous submit path
   * returns ``in_progress``; the background task later updates it to
   * ``done`` or ``partial_failed``. Optional for older mocked responses.
   *
   * 工单装配状态。同步路径返回 ``in_progress``，后台任务后续写入 ``done``
   * 或 ``partial_failed``。为旧测试 mock 兼容留 optional。
   */
  assembly_status?: "in_progress" | "done" | "partial_failed" | null;
  /** Exact-source capture result; optional for older backend compatibility. */
  original_image_status?:
    | "attached"
    | "session_fallback"
    | "not_applicable"
    | "too_large"
    | "failed";
}

export interface BugReportHeldBackAttachment {
  name: string;
  size_bytes: number;
  reason: "too_large" | "unsupported_type" | "empty" | "rejected";
}

export interface BugReportStatusResponse {
  ticket_id: string;
  assembly_status: string | null;
  submission_status: BugReportSubmissionStatus;
  error_type: string | null;
  uploaded_attachments: string[];
  held_back_attachments: BugReportHeldBackAttachment[];
}

export async function submitBugReport(
  payload: BugReportRequestPayload,
  originalImage: File | null = null,
  sourceFiles: ReadonlyArray<File> = [],
): Promise<BugReportResponse> {
  if (originalImage || sourceFiles.length > 0) {
    const form = new FormData();
    form.append("request_payload", JSON.stringify(payload));
    if (originalImage) form.append("original_image", originalImage, originalImage.name);
    for (const file of sourceFiles) {
      if (file !== originalImage) form.append("source_files", file, file.name);
    }
    const { data } = await apiClient.post<BugReportResponse>(
      "/feedback/bug-report",
      form,
    );
    return data;
  }
  const { data } = await apiClient.post<BugReportResponse>(
    "/feedback/bug-report",
    payload,
  );
  return data;
}

export async function getBugReportStatus(
  ticketId: string,
): Promise<BugReportStatusResponse> {
  const { data } = await apiClient.get<BugReportStatusResponse>(
    `/feedback/bug-report/${encodeURIComponent(ticketId)}/status`,
  );
  return data;
}

export async function resubmitBugReport(
  ticketId: string,
): Promise<BugReportStatusResponse> {
  const { data } = await apiClient.post<BugReportStatusResponse>(
    `/feedback/bug-report/${encodeURIComponent(ticketId)}/resubmit`,
  );
  return data;
}
