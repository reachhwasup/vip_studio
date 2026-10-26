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
  return {controls, listeners};
}
test('postponed native update remains visible across tabs and opens download activity', () => {
  const {controls,listeners} = harness();
  listeners['vip-native-update']({detail:{postponed:true,message:'Waiting for subtitles to finish.'}});
  assert.equal(controls.updateNotice.hidden, false);
  assert.equal(controls.updateNoticeMessage.textContent, 'Waiting for subtitles to finish.');
  assert.equal(typeof controls.updateViewActivity.onclick, 'function');
});
