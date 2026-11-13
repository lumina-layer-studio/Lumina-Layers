import type { ProjectSnapshot } from "./types";

const DATABASE_NAME = "lumina-project-recovery-v1";
const STORE_NAME = "snapshots";
const DATABASE_VERSION = 1;

export interface RecoveryRecord {
  key: string;
  projectId: string;
  revisionId: string;
  savedAt: string;
  snapshot: ProjectSnapshot;
}

export type RecoveryStorageErrorCode =
  | "unavailable"
  | "open-failed"
  | "save-failed"
  | "quota-exceeded"
  | "read-failed"
  | "remove-failed";

export class RecoveryStorageError extends Error {
  readonly code: RecoveryStorageErrorCode;

  constructor(
    code: RecoveryStorageErrorCode,
    message: string,
    options?: { cause?: unknown },
  ) {
    super(message);
    if (options?.cause) this.cause = options.cause;
    this.name = "RecoveryStorageError";
    this.code = code;
  }
}

function openDatabase(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined") {
    return Promise.reject(
      new RecoveryStorageError("unavailable", "IndexedDB is unavailable"),
    );
  }
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onerror = () =>
      reject(
        new RecoveryStorageError("open-failed", "Recovery database could not be opened", {
          cause: request.error,
        }),
      );
    request.onupgradeneeded = () => {
      request.result.createObjectStore(STORE_NAME, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
  });
}

export async function saveRecoverySnapshot(
  snapshot: ProjectSnapshot,
): Promise<void> {
  const db = await openDatabase();
  const record: RecoveryRecord = {
    key: snapshot.manifest.projectId + ":" + snapshot.manifest.revisionId,
    projectId: snapshot.manifest.projectId,
    revisionId: snapshot.manifest.revisionId,
    savedAt: new Date().toISOString(),
    snapshot,
  };
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, "readwrite");
      const failure = () => {
        const error = transaction.error;
        const code: RecoveryStorageErrorCode =
          error?.name === "QuotaExceededError" ? "quota-exceeded" : "save-failed";
        reject(
          new RecoveryStorageError(code, "Recovery snapshot could not be saved", {
            cause: error,
          }),
        );
      };
      transaction.onerror = failure;
      transaction.onabort = failure;
      transaction.oncomplete = () => resolve();
      transaction.objectStore(STORE_NAME).put(record);
    });
  } finally {
    db.close();
  }
}

export async function loadRecoverySnapshot(
  projectId: string,
  revisionId: string,
): Promise<RecoveryRecord | null> {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const request = db
      .transaction(STORE_NAME, "readonly")
      .objectStore(STORE_NAME)
      .get(projectId + ":" + revisionId);
    request.onerror = () => {
      db.close();
      reject(
        new RecoveryStorageError("read-failed", "Recovery snapshot could not be read", {
          cause: request.error,
        }),
      );
    };
    request.onsuccess = () => {
      db.close();
      resolve((request.result as RecoveryRecord | undefined) ?? null);
    };
  });
}

export async function removeRecoverySnapshot(
  projectId: string,
  revisionId: string,
): Promise<void> {
  const db = await openDatabase();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, "readwrite");
      transaction.onerror = () =>
        reject(
          new RecoveryStorageError("remove-failed", "Recovery snapshot could not be removed", {
            cause: transaction.error,
          }),
        );
      transaction.onabort = () =>
        reject(
          new RecoveryStorageError("remove-failed", "Recovery snapshot removal was aborted", {
            cause: transaction.error,
          }),
        );
      transaction.oncomplete = () => resolve();
      transaction.objectStore(STORE_NAME).delete(projectId + ":" + revisionId);
    });
  } finally {
    db.close();
  }
}

export async function listRecoverySnapshots(): Promise<RecoveryRecord[]> {
  const db = await openDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).getAll();
      request.onsuccess = () => resolve((request.result as RecoveryRecord[]).sort((a, b) => b.savedAt.localeCompare(a.savedAt)));
      request.onerror = () => reject(new RecoveryStorageError("read-failed", "Recovery snapshots could not be read", { cause: request.error }));
    });
  } finally { db.close(); }
}
