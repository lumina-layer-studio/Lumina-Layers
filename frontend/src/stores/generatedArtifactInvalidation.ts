export interface GeneratedArtifactInvalidationOptions {
  preservePreviews?: boolean;
  source?: "defaults";
}

type InvalidateGeneratedArtifacts = (
  options: GeneratedArtifactInvalidationOptions,
) => void;
type InvalidatePreviewArtifacts = () => void;
type InvalidateSingleItemDownload = () => void;

export interface GeneratedArtifactIdentity {
  revision: number;
  defaultsRevision: number | null;
  deviceProfileId: string;
  buildPlateId: string;
}

const invalidateGeneratedArtifactsHandlers = new Set<
  InvalidateGeneratedArtifacts
>();
let invalidatePreviewArtifactsHandler: InvalidatePreviewArtifacts | null = null;
let invalidateSingleItemDownloadHandler: InvalidateSingleItemDownload | null = null;
let generatedArtifactRevision = 0;
let defaultsRevision = 0;

export function registerGeneratedArtifactInvalidator(
  handler: InvalidateGeneratedArtifacts,
): () => void {
  invalidateGeneratedArtifactsHandlers.add(handler);
  return () => {
    invalidateGeneratedArtifactsHandlers.delete(handler);
  };
}

export function invalidateGeneratedArtifacts(
  options: GeneratedArtifactInvalidationOptions = {},
): void {
  if (options.source === "defaults") defaultsRevision += 1;
  else generatedArtifactRevision += 1;
  invalidateGeneratedArtifactsHandlers.forEach((handler) => handler(options));
}

export function captureGeneratedArtifactIdentity(
  deviceProfileId: string,
  buildPlateId: string,
  usesDefaults = true,
): GeneratedArtifactIdentity {
  return {
    revision: generatedArtifactRevision,
    defaultsRevision: usesDefaults ? defaultsRevision : null,
    deviceProfileId,
    buildPlateId,
  };
}

export function isGeneratedArtifactIdentityCurrent(
  identity: GeneratedArtifactIdentity,
  deviceProfileId: string,
  buildPlateId: string,
): boolean {
  return (
    identity.revision === generatedArtifactRevision &&
    (identity.defaultsRevision === null || identity.defaultsRevision === defaultsRevision) &&
    identity.deviceProfileId === deviceProfileId &&
    identity.buildPlateId === buildPlateId
  );
}

export function registerPreviewArtifactInvalidator(
  handler: InvalidatePreviewArtifacts,
): void {
  invalidatePreviewArtifactsHandler = handler;
}

export function invalidatePreviewArtifacts(): void {
  invalidatePreviewArtifactsHandler?.();
}

export function registerSingleItemDownloadInvalidator(
  handler: InvalidateSingleItemDownload,
): void {
  invalidateSingleItemDownloadHandler = handler;
}

export function invalidateSingleItemDownload(): void {
  invalidateSingleItemDownloadHandler?.();
}
