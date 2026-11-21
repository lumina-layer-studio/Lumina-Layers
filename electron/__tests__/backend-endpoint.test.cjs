"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const helperPath = path.join(__dirname, "../backend-endpoint.cjs");
function helper() {
  assert.ok(fs.existsSync(helperPath), "desktop must provide an owned backend endpoint helper");
  return require(helperPath);
}
async function server(t, handler, port = 0) {
  const instance = http.createServer(handler);
  await new Promise((resolve, reject) => instance.once("error", reject).listen(port, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => { instance.closeAllConnections(); instance.close(resolve); }));
  return instance;
}
const health = id => JSON.stringify({ status: "ok", service: "lumina-studio", desktop_instance_id: id });

test("busy C-Lodop port is skipped without stopping its owner; new backend identity validates", async t => {
  const foreign = await server(t, (_req, res) => res.end("<html>C-Lodop</html>"));
  const endpoint = await helper().selectBackendEndpoint({ preferredPort: foreign.address().port });
  assert.notEqual(endpoint.port, foreign.address().port);
  assert.match(endpoint.instanceId, /^[a-f0-9]{64}$/);
  assert.equal(foreign.listening, true);
  await server(t, (_req, res) => { res.setHeader("content-type", "application/json"); res.end(health(endpoint.instanceId)); }, endpoint.port);
  assert.equal(await probe(endpoint.healthUrl, endpoint.instanceId), true);
  assert.equal(await (await fetch(`http://127.0.0.1:${foreign.address().port}`)).text(), "<html>C-Lodop</html>");
});

test("selection prefers a free port, generates fresh identities, and fails at bounded exhaustion", async t => {
  const occupied = await server(t, (_req, res) => res.end());
  const port = occupied.address().port;
  await assert.rejects(helper().selectBackendEndpoint({ preferredPort: port, maxAttempts: 1 }), /port_in_use/);
  const first = await helper().selectBackendEndpoint();
  const second = await helper().selectBackendEndpoint({ preferredPort: first.port });
  assert.equal(first.port, second.port);
  assert.notEqual(first.instanceId, second.instanceId);
});

test("persisted port keeps the backend endpoint stable across launches", async t => {
  const portFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "lumina-port-state-")), "backend-port.json");
  const first = await helper().selectBackendEndpoint({ portFile, preferredPort: 8100 });
  assert.equal(fs.existsSync(portFile), false, "selection cannot commit before backend health");
  helper().commitBackendEndpoint({ portFile, endpoint: first });
  assert.equal(JSON.parse(fs.readFileSync(portFile, "utf8")).port, first.port);
  const second = await helper().selectBackendEndpoint({ portFile, preferredPort: 8100 });
  assert.equal(second.port, first.port);
  assert.notEqual(second.instanceId, first.instanceId);
});

test("required port check reports a collision and leaves its owner running", async t => {
  const owner = await server(t, (_req, res) => res.end("owner"));
  await assert.rejects(helper().assertPortsAvailable([owner.address().port]), /port_in_use/);
  assert.equal(owner.listening, true);
});

test("required port check releases its probe listener", async () => {
  await helper().assertPortsAvailable([0]);
});

test("a remembered occupied port recovers without advancing the authoritative storage origin", async t => {
  const portFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "lumina-port-state-")), "backend-port.json");
  const first = await helper().selectBackendEndpoint({ portFile, preferredPort: 8101 });
  // This is a persisted version-1 endpoint state.
  fs.writeFileSync(portFile, JSON.stringify({ schemaVersion: 1, port: first.port }));
  let requests = 0;
  const owner = await server(t, (_req, res) => { requests++; res.end("foreign"); }, first.port);
  const recovered = await helper().selectBackendEndpoint({ portFile, preferredPort: 8101 });
  assert.notEqual(recovered.port, first.port);
  assert.equal(recovered.previousOrigin, first.origin);
  assert.equal(recovered.previousPort, first.port);
  assert.equal(JSON.parse(fs.readFileSync(portFile, "utf8")).port, first.port);
  // A failed launch retries from the same source, never from a partly imported target.
  const retry = await helper().selectBackendEndpoint({ portFile, preferredPort: 8101 });
  assert.equal(retry.previousOrigin, first.origin);
  helper().commitBackendEndpoint({ portFile, endpoint: recovered });
  assert.equal(JSON.parse(fs.readFileSync(portFile, "utf8")).port, recovered.port);
  assert.equal(requests, 0, "port probing must not fetch foreign HTTP content");
  assert.equal(owner.listening, true);
});

test("desktop opt-in uses an OS-assigned port after real preferred-range exhaustion", async t => {
  const owner = await server(t, (_req, res) => res.end("foreign"));
  const preferredPort = owner.address().port;
  await assert.rejects(helper().selectBackendEndpoint({ preferredPort, maxAttempts: 1 }), error =>
    error.code === "backend_port_unavailable");
  const recovered = await helper().selectBackendEndpoint({ preferredPort, maxAttempts: 1, allowEphemeralFallback: true });
  assert.notEqual(recovered.port, preferredPort);
  assert.ok(recovered.port >= 1024 && recovered.port <= 65535);
  const bound = await server(t, (_req, res) => res.end("owned"), recovered.port);
  assert.equal(bound.listening, true);
  assert.equal(owner.listening, true);
});

test("corrupt and inaccessible port state are not reset or classified as port exhaustion", async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-port-state-errors-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const portFile = path.join(root, "backend-port.json");
  fs.writeFileSync(portFile, "{broken");
  await assert.rejects(helper().selectBackendEndpoint({ portFile }), error => error.code === "backend_port_state_invalid");
  assert.equal(fs.readFileSync(portFile, "utf8"), "{broken");
  const directory = path.join(root, "directory");
  fs.mkdirSync(directory);
  await assert.rejects(helper().selectBackendEndpoint({ portFile: directory }), error => error.code === "backend_port_state_read_failed");
  assert.equal(fs.statSync(directory).isDirectory(), true);
});

test("commit refuses to overwrite a changed data origin and reports real write I/O errors", async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-port-commit-errors-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const portFile = path.join(root, "backend-port.json");
  const endpoint = await helper().selectBackendEndpoint({ portFile });
  fs.writeFileSync(portFile, JSON.stringify({ schemaVersion: 1, port: 8109 }));
  assert.throws(() => helper().commitBackendEndpoint({ portFile, endpoint }), error => error.code === "backend_port_state_changed");
  assert.equal(JSON.parse(fs.readFileSync(portFile, "utf8")).port, 8109);
  const parentFile = path.join(root, "not-a-directory");
  const unavailableState = path.join(parentFile, "backend-port.json");
  const selected = await helper().selectBackendEndpoint({ portFile: unavailableState });
  fs.writeFileSync(parentFile, "owned-file");
  assert.throws(() => helper().commitBackendEndpoint({ portFile: unavailableState, endpoint: selected }), error =>
    error.code === "backend_port_state_read_failed" || error.code === "backend_port_state_write_failed");
  assert.equal(fs.readFileSync(parentFile, "utf8"), "owned-file");
});

async function probe(url, id) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, res => helper().validateHealthResponse(res, id, valid => { req.destroy(); resolve(valid); }));
    req.on("error", reject);
  });
}

for (const [label, status, type, body] of [
  ["HTML200", 200, "text/html", "<html>C-Lodop</html>"],
  ["redirect", 302, "application/json", health("owned")],
  ["wrong service", 200, "application/json", health("owned").replace("lumina-studio", "another-service")],
  ["old instance", 200, "application/json", health("old")],
  ["missing instance", 200, "application/json", '{"status":"ok","service":"lumina-studio"}'],
  ["malformed", 200, "application/json", "{"],
  ["oversized", 200, "application/json", " ".repeat(17000) + health("owned")],
  ["unhealthy", 200, "application/json", health("owned").replace('"ok"', '"error"')],
]) {
  test(`health rejects ${label}`, async t => {
    const instance = await server(t, (_req, res) => { res.writeHead(status, { "content-type": type }); res.end(body); });
    assert.equal(await probe(`http://127.0.0.1:${instance.address().port}/api/health`, "owned"), false);
  });
}

test("valid JSON with charset and split chunks is accepted", async t => {
  const instance = await server(t, (_req, res) => {
    res.setHeader("content-type", "application/json; charset=utf-8");
    res.write(health("owned").slice(0, 12)); res.end(health("owned").slice(12));
  });
  assert.equal(await probe(`http://127.0.0.1:${instance.address().port}/api/health`, "owned"), true);
});

test("reads the Registry configuration from the selected loopback backend", async t => {
  const registry = "http://localhost:8018/materials/api/material-registry/v1";
  const requests = [];
  const instance = await server(t, (req, res) => {
    requests.push([req.method, req.url, req.headers["x-lumina-contribution"]]);
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(JSON.stringify({ server: registry }));
  });
  assert.equal(await helper().readCommunityServerConfiguration(instance.address().port), registry);
  assert.deepEqual(requests, [["GET", "/api/contributions/connection/server", "1"]]);
});

test("rejects a Registry configuration redirect without following it", async t => {
  const paths = [];
  const instance = await server(t, (req, res) => {
    paths.push(req.url);
    if (req.url === "/redirected") {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ server: "https://example.com/api/material-registry/v1" }));
      return;
    }
    res.writeHead(302, { Location: "/redirected" });
    res.end();
  });
  await assert.rejects(helper().readCommunityServerConfiguration(instance.address().port), /configuration unavailable/);
  assert.deepEqual(paths, ["/api/contributions/connection/server"]);
});

test("rejects a Registry configuration response over the size limit without Content-Length", async t => {
  const instance = await server(t, (_req, res) => {
    res.setHeader("Content-Type", "application/json");
    res.write(" ".repeat(16 * 1024));
    res.end(JSON.stringify({ server: "https://example.com/api/material-registry/v1" }));
  });
  await assert.rejects(helper().readCommunityServerConfiguration(instance.address().port), /configuration unavailable/);
});
