import "fake-indexeddb/auto";
import { afterEach, expect, it, vi } from "vitest";
import { saveProjectFile, type ProjectFileHandle } from "../project/files";
import { createProjectAsset, createProjectSnapshot } from "../project/identity";
import { parseProject } from "../project/archive";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const snapshot = () => createProjectSnapshot({ name: "File", workflowKinds: ["converter"], documents: [{
  documentId: "converter.main", kind: "converter", schemaVersion: 2,
  payload: {}, inputRevisionIds: [], resourceRefs: [], requiredCapabilities: [],
}] });
function destination() {
  let bytes = new Uint8Array();
  const stream = { write: vi.fn(async (value: Uint8Array) => { bytes = value; }), close: vi.fn().mockResolvedValue(undefined), abort: vi.fn() };
  const handle = { name: "file.lum", createWritable: async () => stream, isSameEntry: async () => false } as unknown as ProjectFileHandle;
  return { handle, stream, read: () => parseProject(bytes) };
}

it("retains the written file handle when the recent-project database fails", async () => {
  vi.spyOn(indexedDB, "open").mockImplementation(() => { throw new Error("catalog unavailable"); });
  const target = destination();
  const result = await saveProjectFile(snapshot(), null, false, target.handle);
  expect(target.stream.close).toHaveBeenCalledOnce();
  expect((await target.read()).manifest.name).toBe("File");
  expect(result).toMatchObject({ persisted: true, entry: { handle: target.handle, catalogWarning: expect.any(String) } });
});

it("uses an existing PNG cover without waiting for another image decoder", async () => {
  vi.stubGlobal("createImageBitmap", () => new Promise(() => {}));
  const project = snapshot();
  const bytes = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGMwCq34DwADuwH/hxaC9AAAAABJRU5ErkJggg=="), c => c.charCodeAt(0));
  const asset = await createProjectAsset("thumbnail", bytes, "image/png", "thumbnail.png", "resource");
  project.thumbnail = { ...asset, path: "preview/thumbnail.png" };
  project.manifest.thumbnail = { path: "preview/thumbnail.png", sha256: asset.sha256, byteSize: bytes.length, mediaType: "image/png" };
  const target = destination();
  const result = await Promise.race([saveProjectFile(project, null, false, target.handle), new Promise(resolve => setTimeout(() => resolve("hung"), 80))]);
  expect(result).toMatchObject({ persisted: true, entry: { thumbnailDataUrl: expect.stringMatching(/^data:image\/png;base64,/) } });
  expect((await target.read()).thumbnail?.data).toEqual(bytes);
});
