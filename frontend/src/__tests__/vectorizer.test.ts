// @vitest-environment jsdom

/**
 * Unit tests for vectorizerStore and buildFileUrl.
 * vectorizerStore 和 buildFileUrl 单元测试。
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { StrictMode, createElement } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useVectorizerStore } from "../stores/vectorizerStore";
import { useSettingsStore } from "../stores/settingsStore";
import VectorizerPanel, { buildFileUrl } from "../components/VectorizerPanel";
import { translations } from "../i18n/translations";
import { vectorizeImage } from "../api/vectorizer";

const {
  mockedApiClient,
  apiErrorToVisibleMessageMock,
  downloadResourceBlobMock,
  loadVectorizedSvgIntoConverterSpy,
  setWidgetActiveTabSpy,
} = vi.hoisted(() => ({
  mockedApiClient: {
    defaults: { baseURL: "/api" },
    post: vi.fn(),
    get: vi.fn(),
  },
  apiErrorToVisibleMessageMock: vi.fn((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    if (message === "Request failed with status code 500") {
      return "The server hit an internal error. Try again later, or submit feedback if it keeps happening.";
    }
    if (message === "Request failed with status code 422") {
      return "The request is missing required data or contains invalid values.";
    }
    return message;
  }),
  downloadResourceBlobMock: vi.fn(),
  loadVectorizedSvgIntoConverterSpy: vi.fn(),
  setWidgetActiveTabSpy: vi.fn(),
}));

// Mock apiClient for buildFileUrl tests
vi.mock("../api/client", () => ({
  default: mockedApiClient,
  buildApiResourceUrl: (relativePath: string) => {
    const base = mockedApiClient.defaults.baseURL ?? "";
    if (!relativePath) return base;
    if (/^https?:\/\//i.test(relativePath)) return relativePath;
    const normalizedPath = relativePath.startsWith("/") ? relativePath : `/${relativePath}`;
    if (!base) return normalizedPath;
    const normalizedBase = base.replace(/\/+$/, "");
    const baseIsAbsolute = /^https?:\/\//i.test(normalizedBase);
    if (normalizedPath.startsWith("/api/")) {
      if (!baseIsAbsolute && normalizedBase === "/api") {
        return normalizedPath;
      }
      if (baseIsAbsolute) {
        const parsedBase = new URL(normalizedBase);
        const pathPrefixMatch = parsedBase.pathname.match(/^(.*)\/api$/);
        const pathPrefixRaw = pathPrefixMatch?.[1] ?? "";
        const pathPrefix = pathPrefixRaw === "/" ? "" : pathPrefixRaw.replace(/\/+$/, "");
        return `${parsedBase.origin}${pathPrefix}${normalizedPath}`;
      }
    }
    return `${normalizedBase.replace(/\/+$/, "")}/${normalizedPath.replace(/^\/+/, "")}`;
  },
  apiErrorToVisibleMessage: apiErrorToVisibleMessageMock,
  downloadResourceBlob: downloadResourceBlobMock,
}));

// Mock vectorizeImage to avoid real API calls
vi.mock("../api/vectorizer", () => ({
  vectorizeImage: vi.fn(),
}));

// Mock converterStore and widgetStore for send-to-converter tests
vi.mock("../stores/converter", () => ({
  useConverterStore: {
    getState: vi.fn(() => ({
      loadVectorizedSvgIntoConverter: loadVectorizedSvgIntoConverterSpy,
    })),
  },
}));

vi.mock("../stores/widgetStore", () => ({
  useWidgetStore: {
    getState: vi.fn(() => ({
      setActiveTab: setWidgetActiveTabSpy,
    })),
  },
}));

function resetStore() {
  useVectorizerStore.getState().reset();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getPanelButtonByKey(key: string): HTMLElement {
  const entry = translations[key];
  const labels = [entry?.zh, entry?.en, key].filter(
    (label): label is string => typeof label === "string" && label.length > 0,
  );
  const namePattern = new RegExp(`^(?:${labels.map(escapeRegExp).join("|")})$`, "i");
  return screen.getByRole("button", { name: namePattern });
}

describe("vectorizerStore", () => {
  beforeEach(() => {
    cleanup();
    resetStore();
    mockedApiClient.defaults.baseURL = "/api";
    vi.clearAllMocks();
    downloadResourceBlobMock.mockReset();
    useSettingsStore.setState({ language: "en" });
  });

  // --- Initial state ---
  it("has correct initial state", () => {
    const state = useVectorizerStore.getState();
    expect(state.imageFile).toBeNull();
    expect(state.imagePreviewUrl).toBeNull();
    expect(state.isProcessing).toBe(false);
    expect(state.error).toBeNull();
    expect(state.result).toBeNull();
    expect(state.abortController).toBeNull();
  });

  it("has default params with all 23 fields", () => {
    const { params } = useVectorizerStore.getState();
    const keys = Object.keys(params);
    expect(keys).toHaveLength(23);
    expect(params.num_colors).toBe(0);
    expect(params.smoothness).toBe(0.5);
    expect(params.detail_level).toBe(-1);
  });

  // --- setParam ---
  it("setParam updates a single parameter", () => {
    useVectorizerStore.getState().setParam("num_colors", 32);
    expect(useVectorizerStore.getState().params.num_colors).toBe(32);
  });

  it("setParam does not affect other parameters", () => {
    const before = { ...useVectorizerStore.getState().params };
    useVectorizerStore.getState().setParam("smoothness", 0.9);
    const after = useVectorizerStore.getState().params;
    expect(after.smoothness).toBe(0.9);
    expect(after.num_colors).toBe(before.num_colors);
    expect(after.detail_level).toBe(before.detail_level);
  });

  // --- cancel ---
  it("ignores a completed request from the image replaced by a project restore", async () => {
    let finish!: (value: Awaited<ReturnType<typeof vectorizeImage>>) => void;
    vi.mocked(vectorizeImage).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    useVectorizerStore.getState().setImageFile(new File(["old"], "old.png"));
    const pending = useVectorizerStore.getState().submit();
    const restored = new File(["new"], "restored.png");
    useVectorizerStore.getState().setImageFile(restored);
    finish({ status: "ok", message: "old", svg_url: "/api/files/old", width: 1, height: 1, num_shapes: 1, num_colors: 1, palette: [] });
    await pending;
    expect(useVectorizerStore.getState().imageFile).toBe(restored);
    expect(useVectorizerStore.getState().result).toBeNull();
  });

  it("cancel sets isProcessing=false and abortController=null", () => {
    // Simulate processing state
    const controller = new AbortController();
    useVectorizerStore.setState({
      isProcessing: true,
      abortController: controller,
    });

    useVectorizerStore.getState().cancel();

    const state = useVectorizerStore.getState();
    expect(state.isProcessing).toBe(false);
    expect(state.abortController).toBeNull();
  });

  it("cancel aborts the active AbortController", () => {
    const controller = new AbortController();
    const abortSpy = vi.spyOn(controller, "abort");
    useVectorizerStore.setState({
      isProcessing: true,
      abortController: controller,
    });

    useVectorizerStore.getState().cancel();
    expect(abortSpy).toHaveBeenCalled();
  });

  it("cancel is a no-op when not processing", () => {
    // Should not throw
    useVectorizerStore.getState().cancel();
    expect(useVectorizerStore.getState().isProcessing).toBe(false);
  });

  // --- reset ---
  it("reset restores all state to defaults", () => {
    // Mutate state
    useVectorizerStore.setState({
      isProcessing: true,
      error: "some error",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/files/test.svg",
        width: 100,
        height: 100,
        num_shapes: 10,
        num_colors: 5,
        palette: ["#ff0000"],
      },
    });
    useVectorizerStore.getState().setParam("num_colors", 128);

    useVectorizerStore.getState().reset();

    const state = useVectorizerStore.getState();
    expect(state.imageFile).toBeNull();
    expect(state.imagePreviewUrl).toBeNull();
    expect(state.isProcessing).toBe(false);
    expect(state.error).toBeNull();
    expect(state.result).toBeNull();
    expect(state.params.num_colors).toBe(0);
    expect(state.params.smoothness).toBe(0.5);
  });

  // --- submit without image ---
  it("submit does nothing when imageFile is null", async () => {
    await useVectorizerStore.getState().submit();
    expect(useVectorizerStore.getState().isProcessing).toBe(false);
  });

  it("normalizes generic HTTP status errors from submit", async () => {
    useVectorizerStore.setState({
      imageFile: new File(["img"], "vectorizer.png", { type: "image/png" }),
    });
    vi.mocked(vectorizeImage).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useVectorizerStore.getState().submit();

    expect(apiErrorToVisibleMessageMock).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "Request failed with status code 500",
      }),
    );
    expect(useVectorizerStore.getState().error).toBe(
      "The server hit an internal error. Try again later, or submit feedback if it keeps happening.",
    );
    expect(useVectorizerStore.getState().error).not.toContain("status code 500");
  });
});

describe("VectorizerPanel send-to-converter", () => {
  beforeEach(() => {
    cleanup();
    resetStore();
    mockedApiClient.defaults.baseURL = "/api";
    vi.clearAllMocks();
  });

  it("uses a full-width scroll area with a wide split content layout", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 2400 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 1200 });
    Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: 1 });

    const { container } = render(createElement(VectorizerPanel));
    const scrollArea = container.firstElementChild as HTMLElement;
    const contentShell = scrollArea.firstElementChild as HTMLElement;
    const splitLayout = contentShell.firstElementChild as HTMLElement;

    expect(scrollArea).toHaveClass("panel-surface", "h-full", "w-full", "overflow-auto");
    expect(scrollArea).not.toHaveClass("mx-auto");
    expect(scrollArea).not.toHaveClass("max-w-4xl");
    expect(contentShell).toHaveClass("mx-auto", "w-full", "max-w-[96rem]");
    expect(splitLayout).toHaveClass(
      "grid",
      "min-h-0",
      "gap-5",
      "xl:grid-cols-[minmax(22rem,30rem)_minmax(0,1fr)]",
    );
  });

  it("fetches svg with normalized url and forwards it to converter tab", async () => {
    const svgBlob = new Blob(["<svg/>"], { type: "image/svg+xml" });
    downloadResourceBlobMock.mockResolvedValueOnce(svgBlob);

    useVectorizerStore.setState({
      imagePreviewUrl: "blob:original-preview",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/api/files/vectorized.svg",
        width: 100,
        height: 100,
        num_shapes: 12,
        num_colors: 4,
        palette: ["#000000", "#ffffff"],
      },
    });

    render(createElement(VectorizerPanel));

    fireEvent.click(getPanelButtonByKey("vec.send_to_converter"));

    await waitFor(() => {
      expect(downloadResourceBlobMock).toHaveBeenCalledWith(
        "/api/files/vectorized.svg",
      );
    });

    await waitFor(() => {
      expect(loadVectorizedSvgIntoConverterSpy).toHaveBeenCalledTimes(1);
    });

    const fileArg = loadVectorizedSvgIntoConverterSpy.mock.calls[0]?.[0];
    expect(fileArg).toBeInstanceOf(File);
    expect(fileArg.name).toBe("vectorized.svg");
    expect(fileArg.type).toBe("image/svg+xml");

    expect(setWidgetActiveTabSpy).toHaveBeenCalledWith("converter");
  });

  it("shows a readable error when sending an expired svg to the converter fails", async () => {
    downloadResourceBlobMock.mockRejectedValueOnce(
      new Error("The requested resource was not found or has expired."),
    );

    useVectorizerStore.setState({
      imagePreviewUrl: "blob:original-preview",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/api/files/expired.svg",
        width: 100,
        height: 100,
        num_shapes: 12,
        num_colors: 4,
        palette: ["#000000", "#ffffff"],
      },
    });

    render(createElement(VectorizerPanel));

    fireEvent.click(getPanelButtonByKey("vec.send_to_converter"));

    expect(
      await screen.findByText(/The requested resource was not found or has expired\./),
    ).toBeInTheDocument();
    expect(loadVectorizedSvgIntoConverterSpy).not.toHaveBeenCalled();
    expect(setWidgetActiveTabSpy).not.toHaveBeenCalled();
  });

  it("normalizes raw HTTP status text when sending svg to the converter fails", async () => {
    downloadResourceBlobMock.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    useVectorizerStore.setState({
      imagePreviewUrl: "blob:original-preview",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/api/files/expired.svg",
        width: 100,
        height: 100,
        num_shapes: 12,
        num_colors: 4,
        palette: ["#000000", "#ffffff"],
      },
    });

    render(createElement(VectorizerPanel));

    fireEvent.click(getPanelButtonByKey("vec.send_to_converter"));

    expect(
      await screen.findByText(
        "The server hit an internal error. Try again later, or submit feedback if it keeps happening.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Request failed with status code 500/i)).not.toBeInTheDocument();
    expect(loadVectorizedSvgIntoConverterSpy).not.toHaveBeenCalled();
  });

  it("downloads svg after validating the resource fetch succeeds", async () => {
    const svgBlob = new Blob(["<svg/>"], { type: "image/svg+xml" });
    downloadResourceBlobMock.mockResolvedValueOnce(svgBlob);

    useVectorizerStore.setState({
      imagePreviewUrl: "blob:original-preview",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/api/files/vectorized.svg",
        width: 100,
        height: 100,
        num_shapes: 12,
        num_colors: 4,
        palette: ["#000000", "#ffffff"],
      },
    });

    render(createElement(VectorizerPanel));

    const originalCreateElement = document.createElement.bind(document);
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    const anchorMock = {
      href: "",
      download: "",
      click: vi.fn(),
      remove: vi.fn(),
      style: {},
    } as unknown as HTMLAnchorElement;
    const appendChildSpy = vi
      .spyOn(document.body, "appendChild")
      .mockImplementation((node: Node) => node);
    const createObjectURLSpy = vi.fn().mockReturnValue("blob:download-svg");
    const revokeObjectURLSpy = vi.fn();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectURLSpy,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURLSpy,
    });

    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string, options?: ElementCreationOptions) => {
        if (tagName.toLowerCase() === "a") {
          return anchorMock;
        }
        return originalCreateElement(tagName, options);
      });

    try {
      fireEvent.click(getPanelButtonByKey("vec.download_svg"));
      await waitFor(() => {
        expect(downloadResourceBlobMock).toHaveBeenCalledWith(
          "/api/files/vectorized.svg",
        );
      });
    } finally {
      createElementSpy.mockRestore();
      appendChildSpy.mockRestore();
      Object.defineProperty(URL, "createObjectURL", {
        configurable: true,
        value: originalCreateObjectURL,
      });
      Object.defineProperty(URL, "revokeObjectURL", {
        configurable: true,
        value: originalRevokeObjectURL,
      });
    }

    expect(createObjectURLSpy).toHaveBeenCalledWith(svgBlob);
    expect(anchorMock.href).toBe("blob:download-svg");
    expect(anchorMock.download).toBe("vectorized.svg");
    expect(anchorMock.click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:download-svg");
  });

  it("shows a readable error instead of downloading an expired svg response", async () => {
    downloadResourceBlobMock.mockRejectedValueOnce(
      new Error("The requested resource was not found or has expired."),
    );

    useVectorizerStore.setState({
      imagePreviewUrl: "blob:original-preview",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/api/files/expired.svg",
        width: 100,
        height: 100,
        num_shapes: 12,
        num_colors: 4,
        palette: ["#000000", "#ffffff"],
      },
    });

    render(createElement(VectorizerPanel));

    fireEvent.click(getPanelButtonByKey("vec.download_svg"));

    expect(
      await screen.findByText(/The requested resource was not found or has expired\./),
    ).toBeInTheDocument();
  });

  it("normalizes raw HTTP status text when svg download fails", async () => {
    downloadResourceBlobMock.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    useVectorizerStore.setState({
      imagePreviewUrl: "blob:original-preview",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/api/files/expired.svg",
        width: 100,
        height: 100,
        num_shapes: 12,
        num_colors: 4,
        palette: ["#000000", "#ffffff"],
      },
    });

    render(createElement(VectorizerPanel));

    fireEvent.click(getPanelButtonByKey("vec.download_svg"));

    expect(
      await screen.findByText(
        "The server hit an internal error. Try again later, or submit feedback if it keeps happening.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Request failed with status code 500/i)).not.toBeInTheDocument();
  });

  it("does not reset vectorizer resources during StrictMode initial mount", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const abortSpy = vi.spyOn(controller, "abort");
    const originalRevokeObjectURL = URL.revokeObjectURL;
    const revokeObjectURLSpy = vi.fn();

    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURLSpy,
    });

    useVectorizerStore.setState({
      imageFile: new File(["img"], "vectorizer.png", { type: "image/png" }),
      imagePreviewUrl: "blob:vectorizer-preview",
      isProcessing: true,
      abortController: controller,
    });

    render(createElement(StrictMode, null, createElement(VectorizerPanel)));

    await vi.advanceTimersByTimeAsync(0);

    expect(abortSpy).not.toHaveBeenCalled();
    expect(revokeObjectURLSpy).not.toHaveBeenCalled();
    expect(useVectorizerStore.getState().imagePreviewUrl).toBe("blob:vectorizer-preview");
    expect(useVectorizerStore.getState().abortController).toBe(controller);

    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectURL,
    });
  });

  it("preserves the vectorizer workspace when leaving its tab for another project workflow", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const abortSpy = vi.spyOn(controller, "abort");
    const originalRevokeObjectURL = URL.revokeObjectURL;
    const revokeObjectURLSpy = vi.fn();

    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURLSpy,
    });

    useVectorizerStore.setState({
      imageFile: new File(["img"], "vectorizer.png", { type: "image/png" }),
      imagePreviewUrl: "blob:vectorizer-preview",
      isProcessing: true,
      abortController: controller,
    });

    const view = render(
      createElement(StrictMode, null, createElement(VectorizerPanel)),
    );

    await vi.advanceTimersByTimeAsync(0);

    expect(abortSpy).not.toHaveBeenCalled();
    expect(revokeObjectURLSpy).not.toHaveBeenCalled();

    view.unmount();

    expect(abortSpy).not.toHaveBeenCalled();
    expect(revokeObjectURLSpy).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(0);

    expect(abortSpy).not.toHaveBeenCalled();
    expect(revokeObjectURLSpy).not.toHaveBeenCalled();
    expect(useVectorizerStore.getState().imagePreviewUrl).toBe("blob:vectorizer-preview");
    expect(useVectorizerStore.getState().abortController).toBe(controller);

    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectURL,
    });
  });
});

describe("buildFileUrl", () => {
  beforeEach(() => {
    mockedApiClient.defaults.baseURL = "/api";
  });

  it("prepends apiClient baseURL to legacy relative path", () => {
    const url = buildFileUrl("/files/test.svg");
    expect(url).toBe("/api/files/test.svg");
  });

  it("does not double-prefix api-prefixed paths", () => {
    const url = buildFileUrl("/api/files/test.svg");
    expect(url).toBe("/api/files/test.svg");
  });

  it("preserves path prefix when apiClient baseURL is absolute", () => {
    mockedApiClient.defaults.baseURL = "https://host.example/lumina/api";
    const url = buildFileUrl("/api/files/test.svg");
    expect(url).toBe("https://host.example/lumina/api/files/test.svg");
  });

  it("handles empty relative path", () => {
    const url = buildFileUrl("");
    expect(url).toBe("/api");
  });
});
