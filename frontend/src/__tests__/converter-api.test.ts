import { describe, it, expect, vi, beforeEach } from "vitest";
import apiClient from "../api/client";
import {
  convertPreview,
  convertGenerate,
  fetchLutList,
  getFileUrl,
} from "../api/converter";
import {
  ColorMode,
  ModelingMode,
  StructureMode,
  type ConvertPreviewRequest,
  type ConvertGenerateRequest,
} from "../api/types";

vi.mock("../api/client", () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}));

const mockPost = vi.mocked(apiClient.post);
const mockGet = vi.mocked(apiClient.get);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("convertPreview", () => {
  const previewParams: ConvertPreviewRequest = {
    lut_name: "test-lut",
    target_width_mm: 80,
    auto_bg: true,
    bg_tol: 40,
    color_mode: ColorMode.FOUR_COLOR,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
    quantize_colors: 48,
    enable_cleanup: true,
  };

  it("builds correct FormData and calls POST /convert/preview", async () => {
    const fakeResponse = {
      session_id: "sess-123",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/prev-abc",
      palette: [],
      dimensions: { width: 200, height: 150 },
    };
    mockPost.mockResolvedValueOnce({ data: fakeResponse });

    const file = new File(["img-data"], "photo.png", { type: "image/png" });
    const result = await convertPreview(file, previewParams);

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, formData, config] = mockPost.mock.calls[0];
    expect(url).toBe("/convert/preview");
    expect(formData).toBeInstanceOf(FormData);

    const fd = formData as FormData;
    expect(fd.get("image")).toBeInstanceOf(File);
    expect(fd.get("lut_name")).toBe("test-lut");
    expect(fd.get("target_width_mm")).toBe("80");
    expect(fd.get("auto_bg")).toBe("true");
    expect(fd.get("bg_tol")).toBe("40");
    expect(fd.get("color_mode")).toBe(ColorMode.FOUR_COLOR);
    expect(fd.get("modeling_mode")).toBe(ModelingMode.HIGH_FIDELITY);
    expect(fd.get("quantize_colors")).toBe("48");
    expect(fd.get("enable_cleanup")).toBe("true");

    // 不应设置 responseType: blob（后端返回 JSON）
    expect(config).toMatchObject({ timeout: 0 });
    // 确认没有手动设置 Content-Type（让 axios 自动处理 FormData boundary）
    expect(config).not.toHaveProperty("headers");

    expect(result).toEqual(fakeResponse);
    expect(result.session_id).toBe("sess-123");
    expect(result.preview_url).toBe("/api/files/prev-abc");
  });

  it("propagates network errors", async () => {
    mockPost.mockRejectedValueOnce(new Error("Network Error"));

    const file = new File(["x"], "a.png", { type: "image/png" });
    await expect(convertPreview(file, previewParams)).rejects.toThrow(
      "Network Error"
    );
  });
});

describe("convertGenerate", () => {
  const generateParams: ConvertGenerateRequest = {
    lut_name: "gen-lut",
    target_width_mm: 100,
    auto_bg: false,
    bg_tol: 30,
    color_mode: ColorMode.EIGHT_COLOR,
    modeling_mode: ModelingMode.PIXEL,
    quantize_colors: 64,
    enable_cleanup: false,
    spacer_thick: 1.2,
    structure_mode: StructureMode.DOUBLE_SIDED,
    separate_backing: true,
    add_loop: true,
    loop_width: 4,
    loop_length: 8,
    loop_hole: 2.5,
    enable_relief: false,
    heightmap_max_height: 5.0,
    enable_outline: true,
    outline_width: 2.0,
    enable_cloisonne: false,
    wire_width_mm: 0.4,
    wire_height_mm: 0.4,
    enable_coating: true,
    coating_height_mm: 0.08,
  };

  it("sends JSON body with session_id and params", async () => {
    const fakeResponse = {
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/dl-123",
      preview_3d_url: "/api/files/glb-456",
    };
    mockPost.mockResolvedValueOnce({ data: fakeResponse });

    const result = await convertGenerate("sess-abc", generateParams);

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, body, config] = mockPost.mock.calls[0];
    expect(url).toBe("/convert/generate");

    // 后端期望 JSON body: { session_id, params }
    expect(body).toEqual({
      session_id: "sess-abc",
      params: generateParams,
    });

    expect(config).toMatchObject({ timeout: 0 });
    expect(result).toEqual(fakeResponse);
  });

  it("includes optional fields in params when provided", async () => {
    const paramsWithOptionals: ConvertGenerateRequest = {
      ...generateParams,
      color_height_map: { "#FF0000": 1.5, "#00FF00": 2.0 },
      replacement_regions: [
        {
          quantized_hex: "#AAA",
          matched_hex: "#BBB",
          replacement_hex: "#CCC",
        },
      ],
    };
    mockPost.mockResolvedValueOnce({
      data: { status: "ok", message: "done", download_url: "/api/files/x" },
    });

    await convertGenerate("sess-xyz", paramsWithOptionals);

    const body = mockPost.mock.calls[0][1] as { session_id: string; params: ConvertGenerateRequest };
    expect(body.params.color_height_map).toEqual({
      "#FF0000": 1.5,
      "#00FF00": 2.0,
    });
    expect(body.params.replacement_regions).toEqual([
      { quantized_hex: "#AAA", matched_hex: "#BBB", replacement_hex: "#CCC" },
    ]);
  });

  it("propagates 4xx errors", async () => {
    const axiosError = new Error("Request failed with status code 422") as Error & {
      response?: { status: number; data: { detail: string } };
      isAxiosError?: boolean;
    };
    axiosError.response = { status: 422, data: { detail: "Invalid params" } };
    axiosError.isAxiosError = true;
    mockPost.mockRejectedValueOnce(axiosError);

    await expect(convertGenerate("sess-1", generateParams)).rejects.toThrow(
      "Request failed with status code 422"
    );
  });

  it("propagates 5xx errors", async () => {
    const serverError = new Error("Request failed with status code 500") as Error & {
      response?: { status: number };
      isAxiosError?: boolean;
    };
    serverError.response = { status: 500 };
    serverError.isAxiosError = true;
    mockPost.mockRejectedValueOnce(serverError);

    await expect(convertGenerate("sess-2", generateParams)).rejects.toThrow(
      "Request failed with status code 500"
    );
  });
});

describe("fetchLutList", () => {
  it("returns correct LutListResponse", async () => {
    const mockData = {
      luts: [
        { name: "lut-a", color_mode: ColorMode.FOUR_COLOR, path: "/a.npy" },
        { name: "lut-b", color_mode: ColorMode.BW, path: "/b.npy" },
      ],
    };
    mockGet.mockResolvedValueOnce({ data: mockData });

    const result = await fetchLutList();

    expect(mockGet).toHaveBeenCalledWith("/lut/list", { timeout: 5_000 });
    expect(result).toEqual(mockData);
    expect(result.luts).toHaveLength(2);
    expect(result.luts[0].name).toBe("lut-a");
    expect(result.luts[0].color_mode).toBe(ColorMode.FOUR_COLOR);
  });

  it("propagates network errors", async () => {
    mockGet.mockRejectedValueOnce(new Error("Network Error"));
    await expect(fetchLutList()).rejects.toThrow("Network Error");
  });
});

describe("getFileUrl", () => {
  it("constructs correct URL from file_id", () => {
    expect(getFileUrl("abc123")).toBe("/api/files/abc123");
  });

  it("handles file_id with special characters", () => {
    expect(getFileUrl("file-2024-01-01_model")).toBe(
      "/api/files/file-2024-01-01_model"
    );
  });
});
