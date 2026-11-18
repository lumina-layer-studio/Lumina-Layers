export const MAX_FEEDBACK_IMAGES = 3;
const MAX_UPLOAD_BYTES = 1024 * 1024;

/** Resize screenshots before transmission; the server independently validates and strips metadata. */
export async function prepareFeedbackImage(file: File): Promise<string> {
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) throw new Error("resource_feedback_image_format");
  if (file.size > 20 * 1024 * 1024) throw new Error("resource_feedback_image_large");
  const image = await createImageBitmap(file, { imageOrientation: "from-image" });
  try {
    if (image.width * image.height > 40_000_000) throw new Error("resource_feedback_image_large");
    const ratio = Math.min(1, 1600 / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.width * ratio));
    canvas.height = Math.max(1, Math.round(image.height * ratio));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("resource_feedback_image_failed");
    context.fillStyle = "white";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    let blob: Blob | null = null;
    for (const quality of [0.82, 0.68, 0.52]) {
      blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/jpeg", quality));
      if (blob && blob.size <= MAX_UPLOAD_BYTES) break;
    }
    if (!blob || blob.size > MAX_UPLOAD_BYTES) throw new Error("resource_feedback_image_failed");
    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
      reader.onerror = () => reject(new Error("resource_feedback_image_failed"));
      reader.readAsDataURL(blob);
    });
  } finally {
    image.close();
  }
}
