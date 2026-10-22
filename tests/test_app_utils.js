const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readJSON, resumePosition, selectLibrary} = require('../源码_开源版/static/app-utils.js');
test('HTTP HTML and truncated JSON become readable errors, not parser exceptions', async () => {
  await assert.rejects(readJSON(new Response('<!doctype html>', {status:502, headers:{'content-type':'text/html'}})), /unexpected response.*502/);
  await assert.rejects(readJSON(new Response('{', {headers:{'content-type':'application/json'}})), /incomplete response/);
  assert.deepEqual(await readJSON(new Response('{"error":"Unavailable"}', {status:503,headers:{'content-type':'application/json'}})), {error:'Unavailable'});
});
test('resume ignores completed, invalid and out-of-range positions', () => {
  assert.equal(resumePosition({time:20},100),20);
  for (const saved of [null,{time:-1},{time:NaN},{time:99},{time:120},{time:20,completed:true}]) assert.equal(resumePosition(saved,100),0);
  assert.equal(resumePosition({time:20},NaN),0);
});
test('subtitle and continue filters combine with episode search without reordering original library', () => {
  const a={title:'Alpha',modified:1,episodes:[{title:'Episode 1',url:'/a',subtitle_url:'/a.srt'}]};
  const b={title:'Beta',modified:2,episodes:[{title:'Episode 2',url:'/b',subtitle_url:''}]};
  const items=[a,b], progress={'/a':{time:20,completed:true},'/b':{time:10,completed:false}};
  assert.deepEqual(selectLibrary(items,'','missing','recent',progress),[b]);
  assert.deepEqual(selectLibrary(items,'Episode 2','continue','title',progress),[b]);
  assert.deepEqual(selectLibrary(items,'','all','recent',progress),[b,a]);
  assert.deepEqual(items,[a,b]);
});
