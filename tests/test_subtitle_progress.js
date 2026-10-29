const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../源码_开源版/static/index.html'), 'utf8');
const library = fs.readFileSync(path.join(__dirname, '../源码_开源版/static/library.js'), 'utf8');
function harness(job) {
  const controls = Object.fromEntries(Array.from(html.matchAll(/\bid="([^"]+)"/g), match => [match[1], {dataset: {}, parentElement: {classList: {toggle() {}}}, removeAttribute(key) {delete this[key];}}]));
  const context = vm.createContext({selectedEpisode: {url:'/src/1.mp4'}, subtitleJobs: new Map([['/src/1.mp4',job]]), window:{}, el: id => controls[id]});
  const start = library.indexOf('  function renderSubtitleStatus()');
  const end = library.indexOf("  window.addEventListener('vip-subtitle-progress'",start);
  vm.runInContext(library.slice(start,end),context);
  return {context,controls};
}
test('Library progress renderer binds to the actual HTML control and displays image progress', () => {
  const h=harness({status:'running',stage:'Reading on-screen captions',progress:50,completed:100,total:200});
  h.context.renderSubtitleStatus();
  assert.equal(h.controls.librarySubtitleProgress.value,50);
  assert.equal(h.controls.librarySubtitleProgress.hidden,false);
  assert.match(h.controls.librarySubtitleStatus.textContent,/50%/);
  assert.match(h.controls.librarySubtitleStatus.textContent,/100\/200 images/);
});
test('queued subtitles show zero and preparation switches to indeterminate progress', () => {
  const job={status:'queued',progress:null};const h=harness(job);h.context.renderSubtitleStatus();
  assert.equal(h.controls.librarySubtitleProgress.value,0);
  assert.equal(h.controls.librarySubtitleBadge.textContent,'Queued');
  job.status='running';job.stage='Extracting video frames';h.context.renderSubtitleStatus();
  assert.equal(h.controls.librarySubtitleProgress.value,undefined);
  assert.equal(h.controls.librarySubtitleStatus.textContent,'Extracting video frames');
  assert.equal(h.controls.librarySubtitleBadge.textContent,'Processing');
});
