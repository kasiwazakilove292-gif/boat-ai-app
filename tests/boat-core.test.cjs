const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {parseCSV,resultIndex,matchRecords}=require('../boat-core.js');
const row=(changes={})=>({date:'2026-10-01',race:'1',trifecta:'1-2-3',payout_yen:'1230',...changes});
const record=(changes={})=>({id:1,date:'2026-10-01',raceNo:1,venue:'大村',betType:'3連単',
 combination:'1-2-3',stake:300,result:'未確定',payout:0,...changes});

test('CSV handles BOM, CRLF, embedded quotes, commas and multiline fields',()=>{
 const rows=parseCSV('\ufeffdate,note\r\n2026-10-01,"a,""b""\nc"\r\n',['date','note']);
 assert.deepEqual(rows,[{date:'2026-10-01',note:'a,"b"\nc'}]);
});
test('CSV rejects missing columns, duplicate columns, broken rows and quotes',()=>{
 for(const text of ['date,x\na,b','date,date\na,b','date,note\na','date,note\na,"b']){
  assert.throws(()=>parseCSV(text,['date','note']));
 }
});
test('official payout scales from 100 yen, never from estimated odds',()=>{
 const plan=matchRecords([record({odds:999})],resultIndex([row()]).index);
 assert.equal(plan.hits[0].payout,3690);
});
test('unmatched tickets remain manual because refunds are unknown',()=>{
 const original=record({combination:'4-5-6'});
 const plan=matchRecords([original],resultIndex([row()]).index);
 assert.equal(plan.hits.length,0);
 assert.equal(plan.checks.length,1);
 assert.equal(original.result,'未確定');
});
test('settled records, other venues and other bet types are not updated',()=>{
 const plan=matchRecords([record({result:'返還'}),record({venue:'福岡'}),record({betType:'3連複'})],resultIndex([row()]).index);
 assert.equal(plan.hits.length,0);
 assert.equal(plan.unsupported,2);
});
test('missing result is distinct from an unmatched combination',()=>{
 const plan=matchRecords([record({raceNo:2})],resultIndex([row()]).index);
 assert.equal(plan.missing,1);
 assert.equal(plan.checks.length,0);
});
test('duplicate or conflicting results are blocked, irrespective of order',()=>{
 for(const duplicate of [row(),row({trifecta:'4-5-6'}),row({payout_yen:'NaN'})]){
  for(const rows of [[row(),duplicate],[duplicate,row()]]){
   const result=resultIndex(rows);
   assert.equal(result.index.size,0);
   assert.equal(result.blocked.size,1);
  }
 }
});
test('invalid result values cannot produce a payout',()=>{
 for(const changes of [{date:'2026-02-30'},{race:'13'},{trifecta:'1-1-2'},
  {payout_yen:'0'},{payout_yen:'Infinity'},{payout_yen:'-10'},{payout_yen:'12.3'}]){
  assert.equal(resultIndex([row(changes)]).index.size,0);
 }
});
test('bad combinations, fractional or zero stakes and invalid dates are not settled',()=>{
 const rows=[record({stake:0}),record({stake:150}),record({stake:NaN}),record({stake:Infinity}),
 record({stake:5100}),record({combination:'1-1-2'}),record({date:'2026-02-30'})];
 const plan=matchRecords(rows,resultIndex([row()]).index);
 assert.equal(plan.hits.length,0);
 assert.equal(plan.invalid,rows.length);
});
test('loading or previewing results does not mutate paper records',()=>{
 const records=[record(),record({id:2,result:'的中',payout:4560})];
 const before=JSON.stringify(records);
 matchRecords(records,resultIndex([row()]).index);
 assert.equal(JSON.stringify(records),before);
});
test('all inline and external app scripts parse',()=>{
 const html=fs.readFileSync(require.resolve('../index.html'),'utf8');
 for(const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
 for(const file of ['boat-core.js','validation.js'])new vm.Script(fs.readFileSync(require.resolve('../'+file),'utf8'));
});
