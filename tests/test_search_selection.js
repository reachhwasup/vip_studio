const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('源码_开源版/static/index.html', 'utf8');
function harness() {
  const context = vm.createContext({rows:[
    {id:'ready',availability:'available',checked:false},
    {id:'empty',availability:'unavailable',checked:true},
    {id:'unknown',availability:'unknown',checked:false}
  ], renders:0, renderRows(){this.renders++;}});
  vm.runInContext(html.slice(html.indexOf('function canSelectRow('),html.indexOf('function updateTableStatus(')),context);
  return context;
}
test('select all skips unavailable titles and clears stale selection on them',()=>{
  const h=harness();h.selectAllRows(true);
  assert.equal(h.rows[1].checked,false);
  assert.deepEqual(Array.from(h.selectedRows(),row=>row.id),['ready','unknown']);
  h.selectAllRows(false);assert.equal(h.selectedRows().length,0);
});
test('unavailable titles remain excluded even when saved selection is stale',()=>{
  const h=harness();assert.equal(h.selectedRows().length,0);
  h.rows[0].checked=true;assert.deepEqual(Array.from(h.selectedRows(),row=>row.id),['ready']);
});
