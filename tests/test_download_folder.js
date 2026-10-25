const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function harness(fetch) {
  const fields = {}, scheduled = [];
  let resumes = 0;
  const context = vm.createContext({running: true, fetch, readFolderResponse: async response => response.data,
    $: id => fields[id] ||= {value: '', textContent: '', scrollIntoView() {}},
    renderTasks() {}, setTab() {}, toast() {}, showDownloadPath() {},
    setTimeout: callback => scheduled.push(callback), startQueue: () => resumes++,
  });
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname, '../源码_开源版/static/download-folder.js'), 'utf8'), context);
  return {context, fields, scheduled, resumes: () => resumes};
}
test('one native picker handles concurrent folder failures and resumes once after save', async () => {
  let picker, opened = 0, saved = 0;
  const h = harness((url, options) => {
    if (url.endsWith('/browse')) { opened++; return new Promise(resolve => picker = resolve); }
    saved++; assert.equal(JSON.parse(options.body).download_path, '/new/videos');
    return Promise.resolve({ok: true, data: {download_path: '/new/videos'}});
  });
  const first = h.context.recoverDownloadFolder(), second = h.context.recoverDownloadFolder();
  assert.equal(opened, 1); assert.equal(h.context.running, false);
  picker({ok: true, data: {download_path: '/new/videos'}});
  await Promise.all([first, second]); assert.equal(saved, 1); assert.equal(h.scheduled.length, 1);
  h.scheduled[0](); assert.equal(h.resumes(), 1);
});
test('cancelling the picker keeps the queue paused and does not save a folder', async () => {
  let requests = 0;
  const h = harness(async () => {requests++; return {ok: true, data: {cancelled: true}};});
  assert.equal(await h.context.recoverDownloadFolder(), false);
  assert.equal(h.context.running, false); assert.equal(requests, 1); assert.equal(h.scheduled.length, 0);
  assert.match(h.fields.downloadPathStatus.textContent, /remain queued/);
});
test('preflight opens folder selection for a missing folder instead of starting transfers', async () => {
  const urls = [];
  const h = harness(async url => {urls.push(url); return {ok: true, data: url.includes('?check=1') ? {available: false} : {cancelled: true}};});
  assert.equal(await h.context.checkDownloadFolder(), false);
  assert.deepEqual(urls, ['/api/download-path?check=1', '/api/download-path/browse']);
});
