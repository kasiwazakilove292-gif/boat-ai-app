/* Entry-only ranking model. No result, odds, exhibition or motor-id history input. */
(function(root,factory){
 const api=factory();
 if(typeof module==="object"&&module.exports)module.exports=api;
 else root.BoatModel=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
 "use strict";
 const fields=["national_win_rate","national_2rate","local_win_rate","motor_2rate","average_st","f_count"];
 const featureNames=[...Array.from({length:6},(_,i)=>"lane_"+(i+1)),...fields];
 const specs=[[0,10,2,true],[0,100,25,false],[0,10,2,false],[0,100,25,false],[0,1,-.05,false],[0,9,1,false]];
 function matrix(rows){
  if(!Array.isArray(rows)||rows.length!==6||new Set(rows.map(r=>Number(r.boat_no))).size!==6
     ||rows.some(r=>!Number.isInteger(Number(r.boat_no))||Number(r.boat_no)<1||Number(r.boat_no)>6)
     ||new Set(rows.map(r=>r.racer_id)).size!==6||rows.some(r=>!/^\d{4}$/.test(r.racer_id))){
   throw new Error("6艇・6選手の出走表がそろっていません。");
  }
  rows=[...rows].sort((a,b)=>Number(a.boat_no)-Number(b.boat_no));
  const x=rows.map((r,i)=>Array.from({length:12},(_,j)=>j<6&&i===j?1:0));
  fields.forEach((field,column)=>{
   const [min,max,scale,required]=specs[column];
   const values=rows.map(row=>{
    const raw=row[field];
    if(raw==null||raw===""||raw==="-"){
     if(required)throw new Error("全国勝率が欠損しています。");
     return null;
    }
    const value=Number(raw);
    if(!Number.isFinite(value)||value<min||value>max)throw new Error("出走表の数値に異常があります。");
    return value;
   });
   const present=values.filter(v=>v!==null);
   const mean=present.length?present.reduce((a,b)=>a+b,0)/present.length:0;
   values.forEach((value,i)=>{x[i][column+6]=value===null?0:(value-mean)/scale;});
  });
  return x;
 }
 function validate(model){
  if(!model||model.schema_version!==1||model.algorithm!=="entry_pl_v1"
     ||JSON.stringify(model.features)!==JSON.stringify(featureNames)
     ||!Array.isArray(model.weights)||model.weights.length!==12
     ||model.weights.some(w=>typeof w!=="number"||!Number.isFinite(w)||Math.abs(w)>100)
     ||typeof model.temperature!=="number"||!Number.isFinite(model.temperature)||model.temperature<=0
     ||!/^\d{4}-\d{2}-\d{2}$/.test(model.trained_through)
     ||!model.version||!model.evaluation?.metrics){
   throw new Error("モデルの形式が異なります。再読み込みしてください。");
  }
 }
 function distribution(x,weights,temperature){
  if(!Array.isArray(x)||x.length!==6||x.some(r=>!Array.isArray(r)||r.length!==12||r.some(v=>!Number.isFinite(v)))
     ||weights.length!==12||weights.some(v=>!Number.isFinite(v))||!Number.isFinite(temperature)||temperature<=0){
   throw new Error("予想計算の入力が不正です。");
  }
  const scores=x.map(row=>row.reduce((s,v,i)=>s+v*weights[i],0)/temperature);
  const maximum=Math.max(...scores);
  const strength=scores.map(s=>Math.exp(s-maximum));
  const total=strength.reduce((a,b)=>a+b,0);
  const result=[];
  for(let a=0;a<6;a++)for(let b=0;b<6;b++)if(b!==a)for(let c=0;c<6;c++)if(c!==a&&c!==b){
   const afterA=strength.reduce((sum,v,i)=>sum+(i===a?0:v),0);
   const afterAB=strength.reduce((sum,v,i)=>sum+(i===a||i===b?0:v),0);
   const probability=strength[a]/total*strength[b]/afterA*strength[c]/afterAB;
   if(!Number.isFinite(probability))throw new Error("予想確率を計算できません。");
   result.push({combination:[a+1,b+1,c+1].join("-"),probability});
  }
  return result;
 }
 function aggregate(trifectas,type){
  if(!["3連単","2連単","3連複"].includes(type))throw new Error("券種が不正です。");
  const grouped=new Map();
  trifectas.forEach(row=>{
   const boats=row.combination.split("-").map(Number);
   const key=type==="2連単"?boats.slice(0,2).join("-")
    :type==="3連複"?[...boats].sort((a,b)=>a-b).join("-"):row.combination;
   grouped.set(key,(grouped.get(key)||0)+row.probability);
  });
  return [...grouped].map(([combination,probability])=>({combination,probability}))
   .sort((a,b)=>b.probability-a.probability||a.combination.localeCompare(b.combination));
 }
 function predict(model,rows,day){
  validate(model);
  if(!/^\d{4}-\d{2}-\d{2}$/.test(day)||new Date(day).toISOString().slice(0,10)!==day){
   throw new Error("レース日が不正です。");
  }
  if(day<=model.trained_through){
   throw new Error("この日は配信モデルの学習期間内です。過去の成績は時系列テストの集計で確認してください。");
  }
  if(!Array.isArray(rows)||rows.length!==6)throw new Error("このレースは6艇分の出走表がまだ保存されていません。");
  if(rows.some(r=>r.date!==day||r.venue!=="24"||!Number.isInteger(Number(r.race_no))
     ||Number(r.race_no)<1||Number(r.race_no)>12)||new Set(rows.map(r=>Number(r.race_no))).size!==1){
   throw new Error("異なる日付・場・レースのデータが混ざっています。");
  }
  return distribution(matrix(rows),model.weights,model.temperature);
 }
 return {matrix,validate,distribution,aggregate,predict,featureNames};
});
