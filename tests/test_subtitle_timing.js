const test = require('node:test');
const assert = require('node:assert/strict');
const retime = require('../源码_开源版/static/subtitle-timing.js');
const cues = [{start_time: 2, end_time: 4, text: 'Hello', speaker: 'A', original_text: '你好'}, {start_time: 8, end_time: 10, text: 'Bye'}];
test('stretches fast captions and compresses slow captions, including gaps', () => {
  assert.deepEqual(retime(cues, 20).map(c => [c.start_time, c.end_time]), [[4, 8], [16, 20]]);
  assert.deepEqual(retime(cues, 5).map(c => [c.start_time, c.end_time]), [[1, 2], [4, 5]]);
});
test('offset and target end compose; metadata and originals are preserved', () => {
  const result = retime(cues, 12, 2);
  assert.deepEqual(result[0], {...cues[0], start_time: 4, end_time: 6});
  assert.equal(result[1].end_time, 12);
  assert.equal(cues[0].start_time, 2);
});
test('uses the latest end even for unsorted or overlapping captions', () => {
  assert.equal(retime([...cues].reverse(), 20)[0].end_time, 20);
});
test('rejects invalid transformations atomically instead of dropping or truncating captions', () => {
  for (const end of [0, -1, NaN, Infinity]) assert.throws(() => retime(cues, end));
  assert.throws(() => retime([], 10));
  assert.throws(() => retime(cues, 10, -10));
  assert.throws(() => retime(cues, 10, 10));
  assert.throws(() => retime(cues, .001));
  assert.throws(() => retime(cues, 1000), /30-second/);
  assert.throws(() => retime([{start_time: 4, end_time: 2}], 10));
  assert.equal(cues[1].end_time, 10);
});
