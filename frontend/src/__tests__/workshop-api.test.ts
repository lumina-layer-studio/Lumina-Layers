import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AxiosRequestConfig } from "axios";

const getMock = vi.hoisted(() => vi.fn());
const postMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  default: {
    get: getMock,
    post: postMock,
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import { workshopApi } from "../api/workshop";

describe("Workshop API resource paths", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not duplicate the shared /api prefix for module details", async () => {
    getMock.mockResolvedValue({
      data: {
        module_id: "fixture.hello",
        version: "1.0.0",
        readme_markdown: "# Fixture",
        license_text: "MIT",
        gallery_urls: [],
      },
    });

    await workshopApi.fetchDetails(
      "/api/workshop/v1/modules/fixture.hello/1.0.0/details",
    );

    expect(getMock).toHaveBeenCalledWith(
      "/workshop/v1/modules/fixture.hello/1.0.0/details",
    );
  });

  it("reports local upload bytes and polls install progress on an HTTP LAN origin", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("crypto", {
      getRandomValues: (buffer: Uint8Array) => buffer.fill(42),
    });
    let deliverInstall: (() => void) | undefined;
    try {
      postMock.mockImplementation((_url, _payload, options: AxiosRequestConfig) => {
        options.onUploadProgress?.({
          loaded: 1024, total: 4096, bytes: 1024, rate: 1024, estimated: 3, lengthComputable: true,
        });
        return new Promise((resolve) => { deliverInstall = () => resolve({ data: { module: null } }); });
      });
      getMock.mockResolvedValue({ data: { phase: "installing" } });
      const listener = vi.fn();
      const request = workshopApi.installLocal(new File(["fixture"], "fixture.hello.lumina-workshop"), listener);
      const id = "2a".repeat(16);
      expect(postMock.mock.calls[0][2].params.progress_id).toBe(id);
      expect(listener).toHaveBeenCalledWith(expect.objectContaining({
        phase: "uploading", download: expect.objectContaining({
          received_bytes: 1024, total_bytes: 4096, bytes_per_second: 1024, eta_seconds: 3,
        }),
      }));
      await vi.advanceTimersByTimeAsync(300);
      expect(getMock).toHaveBeenCalledWith(`/workshop/v1/install/progress/${id}`, { suppressErrorTicket: true });
      expect(listener).toHaveBeenCalledWith({ phase: "installing" });
      deliverInstall?.();
      await request;
      await vi.advanceTimersByTimeAsync(1_000);
      expect(getMock).toHaveBeenCalledTimes(1);
    } finally {
      deliverInstall?.();
      vi.unstubAllGlobals();
      vi.useRealTimers();
    }
  });
});
