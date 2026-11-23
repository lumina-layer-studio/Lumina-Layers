import { describe, expect, it, vi } from "vitest";

import type { GradientCardMaterialBulkImportResponse } from "../api/types";
import {
  WORKSHOP_PERMISSION_NAMES,
  isWorkshopRpcMethod,
} from "../workshop/contracts";
import {
  createSyntheticWorkshopHandlers,
  createWorkshopMaterialImportHandler,
  type WorkshopMaterialImportConfirmation,
  type WorkshopMaterialImportServices,
} from "../workshop/runtime/handlers";
import { WORKSHOP_MATERIAL_IMPORT_MAX_BYTES } from "../workshop/runtime/payloadValidation";
import { createWorkshopRpcHost } from "../workshop/runtime/rpcHost";

const identity = { moduleId: "example.calibration", moduleVersion: "1.0.0" };

function request(payload: unknown, requestId = "import-1") {
  return {
    protocol: "lumina-workshop-rpc",
    version: 1,
    kind: "request",
    requestId,
    method: "material.import",
    payload,
  };
}

function archive(bytes = 16): ArrayBuffer {
  return new Uint8Array(bytes).fill(7).buffer;
}

function importResponse(): GradientCardMaterialBulkImportResponse {
  return {
    status: "success",
    message: "Imported 1 material",
    imported_count: 1,
    imported_materials: [
      { material_name: "PLA White", directory_name: "example-pla-white" },
    ],
  };
}

function httpError(status: number, detail: unknown = "detail") {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: { detail } },
  });
}

function setup(
  overrides: Partial<WorkshopMaterialImportServices> = {},
  permissions: string[] = ["material.import"],
) {
  const prompts: Array<{
    request: WorkshopMaterialImportConfirmation;
    signal: AbortSignal;
    answer(confirmed: boolean): void;
  }> = [];
  const services = {
    confirm: vi.fn(
      (request: WorkshopMaterialImportConfirmation, signal: AbortSignal) =>
        new Promise<boolean>((resolve) => {
          signal.addEventListener("abort", () => resolve(false));
          prompts.push({ request, signal, answer: resolve });
        }),
    ),
    importArchive: vi.fn().mockResolvedValue(importResponse()),
    refreshLibrary: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  const host = createWorkshopRpcHost({
    identity,
    permissions: new Set(permissions),
    handlers: {
      "material.import": createWorkshopMaterialImportHandler(services),
    },
  });
  const nextPrompt = async () => {
    await vi.waitFor(() => expect(prompts.length).toBeGreaterThan(0));
    return prompts.shift()!;
  };
  return { host, services, nextPrompt };
}

describe("Workshop material.import contract", () => {
  it("appends the permission and method to the host-side contract", () => {
    expect(WORKSHOP_PERMISSION_NAMES).toEqual([
      "image.pick",
      "project.storage",
      "color-library.read",
      "handoff.image",
      "material.import",
    ]);
    expect(isWorkshopRpcMethod("material.import")).toBe(true);
  });

  it("denies a module that did not declare material.import", async () => {
    const { host, services } = setup({}, ["color-library.read"]);
    const response = await host.dispatch(
      request({ archiveBytes: archive(), fileName: "material.zip" }),
    );
    expect(response).toMatchObject({
      ok: false,
      error: { code: "permission-denied" },
    });
    expect(services.confirm).not.toHaveBeenCalled();
  });

  it.each([
    [
      "oversized archive",
      { archiveBytes: archive(WORKSHOP_MATERIAL_IMPORT_MAX_BYTES + 1), fileName: "big.zip" },
      "rpc-binary-too-large",
    ],
    ["empty archive", { archiveBytes: new ArrayBuffer(0), fileName: "a.zip" }, "rpc-payload-invalid"],
    ["typed array instead of buffer", { archiveBytes: new Uint8Array(4), fileName: "a.zip" }, "rpc-payload-invalid"],
    ["name without .zip", { archiveBytes: archive(), fileName: "material.json" }, "rpc-payload-invalid"],
    ["path in name", { archiveBytes: archive(), fileName: "../material.zip" }, "rpc-payload-invalid"],
    ["unknown key", { archiveBytes: archive(), fileName: "a.zip", directory: "x" }, "rpc-payload-invalid"],
    [
      "too many summary materials",
      {
        archiveBytes: archive(),
        fileName: "a.zip",
        summary: { materials: Array.from({ length: 17 }, (_, i) => ({ name: `M${i}` })) },
      },
      "rpc-payload-invalid",
    ],
    [
      "long summary string",
      { archiveBytes: archive(), fileName: "a.zip", summary: { materials: [{ name: "x".repeat(121) }] } },
      "rpc-payload-invalid",
    ],
    [
      "multi-line summary text",
      { archiveBytes: archive(), fileName: "a.zip", summary: { materials: [{ name: "PLA\nWhite" }] } },
      "rpc-payload-invalid",
    ],
    [
      "too many notes",
      {
        archiveBytes: archive(),
        fileName: "a.zip",
        summary: { materials: [{ name: "PLA", notes: Array.from({ length: 9 }, () => "n") }] },
      },
      "rpc-payload-invalid",
    ],
    [
      "unknown summary field",
      { archiveBytes: archive(), fileName: "a.zip", summary: { materials: [{ name: "PLA", rgb: [1, 2, 3] }] } },
      "rpc-payload-invalid",
    ],
  ])("rejects a %s before any dialog", async (_label, payload, code) => {
    const { host, services } = setup();
    const response = await host.dispatch(request(payload));
    expect(response).toMatchObject({ ok: false, error: { code } });
    expect(services.confirm).not.toHaveBeenCalled();
    expect(services.importArchive).not.toHaveBeenCalled();
  });

  it("returns cancelled without contacting the server when the user declines", async () => {
    const { host, services, nextPrompt } = setup();
    const pending = host.dispatch(
      request({ archiveBytes: archive(), fileName: "material.zip" }),
    );
    (await nextPrompt()).answer(false);
    expect(await pending).toMatchObject({
      ok: true,
      result: { status: "cancelled" },
    });
    expect(services.importArchive).not.toHaveBeenCalled();
    expect(services.refreshLibrary).not.toHaveBeenCalled();
  });

  it("imports once after confirmation, refreshes the library, and maps the result", async () => {
    const { host, services, nextPrompt } = setup();
    const summary = {
      materials: [{ name: "PLA White", brand: "Example", notes: ["3 readings"] }],
    };
    const pending = host.dispatch(
      request({ archiveBytes: archive(32), fileName: "pla-white.zip", summary }),
    );
    const prompt = await nextPrompt();
    expect(prompt.request).toEqual({
      identity,
      fileName: "pla-white.zip",
      sizeBytes: 32,
      summary,
    });
    prompt.answer(true);
    expect(await pending).toMatchObject({
      ok: true,
      result: {
        status: "imported",
        materials: [{ directoryName: "example-pla-white", name: "PLA White" }],
      },
    });
    expect(services.importArchive).toHaveBeenCalledTimes(1);
    const file = vi.mocked(services.importArchive).mock.calls[0][0];
    expect(file.name).toBe("pla-white.zip");
    expect(file.size).toBe(32);
    expect(services.refreshLibrary).toHaveBeenCalledTimes(1);
  });

  it("still reports success when only the library refresh fails", async () => {
    const { host, nextPrompt } = setup({
      refreshLibrary: vi.fn().mockRejectedValue(new Error("offline")),
    });
    const pending = host.dispatch(
      request({ archiveBytes: archive(), fileName: "material.zip" }),
    );
    (await nextPrompt()).answer(true);
    expect(await pending).toMatchObject({ ok: true, result: { status: "imported" } });
  });

  it.each([
    [httpError(422, "Material archive is missing material.json"), "material-import-invalid", "Material archive is missing material.json", false],
    [httpError(422, "Bad file /tmp/upload-123/archive.zip"), "material-import-invalid", "The material archive is invalid.", false],
    [httpError(422, [{ msg: "field required" }]), "material-import-invalid", "The material archive is invalid.", false],
    [httpError(403), "material-import-unavailable", "Material import is only available on a local or desktop host.", false],
    [httpError(500), "material-import-failed", "The host could not import the material archive.", true],
    [new Error("Network Error"), "material-import-failed", "The host could not import the material archive.", true],
  ])("maps import failure %# to a stable code", async (error, code, message, retryable) => {
    const { host, services, nextPrompt } = setup({
      importArchive: vi.fn().mockRejectedValue(error),
    });
    const pending = host.dispatch(
      request({ archiveBytes: archive(), fileName: "material.zip" }),
    );
    (await nextPrompt()).answer(true);
    expect(await pending).toEqual({
      protocol: "lumina-workshop-rpc",
      version: 1,
      kind: "response",
      requestId: "import-1",
      ok: false,
      error: { code, message, retryable },
    });
    expect(services.refreshLibrary).not.toHaveBeenCalled();
  });

  it("allows one pending import per module", async () => {
    const { host, nextPrompt } = setup();
    const first = host.dispatch(
      request({ archiveBytes: archive(), fileName: "first.zip" }, "first"),
    );
    const prompt = await nextPrompt();
    expect(
      await host.dispatch(
        request({ archiveBytes: archive(), fileName: "second.zip" }, "second"),
      ),
    ).toMatchObject({
      ok: false,
      error: { code: "material-import-busy", retryable: true },
    });
    prompt.answer(false);
    expect(await first).toMatchObject({ ok: true, result: { status: "cancelled" } });

    const third = host.dispatch(
      request({ archiveBytes: archive(), fileName: "third.zip" }, "third"),
    );
    (await nextPrompt()).answer(false);
    expect(await third).toMatchObject({ ok: true, result: { status: "cancelled" } });
  });

  it("dismisses the dialog when the frame closes", async () => {
    const { host, services, nextPrompt } = setup();
    const pending = host.dispatch(
      request({ archiveBytes: archive(), fileName: "material.zip" }),
    );
    const prompt = await nextPrompt();
    host.close();
    expect(prompt.signal.aborted).toBe(true);
    expect(await pending).toMatchObject({ ok: false, error: { code: "rpc-host-closed" } });
    await Promise.resolve();
    expect(services.importArchive).not.toHaveBeenCalled();
  });

  it("returns a fixture result from synthetic handlers without touching the library", async () => {
    const handler = createSyntheticWorkshopHandlers()["material.import"];
    expect(handler).toBeDefined();
    expect(
      await handler!(
        { archiveBytes: archive(), fileName: "material.zip" },
        { identity, signal: new AbortController().signal },
      ),
    ).toEqual({
      status: "imported",
      materials: [{ directoryName: "fixture-material", name: "Fixture material" }],
    });
  });
});
