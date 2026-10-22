const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../源码_开源版/static/index.html'), 'utf8');
const between = (a, b) => html.slice(html.indexOf(a), html.indexOf(b, html.indexOf(a)));
function harness(count = 9, parallel = 4, subtitles = false) {
  const pending = [], urls = [];
  const context = vm.createContext({
    tasks: Array.from({length: count}, (_, i) => ({id: String(i), title: 'Episode ' + i, status: 'pending'})),
    running: false, activeWorkers: 0, queueStats: null, subtitleReady: subtitles,
    subtitlesWanted: () => subtitles, values: new Map([['duanju_parallel', String(parallel)]]),
    localStorage: {getItem: key => context.values.get(key) ?? null},
    $: () => ({checked: false}), askNotifyPermission() {}, renderTasks() {}, toast() {},
    watchProgress: () => () => {}, skipExistingWanted: () => true, safe: value => value,
    briefError: value => value, NETWORK_ERROR: /never/, setTab() {}, loadConfig() {},
    queueEnded() { context.running = false; context.queueStats = null; },
    fetch(url) { urls.push(url); return new Promise(resolve => pending.push(() => resolve({ok: true, data: {url: '/src/' + new URL('http://local' + url).searchParams.get('vid') + '.mp4', subtitle_job: subtitles ? {id: 'job-' + urls.length, status: 'queued'} : undefined}}))); },
    vipReadJSON: async response => response.data,
  });
  vm.runInContext(between('function parallelWanted()', 'function skipExistingWanted()'), context);
  vm.runInContext(between('async function startQueue()', 'function queueEnded()'), context);
  const start = html.indexOf('async function runTask(t)');
  vm.runInContext(html.slice(start, html.indexOf('\n', start)), context);
  return {context, pending, urls, flush: () => new Promise(resolve => setImmediate(resolve))};
}
test('runs four different episode transfers together and does not duplicate on repeated Start', async () => {
  const h = harness(); await h.context.startQueue(); await h.context.startQueue();
  assert.equal(h.urls.length, 4); assert.equal(h.context.activeWorkers, 4);
  assert.equal(new Set(h.urls).size, 4);
  h.pending.shift()(); await h.flush();
  assert.equal(h.urls.length, 5);
  while (h.pending.length) { h.pending.shift()(); await h.flush(); }
  assert.equal(h.context.tasks.filter(t => t.status === 'done').length, 9);
  assert.equal(h.context.activeWorkers, 0);
});
test('reducing concurrency drains extra workers before starting more episodes', async () => {
  const h = harness(); await h.context.startQueue(); h.context.values.set('duanju_parallel', '1');
  for (let i = 0; i < 3; i++) { h.pending.shift()(); await h.flush(); assert.equal(h.urls.length, 4); }
  assert.equal(h.context.activeWorkers, 1);
  h.pending.shift()(); await h.flush(); assert.equal(h.urls.length, 5);
});
test('raising concurrency starts extra transfers immediately and Pause preserves pending episodes', async () => {
  const h = harness(8, 1); await h.context.startQueue(); assert.equal(h.urls.length, 1);
  h.context.values.set('duanju_parallel', '4'); await h.context.startQueue(); assert.equal(h.urls.length, 4);
  h.context.running = false;
  while (h.pending.length) { h.pending.shift()(); await h.flush(); }
  assert.equal(h.urls.length, 4); assert.equal(h.context.tasks.filter(t => t.status === 'pending').length, 4);
});
test('queued subtitles release download slots so later video transfers can start', async () => {
  const h = harness(8, 4, true); await h.context.startQueue();
  assert.ok(h.urls.every(url => url.includes('subtitles=background')));
  h.pending.shift()(); await h.flush();
  assert.equal(h.urls.length, 5);
  assert.equal(h.context.tasks[0].status, 'done');
  assert.equal(h.context.tasks[0].subtitleStatus, 'queued');
});
test('parallel preference defaults to three and validates stored values', () => {
  const h = harness();
  h.context.values.clear(); assert.equal(h.context.parallelWanted(), 3);
  for (const value of ['0', '5', 'Infinity', '2wrong', '1.5', '']) {
    h.context.values.set('duanju_parallel', value); assert.equal(h.context.parallelWanted(), 3);
  }
  h.context.values.set('duanju_parallel', '1'); assert.equal(h.context.parallelWanted(), 1);
});
test('background subtitle status updates do not undo completed video downloads', async () => {
  const tasks = [{id: '1', status: 'done', url: 'http://127.0.0.1:5056/src/1.mp4', subtitleJobId: 'a', subtitleStatus: 'queued', msg: 'Download complete · subtitles queued · cover saved'}, {id: '2', status: 'done', subtitleJobId: 'b', subtitleStatus: 'running', msg: 'Download complete'}, {id: '3', status: 'done', subtitleJobId: 'missing', subtitleStatus: 'queued', msg: 'Download complete'}];
  let requestCount = 0; const events = [];
  const context = vm.createContext({tasks, setInterval() {}, renderTasks() {}, URL, CustomEvent: class {constructor(name, options) {this.detail = options.detail;}}, window: {location: {href: 'http://127.0.0.1:5056/'}, dispatchEvent(event) {events.push(event);}},
    fetch: async () => { requestCount++; return {ok: true}; },
    vipReadJSON: async () => ({jobs: {a: {status: 'done', subtitle_url: '/src/1.srt'}, b: {status: 'error', error: 'Recognition failed'}}}),
  });
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname, '../源码_开源版/static/download-subtitles.js'), 'utf8'), context);
  await context.pollDownloadSubtitles();
  assert.ok(tasks.every(t => t.status === 'done'));
  assert.equal(tasks[0].subtitle, '/src/1.srt');
  assert.equal(tasks[0].msg, 'Download complete · cover saved · Subtitles: ready');
  assert.equal(events[0].detail.url, '/src/1.mp4');
  assert.equal(events[0].detail.subtitle_url, '/src/1.srt');
  assert.match(tasks[1].detail, /Recognition failed/);
  assert.equal(tasks[2].subtitleStatus, 'unavailable');
  await context.pollDownloadSubtitles(); assert.equal(requestCount, 1);
});
