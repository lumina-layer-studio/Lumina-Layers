import type { PreviewSpaceBounds, PreviewSpacePoint } from "./previewSpace";

export interface KeychainReference {
  bounds_mm: [number, number, number, number];
  outlines_mm?: number[][][];
  /** Constant-height segments in the (tangent, outward) frame of top, bottom, right, left. */
  bands_mm?: [number, number, number][][];
}

export interface PreviewCanvasBounds extends PreviewSpaceBounds {
  keychainAttachment?: { reference: KeychainReference; assetCenter: PreviewSpacePoint };
}

export function readKeychainReference(userData: Record<string, unknown>): KeychainReference | undefined {
  const reference = userData.lumina_keychain_attachment as KeychainReference | undefined;
  if (!reference) return undefined;
  const bounds = reference.bounds_mm;
  return Array.isArray(bounds) && bounds.length === 4 && bounds.every(Number.isFinite)
    && (Array.isArray(reference.outlines_mm)
      || (Array.isArray(reference.bands_mm) && reference.bands_mm.length === 4))
    ? reference
    : undefined;
}
