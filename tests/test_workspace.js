const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('源码_开源版/static/index.html', 'utf8');
const source = fs.readFileSync('源码_开源版/static/workspace.js', 'utf8');
function harness() {
  const controls = Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], {textContent: '', hidden: true, classList: {toggle() {}, add() {}}}]));
  const listeners = {};
  const context = vm.createContext({window: {addEventListener: (key, fn) => {listeners[key] = fn;}}, document: {getElementById: key => controls[key], addEventListener() {}, querySelector() {}}, MutationObserver: class {observe() {}}, setTab() {}, setDownloadView() {}});
  vm.runInContext(source, context);
  return {summary: context.window.vipWorkspaceSummary, controls, listeners};
}
test('activity distinguishes a paused queue from active transfers and saved videos', () => {
  const {summary} = harness();
  assert.equal(summary([{status:'pending'}], new Map(), false).videos, 'Queue paused');
  assert.equal(summary([{status:'pending'}], new Map(), true).videos, 'Starting downloads');
  const active = summary([{status:'running'}, {status:'error'}, {status:'done'}], new Map(), true);
  assert.equal(active.videos, '1 downloading');
  assert.equal(active.videoDetail, '0 waiting · 1 failed · 1 saved');
});
test('subtitle summary deduplicates jobs observed in Downloads and Library', () => {
  const {summary} = harness();
  const state = summary([{status:'done',subtitleJobId:'a',subtitleStatus:'running',subtitleProgress:54,subtitleStage:'Reading captions'}], new Map([['a',{status:'running'}], ['b',{status:'queued'}]]), false);
  assert.equal(state.subtitles, 'Processing · 54%');
  assert.equal(state.subtitleDetail, 'Reading captions · 1 waiting');
  assert.equal(state.busy, true);
});
test('completed subtitles clear the activity state without hiding saved videos', () => {
  const {summary} = harness();
  const state = summary([{status:'done',subtitleJobId:'a',subtitleStatus:'done'}], new Map(), false);
  assert.equal(state.subtitles, 'No active jobs'); assert.equal(state.videos, '1 saved'); assert.equal(state.busy, false);
});
test('postponed native update remains visible across tabs and opens download activity', () => {
  const {controls,listeners} = harness();
  listeners['vip-native-update']({detail:{postponed:true,message:'Waiting for subtitles to finish.'}});
  assert.equal(controls.updateNotice.hidden, false);
  assert.equal(controls.updateNoticeMessage.textContent, 'Waiting for subtitles to finish.');
  assert.equal(typeof controls.updateViewActivity.onclick, 'function');
});
