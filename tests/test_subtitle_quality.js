const test = require('node:test');
const assert = require('node:assert/strict');
const analyze = require('../源码_开源版/static/subtitle-quality.js');
const cue = (start_time, end_time, text = '你好') => ({start_time, end_time, text});
test('finds opening, interior and trailing gaps without assuming silence is dialogue', () => {
  assert.deepEqual(analyze([cue(6, 8), cue(14, 16)], 23).filter(i => i.kind === 'gap').map(i => i.time), [0, 8, 16]);
});
test('nested and unsorted cues preserve original indices and covered interval', () => {
  const issues = analyze([cue(5, 6), cue(0, 12), cue(8, 9), cue(12, 13)], 13);
  assert.deepEqual(issues.filter(i => i.kind === 'overlap').map(i => i.index), [0, 2]);
  assert.equal(issues.filter(i => i.kind === 'gap').length, 0);
});
test('adjacent captions and multilingual text remain unflagged', () => {
  assert.deepEqual(analyze([cue(0, 2, 'សួស្តី'), cue(2, 4, '你好'), cue(4, 6, 'Hello')], 6), []);
});
test('detects bad OCR, empty text, invalid timings, speed and video overrun', () => {
  const kinds = analyze([cue(0, 1, '\uFFFD'), cue(1, 2, ''), cue(4, 3), cue(3, 3.1, 'Too much text to read'), cue(5, 7, 'aaaaa')], 6).map(i => i.kind);
  for (const kind of ['text', 'timing', 'reading']) assert.ok(kinds.includes(kind));
});
test('checks refresh after a correction and tolerate unknown duration', () => {
  const cues = [cue(0, 3), cue(2, 4)];
  assert.ok(analyze(cues, NaN).some(i => i.kind === 'overlap'));
  cues[1].start_time = 3;
  assert.deepEqual(analyze(cues, NaN), []);
});
