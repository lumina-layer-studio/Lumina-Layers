"use strict";
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const { randomBytes } = require("node:crypto");

const PORT_STATE_VERSION = 1;
const LOCAL_JSON_LIMIT = 16 * 1024;

function validatePort(value) {
  return Number.isInteger(value) && value >= 1024 && value <= 65535;
}

function portError(code, cause) {
  const error = new Error(code === "backend_port_unavailable" ? "port_in_use:no_available_backend_port" : code);
  error.code = code;
  if (cause) error.cause = cause;
  return error;
}

function readStablePort(portFile) {
  if (portFile === undefined) return null;
  if (typeof portFile !== "string" || !path.isAbsolute(portFile)) {
    throw new TypeError("Stable backend port file must be an absolute path.");
  }
  let contents;
  try {
    contents = fs.readFileSync(portFile, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw portError("backend_port_state_read_failed", error);
  }
  let parsed;
  try { parsed = JSON.parse(contents); }
  catch (error) { throw portError("backend_port_state_invalid", error); }
  if (parsed?.schemaVersion !== PORT_STATE_VERSION || !validatePort(parsed.port)) {
    throw portError("backend_port_state_invalid");
  }
  return parsed.port;
}

function writeStablePort(portFile, port) {
  if (portFile === undefined) return;
  const temporary = `${portFile}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`;
  try {
    fs.mkdirSync(path.dirname(portFile), { recursive: true });
    fs.writeFileSync(temporary, `${JSON.stringify({ schemaVersion: PORT_STATE_VERSION, port })}\n`, { mode: 0o600, flag: "wx" });
    fs.renameSync(temporary, portFile);
  } catch (error) {
    throw portError("backend_port_state_write_failed", error);
  } finally {
    try { fs.unlinkSync(temporary); } catch (_) { /* Best-effort cleanup of this launch's temporary file only. */ }
  }
}

async function availablePort(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", error => {
      if (["EADDRINUSE", "EACCES"].includes(error.code)) resolve(null);
      else reject(portError("backend_port_probe_failed", error));
    });
    server.listen({ port, host: "127.0.0.1", exclusive: true }, () => {
      const selected = server.address().port;
      server.close(error => error ? reject(portError("backend_port_probe_failed", error)) : resolve(selected));
    });
  });
}

/** Check required local ports without terminating their owners. */
async function assertPortsAvailable(ports) {
  for (const port of ports) {
    await new Promise((resolve, reject) => {
      const server = net.createServer();
      server.once("error", error => reject(new Error(`port_in_use:${port}:${error.code}`)));
      server.listen(port, "127.0.0.1", () => server.close(resolve));
    });
  }
}

/** Select a loopback endpoint; commit it only after owned backend health succeeds. */
async function selectBackendEndpoint({ preferredPort = 8000, maxAttempts = 100, portFile, allowEphemeralFallback = false } = {}) {
  if (!Number.isInteger(preferredPort) || preferredPort < 1024 || preferredPort > 65535 ||
      !Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 100 || typeof allowEphemeralFallback !== "boolean") {
    throw new TypeError("Invalid backend port range.");
  }
  const stablePort = readStablePort(portFile);
  if (stablePort !== null && await availablePort(stablePort)) {
    return makeEndpoint(stablePort, stablePort);
  }
  for (let port = preferredPort; port < Math.min(preferredPort + maxAttempts, 65536); port++) {
    if (port !== stablePort && await availablePort(port)) {
      return makeEndpoint(port, stablePort);
    }
  }
  // Windows may reserve the whole preferred range. The OS chooses a loopback
  // port; this opt-in remains bounded and never changes firewall/owner state.
  if (allowEphemeralFallback) {
    for (let attempt = 0; attempt < 5; attempt++) {
      const port = await availablePort(0);
      if (validatePort(port)) return makeEndpoint(port, stablePort);
    }
  }
  throw portError("backend_port_unavailable");
}

/** Persist the selected endpoint only after owned backend health succeeds. */
function commitBackendEndpoint({ portFile, endpoint }) {
  if (!endpoint || !validatePort(endpoint.port) || endpoint.origin !== `http://127.0.0.1:${endpoint.port}` ||
      !(endpoint.previousPort === null || validatePort(endpoint.previousPort))) {
    throw new TypeError("Invalid selected backend endpoint.");
  }
  const previousPort = readStablePort(portFile);
  if (previousPort !== endpoint.previousPort) throw portError("backend_port_state_changed");
  writeStablePort(portFile, endpoint.port);
}

function makeEndpoint(port, previousPort) {
  const origin = `http://127.0.0.1:${port}`;
  return {
    port, origin, healthUrl: `${origin}/api/health`, instanceId: randomBytes(32).toString("hex"), previousPort,
    previousOrigin: previousPort !== null && previousPort !== port ? `http://127.0.0.1:${previousPort}` : null,
  };
}

function isSmallJsonResponse(response) {
  return response.statusCode === 200 &&
    /^application\/json(?:\s*;|$)/i.test(response.headers?.["content-type"] || "") &&
    !(Number(response.headers?.["content-length"]) > LOCAL_JSON_LIMIT);
}

/** Read a fixed API route on the owned backend outside Chromium's renderer session. */
async function readCommunityServerConfiguration(port) {
  if (!validatePort(port)) throw new TypeError("Invalid backend port.");
  const response = await new Promise((resolve, reject) => {
    http.get({
      hostname: "127.0.0.1",
      port,
      path: "/api/contributions/connection/server",
      headers: { "X-Lumina-Contribution": "1", Accept: "application/json" },
      agent: false,
      signal: AbortSignal.timeout(3000),
    }, resolve).once("error", reject);
  });
  if (!isSmallJsonResponse(response)) {
    response.destroy();
    throw new Error("Community server configuration unavailable.");
  }
  const chunks = [];
  let bytes = 0;
  for await (const chunk of response) {
    bytes += chunk.length;
    if (bytes > LOCAL_JSON_LIMIT) throw new Error("Community server configuration unavailable.");
    chunks.push(chunk);
  }
  const configuration = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  if (typeof configuration?.server !== "string" || !configuration.server) {
    throw new Error("Invalid community server configuration.");
  }
  return configuration.server;
}

/** Read only a small JSON health document and verify this launch, not just HTTP success. */
function validateHealthResponse(response, instanceId, done) {
  let finished = false;
  const finish = valid => {
    if (finished) return;
    finished = true;
    done(valid);
  };
  if (!isSmallJsonResponse(response) || !instanceId) {
    finish(false);
    return;
  }
  const chunks = [];
  let bytes = 0;
  response.on("data", chunk => {
    if (finished) return;
    bytes += chunk.length;
    if (bytes > LOCAL_JSON_LIMIT) { finish(false); return; }
    chunks.push(chunk);
  });
  response.once("aborted", () => finish(false));
  response.once("error", () => finish(false));
  response.once("end", () => {
    if (finished) return;
    try {
      const data = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      finish(data?.status === "ok" && data?.service === "lumina-studio" && data?.desktop_instance_id === instanceId);
    } catch { finish(false); }
  });
}

module.exports = {
  assertPortsAvailable,
  selectBackendEndpoint,
  commitBackendEndpoint,
  validateHealthResponse,
  readCommunityServerConfiguration,
};
