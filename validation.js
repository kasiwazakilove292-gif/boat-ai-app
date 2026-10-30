/* Retrospective benchmarks and conservative matching of paper records. */
(()=>{
 "use strict";
 let summary=null,windowName="all",resultIndex=null;
 const number=value=>Number(value).toLocaleString("ja-JP");
 const percent=value=>value==null?"—":Number(value).toFixed(1)+"%";

 async function savedText(filename){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),20000);
  try{
   const response=await fetch(DATA_ROOT+filename+"?v="+Date.now(),{
    cache:"no-store",signal:controller.signal
   });
   if(!response.ok)throw new Error("HTTP "+response.status);
   return await response.text();
  }finally{clearTimeout(timer);}
 }

 function renderValidation(){
  if(!summary)return;
  const d=summary.data;
  const issues=Object.values(summary.issues).reduce((n,v)=>n+Number(v),0);
  const period=windowName==="recent"
   ?`${d.recent_start} 〜 ${d.last_date}（直近${number(d.recent_days)}開催日分）`
   :`${d.first_date} 〜 ${d.last_date}（${number(d.race_days)}開催日分）`;
  const table=summary.benchmarks.map(rule=>{
   const b=rule[windowName];
   return `<tr><th scope="row">${E(rule.label)}</th>
    <td>${number(b.races)}R</td><td>${number(b.hits)}件<br>${percent(b.hit_pct)}</td>
    <td><b>${percent(b.roi_pct)}</b></td><td>${yen(b.net_yen)}</td></tr>`;
  }).join("");
  $("validationContent").innerHTML=`
   <div class="card">
    <h2>検証に使えるデータ</h2>
    <div class="metrics">
     <div class="metric"><small>出走表が6艇そろうレース</small><strong>${number(d.complete_entry_races)}R</strong></div>
     <div class="metric"><small>出走表・結果・勝率がそろう</small><strong>${number(d.eligible_races)}R</strong></div>
     <div class="metric"><small>締切前に6艇の展示を保存</small><strong>${number(d.predeadline_exhibition_races)}R</strong></div>
     <div class="metric"><small>そのうち結果も保存済み</small><strong>${number(d.predeadline_exhibition_with_result)}R</strong></div>
    </div>
    <p class="muted">出走表のみで結果が未収集：${number(d.entry_races_without_results)}R。結果と6艇の出走表を結合できない：${number(d.result_races_without_complete_entries)}R。勝率不足による検証除外：${number(d.joined_races_without_valid_rates)}R。</p>
    <div class="warn">これは過去にさかのぼった参考検証です。対象のうち${number(d.retrospective_entry_races)}Rはレース日より後に出走表を取得しています。実運用で締切前に出した予想の成績とは区別してください。展示・気象・モーター履歴は今回の比較には使っていません。</div>
    ${issues?`<p class="warn">形式不正・重複など${number(issues)}件を検出しました。該当データは集計で除外・保留しています。</p>`:""}
   </div>
   <div class="card">
    <h2>比較の基準となる2つのルール</h2>
    <p class="warn">返還未反映の参考値です。元の結果CSVには返還情報がないため、着順不一致の買い目は返還対象でも支出100円・払戻0円として仮計算しています。正式な回収率ではありません。</p>
    <label for="benchmarkWindow">集計期間</label>
    <select id="benchmarkWindow"><option value="all">対象の全期間</option><option value="recent">直近20%の開催日</option></select>
    <p class="muted">${E(d.eligible_races?period:"検証に使えるレースがありません。")}</p>
    <div style="overflow:auto"><table>
     <thead><tr><th>ルール</th><th>対象</th><th>的中</th><th>参考回収率</th><th>仮収支</th></tr></thead>
     <tbody>${table}</tbody>
    </table></div>
    <p class="muted">1レース1点・100円固定。的中時は公式の100円あたり払戻を加算し、回収率＝払戻合計÷記録額合計で計算します。全国勝率は保存済みの出走表の値を使い、同率は艇番順にします。両ルールは同じ対象レースで比較しています。</p>
    <p class="muted">この2つの固定ルールでは学習・最適化は行っていません。直近20%も同じ固定ルールを再集計した参考値です。学習モデルのテスト成績は「自動予想」で確認できます。データのない日や不成立レースは含めず、結果が増えると対象期間は変わります。</p>
    <a id="validationCSV" class="muted" href="${E(DATA_ROOT)}validation_races.csv" target="_blank" rel="noopener">レースごとの検証CSVを開く ↗</a>
   </div>`;
  $("benchmarkWindow").value=windowName;
  $("benchmarkWindow").onchange=e=>{windowName=e.target.value;renderValidation();};
 }

 async function loadValidation(){
  if($("refreshValidation").disabled)return;
  $("refreshValidation").disabled=true;
  $("validationStatus").textContent="検証データを読み込んでいます…";
  try{
   const value=JSON.parse(await savedText("validation_summary.json"));
   if(value.schema_version!==1||!value.data||!Array.isArray(value.benchmarks)
      ||!value.issues||value.benchmarks.length!==2
      ||value.benchmarks.some(b=>!b.all||!b.recent)
      ||!Number.isSafeInteger(value.data.eligible_races)){
    throw new Error("集計形式が異なります");
   }
   summary=value;
   renderValidation();
   $("validationStatus").textContent="集計更新："+timeText(value.generated_at)+"。保存済みCSVから再計算した集計です。";
  }catch{
   $("validationStatus").textContent=summary
    ?"更新できませんでした。前に読み込んだ集計を表示しています。集計時刻を確認してください。"
    :"検証データを読み込めませんでした。通信状態と集計処理の完了を確認し、もう一度更新してください。";
  }finally{$("refreshValidation").disabled=false;}
 }
 $("refreshValidation").onclick=loadValidation;
 document.querySelector('[data-tab="validation"]').addEventListener("click",()=>{
  if(!summary)loadValidation();
 });

 function showMatches(){
  const plan=BoatCore.matchRecords(records,resultIndex);
  $("matchStatus").textContent=
   `的中一致 ${plan.hits.length}件 ／ 着順不一致・返還要確認 ${plan.checks.length}件 ／ 結果未収集 ${plan.missing}件 ／ 対象外の場・券種 ${plan.unsupported}件 ／ 入力要確認 ${plan.invalid}件`;
  const hitRows=plan.hits.map(({record,payout})=>`
   <div class="record"><b>${E(record.date)} 大村 ${Number(record.raceNo)}R</b>
   <p>${E(record.combination)}｜${yen(record.stake)} → 総払戻 ${yen(payout)}</p></div>`).join("");
  const checkRows=plan.checks.map(({record,result})=>`
   <div class="record"><b>${E(record.date)} 大村 ${Number(record.raceNo)}R</b>
   <p>${E(record.combination)} ／ 公式着順 ${E(result.trifecta)}</p>
   <p class="muted">返還対象の有無を公式で確認してから、下の結果入力で確定してください。</p></div>`).join("");
  $("matchPreview").innerHTML=hitRows+checkRows;
  $("applyMatched").classList.toggle("hidden",!plan.hits.length);
  $("applyMatched").textContent=`一致した的中${plan.hits.length}件を保存`;
  return plan;
 }
 $("matchResults").onclick=async()=>{
  if($("matchResults").disabled)return;
  $("matchResults").disabled=true;
  $("applyMatched").classList.add("hidden");
  $("matchPreview").innerHTML="";
  $("matchStatus").textContent="公式結果の保存データを確認しています…";
  resultIndex=null;
  try{
   const rows=BoatCore.parseCSV(await savedText("omura_results.csv"),
    ["date","race","trifecta","payout_yen"]);
   const result=BoatCore.resultIndex(rows);
   resultIndex=result.index;
   showMatches();
   if(result.blocked.size)$("matchStatus").textContent+=`。重複・不正結果${result.blocked.size}Rは照合から除外。`;
  }catch{
   $("matchStatus").textContent="公式結果を読み込めませんでした。記録は変更していません。もう一度お試しください。";
  }finally{$("matchResults").disabled=false;}
 };
 $("applyMatched").onclick=()=>{
  if(!resultIndex)return;
  // Recompute against current records: manual settlement may have happened
  // since the preview was loaded. Never overwrite already-settled records.
  const plan=BoatCore.matchRecords(records,resultIndex);
  const updates=new Map(plan.hits.map(hit=>[hit.record,hit]));
  const previous=records;
  const matchedAt=new Date().toISOString();
  records=records.map(r=>updates.has(r)?{
   ...r,result:"的中",payout:updates.get(r).payout,
   resultSource:"official_saved_trifecta",matchedAt
  }:r);
  try{
   save();
   showMatches();
   $("matchStatus").textContent=`的中${plan.hits.length}件を保存しました。`+$("matchStatus").textContent;
  }catch{
   records=previous;
   render();
   $("matchStatus").textContent="端末への保存に失敗しました。記録は確定していません。空き容量を確認してください。";
  }
 };
})();
