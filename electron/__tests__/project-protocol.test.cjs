const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  ProjectOpenBroker,
  validateProjectPath,
} = require("../project-protocol.cjs");

test("app-ready is distinct from project-opened and request ids are idempotent", async () => {
  const projectPath = path.join(os.tmpdir(), "example.lum");
  const calls = [];
  const broker = new ProjectOpenBroker({
    openProject: async ({ projectPath }) => {
      calls.push(projectPath);
      return { status: "opened", bytes: Buffer.from("lum") };
    },
  });
  const states = [];
  broker.on("state", (state) => states.push(state.state));

  const first = broker.request({
    requestId: "request-1",
    projectPath,
  });
  assert.equal(broker.get("request-1").state, "awaiting-user");
  broker.markAppReady();
  const duplicate = broker.request({
    requestId: "request-1",
    projectPath,
  });
  assert.strictEqual(first, duplicate);

  const result = await first;
  assert.equal(result.state, "opening");
  assert.equal(broker.complete("request-1", { state: "opened" }), true);
  assert.equal(broker.get("request-1").state, "opened");
  assert.deepEqual(states, ["received", "awaiting-user", "opening", "opening", "opened"]);
  assert.equal(calls.length, 1);
});

test("limited and failed outcomes remain explicit", async () => {
  const limited = new ProjectOpenBroker({
    appReady: true,
    openProject: async () => ({ status: "limited", reason: "unsupported-capability" }),
  });
  const limitedOpening = await limited.request({
    requestId: "limited-1",
    projectPath: path.join(os.tmpdir(), "limited.lum"),
  });
  assert.equal(limitedOpening.state, "opening");
  limited.complete("limited-1", { state: "limited", result: { reason: "unsupported-capability" } });
  assert.equal(limited.get("limited-1").state, "limited");

  const failed = new ProjectOpenBroker({
    appReady: true,
    openProject: async () => {
      throw new Error("corrupt project");
    },
  });
  const failedResult = await failed.request({
    requestId: "failed-1",
    projectPath: path.join(os.tmpdir(), "failed.lum"),
  });
  assert.equal(failedResult.state, "failed");
  assert.match(failedResult.error, /corrupt/);
});

test("a cancelled opener cannot publish opened after its promise resolves", async () => {
  let releaseOpen;
  const broker = new ProjectOpenBroker({
    appReady: true,
    openProject: () => new Promise((resolve) => {
      releaseOpen = resolve;
    }),
  });
  const openingStates = [];
  broker.on("state", (state) => openingStates.push(state.state));

  const resultPromise = broker.request({
    requestId: "cancel-race",
    projectPath: path.join(os.tmpdir(), "cancel-race.lum"),
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(broker.cancel("cancel-race"), true);
  releaseOpen({ status: "opened", bytes: Buffer.from("late") });

  const result = await resultPromise;
  assert.equal(result.state, "cancelled");
  assert.equal(broker.get("cancel-race").state, "cancelled");
  assert.equal(openingStates.includes("opened"), false);
});

test("the native opener rejects a non-ZIP project before reporting opened", async () => {
  const projectPath = path.join(
    fs.mkdtempSync(path.join(os.tmpdir(), "lumina-invalid-project-")),
    "invalid.lum",
  );
  try {
    fs.writeFileSync(projectPath, Buffer.from("not a lumina project"));
    const broker = new ProjectOpenBroker({ appReady: true });
    const result = await broker.request({
      requestId: "invalid-project",
      projectPath,
    });
    assert.notEqual(result.state, "opened");
    assert.equal(result.state, "failed");
  } finally {
    fs.rmSync(path.dirname(projectPath), { recursive: true, force: true });
  }
});

test("project paths are absolute .lum paths without NUL bytes", () => {
  const projectPath = path.join(os.tmpdir(), "a.lum");
  assert.equal(validateProjectPath(projectPath), projectPath);
  assert.throws(() => validateProjectPath("relative.lum"), /absolute/);
  assert.throws(() => validateProjectPath(path.join(os.tmpdir(), "a.zip")), /\.lum/);
  assert.throws(() => validateProjectPath(path.join(os.tmpdir(), "a\0.lum")), /absolute|path/);
});
