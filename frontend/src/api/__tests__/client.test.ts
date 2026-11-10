import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../utils/clientLog", () => ({
  postClientLog: vi.fn(),
  summarizeErrorForLog: (error: unknown) => ({
    error_message: error instanceof Error ? error.message : String(error),
  }),
}));

import { postClientLog } from "../../utils/clientLog";
import { useActionHistoryStore } from "../../stores/actionHistoryStore";
import { useSettingsStore } from "../../stores/settingsStore";
import apiClient, {
  apiErrorToVisibleMessage,
  assertResourceDownloadAvailable,
  buildApiResourceUrl,
  downloadResourceBlob,
} from "../client";

const jsonHeaders = {
  get: (name: string) =>
    name.toLowerCase() === "content-type" ? "application/json" : null,
};

describe("apiClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useActionHistoryStore.getState()._resetForTests();
    useSettingsStore.setState({ language: "en" });
    apiClient.defaults.baseURL = "/api";
  });

  afterEach(() => {
    apiClient.defaults.adapter = undefined;
  });

  it.each([400, 409, 422, 500, 503])("preserves the original HTTP %s response and logs its diagnostics", async (status) => {
    const detail = "Traceback: /Users/min/source.svg: WorkerError: invalid geometry";
    const data = { detail, state: { source: "plate.stl", slots: [1, 2, 3] } };
    const error = Object.assign(new Error("Request failed"), {
      config: { method: "post", url: "/convert/generate" },
      response: { status, data, headers: { "x-request-id": "complete-error" } },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);
    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    expect(rejected.message).toBe(detail);
    expect(rejected.response.data).toBe(data);
    expect(postClientLog).toHaveBeenCalledWith("api: request failed", expect.objectContaining({
      details: expect.objectContaining({ response_detail: data, status_code: status, request_id: "complete-error" }),
    }));
  });

  it("keeps suppressed background probes out of client logs and action history", async () => {
    const error = new Error("Request failed with status code 503");
    Object.assign(error, {
      config: { method: "get", url: "/health", suppressClientLog: true },
      response: { status: 503, data: {} },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(
      apiClient.get("/health", { suppressClientLog: true }),
    ).rejects.toMatchObject({
      message: "Server temporarily unavailable. Please try again later.",
    });

    expect(postClientLog).not.toHaveBeenCalled();
    expect(useActionHistoryStore.getState().history).toHaveLength(0);
  });

  it("keeps intentional request cancellation out of client error diagnostics", async () => {
    const error = Object.assign(new Error("canceled"), {
      name: "CanceledError",
      code: "ERR_CANCELED",
      __CANCEL__: true,
      config: { method: "post", url: "/convert/preview" },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/preview", {})).rejects.toBe(error);

    expect(error.message).toBe("canceled");
    expect(postClientLog).not.toHaveBeenCalled();
    expect(useActionHistoryStore.getState().history).toHaveLength(0);
  });

  it("turns FastAPI validation details into a readable rejected message", async () => {
    const error = new Error("Request failed with status code 422");
    Object.assign(error, {
      config: { method: "post", url: "/convert/puzzle-layout-preview" },
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ["body", "session_id"], msg: "Field required" },
            { loc: ["body", "params"], msg: "Field required" },
          ],
        },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(
      apiClient.post("/convert/puzzle-layout-preview", {}),
    ).rejects.toMatchObject({
      message: "body.session_id: Field required; body.params: Field required",
    });

    expect(postClientLog).toHaveBeenCalledWith(
      "api: request failed",
      expect.objectContaining({
        details: expect.objectContaining({
          status_code: 422,
          error_message:
            "body.session_id: Field required; body.params: Field required",
        }),
      }),
    );
  });

  it.each([
    {
      language: "en" as const,
      expected:
        "Vector Native mode requires an SVG file. Upload an SVG, or switch to High-Fidelity or Pixel Art mode.",
    },
    {
      language: "zh" as const,
      expected:
        "矢量建模模式仅支持 SVG 文件。请上传 SVG，或切换到“高保真”或“像素艺术”模式。",
    },
  ])(
    "translates the structured SVG requirement in $language",
    async ({ language, expected }) => {
      useSettingsStore.setState({ language });
      const safeEnglishFallback =
        "⚠️ Vector Native mode requires SVG files!\n\n" +
        "Your file is not an SVG. Please either:\n" +
        "• Upload an SVG file, or\n" +
        "• Switch to 'High-Fidelity' or 'Pixel Art' mode";
      const detail = {
        error: "vector_native_requires_svg",
        message: safeEnglishFallback,
      };
      const error = new Error("Request failed with status code 422");
      Object.assign(error, {
        config: { method: "post", url: "/convert/generate" },
        response: { status: 422, data: { detail } },
      });
      apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

      const rejected = await apiClient
        .post("/convert/generate", {})
        .catch((err) => err);

      expect(rejected).toMatchObject({ message: expected });
      expect(rejected.response?.data?.detail).toEqual(detail);
    },
  );

  it.each([
    {
      code: "source_image_unreadable",
      status: 422,
      language: "en" as const,
      expected:
        "The image could not be read. Check that the file is not damaged, then re-export it as PNG, JPEG, or WebP and upload it again.",
    },
    {
      code: "source_image_unreadable",
      status: 422,
      language: "zh" as const,
      expected:
        "无法读取这张图片。请确认文件未损坏，并重新导出为 PNG、JPEG 或 WebP 后再上传。",
    },
    {
      code: "source_image_too_large",
      status: 413,
      language: "en" as const,
      expected:
        "The image dimensions are too large to process safely. Reduce the image resolution and upload it again.",
    },
    {
      code: "source_image_too_large",
      status: 413,
      language: "zh" as const,
      expected: "图片像素尺寸过大，无法安全处理。请缩小图片分辨率后重新上传。",
    },
    {
      code: "source_svg_invalid",
      status: 422,
      language: "en" as const,
      expected:
        "The SVG could not be parsed. Re-export a valid SVG from your design application and upload it again.",
    },
    {
      code: "source_svg_invalid",
      status: 422,
      language: "zh" as const,
      expected: "无法解析 SVG 文件。请在设计软件中重新导出有效的 SVG 后再上传。",
    },
    {
      code: "source_svg_no_renderable_geometry",
      status: 422,
      language: "en" as const,
      expected:
        "The SVG has no visible filled geometry supported by Vector mode. Make the artwork visible, convert strokes and text to filled paths, or switch to High-Fidelity mode.",
    },
    {
      code: "source_svg_no_renderable_geometry",
      status: 422,
      language: "zh" as const,
      expected:
        "SVG 中没有矢量模式可用的可见填充几何。请显示图稿，将描边和文字转换为填充路径，或切换到“高保真”模式。",
    },
  ])(
    "translates converter source error $code in $language",
    async ({ code, status, language, expected }) => {
      useSettingsStore.setState({ language });
      const detail = {
        error: code,
        message:
          status === 503
            ? "Customer project alpha must remain private."
            : "Safe server fallback for older clients.",
        ...(status === 503
          ? {
              requested_bytes: 8589934592,
              reason: "host_capacity_busy",
            }
          : {}),
      };
      const error = new Error(`Request failed with status code ${status}`);
      Object.assign(error, {
        config: { method: "post", url: "/convert/preview" },
        response: { status, data: { detail } },
      });
      apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

      const rejected = await apiClient
        .post("/convert/preview", {})
        .catch((err) => err);

      expect(rejected).toMatchObject({ message: expected });
      if (status === 503) {
        expect(rejected.response?.data?.detail).toEqual({
          error: code,
          message: expected,
        });
        expect(JSON.stringify(rejected.response?.data)).not.toContain(
          "Customer project alpha",
        );
        expect(JSON.stringify(rejected.response?.data)).not.toContain(
          "requested_bytes",
        );
      } else {
        expect(rejected.response?.data?.detail).toEqual(detail);
      }
    },
  );

  it.each([
    {
      language: "en" as const,
      expected:
        "The model is not a closed solid and cannot be cut safely. Repair the mesh and upload it again.",
    },
    {
      language: "zh" as const,
      expected: "模型不是闭合实体，无法安全开槽。请先修复网格后重新上传。",
    },
  ])(
    "translates the model-surface closed-solid error in $language",
    async ({ language, expected }) => {
      useSettingsStore.setState({ language });
      const detail = {
        error: "model_surface_mesh_not_watertight",
        message: "The model is not a closed solid and cannot be cut safely.",
      };
      const error = new Error("Request failed with status code 422");
      Object.assign(error, {
        config: { method: "post", url: "/convert/model-surface/upload" },
        response: { status: 422, data: { detail } },
      });
      apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

      const rejected = await apiClient
        .post("/convert/model-surface/upload", {})
        .catch((err) => err);

      expect(rejected).toMatchObject({ message: expected });
      expect(rejected.response?.data?.detail).toEqual(detail);
    },
  );

  it.each([
    {
      language: "en" as const,
      expected:
        "This model needs 6 material slots, but the selected 3MF template has 4. Choose a template with at least 6 slots or use fewer materials.",
    },
    {
      language: "zh" as const,
      expected:
        "当前模型需要 6 个耗材槽，但所选 3MF 模板只有 4 个。请换用至少 6 槽的模板，或减少模型使用的耗材。",
    },
  ])(
    "translates template capacity with the required and available slots in $language",
    async ({ language, expected }) => {
      useSettingsStore.setState({ language });
      const detail = {
        code: "template_slot_capacity",
        required_slots: 6,
        available_slots: 4,
        message: "Server fallback for older clients.",
      };
      const error = Object.assign(new Error("Request failed with status code 422"), {
        config: { method: "post", url: "/convert/export-materials" },
        response: { status: 422, data: { detail } },
      });
      apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

      const rejected = await apiClient.post("/convert/export-materials", {}).catch((err) => err);

      expect(rejected.message).toBe(expected);
      expect(rejected.response.data.detail).toEqual(detail);
    },
  );

  it("keeps the server capacity message when slot counts are unavailable", async () => {
    const fallback = "Choose a template with enough material slots.";
    const error = Object.assign(new Error("Request failed with status code 422"), {
      config: { method: "post", url: "/convert/export-materials" },
      response: {
        status: 422,
        data: { detail: { code: "template_slot_capacity", message: fallback } },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/export-materials", {})).rejects.toMatchObject({
      message: fallback,
    });
  });

  it.each([
    "future_validation_code",
    "constructor",
    "toString",
    "__proto__",
  ])(
    "uses the safe fallback message for unknown structured code %s",
    async (errorCode) => {
      useSettingsStore.setState({ language: "zh" });
      const safeFallback = "This validation message is safe to display.";
      const error = new Error("Request failed with status code 422");
      Object.assign(error, {
        config: { method: "post", url: "/convert/generate" },
        response: {
          status: 422,
          data: {
            detail: {
              error: errorCode,
              message: safeFallback,
            },
          },
        },
      });
      apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

      await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
        message: safeFallback,
      });
    },
  );

  it("uses structured detail object messages before HTTP status fallbacks", async () => {
    const error = new Error("Request failed with status code 422");
    Object.assign(error, {
      config: { method: "post", url: "/convert/preview" },
      response: {
        status: 422,
        data: {
          detail: {
            error: "preview_cache_size_limit_exceeded",
            message:
              "Estimated preview cache arrays exceed the configured limit.",
            estimate_bytes: 640_000_000,
            max_bytes: 536_870_912,
            estimated_width: 2000,
            estimated_height: 2000,
            estimated_layers: 5,
          },
        },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/preview", {})).rejects.toMatchObject({
      message: expect.stringContaining(
        "Estimated preview cache arrays exceed the configured limit.",
      ),
    });

    expect(postClientLog).toHaveBeenCalledWith(
      "api: request failed",
      expect.objectContaining({
        details: expect.objectContaining({
          status_code: 422,
          error_message: expect.stringContaining(
            "Estimated preview cache arrays exceed the configured limit.",
          ),
        }),
      }),
    );
  });

  it("uses a top-level message before a structured detail error code", async () => {
    const error = new Error("Request failed with status code 409");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 409,
        data: {
          detail: { error: "preview_cache_missing" },
          message: "Preview cache is missing. Run preview again.",
        },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
      message: "Preview cache is missing. Run preview again.",
    });
  });

  it("uses a readable HTTP fallback when the response has no detail", async () => {
    const error = new Error("Request failed with status code 503");
    Object.assign(error, {
      config: { method: "get", url: "/system/settings" },
      response: { status: 503, data: {} },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.get("/system/settings")).rejects.toMatchObject({
      message: "Server temporarily unavailable. Please try again later.",
    });
  });

  it("explains quota/payment failures with the HTTP 402 fallback", async () => {
    const error = new Error("Request failed with status code 402");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: { status: 402, data: {} },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
      message:
        "This action requires an available quota or payment before it can continue.",
    });
  });

  it("keeps backend details where numbers are part of the real message", async () => {
    const error = new Error("Request failed with status code 422");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: { status: 422, data: { detail: "value must be <= 500" } },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    expect(rejected).toMatchObject({
      message: "value must be <= 500",
    });
    expect(rejected.response?.data?.detail).toBe("value must be <= 500");
  });

  it("still replaces generic request-failed status details", async () => {
    const error = new Error("Request failed with status code 500");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 500,
        data: { detail: "Request failed with status code 500" },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
      message: "The server hit an internal error. Try again later, or submit feedback if it keeps happening.",
    });
  });

  it("uses a language fallback for unknown client errors without exposing status numbers", async () => {
    const error = new Error("Request failed with status code 418");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: { status: 418, data: {} },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
      message:
        "The server did not accept the request. Check the current input, permissions, or resource availability.",
    });
  });

  it("normalizes bare generic HTTP errors for store-level callers", () => {
    expect(
      apiErrorToVisibleMessage(
        new Error("Request failed with status code 500"),
      ),
    ).toBe("The server hit an internal error. Try again later, or submit feedback if it keeps happening.");
    expect(
      apiErrorToVisibleMessage(new Error("Request failed with status code 422")),
    ).toBe("The request is missing required data or contains invalid values.");
    expect(
      apiErrorToVisibleMessage(new Error("Vectorizer dependency missing")),
    ).toBe("Vectorizer dependency missing");
  });

  it("normalizes bare network and timeout errors for visible UI callers", () => {
    for (const error of [
      new Error("Network Error"),
      new TypeError("Failed to fetch"),
      new Error("timeout of 30000ms exceeded"),
    ]) {
      const message = apiErrorToVisibleMessage(error);
      expect(message).toBe(
        "The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again.",
      );
      expect(message).not.toMatch(/Network Error|Failed to fetch|timeout of/i);
    }
  });

  it("uses the provided fallback for bare non-Error rejection values", () => {
    expect(apiErrorToVisibleMessage("string error", "批量处理失败")).toBe(
      "批量处理失败",
    );
    expect(
      apiErrorToVisibleMessage(
        "AxiosError: Request failed with status code 500",
        "向量化失败",
      ),
    ).toBe("向量化失败");
    expect(apiErrorToVisibleMessage({ message: "opaque object" }, "操作失败")).toBe(
      "操作失败",
    );
  });

  it("preserves readable response details on non-Error response-shaped values", () => {
    expect(
      apiErrorToVisibleMessage(
        {
          response: {
            status: 422,
            data: { detail: "请先选择要处理的图片。" },
          },
        },
        "操作失败",
      ),
    ).toBe("请先选择要处理的图片。");
  });

  it("builds resource URLs without double-prefixing API file paths", () => {
    expect(buildApiResourceUrl("/api/files/model.3mf")).toBe("/api/files/model.3mf");
    expect(buildApiResourceUrl("/files/model.3mf")).toBe("/api/files/model.3mf");

    apiClient.defaults.baseURL = "https://host.example/lumina/api";

    expect(buildApiResourceUrl("/api/files/model.3mf")).toBe(
      "https://host.example/lumina/api/files/model.3mf",
    );
    expect(buildApiResourceUrl("files/model.3mf")).toBe(
      "https://host.example/lumina/api/files/model.3mf",
    );
  });

  it("turns failed resource downloads into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: jsonHeaders,
      json: () => Promise.resolve({ detail: "Not Found" }),
    }) as unknown as typeof fetch;

    try {
      await expect(downloadResourceBlob("/api/files/missing")).rejects.toThrow(
        "The requested resource was not found or has expired.",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("records failed resource downloads in client logs and action history", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: new Headers({
        "content-type": "application/json",
        "x-request-id": "req-resource-404",
      }),
      json: () => Promise.resolve({ detail: "File not found or expired" }),
    }) as unknown as typeof fetch;

    try {
      await expect(downloadResourceBlob("/api/files/missing")).rejects.toThrow(
        "File not found or expired",
      );

      expect(postClientLog).toHaveBeenCalledWith(
        "api: request failed",
        expect.objectContaining({
          scope: "api",
          phase: "request-failed",
          method: "error",
          details: expect.objectContaining({
            method: "GET",
            url: "/api/files/missing",
            status_code: 404,
            request_id: "req-resource-404",
            error_message: "File not found or expired",
          }),
        }),
      );
      expect(useActionHistoryStore.getState().history.at(-1)?.error).toEqual(
        expect.objectContaining({
          status_code: 404,
          path: "/api/files/missing",
          request_id: "req-resource-404",
          error_message: "File not found or expired",
        }),
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("uses structured detail object messages for failed resource downloads", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 422,
      headers: jsonHeaders,
      json: () =>
        Promise.resolve({
          detail: {
            error: "preview_cache_size_limit_exceeded",
            message:
              "Estimated preview cache arrays exceed the configured limit.",
          },
        }),
    }) as unknown as typeof fetch;

    try {
      await expect(downloadResourceBlob("/api/files/preview")).rejects.toThrow(
        "Estimated preview cache arrays exceed the configured limit.",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("turns resource download network failures into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch")) as unknown as typeof fetch;

    try {
      let caught: unknown;
      try {
        await downloadResourceBlob("/api/files/model");
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(Error);
      expect((caught as Error).message).toBe(
        "The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again.",
      );
      expect((caught as Error).message).not.toContain("Failed to fetch");
      expect((caught as Error).cause).toBeInstanceOf(TypeError);
      expect(
        (caught as Error & { response?: { status: number | null } }).response
          ?.status,
      ).toBeNull();
      expect(
        (
          (caught as Error & { response?: { data: { detail?: unknown } } })
            .response?.data.detail
        ),
      ).toBe("The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again.");
      expect(
        (
          (caught as Error & { response?: { data: { url?: unknown } } })
            .response?.data.url
        ),
      ).toBe("/api/files/model");
      expect(postClientLog).toHaveBeenCalledWith(
        "api: request failed",
        expect.objectContaining({
          scope: "api",
          phase: "request-failed",
          method: "error",
          details: expect.objectContaining({
            method: "GET",
            url: "/api/files/model",
            status_code: null,
            request_id: null,
            error_message:
              "The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again.",
          }),
        }),
      );
      expect(useActionHistoryStore.getState().history).toHaveLength(0);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("turns interrupted resource body reads into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: { get: () => "application/octet-stream" },
      blob: () =>
        Promise.reject(
          new TypeError("NetworkError when attempting to fetch resource."),
        ),
    }) as unknown as typeof fetch;

    try {
      let caught: unknown;
      try {
        await downloadResourceBlob("/api/files/model");
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(Error);
      expect((caught as Error).message).toBe(
        "The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again.",
      );
      expect((caught as Error).message).not.toContain("NetworkError");
      expect((caught as Error).cause).toBeInstanceOf(TypeError);
      expect(
        (caught as Error & { response?: { status: number | null } }).response
          ?.status,
      ).toBeNull();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("validates resource downloads with a bounded range request", async () => {
    const originalFetch = globalThis.fetch;
    const cancel = vi.fn().mockResolvedValue(undefined);
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 206,
      headers: { get: () => "application/octet-stream" },
      body: { cancel },
    }) as unknown as typeof fetch;

    try {
      await expect(
        assertResourceDownloadAvailable("/api/files/model"),
      ).resolves.toBeUndefined();
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/files/model",
        expect.objectContaining({
          headers: expect.any(Headers),
        }),
      );
      const init = vi.mocked(globalThis.fetch).mock.calls[0]?.[1] as RequestInit;
      expect((init.headers as Headers).get("Range")).toBe("bytes=0-0");
      expect(cancel).toHaveBeenCalledOnce();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("turns resource validation network failures into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch")) as unknown as typeof fetch;

    try {
      let caught: unknown;
      try {
        await assertResourceDownloadAvailable("/api/files/model");
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(Error);
      expect((caught as Error).message).toBe(
        "The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again.",
      );
      expect((caught as Error).message).not.toContain("Failed to fetch");
      expect((caught as Error).cause).toBeInstanceOf(TypeError);
      expect(
        (caught as Error & { response?: { status: number | null } }).response
          ?.status,
      ).toBeNull();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("turns failed resource validation into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: jsonHeaders,
      json: () => Promise.resolve({ detail: "File not found or expired" }),
    }) as unknown as typeof fetch;

    try {
      await expect(
        assertResourceDownloadAvailable("/api/files/missing-model"),
      ).rejects.toThrow("File not found or expired");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
