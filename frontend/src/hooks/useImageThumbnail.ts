import { useEffect, useState } from "react";

// Covers the uploader's tallest preview (18rem) on a 2.5x display.
const THUMBNAIL_MAX_EDGE_PX = 768;

/**
 * Returns a downscaled URL for small on-screen previews of `sourceUrl`.
 *
 * Painting a full-size source into a small box makes every repaint of its layer
 * stall scrolling. The source URL is returned until the thumbnail is ready, and
 * whenever a thumbnail is unnecessary or cannot be made. Crop and rotation must
 * keep using the source URL.
 */
export function useImageThumbnail(sourceUrl: string | null): string | null {
  const [thumbnail, setThumbnail] = useState<{ sourceUrl: string; url: string } | null>(null);

  useEffect(() => {
    if (!sourceUrl) return;
    let cancelled = false;
    let thumbnailUrl: string | null = null;

    const image = new Image();
    image.onload = () => {
      const longEdge = Math.max(image.naturalWidth, image.naturalHeight);
      if (cancelled || longEdge <= THUMBNAIL_MAX_EDGE_PX) return;

      const scale = THUMBNAIL_MAX_EDGE_PX / longEdge;
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      const context = canvas.getContext("2d");
      if (!context) return;
      context.imageSmoothingQuality = "high";

      try {
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        // PNG keeps the alpha channel the checkerboard preview relies on.
        canvas.toBlob((blob) => {
          if (!blob || cancelled) return;
          thumbnailUrl = URL.createObjectURL(blob);
          setThumbnail({ sourceUrl, url: thumbnailUrl });
        }, "image/png");
      } catch {
        // A tainted or undecodable image keeps showing the source URL.
      }
    };
    image.src = sourceUrl;

    return () => {
      cancelled = true;
      image.onload = null;
      if (thumbnailUrl) URL.revokeObjectURL(thumbnailUrl);
      setThumbnail(null);
    };
  }, [sourceUrl]);

  return thumbnail?.sourceUrl === sourceUrl ? thumbnail.url : sourceUrl;
}
