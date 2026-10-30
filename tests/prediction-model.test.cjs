const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const api=require('../prediction-model.js');
const model=require('../data/prediction_model.json');
const rows=()=>Array.from({length:6},(_,i)=>({date:'2099-01-01',venue:'24',race_no:'1',
 boat_no:String(i+1),racer_id:String(4001+i),national_win_rate:String(4+(i+1)*.2),
 national_2rate:String(31+i),local_win_rate:String(3+(i+1)*.3),motor_2rate:String(22+i*2),
 average_st:String(.13+i*.01),f_count:String((i+1)%2)}));
function near(a,b,tol=1e-10){assert.ok(Math.abs(a-b)<tol,`${a} != ${b}`);}

test('uniform scores give 120 mutually exclusive orders totaling one',()=>{
 const p=api.distribution(api.matrix(rows()),Array(12).fill(0),1);
 assert.equal(p.length,120);
 assert.equal(new Set(p.map(r=>r.combination)).size,120);
 p.forEach(r=>near(r.probability,1/120));
 near(p.reduce((s,r)=>s+r.probability,0),1);
});
test('all bet types preserve mass and have exactly 120, 30 or 20 outcomes',()=>{
 const p=api.distribution(api.matrix(rows()),Array(12).fill(0),1);
 for(const [type,size,prob] of [['3連単',120,1/120],['2連単',30,1/30],['3連複',20,1/20]]){
  const result=api.aggregate(p,type);
  assert.equal(result.length,size);
  result.forEach(r=>near(r.probability,prob));
  near(result.reduce((s,r)=>s+r.probability,0),1);
 }
});
test('browser probabilities match exported Python values for all 120 orders',()=>{
 api.validate(model);
 const p=api.distribution(model.parity_fixture.x,model.weights,model.temperature);
 p.forEach((row,i)=>near(row.probability,model.parity_fixture.probabilities[i],1e-11));
 assert.equal(api.aggregate(p,'3連単')[0].combination,model.parity_fixture.top3);
});
test('feature ordering, centering and missing ST imputation agree with specification',()=>{
 const r=rows();r[0].average_st='';
 const x=api.matrix(r);
 assert.equal(x[0][10],0);
 for(let j=6;j<12;j++)near(x.reduce((s,r)=>s+r[j],0),0);
 assert.ok(x[1][10]>x[5][10]);
 assert.deepEqual(api.matrix(r),api.matrix([...r].reverse()));
});
test('incomplete fields, duplicate lanes, duplicate racers and invalid numbers are rejected',()=>{
 for(const change of [{national_win_rate:''},{national_win_rate:'NaN'},{average_st:'Infinity'},
  {motor_2rate:'101'},{boat_no:'1'},{racer_id:'4001'}]){
  assert.throws(()=>api.matrix(rows().map(r=>({...r,...change}))));
 }
 assert.throws(()=>api.matrix(rows().slice(0,5)));
});
test('prediction refuses any day on or before the deployment training end',()=>{
 for(const day of ['2024-01-01',model.trained_through]){
  assert.throws(()=>api.predict(model,rows().map(r=>({...r,date:day})),day),/学習期間内/);
 }
 assert.equal(api.predict(model,rows(),'2099-01-01').length,120);
});
test('mixed dates, venues, races and invalid race numbers cannot be predicted',()=>{
 for(const change of [{date:'2099-01-02'},{venue:'23'},{race_no:'2'},{race_no:'0'},{race_no:'bad'}]){
  const r=rows();r[0]={...r[0],...change};
  assert.throws(()=>api.predict(model,r,'2099-01-01'));
 }
});
test('an uncollected race is reported as missing instead of mixed data',()=>{
 assert.throws(()=>api.predict(model,[],'2099-01-01'),/6艇分の出走表/);
});
test('malformed model, unknown features and non-finite weights are refused',()=>{
 for(const change of [{schema_version:2},{features:[]},{temperature:0},{weights:Array(12).fill(NaN)}]){
  assert.throws(()=>api.validate({...model,...change}));
 }
});
test('forecast scripts and inline app script parse',()=>{
 for(const f of ['prediction-model.js','forecast-ui.js'])new vm.Script(fs.readFileSync(require.resolve('../'+f),'utf8'));
 const html=fs.readFileSync(require.resolve('../index.html'),'utf8');
 for(const m of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
});
