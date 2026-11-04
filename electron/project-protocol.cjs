const fs = require("fs");
const path = require("path");
const { EventEmitter } = require("events");

const PROJECT_OPEN_STATES = Object.freeze([
  "received",
  "awaiting-user",
  "opening",
  "opened",
  "limited",
  "cancelled",
  "failed",
]);

const MAX_PROJECT_BYTES = 512 * 1024 * 1024;
const TERMINAL_PROJECT_OPEN_STATES = new Set([
  "opened",
  "limited",
  "cancelled",
  "failed",
]);

function validateRequestId(value) {
  if (typeof value !== "string" || value.length === 0 || value.length > 128) {
    throw new Error("Invalid project request id");
  }
  if (!/^[A-Za-z0-9._:-]+$/.test(value)) {
    throw new Error("Invalid project request id");
  }
  return value;
}

function validateProjectPath(value) {
  if (typeof value !== "string" || value.length === 0 || value.length > 4096) {
    throw new Error("Invalid project path");
  }
  if (value.includes("\0") || !path.isAbsolute(value)) {
    throw new Error("Project path must be an absolute local path");
  }
  const normalized = path.normalize(value);
  if (path.extname(normalized).toLowerCase() !== ".lum") {
    throw new Error("Only .lum project files are supported");
  }
  return normalized;
}

class ProjectOpenBroker extends EventEmitter {
  constructor(options = {}) {
    super();
    this.appReady = Boolean(options.appReady);
    this.entries = new Map();
    this.openProject = options.openProject || (async ({ projectPath }) => {
      const stat = await fs.promises.stat(projectPath);
      if (!stat.isFile() || stat.size > MAX_PROJECT_BYTES) {
        throw new Error("Project file is missing or exceeds the size limit");
      }
      const bytes = await fs.promises.readFile(projectPath);
      if (
        bytes.byteLength < 4 ||
        bytes[0] !== 0x50 ||
        bytes[1] !== 0x4b ||
        ![0x03, 0x05, 0x07].includes(bytes[2]) ||
        ![0x04, 0x06, 0x08].includes(bytes[3])
      ) {
        throw new Error("Project file is not a ZIP package");
      }
      return { status: "opening", bytes, path: projectPath };
    });
  }

  markAppReady() {
    this.appReady = true;
    for (const entry of this.entries.values()) {
      if (entry.state === "awaiting-user" && !entry.resolved) this.#begin(entry);
    }
  }

  request(input) {
    const requestId = validateRequestId(input?.requestId);
    const projectPath = validateProjectPath(input?.projectPath);
    const existing = this.entries.get(requestId);
    if (existing) return existing.promise;

    const entry = {
      requestId,
      projectPath,
      state: "received",
      error: null,
      result: null,
      promise: null,
      resolved: false,
    };
    // The request promise resolves when native I/O has produced a package
    // payload.  ``opened``/``limited`` are renderer-owned terminal states and
    // must be committed only after trusted parsing and restore complete.
    entry.promise = new Promise((resolve) => {
      entry.resolveInitial = resolve;
    });
    this.entries.set(requestId, entry);
    this.#emit(entry, "received");
    if (this.appReady) this.#begin(entry);
    else this.#emit(entry, "awaiting-user");
    return entry.promise;
  }

  cancel(requestId) {
    const entry = this.entries.get(validateRequestId(requestId));
    if (!entry || TERMINAL_PROJECT_OPEN_STATES.has(entry.state)) {
      return false;
    }
    this.#finish(entry, "cancelled", null, null);
    return true;
  }

  complete(requestId, input = {}) {
    const entry = this.entries.get(validateRequestId(requestId));
    if (!entry || TERMINAL_PROJECT_OPEN_STATES.has(entry.state)) return false;
    const state = input.state;
    if (!TERMINAL_PROJECT_OPEN_STATES.has(state) || state === "cancelled") {
      throw new Error("Invalid project restore completion state");
    }
    this.#finish(
      entry,
      state,
      input.error ? String(input.error) : null,
      input.result === undefined ? entry.result : input.result,
    );
    return true;
  }

  progress(requestId, state) {
    const entry = this.entries.get(validateRequestId(requestId));
    if (!entry || !entry.resolved || TERMINAL_PROJECT_OPEN_STATES.has(entry.state)) return false;
    if (!["awaiting-user", "opening"].includes(state)) throw new Error("Invalid project progress state");
    this.#emit(entry, state);
    return true;
  }

  get(requestId) {
    const entry = this.entries.get(validateRequestId(requestId));
    if (!entry) return null;
    return {
      requestId: entry.requestId,
      state: entry.state,
      error: entry.error,
      result: entry.result,
    };
  }

  #begin(entry) {
    if (entry.state !== "received" && entry.state !== "awaiting-user") return;
    this.#emit(entry, "opening");
    Promise.resolve()
      .then(() => this.openProject({ projectPath: entry.projectPath, requestId: entry.requestId }))
      .then((result) => {
        if (TERMINAL_PROJECT_OPEN_STATES.has(entry.state)) return;
        entry.result = result ?? null;
        // Native code has only opened a trusted file capability/byte payload.
        // It has not parsed or restored the project yet.
        this.#emit(entry, "opening");
        this.#resolveInitial(entry);
      })
      .catch((error) => {
        this.#finish(entry, "failed", error instanceof Error ? error.message : String(error), null);
      });
  }

  #emit(entry, state) {
    if (!PROJECT_OPEN_STATES.includes(state)) throw new Error("Unknown project state");
    entry.state = state;
    const update = this.get(entry.requestId);
    this.emit("state", update);
  }

  #finish(entry, state, error, result) {
    if (TERMINAL_PROJECT_OPEN_STATES.has(entry.state)) return;
    entry.error = error;
    entry.result = result;
    this.#emit(entry, state);
    this.#resolveInitial(entry);
  }

  #resolveInitial(entry) {
    if (entry.resolved) return;
    entry.resolved = true;
    entry.resolveInitial(this.get(entry.requestId));
  }
}

module.exports = {
  MAX_PROJECT_BYTES,
  PROJECT_OPEN_STATES,
  ProjectOpenBroker,
  TERMINAL_PROJECT_OPEN_STATES,
  validateProjectPath,
  validateRequestId,
};
