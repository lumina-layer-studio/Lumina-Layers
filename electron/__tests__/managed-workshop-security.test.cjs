const test = require('node:test');
const assert = require('node:assert/strict');
const security = require('../workshop-security.cjs');
const host = 'http://127.0.0.1:8000/';
const moduleUrl = 'lumina-workshop://fixture.hello/1.0.0/ui/index.html';

test('managed desktop enables only its exact frontend and preserves module isolation', () => {
  assert.equal(security.isAllowedWorkshopIpcSender(host), false);
  security.enableManagedDesktopHost();
  assert.equal(security.isAllowedWorkshopRequest({ url: host, resourceType: 'mainFrame', frameUrl: 'about:blank', initiator: null }), true);
  assert.equal(security.isAllowedWorkshopRequest({ url: `${host}hdr/studio.hdr`, resourceType: 'fetch', frameUrl: host, initiator: host }), true);
  assert.equal(security.isAllowedWorkshopIpcSender(host), true);
  assert.equal(security.isAllowedWorkshopDownload({ frameUrl: host, url: `${host}api/files/result.3mf` }), true);
  assert.equal(security.isAllowedWorkshopDownload({ frameUrl: host, url: `blob:${host}svg-result` }), true);
  for (const url of ['blob:null/result', 'blob:http://localhost:8000/result', 'blob:http://127.0.0.1:9000/result', 'blob:https://example.com/result', 'data:image/svg+xml,test']) {
    assert.equal(security.isAllowedWorkshopDownload({ frameUrl: host, url }), false, url);
  }
  for (const untrusted of ['http://localhost:8000/', 'http://127.0.0.1:9000/', 'http://user@127.0.0.1:8000/', `${host}api/files/untrusted.html`, 'https://example.com/']) {
    assert.equal(security.isAllowedWorkshopIpcSender(untrusted), false, untrusted);
  }
  assert.equal(security.isAllowedWorkshopRequest({ url: `${host}api/settings`, resourceType: 'fetch', frameUrl: moduleUrl, initiator: 'null' }), false);
  assert.equal(security.isAllowedWorkshopIpcSender(moduleUrl), false);
  assert.equal(security.isAllowedWorkshopDownload({ frameUrl: moduleUrl, url: `${host}api/files/result.3mf` }), false);
  assert.equal(security.isAllowedWorkshopDownload({ frameUrl: moduleUrl, url: `blob:${host}svg-result` }), false);
});
