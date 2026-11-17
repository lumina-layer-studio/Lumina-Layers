import { downloadResourceBlob } from "../api/client";
import { createProjectAsset } from "./identity";
import type { ProjectSnapshot } from "./types";

/** Covers are derived presentation data; an unavailable renderer must never lose a save. */
export async function attachProjectThumbnail(snapshot: ProjectSnapshot, workflow: string, preview: string | null) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const controller = new AbortController();
  const create = async () => {
    let blob: Blob | null = null;
    if (preview) {
      try { blob = await downloadResourceBlob(preview, { signal: controller.signal }); } catch { /* Fall back to the embedded source. */ }
    }
    if (controller.signal.aborted) return null;
    const source = Object.values(snapshot.assets).find(asset => /^image\/(png|jpeg|webp|svg\+xml)$/.test(asset.mediaType));
    if (!blob && source) blob = new Blob([source.data], { type: source.mediaType });
    const canvas = document.createElement("canvas");
    canvas.width = 640; canvas.height = 400;
    const context = canvas.getContext("2d");
    if (!context) return null;
    context.fillStyle = "#e8edf3"; context.fillRect(0, 0, 640, 400);
    if (blob) {
      const image = await createImageBitmap(blob);
      try {
        const scale = Math.min(608 / image.width, 368 / image.height);
        context.drawImage(image, (640 - image.width * scale) / 2, (400 - image.height * scale) / 2, image.width * scale, image.height * scale);
      } finally { image.close(); }
    } else {
      context.fillStyle = "#344459"; context.font = "600 28px sans-serif"; context.fillText(snapshot.manifest.name.slice(0, 32), 32, 180);
      context.font = "18px sans-serif"; context.fillText(workflow, 32, 220);
    }
    const png = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/png"));
    return png ? createProjectAsset("thumbnail", new Uint8Array(await png.arrayBuffer()), "image/png", "thumbnail.png", "resource") : null;
  };
  try {
    // Only publish the returned asset. A timed-out task cannot mutate an already-saved archive.
    const asset = await Promise.race([create(), new Promise<null>(resolve => { timer = setTimeout(() => resolve(null), 2000); })]);
    if (asset) {
      snapshot.thumbnail = { ...asset, path: "preview/thumbnail.png" };
      snapshot.manifest.thumbnail = { path: "preview/thumbnail.png", sha256: asset.sha256, byteSize: asset.byteSize, mediaType: "image/png" };
    }
  } catch { /* Missing or undecodable covers are valid projects. */ }
  finally { clearTimeout(timer); controller.abort(); }
}
