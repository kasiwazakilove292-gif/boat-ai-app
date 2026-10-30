(()=>{
 "use strict";
 let model=null,modelRequest=null,current=null;
 const pct=p=>(p*100).toFixed(2)+"%";
 const num=n=>Number(n).toLocaleString("ja-JP");
 for(let n=1;n<=12;n++)$("forecastRace").add(new Option(n+"R",n));
 $("forecastDate").value=jstDate();

 function report(){
  if(!model)return;
  const e=model.evaluation,m=e.metrics;
  const rows=[["学習モデル v1",m.model],["艇番順 1-2-3",m.lane_order],["全国勝率の高い順",m.national_win_rate]];
  $("modelReport").innerHTML=`<h2>モデルの時系列テスト</h2>
   <p class="muted">${E(e.test.first_date)} 〜 ${E(e.test.last_date)} ／ ${num(e.test.races)}R。テスト用モデルが学習・調整に使わなかった期間です。</p>
   <div class="metrics">
    <div class="metric"><small>3連単・最上位1点の的中率</small><strong>${m.model.hit_pct.toFixed(1)}%</strong></div>
    <div class="metric"><small>返還未反映の参考回収率</small><strong>${m.model.roi_pct.toFixed(2)}%</strong></div>
   </div>
   <p class="warn">実運用前の過去検証です。${num(e.retrospective_entry_races)}Rはレース日より後に出走表を取得しています。返還情報がないため、着順不一致は返還対象でも支出100円・払戻0円と仮計算しています。</p>
   <div style="overflow:auto"><table><thead><tr><th>同じテスト期間で比較</th><th>的中数</th><th>参考回収率</th></tr></thead>
   <tbody>${rows.map(([label,b])=>`<tr><th scope="row">${E(label)}</th><td>${num(b.hits)}件</td><td>${b.roi_pct.toFixed(2)}%</td></tr>`).join("")}</tbody></table></div>
   <details id="modelDetails"><summary>学習期間と確率の検証を見る</summary>
    <p>学習：${E(e.train.first_date)} 〜 ${E(e.train.last_date)}（${num(e.train.races)}R）<br>
    確率の調整：${E(e.validation.first_date)} 〜 ${E(e.validation.last_date)}（${num(e.validation.races)}R）<br>
    テスト：${E(e.test.first_date)} 〜 ${E(e.test.last_date)}（${num(e.test.races)}R）</p>
    <p>確率誤差（対数損失・小さいほど良い）：${m.negative_log_likelihood.toFixed(3)} ／ 120通りを一律とする場合 ${m.uniform_negative_log_likelihood.toFixed(3)}。1着の的中率 ${m.first_place_hit_pct.toFixed(1)}%。</p>
    <p>テスト完了後、配信用モデルを全${num(model.training_races)}Rで別に学習しています。上のテスト成績は、全期間で再学習する前のモデルの値です。配信用モデルの学習期間内の日付には予想を表示しません。</p>
    <p>配信モデル：${E(model.version)}<br>学習データ：${E(model.trained_from)} 〜 ${E(model.trained_through)}<br>更新：${timeText(model.generated_at)}</p>
   </details>`;
 }
 async function loadModel(){
  if(model)return model;
  if(modelRequest)return modelRequest;
  modelRequest=(async()=>{
   const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
   try{
    const response=await fetch(DATA_ROOT+"prediction_model.json?v="+Date.now(),{cache:"no-store",signal:controller.signal});
    if(!response.ok)throw new Error("モデルを取得できませんでした。");
    const value=await response.json();
    BoatModel.validate(value);
    model=value;
    report();
    return model;
   }finally{clearTimeout(timer);}
  })().finally(()=>{modelRequest=null;});
  return modelRequest;
 }

 function timing(rows,day,race){
  const now=Date.now();
  const bs=beforeInfo.filter(r=>r.date===day&&r.venue==="24"&&Number(r.race_no)===race);
  const deadlines=[...new Set(bs.map(r=>r.deadline_at).filter(t=>
   typeof t==="string"&&t.startsWith(day+"T")&&Number.isFinite(Date.parse(t))))];
  const deadline=deadlines.length===1?deadlines[0]:null;
  const times=rows.map(r=>Date.parse(r.collected_at));
  const known=times.every(t=>Number.isFinite(t)&&t<=now);
  const newest=known?Math.max(...times):null;
  const oldest=known?Math.min(...times):null;
  const reasons=[];
  if(day!==jstDate())reasons.push(day<jstDate()?"過去日の参考表示です。":"開催日前の参考表示です。");
  if(!deadline)reasons.push("締切予定時刻が未取得です。");
  else if(now>=Date.parse(deadline))reasons.push("締切予定時刻を過ぎています。");
  if(!known)reasons.push("出走表の取得時刻を確認できません。");
  else if(now-oldest>30*60000)reasons.push("出走表の取得から30分以上経過しています。");
  if(deadline&&known&&times.some(t=>t>=Date.parse(deadline)))reasons.push("出走表は締切後に取得されています。");
  return {deadline,newest,reasons,mode:reasons.length?"reference":"paper_before_deadline"};
 }
 function draw(){
  if(!current)return;
  const type=$("forecastType").value;
  const t=timing(current.rows,current.day,current.race);
  const candidates=BoatModel.aggregate(current.distribution,type).slice(0,5);
  const first=Array(6).fill(0);
  current.distribution.forEach(r=>{first[Number(r.combination[0])-1]+=r.probability;});
  $("forecastOutput").innerHTML=`<div class="card">
   <h2>${E(current.day)} 大村 ${current.race}R</h2>
   <div class="data-state ${t.reasons.length?"caution":""}">${t.reasons.length?E(t.reasons.join(" "))+" 締切前の記録とは分けて保存します。":"締切予定："+timeText(t.deadline)+"。ペーパーテスト用の予想です。"}</div>
   <p class="muted">出走表の取得：${timeText(t.newest?new Date(t.newest).toISOString():null)}。モデルの学習は${E(model.trained_through)}まで。</p>
   <h2 style="margin-top:18px">1着の推定確率</h2>
   <div class="forecast-first">${first.map((p,i)=>`<div><span class="lane lane${i+1}">${i+1}</span><b>${pct(p)}</b></div>`).join("")}</div>
   <h2 style="margin-top:18px">${E(type)} 上位5候補</h2>
   ${candidates.map((p,i)=>`<div class="forecast-pick"><div><b>${E(p.combination)}</b><p class="muted">モデル推定 ${pct(p.probability)}</p></div><button class="btn secondary" data-forecast-pick="${i}">${t.mode==="reference"?"参考記録へ":"ペーパー記録へ"}</button></div>`).join("")}
   <p class="muted">推定確率は検証中です。オッズを取得していないため、期待回収率や購入推奨額は自動計算しません。候補を選ぶと記録フォームへ進み、オッズを自分で入力できます。</p>
   </div>`;
  $("forecastOutput").querySelectorAll("[data-forecast-pick]").forEach(button=>{
   button.onclick=()=>{
    const candidate=candidates[Number(button.dataset.forecastPick)];
    const freshTiming=timing(current.rows,current.day,current.race);
    const probability=Number((candidate.probability*100).toFixed(2))/100;
    pendingForecast={date:current.day,venue:"大村",raceNo:current.race,betType:type,
     combination:candidate.combination,probability,modelVersion:model.version,
     modelTrainedThrough:model.trained_through,predictionGeneratedAt:current.generatedAt,
     predictionMode:freshTiming.mode,deadline:freshTiming.deadline,
     entryCollectedAt:freshTiming.newest?new Date(freshTiming.newest).toISOString():""};
    $("raceDate").value=current.day;$("venue").value="大村";$("raceNo").value=current.race;
    $("betType").value=type;$("combination").value=candidate.combination;
    $("prob").value=(probability*100).toFixed(2);$("odds").value="";$("stake").value="100";
    $("notes").value=`モデル ${model.version} ／ ${freshTiming.mode==="reference"?"参考記録":"締切前・端末時刻による記録"}`;
    $("forecastRecordNote").textContent="候補とモデル推定確率を引き継ぎました。オッズを入力し、内容を確認して記録してください。";
    $("forecastRecordNote").classList.remove("hidden");
    evUpdate();
    document.querySelector('[data-tab="predict"]').click();
   };
  });
 }
 function clear(){current=null;$("forecastOutput").innerHTML="";}
 async function run(){
  if($("runForecast").disabled)return;
  clear();
  $("runForecast").disabled=true;
  $("latestForecast").classList.add("hidden");
  $("forecastStatus").textContent="出走表とモデルを読み込んでいます…";
  try{
   await Promise.all([loadModel(),loadRaceData()]);
   if(dataError.includes("出走表"))throw new Error("出走表の更新に失敗しました。再読み込み後にお試しください。");
   const day=$("forecastDate").value,race=Number($("forecastRace").value);
   const rows=entries.filter(r=>r.date===day&&r.venue==="24"&&Number(r.race_no)===race);
   const distribution=BoatModel.predict(model,rows,day);
   current={rows,day,race,distribution,generatedAt:new Date().toISOString()};
   draw();
   $("forecastStatus").textContent="出走表から予想を計算しました。表示時刻とモデルのテスト成績も確認してください。";
  }catch(error){
   $("forecastStatus").textContent=error?.name==="AbortError"?"読み込みが時間切れになりました。もう一度お試しください。":error.message||"予想を計算できませんでした。";
   if(model){
    const dates=[...new Set(entries.filter(r=>r.venue==="24"&&r.date>model.trained_through).map(r=>r.date))].sort();
    const latest=dates.at(-1);
    if(latest&&latest!==$("forecastDate").value){
     $("latestForecast").textContent="保存済み最新日（"+latest+"）で見る";
     $("latestForecast").classList.remove("hidden");
     $("latestForecast").onclick=()=>{$("forecastDate").value=latest;run();};
    }
   }
  }finally{$("runForecast").disabled=false;}
 }
 $("runForecast").onclick=run;
 $("forecastType").onchange=draw;
 ["forecastDate","forecastRace"].forEach(id=>$(id).addEventListener("change",()=>{
  clear();$("forecastStatus").textContent="条件を変更しました。「このレースを予想」で再計算してください。";
 }));
 document.querySelector('[data-tab="forecast"]').addEventListener("click",()=>{
  if(!current){$("forecastDate").value=$("dataDate").value;$("forecastRace").value=$("dataRace").value;}
  loadModel().catch(()=>{$("modelReport").innerHTML='<h2>モデルの時系列テスト</h2><p class="muted">モデルを取得できませんでした。「このレースを予想」で再読み込みできます。</p>';});
 });
})();
