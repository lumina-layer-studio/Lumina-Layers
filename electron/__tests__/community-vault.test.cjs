const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");

const modulePath = path.join(__dirname, "../community-vault.cjs");

function encryption() {
  const key = crypto.randomBytes(32);
  return {
    isEncryptionAvailable: () => true,
    getSelectedStorageBackend: () => "keychain",
    encryptString(value) {
      const iv = crypto.randomBytes(12);
      const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
      return Buffer.concat([iv, cipher.update(value), cipher.final(), cipher.getAuthTag()]);
    },
    decryptString(value) {
      const cipher = crypto.createDecipheriv("aes-256-gcm", key, value.subarray(0, 12));
      cipher.setAuthTag(value.subarray(-16));
      return Buffer.concat([cipher.update(value.subarray(12, -16)), cipher.final()]).toString();
    },
  };
}

test("vault protects saved device credentials and isolates each source and workspace", async (t) => {
  assert.ok(fs.existsSync(modulePath), "Desktop must own the protected credential store");
  const {createCommunityVault} = require(modulePath);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-vault-"));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const safeStorage = encryption();
  let broker = await createCommunityVault({directory: root, safeStorage});
  const call = async (action, source, value) => {
    const response = await fetch(broker.env.LUMINA_COMMUNITY_VAULT_URL, {
      method: "POST",
      headers: {"X-Lumina-Vault": broker.env.LUMINA_COMMUNITY_VAULT_TOKEN, "Content-Type": "application/json"},
      body: JSON.stringify({action, source, value}),
    });
    return {status: response.status, body: await response.json()};
  };
  const source = "https://registry.example/api/material-registry/v1";
  const value = {refresh_token: "studio_refresh_secret", subject: "user-a", device_id: "device-a"};
  assert.equal((await call("save", source, value)).status, 200);
  assert.deepEqual((await call("load", source)).body.value, value);
  assert.equal((await call("load", "https://other.example/api/material-registry/v1")).body.value, null);
  assert.ok(!fs.readFileSync(path.join(root, "community-accounts.enc")).includes(Buffer.from("studio_refresh_secret")));
  await broker.close();
  broker = await createCommunityVault({directory: root, safeStorage});
  t.after(() => broker.close());
  assert.deepEqual((await call("load", source)).body.value, value);
  assert.equal((await call("delete", source)).status, 200);
  assert.equal((await call("load", source)).body.value, null);
  const other = await createCommunityVault({directory: path.join(root, "instance"), safeStorage});
  t.after(() => other.close());
  assert.notEqual(other.env.LUMINA_COMMUNITY_VAULT_TOKEN, broker.env.LUMINA_COMMUNITY_VAULT_TOKEN);
});

test("vault denies browser origins, unauthenticated requests, and plaintext storage", async (t) => {
  assert.ok(fs.existsSync(modulePath));
  const {createCommunityVault} = require(modulePath);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-vault-"));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const unavailable = await createCommunityVault({directory: root,
    safeStorage: {...encryption(), getSelectedStorageBackend: () => "basic_text"}});
  assert.deepEqual(unavailable.env, {});
  await unavailable.close();
  const broker = await createCommunityVault({directory: root, safeStorage: encryption()});
  t.after(() => broker.close());
  for (const headers of [{}, {"X-Lumina-Vault": "é".repeat(64)},
    {Origin: "http://localhost:4174", "X-Lumina-Vault": broker.env.LUMINA_COMMUNITY_VAULT_TOKEN}]) {
    const response = await fetch(broker.env.LUMINA_COMMUNITY_VAULT_URL, {
      method: "POST", headers, body: JSON.stringify({action: "load", source: "https://example.com"}),
    });
    assert.equal(response.status, 403);
  }
});

test("an unavailable OS credential service leaves local Studio usable", async () => {
  const {createCommunityVault} = require(modulePath);
  const broker = await createCommunityVault({directory: "/unused", safeStorage: {
    isEncryptionAvailable() { throw new Error("OS service is unavailable"); },
  }});
  assert.deepEqual(broker.env, {});
  await broker.close();
});
