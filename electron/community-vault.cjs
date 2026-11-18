"use strict";
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

async function createCommunityVault({directory, safeStorage}) {
  const unavailable = () => ({env: {}, close: async () => {}});
  try {
    if (!safeStorage.isEncryptionAvailable() || safeStorage.getSelectedStorageBackend?.() === "basic_text") {
      return unavailable();
    }
  } catch { return unavailable(); }
  const filename = path.join(directory, "community-accounts.enc");
  const secret = crypto.randomBytes(32).toString("hex");
  const server = http.createServer(async (request, response) => {
    const send = (status, body) => {
      response.writeHead(status, {"Content-Type": "application/json", "Cache-Control": "no-store"});
      response.end(JSON.stringify(body));
    };
    const supplied = request.headers["x-lumina-vault"];
    if (request.method !== "POST" || request.url !== "/" || request.headers.origin !== undefined
        || typeof supplied !== "string" || !/^[a-f0-9]{64}$/.test(supplied)
        || !crypto.timingSafeEqual(Buffer.from(supplied), Buffer.from(secret))) {
      send(403, {error: "Denied"}); return;
    }
    try {
      let body = "";
      for await (const part of request) {
        body += part;
        if (body.length > 16384) { send(413, {error: "Too large"}); return; }
      }
      const {action, source, value} = JSON.parse(body);
      if (typeof source !== "string") { send(400, {error: "Invalid source"}); return; }
      const url = new URL(source);
      if (source.length > 2048 || url.username || url.password || url.search || url.hash
          || (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)))) {
        send(400, {error: "Invalid source"}); return;
      }
      const key = crypto.createHash("sha256").update(source).digest("hex");
      let entries = {};
      if (fs.existsSync(filename)) {
        entries = JSON.parse(safeStorage.decryptString(fs.readFileSync(filename)));
        if (!entries || typeof entries !== "object" || Array.isArray(entries)) {
          send(503, {error: "Protected storage is unavailable"}); return;
        }
      }
      if (action === "load") { send(200, {value: entries[key] || null}); return; }
      if (action === "save") {
        if (!value || typeof value !== "object" || typeof value.refresh_token !== "string"
            || !value.refresh_token.startsWith("studio_refresh_") || value.refresh_token.length > 128) {
          send(400, {error: "Invalid credential"}); return;
        }
        entries[key] = value;
      } else if (action === "delete") {
        delete entries[key];
      } else { send(400, {error: "Invalid action"}); return; }
      fs.mkdirSync(directory, {recursive: true, mode: 0o700});
      const temporary = filename + "." + crypto.randomBytes(8).toString("hex") + ".tmp";
      try {
        fs.writeFileSync(temporary, safeStorage.encryptString(JSON.stringify(entries)), {mode: 0o600, flag: "wx"});
        fs.renameSync(temporary, filename);
      } finally {
        if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
      }
      send(200, {ok: true});
    } catch {
      // Never return credential text, file contents or OS secret-store errors.
      send(503, {error: "Protected storage is unavailable"});
    }
  });
  server.requestTimeout = 5000;
  server.headersTimeout = 5000;
  try {
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
  } catch { return unavailable(); }
  server.unref();
  return {
    env: {
      LUMINA_COMMUNITY_VAULT_URL: `http://127.0.0.1:${server.address().port}/`,
      LUMINA_COMMUNITY_VAULT_TOKEN: secret,
    },
    close: () => new Promise((resolve) => { server.close(resolve); server.closeAllConnections(); }),
  };
}

module.exports = {createCommunityVault};
