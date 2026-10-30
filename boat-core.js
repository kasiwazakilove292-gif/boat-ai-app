/* Shared parsing and result matching; also exercised by Node's test runner. */
(function(root,factory){
 const api=factory();
 if(typeof module==="object"&&module.exports)module.exports=api;
 else root.BoatCore=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
 "use strict";
 function parseCSV(text,required=[]){
  text=text.replace(/^\uFEFF/,"");
  const rows=[];
  let row=[],cell="",quoted=false;
  for(let i=0;i<text.length;i++){
   const c=text[i];
   if(c==='"'){
    if(quoted&&text[i+1]==='"'){cell+='"';i++;}
    else quoted=!quoted;
   }else if(c===","&&!quoted){row.push(cell);cell="";}
   else if((c==="\n"||c==="\r")&&!quoted){
    if(c==="\r"&&text[i+1]==="\n")i++;
    row.push(cell);
    if(row.some(x=>x!==""))rows.push(row);
    row=[];cell="";
   }else cell+=c;
  }
  if(quoted)throw new Error("CSVの引用符が閉じていません");
  if(cell!==""||row.length){row.push(cell);rows.push(row);}
  const headers=rows.shift()||[];
  if(new Set(headers).size!==headers.length||!required.every(k=>headers.includes(k))){
   throw new Error("CSV形式を確認できません");
  }
  return rows.map(values=>{
   if(values.length!==headers.length)throw new Error("CSVの列数が異なります");
   return Object.fromEntries(headers.map((h,i)=>[h,values[i]]));
  });
 }
 function validDate(value){
  return typeof value==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(value)
   &&Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;
 }
 function validCombination(value){
  return typeof value==="string"&&/^[1-6]-[1-6]-[1-6]$/.test(value)
   &&new Set(value.split("-")).size===3;
 }
 function resultIndex(rows){
  const index=new Map(),blocked=new Set();
  for(const row of rows){
   const race=Number(row.race),key=row.date+":"+race;
   if(!validDate(row.date)||!Number.isInteger(race)||race<1||race>12)continue;
   if(index.has(key)||blocked.has(key)||!validCombination(row.trifecta)
      ||!/^\d+$/.test(String(row.payout_yen))
      ||!Number.isSafeInteger(Number(row.payout_yen))||Number(row.payout_yen)<=0){
    blocked.add(key);index.delete(key);continue;
   }
   index.set(key,{trifecta:row.trifecta,payoutYen:Number(row.payout_yen)});
  }
  return {index,blocked};
 }
 function matchRecords(records,index){
  const hits=[],checks=[];
  let missing=0,unsupported=0,invalid=0;
  for(const record of records.filter(r=>r.result==="未確定")){
   if(record.venue!=="大村"||record.betType!=="3連単"){unsupported++;continue;}
   if(!validDate(record.date)||!Number.isInteger(Number(record.raceNo))
      ||Number(record.raceNo)<1||Number(record.raceNo)>12
      ||!validCombination(record.combination)
      ||!Number.isSafeInteger(record.stake)||record.stake<=0||record.stake>5000
      ||record.stake%100!==0){invalid++;continue;}
   const result=index.get(record.date+":"+Number(record.raceNo));
   if(!result){missing++;continue;}
   if(record.combination!==result.trifecta){checks.push({record,result});continue;}
   const payout=result.payoutYen*(record.stake/100);
   if(!Number.isSafeInteger(payout)){invalid++;continue;}
   hits.push({record,result,payout});
  }
  return {hits,checks,missing,unsupported,invalid};
 }
 return {parseCSV,resultIndex,matchRecords};
});
