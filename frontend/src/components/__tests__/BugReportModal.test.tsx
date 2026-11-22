import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api/feedback", () => ({
  getBugReportStatus: vi.fn(),
  resubmitBugReport: vi.fn(),
  submitBugReport: vi.fn(),
}));

vi.mock("../../utils/bugReportContext", () => ({
  collectBugReportContext: vi.fn(),
  collectBugReportOriginalImage: vi.fn(),
  collectBugReportSourceFiles: vi.fn(() => []),
}));

import {
  getBugReportStatus,
  resubmitBugReport,
  submitBugReport,
} from "../../api/feedback";
import {
  collectBugReportContext,
  collectBugReportOriginalImage,
  collectBugReportSourceFiles,
} from "../../utils/bugReportContext";
import { BugReportModal } from "../BugReportModal";

function createBugReportContext(
  overrides: Partial<ReturnType<typeof collectBugReportContext>> = {},
): ReturnType<typeof collectBugReportContext> {
  return {
    url: "http://localhost:5174/",
    user_agent: "vitest-agent",
    screen_width: 1280,
    screen_height: 720,
    device_pixel_ratio: 1,
    app_version: "2.0.0",
    language: "zh",
    theme: "light",
    active_tab: "converter",
    active_session_ids: {
      converter: "session-12345678",
      single_stage: null,
    },
    color_mode: "4-Color (RYBW)",
    lut_name: "Test LUT",
    source_version: "legacy",
    selected_native_brand_key: null,
    selected_native_db_names: [],
    selected_material_dir_names: [],
    material_layer_count: null,
    material_layer_height_mm: null,
    material_backing_material_dir_name: null,
    recent_client_logs: [],
    ...overrides,
  };
}

function createSensitiveBugReportContext(): ReturnType<typeof collectBugReportContext> {
  return createBugReportContext({
    active_final_artifact_ref: {
      session_id: "session-12345678",
      download_url: "/api/files/output-model",
      artifact_type: "3mf",
      disk_path: "/Users/min/private/final-output.3mf",
      source: "converter",
    },
    action_history: [
      {
        timestamp: 1_781_999_000_000,
        action_type: "api_error",
        snapshot: {
          color_mode: "4-Color (RYBW)",
          lut_name: "Test LUT",
          source_version: "legacy",
          selected_native_db_names: [],
          selected_material_dir_names: [],
          material_layer_count: null,
          material_layer_height_mm: null,
          material_backing_material_dir_name: null,
          active_tab: "converter",
          advanced_params: null,
        },
        error: {
          status_code: 500,
          path: "/api/converter/preview",
          error_message:
            "Request failed with status code 500 while reading /Users/min/private/source.png",
        },
      },
    ],
    recent_client_logs: [
      {
        timestamp: "2026-06-21T10:00:00.000Z",
        method: "error",
        label: "Request failed with status code 500",
        elapsed_ms: null,
        scope: "\\\\LUMINA-NAS\\private\\trace.log",
        details: {
          "Request failed with status code 500": "transport",
          api_path_transport_error:
            "Request failed with status code 500 at /api/files/output-model",
          error_message:
            "AxiosError: Request failed with status code 500 at /Users/min/private/source.png",
          home_path: "/home/min/private/source.png",
          private_tmp_path: "/private/tmp/lumina/private/source.png",
          tmp_path: "/tmp/lumina/private/source.png",
          var_path: "/var/folders/private/source.png",
          volume_path: "/Volumes/Work/private/source.png",
          mnt_path: "/mnt/lumina/private/source.png",
          opt_path: "/opt/lumina/private/source.png",
          error_stack:
            "Error: boom\n    at convert (/Users/min/CascadeProjects/Lumina-studio/frontend/src/api/client.ts:12:3)",
          path: "/Users/min/private/output.3mf",
          cache_url: "file:///Users/min/private/cache/model.glb",
          local_cache_url: "file://localhost/Users/min/private/cache/model.glb",
          unc_path: "\\\\LUMINA-NAS\\share\\secret.3mf",
          windows_file_url: "file:///C:/tmp/lumina/model.glb",
          windows_path: "C:\\Users\\min\\private\\output.3mf",
          windows_tmp_path: "C:\\tmp\\lumina\\output.3mf",
          windows_program_data_path: "C:/ProgramData/Lumina/output.3mf",
          windows_temp_path: "C:\\Windows\\Temp\\lumina\\output.3mf",
          status_code: 500,
        },
      },
    ],
  });
}

function expectManualFallbackTextComplete(text: string, description?: string): void {
  if (description != null) expect(text).toContain(`"description": "${description}"`);
  expectFullDiagnosticText(text);
  expect(text).toContain("Request failed with status code 500");
  expect(text).toContain("500");
  expect(text).toContain("/api/files/output-model");
}

function expectFullDiagnosticText(text: string): void {
  expect(text).toContain("/Users/min");
  expect(text).toContain("error_stack");
}

function submitDiagnosticsOnly(): void {
  fireEvent.click(screen.getByRole("switch", { name: "需要人工回复 / 修复后通知我" }));
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
}

describe("BugReportModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(submitBugReport).mockReset();
    vi.mocked(getBugReportStatus).mockReset();
    vi.mocked(resubmitBugReport).mockReset();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: undefined,
    });
    vi.mocked(collectBugReportContext).mockReturnValue(createBugReportContext());
    vi.mocked(collectBugReportOriginalImage).mockReturnValue(null);
    vi.mocked(collectBugReportSourceFiles).mockReturnValue([]);
  });

  it("warns about incomplete collection and recaptures the frozen sources as a new ticket", async () => {
    const original = new File(["<svg>original</svg>"], "original.svg");
    const model = new File(["solid model"], "plate.stl");
    vi.mocked(collectBugReportOriginalImage).mockReturnValue(original);
    vi.mocked(collectBugReportSourceFiles).mockReturnValue([original, model]);
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "LUM-202610-12345678", submission_status: "pending", dump_path: "feedback/first",
    }).mockResolvedValueOnce({
      ticket_id: "LUM-202610-87654321", submission_status: "pending", dump_path: "feedback/second",
    });
    vi.mocked(getBugReportStatus).mockResolvedValueOnce({
      ticket_id: "LUM-202610-12345678", assembly_status: "partial_failed", submission_status: "submitted",
      error_type: null, uploaded_attachments: ["original.svg"], held_back_attachments: [],
    });
    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "Model failed" } });
    submitDiagnosticsOnly();
    expect(await screen.findByTestId("bug-report-collection-incomplete", {}, { timeout: 3500 })).toHaveTextContent("资料采集不完整");
    vi.mocked(collectBugReportOriginalImage).mockReturnValue(null);
    vi.mocked(collectBugReportSourceFiles).mockReturnValue([]);
    fireEvent.click(screen.getByRole("button", { name: "重新采集并提交全部资料" }));
    await waitFor(() => expect(submitBugReport).toHaveBeenCalledTimes(2));
    const [payload, image, files] = vi.mocked(submitBugReport).mock.calls[1];
    expect(payload).toBe(vi.mocked(submitBugReport).mock.calls[0][0]);
    expect(image).toBe(original);
    expect(files?.[0]).toBe(original);
    expect(files?.[1]).toBe(model);
    expect(resubmitBugReport).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("bug-report-ticket-id")).toHaveTextContent("LUM-202610-87654321"));
  });

  it("disables submit until description has content", () => {
    render(<BugReportModal open onClose={() => {}} />);

    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    expect(screen.getByRole("button", { name: "发送" })).not.toBeDisabled();
  });

  it.each(["", "  ", "a b", "x".repeat(321)])("requires a reply contact by default", (contact) => {
    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "Preview failed" } });
    expect(screen.getByRole("switch", { name: "需要人工回复 / 修复后通知我" })).toBeChecked();
    const input = screen.getByLabelText("联系方式（邮箱、QQ 或微信）");
    expect(input).toBeRequired();
    fireEvent.change(input, { target: { value: contact } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(screen.getByText(/请填写.+邮箱、QQ 或微信/)).toBeInTheDocument();
    expect(input).toHaveFocus();
    expect(submitBugReport).not.toHaveBeenCalled();
  });

  it.each(["123456789", "  wx_fixture  "])("accepts QQ and WeChat for replies", async (contact) => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "LUM-test", submission_status: "disabled", dump_path: "feedback/test",
    });
    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "Preview failed" } });
    fireEvent.change(screen.getByLabelText("联系方式（邮箱、QQ 或微信）"), { target: { value: contact } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-ticket-id");
    expect(submitBugReport).toHaveBeenCalledWith(expect.objectContaining({
      needs_reply: true, user_contact: contact.trim(), user_email: null,
    }));
  });

  it("submits a diagnostic-only report when the user opts out of a reply", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "LUM-test", submission_status: "disabled", dump_path: "feedback/test",
    });
    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "Preview failed" } });
    fireEvent.change(screen.getByLabelText("联系方式（邮箱、QQ 或微信）"), { target: { value: "wx_fixture" } });
    fireEvent.click(screen.getByRole("switch", { name: "需要人工回复 / 修复后通知我" }));
    expect(screen.getByText("仅上报诊断信息，无需回复")).toBeInTheDocument();
    expect(screen.queryByLabelText("联系方式（邮箱、QQ 或微信）")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-ticket-id");
    expect(submitBugReport).toHaveBeenCalledWith(expect.objectContaining({
      needs_reply: false, user_contact: null, user_email: null,
    }));
  });

  it("summarizes recent API client errors from the captured context", () => {
    vi.mocked(collectBugReportContext).mockReturnValueOnce(createBugReportContext({
      recent_client_logs: [
        {
          timestamp: "2026-06-18T15:00:00.000Z",
          method: "error",
          label: "api: request failed",
          elapsed_ms: null,
          scope: "api",
          phase: "request-failed",
          details: {
            status_code: 500,
            url: "/convert/generate",
            error_message: "The server hit an internal error.",
          },
        },
      ],
    }));

    render(<BugReportModal open onClose={() => {}} />);

    expect(screen.getByText("近期接口错误")).toBeInTheDocument();
    const summary = within(screen.getByTestId("bug-report-context-summary"));
    expect(summary.getByText("The server hit an internal error.")).toBeInTheDocument();
    expect(summary.queryByText(/\/convert\/generate/)).not.toBeInTheDocument();
  });

  it("replaces generic status-code API errors in the context summary", () => {
    vi.mocked(collectBugReportContext).mockReturnValueOnce(createBugReportContext({
      recent_client_logs: [
        {
          timestamp: "2026-06-18T15:00:00.000Z",
          method: "error",
          label: "api: request failed",
          elapsed_ms: null,
          scope: "api",
          phase: "request-failed",
          details: {
            status_code: 402,
            path: "/api/quota/check",
            error_message: "Request failed with status code 402",
          },
        },
      ],
    }));

    render(<BugReportModal open onClose={() => {}} />);

    const summary = within(screen.getByTestId("bug-report-context-summary"));
    expect(
      summary.getByText("此操作需要可用额度或付款状态后才能继续。"),
    ).toBeInTheDocument();
    expect(summary.queryByText("402 · /api/quota/check")).not.toBeInTheDocument();
    expect(summary.queryByText(/\/api\/quota\/check/)).not.toBeInTheDocument();
    expect(
      summary.queryByText("Request failed with status code 402"),
    ).not.toBeInTheDocument();
  });

  it("replaces transport-prefixed API errors in the context summary", () => {
    vi.mocked(collectBugReportContext).mockReturnValueOnce(createBugReportContext({
      recent_client_logs: [
        {
          timestamp: "2026-06-18T15:00:00.000Z",
          method: "error",
          label: "api: request failed",
          elapsed_ms: null,
          scope: "api",
          phase: "request-failed",
          details: {
            status_code: 500,
            url: "/convert/generate",
            error_message: "AxiosError: Request failed with status code 500 at /convert/generate",
          },
        },
      ],
    }));

    render(<BugReportModal open onClose={() => {}} />);

    const summary = within(screen.getByTestId("bug-report-context-summary"));
    expect(
      summary.getByText("服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。"),
    ).toBeInTheDocument();
    expect(summary.queryByText(/AxiosError/)).not.toBeInTheDocument();
    expect(summary.queryByText(/\/convert\/generate/)).not.toBeInTheDocument();
  });

  it("submits the built payload and shows a success toast", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      submission_status: "disabled",
      dump_path: "feedback/abc12345.json",
    });

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed after generate." },
    });
    fireEvent.change(screen.getByLabelText("联系方式（邮箱、QQ 或微信）"), {
      target: { value: "user@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(submitBugReport).toHaveBeenCalledWith({
        description: "Preview failed after generate.",
        user_email: "user@example.com",
        user_contact: "user@example.com",
        needs_reply: true,
        context: vi.mocked(collectBugReportContext).mock.results[0]?.value,
        screenshot_data_url: null,
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("工单号：abc12345");
  });

  it("submits the active converter source and reports exact attachment success", async () => {
    const original = new File(["<svg/>"], "source.svg", {
      type: "image/svg+xml",
    });
    vi.mocked(collectBugReportOriginalImage).mockReturnValue(original);
    vi.mocked(collectBugReportContext).mockReturnValue(
      createBugReportContext({
        active_original_image_ref: {
          session_id: null,
          filename: "source.svg",
          source: "converter",
        },
      }),
    );
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "LUM-202608-deadbeef",
      submission_status: "disabled",
      dump_path: "feedback/2026-08/LUM-202608-deadbeef",
      original_image_status: "attached",
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed before a session existed." },
    });
    submitDiagnosticsOnly();

    await waitFor(() => {
      expect(submitBugReport).toHaveBeenCalledWith(
        expect.objectContaining({
          description: "Preview failed before a session existed.",
        }),
        original,
        [],
      );
    });
    const status = await screen.findByTestId("bug-report-original-image-status");
    expect(status).toHaveAttribute("data-status", "attached");
    expect(status).toHaveTextContent("转换原图已按原始字节随工单保存");
  });

  it("warns when an oversized original could not be saved", async () => {
    const original = new File(["x"], "oversized.png", { type: "image/png" });
    vi.mocked(collectBugReportOriginalImage).mockReturnValue(original);
    vi.mocked(collectBugReportContext).mockReturnValue(
      createBugReportContext({
        active_original_image_ref: {
          session_id: null,
          filename: "oversized.png",
          source: "converter",
        },
      }),
    );
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "LUM-202608-c0ffee00",
      submission_status: "disabled",
      dump_path: "feedback/2026-08/LUM-202608-c0ffee00",
      original_image_status: "too_large",
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Large source failed." },
    });
    submitDiagnosticsOnly();

    const status = await screen.findByTestId("bug-report-original-image-status");
    expect(status).toHaveAttribute("data-status", "too_large");
    expect(status).toHaveTextContent("旧版本客户端因大小限制省略了原图");
  });

  it.each([
    ["session_fallback", "转换原图已从当前转换会话恢复"],
    ["failed", "原图保存失败"],
    ["not_applicable", "本次没有单独的转换原图"],
  ] as const)("shows the %s original-image result", async (imageStatus, text) => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "LUM-202608-0123abcd",
      submission_status: "disabled",
      dump_path: "feedback/2026-08/LUM-202608-0123abcd",
      original_image_status: imageStatus,
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Check source attachment status." },
    });
    submitDiagnosticsOnly();

    const status = await screen.findByTestId("bug-report-original-image-status");
    expect(status).toHaveAttribute("data-status", imageStatus);
    expect(status).toHaveTextContent(text);
  });

  it("submits an attached screenshot data URL", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      submission_status: "disabled",
      dump_path: "feedback/abc12345.json",
    });
    const screenshot = new File(["fake png"], "preview.png", { type: "image/png" });

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed after generate." },
    });
    fireEvent.change(screen.getByLabelText("截图（可选）"), {
      target: { files: [screenshot] },
    });

    expect(await screen.findByText("preview.png")).toBeInTheDocument();

    submitDiagnosticsOnly();

    await waitFor(() => {
      expect(submitBugReport).toHaveBeenCalledWith(
        expect.objectContaining({
          screenshot_data_url: expect.stringMatching(/^data:image\/png;base64,/),
        }),
      );
    });
  });

  it("rejects non-image screenshot attachments before submit", async () => {
    const textFile = new File(["not image"], "notes.txt", { type: "text/plain" });

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("截图（可选）"), {
      target: { files: [textFile] },
    });

    expect(await screen.findByText("请选择图片文件作为截图。")).toBeInTheDocument();
    expect(submitBugReport).not.toHaveBeenCalled();
  });

  it("renders a persistent success view with ticket id and a manual close button when uploads are off", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      submission_status: "disabled",
      dump_path: "feedback/20260429T162531Z_abc.json",
    });
    const onClose = vi.fn();

    render(<BugReportModal open onClose={onClose} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed after generate." },
    });
    submitDiagnosticsOnly();

    expect(await screen.findByTestId("bug-report-ticket-id")).toHaveTextContent("abc12345");
    expect(screen.queryByTestId("bug-report-dump-path")).not.toBeInTheDocument();
    expect(screen.queryByText("feedback/20260429T162531Z_abc.json")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "本机已关闭反馈上传，报告只保存在本机。请用下面的方式手动发送。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-copy-submitted-report")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "完成" })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("问题描述")).not.toBeInTheDocument();
  });

  it("polls the upload until the official service confirms it", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "LUM-202609-deadbeef",
      submission_status: "pending",
      dump_path: "feedback/2026-09/LUM-202609-deadbeef",
    });
    vi.mocked(getBugReportStatus).mockResolvedValueOnce({
      ticket_id: "LUM-202609-deadbeef",
      assembly_status: "done",
      submission_status: "pending",
      error_type: null,
      uploaded_attachments: [],
      held_back_attachments: [],
    }).mockResolvedValueOnce({
      ticket_id: "LUM-202609-deadbeef",
      assembly_status: "done",
      submission_status: "submitted",
      error_type: null,
      uploaded_attachments: ["original.png"],
      held_back_attachments: [
        { name: "final.3mf", size_bytes: 50_000_000, reason: "too_large" },
      ],
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    submitDiagnosticsOnly();

    const status = await screen.findByTestId("bug-report-upload-status");
    expect(status).toHaveAttribute("data-status", "pending");
    expect(status).toHaveTextContent("正在上传到官方问题收集服务");
    await waitFor(
      () => expect(screen.getByTestId("bug-report-upload-status")).toHaveAttribute(
        "data-status",
        "submitted",
      ),
      { timeout: 5000 },
    );
    expect(getBugReportStatus).toHaveBeenCalledWith("LUM-202609-deadbeef");
    expect(screen.getByText("已上传到官方问题收集服务，开发者会根据工单号跟进。")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-upload-held-back")).toHaveTextContent("final.3mf");
    expect(screen.queryByTestId("bug-report-copy-submitted-report")).not.toBeInTheDocument();
    expect(screen.queryByText("feedback/2026-09/LUM-202609-deadbeef")).not.toBeInTheDocument();
  }, 10_000);

  it("shows pending upload status without manual fallback", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "pending123",
      submission_status: "pending",
      dump_path: "feedback/pending123.json",
    });
    vi.mocked(getBugReportStatus).mockReturnValue(new Promise(() => {}));

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    submitDiagnosticsOnly();

    const uploadStatus = await screen.findByTestId("bug-report-upload-status");
    expect(uploadStatus).toHaveAttribute("data-status", "pending");
    expect(screen.queryByTestId("bug-report-upload-retry")).not.toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-copy-submitted-report")).not.toBeInTheDocument();
  });

  it("retries a failed upload and hides manual fallback once it succeeds", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "LUM-202609-0000abcd",
      submission_status: "pending",
      dump_path: "feedback/2026-09/LUM-202609-0000abcd",
    });
    vi.mocked(getBugReportStatus).mockResolvedValueOnce({
      ticket_id: "LUM-202609-0000abcd",
      assembly_status: "done",
      submission_status: "failed",
      error_type: "ServerUnavailable",
      uploaded_attachments: [],
      held_back_attachments: [],
    });
    vi.mocked(resubmitBugReport).mockResolvedValueOnce({
      ticket_id: "LUM-202609-0000abcd",
      assembly_status: "done",
      submission_status: "submitted",
      error_type: null,
      uploaded_attachments: ["original.png"],
      held_back_attachments: [],
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    submitDiagnosticsOnly();

    const retry = await screen.findByTestId("bug-report-upload-retry", {}, { timeout: 5000 });
    expect(screen.getByText("报告已保存在本机。工单号：LUM-202609-0000abcd")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-copy-submitted-report")).toBeInTheDocument();
    fireEvent.click(retry);

    await waitFor(() => {
      expect(resubmitBugReport).toHaveBeenCalledWith("LUM-202609-0000abcd");
    });
    expect(await screen.findByText("已上传到官方问题收集服务，开发者会根据工单号跟进。")).toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-copy-submitted-report")).not.toBeInTheDocument();
  }, 10_000);

  it("preserves full client diagnostics from the submitted manual fallback", async () => {
    const sensitiveContext = createSensitiveBugReportContext();
    vi.mocked(collectBugReportContext).mockReturnValue(sensitiveContext);
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "emailfail",
      submission_status: "failed",
      dump_path: "feedback/emailfail.json",
    });
    const writeText = vi.fn().mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    submitDiagnosticsOnly();

    const fallbackText = await screen.findByTestId(
      "bug-report-submitted-fallback-text",
    );
    expectManualFallbackTextComplete(
      fallbackText.textContent ?? "",
      "Crash after generate.",
    );
    expectManualFallbackTextComplete(
      decodeURIComponent(
        screen.getByText("用默认邮箱发送").getAttribute("href") ?? "",
      ),
      "Crash after generate.",
    );
    expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ context: sensitiveContext }),
    );

    fireEvent.click(screen.getByTestId("bug-report-copy-submitted-report"));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expectManualFallbackTextComplete(
      String(writeText.mock.calls[0]?.[0]),
      "Crash after generate.",
    );
  });

  it("preserves non-error HTTP status text from the submitted manual fallback", async () => {
    vi.mocked(collectBugReportContext).mockReturnValueOnce(createBugReportContext({
      recent_client_logs: [
        {
          timestamp: "2026-06-21T10:00:00.000Z",
          method: "error",
          label: "Request failed with status code 302",
          elapsed_ms: null,
          scope: "api",
          details: {
            status_code: 302,
            url: "/api/files/output-model",
            error_message: "Request failed with status code 302",
          },
        },
      ],
    }));
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "redirect",
      submission_status: "failed",
      dump_path: "feedback/redirect.json",
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview redirected after generate." },
    });
    submitDiagnosticsOnly();

    const fallbackText = await screen.findByTestId(
      "bug-report-submitted-fallback-text",
    );
    const text = fallbackText.textContent ?? "";
    expect(text).toContain("Request failed with status code 302");
    expect(text).toMatch(/\b302\b/);
  });

  it("keeps manual fallback actions visible when the upload retry fails", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "uploadfail",
      submission_status: "failed",
      dump_path: "feedback/uploadfail.json",
    });
    vi.mocked(resubmitBugReport).mockRejectedValueOnce(new Error("offline"));

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    submitDiagnosticsOnly();
    fireEvent.click(await screen.findByTestId("bug-report-upload-retry"));

    expect(await screen.findByText("仍然失败，请稍后再试。")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-copy-submitted-report")).toBeInTheDocument();
    expect(screen.getByText("用默认邮箱发送")).toHaveAttribute(
      "href",
      expect.stringContaining("mailto:"),
    );
    expect(screen.getByText("打开 QQ 邮箱")).toHaveAttribute("href", "https://mail.qq.com/");
  });

  it("invokes onClose only when the success Done button is clicked", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      submission_status: "disabled",
      dump_path: "feedback/abc12345.json",
    });
    const onClose = vi.fn();

    render(<BugReportModal open onClose={onClose} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    submitDiagnosticsOnly();

    await screen.findByTestId("bug-report-ticket-id");
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("copies the ticket id to the clipboard when the copy button is pressed", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      submission_status: "disabled",
      dump_path: "feedback/abc12345.json",
    });
    const writeText = vi.fn().mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    submitDiagnosticsOnly();
    await screen.findByTestId("bug-report-ticket-id");

    fireEvent.click(screen.getByTestId("bug-report-copy-ticket"));

    expect(writeText).toHaveBeenCalledWith("abc12345");
    expect(await screen.findByText("已复制")).toBeInTheDocument();
  });

  it("falls back to selection copy when clipboard write fails", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      submission_status: "disabled",
      dump_path: "feedback/abc12345.json",
    });
    const writeText = vi.fn().mockRejectedValueOnce(new Error("not allowed"));
    const execCommand = vi.fn().mockReturnValueOnce(true);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    submitDiagnosticsOnly();
    await screen.findByTestId("bug-report-ticket-id");

    fireEvent.click(screen.getByTestId("bug-report-copy-ticket"));

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("abc12345");
      expect(execCommand).toHaveBeenCalledWith("copy");
    });
    expect(await screen.findByText("已复制")).toBeInTheDocument();
  });

  it("shows a manual-copy warning when all copy strategies fail", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      submission_status: "disabled",
      dump_path: "feedback/abc12345.json",
    });
    const writeText = vi.fn().mockRejectedValueOnce(new Error("not allowed"));
    const execCommand = vi.fn().mockReturnValueOnce(false);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    submitDiagnosticsOnly();
    await screen.findByTestId("bug-report-ticket-id");

    fireEvent.click(screen.getByTestId("bug-report-copy-ticket"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "自动复制失败，请手动选中工单号复制。",
    );
    expect(screen.getByTestId("bug-report-copy-ticket")).toHaveTextContent("复制");
  });

  it("resets the success view back to a fresh form when the modal is reopened", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      submission_status: "disabled",
      dump_path: "feedback/abc12345.json",
    });
    const onClose = vi.fn();

    const { rerender } = render(<BugReportModal open onClose={onClose} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    submitDiagnosticsOnly();
    await screen.findByTestId("bug-report-ticket-id");

    rerender(<BugReportModal open={false} onClose={onClose} />);
    rerender(<BugReportModal open onClose={onClose} />);

    expect(screen.queryByTestId("bug-report-ticket-id")).not.toBeInTheDocument();
    expect(screen.getByLabelText("问题描述")).toBeInTheDocument();
    expect((screen.getByLabelText("问题描述") as HTMLTextAreaElement).value).toBe("");
  });

  it("keeps the modal open on submit failure and shows an error toast", async () => {
    vi.mocked(submitBugReport).mockRejectedValueOnce(new Error("boom"));
    const onClose = vi.fn();
    render(<BugReportModal open onClose={onClose} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    submitDiagnosticsOnly();

    expect(await screen.findByRole("alert")).toHaveTextContent("提交失败，请稍后再试。");
    expect(screen.getByText("如果多次失败，请复制下面的反馈内容，通过邮箱或即时通讯发给开发者。")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-fallback-text")).toHaveTextContent(
      '"description": "Preview failed"',
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("preserves full client diagnostics from the failed-submit manual fallback", async () => {
    const sensitiveContext = createSensitiveBugReportContext();
    const userDescription = "I got Request failed with status code 500 after generate";
    vi.mocked(collectBugReportContext).mockReturnValue(sensitiveContext);
    vi.mocked(submitBugReport).mockRejectedValueOnce(new Error("boom"));
    const writeText = vi.fn().mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: userDescription },
    });
    submitDiagnosticsOnly();

    const fallbackText = await screen.findByTestId("bug-report-fallback-text");
    expectManualFallbackTextComplete(fallbackText.textContent ?? "", userDescription);
    expectManualFallbackTextComplete(
      decodeURIComponent(
        screen.getByText("用默认邮箱发送").getAttribute("href") ?? "",
      ),
      userDescription,
    );
    expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ context: sensitiveContext }),
    );

    fireEvent.click(screen.getByTestId("bug-report-copy-failed-report"));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expectManualFallbackTextComplete(String(writeText.mock.calls[0]?.[0]), userDescription);
  });

  it("copies the failed report payload for manual fallback", async () => {
    vi.mocked(submitBugReport).mockRejectedValueOnce(new Error("boom"));
    const writeText = vi.fn().mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    submitDiagnosticsOnly();
    await screen.findByTestId("bug-report-fallback-text");

    fireEvent.click(screen.getByTestId("bug-report-copy-failed-report"));

    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('"description": "Preview failed"'),
    );
    expect(await screen.findByText("反馈内容已复制")).toBeInTheDocument();
  });

  it("clears the failed report fallback when the description changes", async () => {
    vi.mocked(submitBugReport).mockRejectedValueOnce(new Error("boom"));
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    submitDiagnosticsOnly();
    await screen.findByTestId("bug-report-fallback-text");

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed again" },
    });

    expect(screen.queryByTestId("bug-report-fallback-text")).not.toBeInTheDocument();
  });

  it("shows inline validation when description is empty", async () => {
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.blur(screen.getByLabelText("问题描述"));

    expect(await screen.findByText("请填写问题描述")).toBeInTheDocument();
    expect(submitBugReport).not.toHaveBeenCalled();
  });

  it("preserves long descriptions", async () => {
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "x".repeat(10001) },
    });

    expect(
      (screen.getByLabelText("问题描述") as HTMLTextAreaElement).value,
    ).toHaveLength(10001);
    expect(screen.queryByText("问题描述已截断到 10000 个字符。")).toBeNull();
  });

  it("expands the collected context disclosure", async () => {
    vi.mocked(collectBugReportContext).mockReturnValueOnce(createBugReportContext({
      recent_client_logs: [
        {
          timestamp: "2026-06-18T15:00:00.000Z",
          method: "error",
          label: "api: request failed",
          elapsed_ms: null,
          scope: "api",
          phase: "request-failed",
          details: {
            status_code: 500,
            path: "/api/files/output-model",
            url: "/convert/generate",
            error_message: "The server hit an internal error.",
          },
        },
      ],
    }));

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.click(screen.getByText("已自动收集的信息（点击展开）"));

    // Full JSON is now serialized lazily on an idle callback; wait for the
    // text to appear.
    // JSON 现在通过 idle 回调按需序列化；等待文本出现。
    await screen.findByText(/"active_tab":\s*"converter"/, undefined, {
      timeout: 1500,
    });
    const fullContext = screen.getByTestId("bug-report-context-json").textContent ?? "";
    expect(fullContext).toContain('"path": "/api/files/output-model"');
    expect(fullContext).toContain('"url": "/convert/generate"');
  });

  it("preserves full client diagnostics from the expanded context disclosure", async () => {
    vi.mocked(collectBugReportContext).mockReturnValue(
      createSensitiveBugReportContext(),
    );

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.click(screen.getByText("已自动收集的信息（点击展开）"));

    await screen.findByText(/"active_tab":\s*"converter"/, undefined, {
      timeout: 1500,
    });
    expectManualFallbackTextComplete(
      screen.getByTestId("bug-report-context-json").textContent ?? "",
    );
  });

  it("resets local form state when cancelled", () => {
    const onClose = vi.fn();
    const { rerender } = render(<BugReportModal open onClose={onClose} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(<BugReportModal open={false} onClose={onClose} />);
    rerender(<BugReportModal open onClose={onClose} />);
    expect((screen.getByLabelText("问题描述") as HTMLTextAreaElement).value).toBe("");
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<BugReportModal open onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps draft content when the backdrop is clicked", () => {
    const onClose = vi.fn();
    render(<BugReportModal open onClose={onClose} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    fireEvent.click(screen.getByTestId("bug-report-backdrop"));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect((screen.getByLabelText("问题描述") as HTMLTextAreaElement).value).toBe(
      "Preview failed",
    );
  });
});
