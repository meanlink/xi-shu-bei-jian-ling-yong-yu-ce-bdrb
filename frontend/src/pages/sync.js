import {sync,erp} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,date,notify} from '../utils/dom.js';
import {route} from '../router/index.js';
import {SyncStatus,SyncDecision} from '../constants/enums.js';

const canWrite=()=>session.user.role!=='viewer';

function roundCard(r,selected){
 const pct=r.cutoff>r.start_after?Math.min(100,Math.round((r.cursor-r.start_after)/(r.cutoff-r.start_after)*100)):100;
 const actions=[];
 if(r.status==='syncing'&&!r.paused)actions.push('<button class="button small" data-pause="'+r.id+'" '+(canWrite()?'':'disabled')+'>暂停接续</button>');
 if(r.status==='syncing'&&r.paused)actions.push('<button class="button small" data-resume="'+r.id+'" '+(canWrite()?'':'disabled')+'>继续接续</button>');
 if(['blocked','failed','reconciling'].includes(r.status))actions.push('<button class="button small" data-resume="'+r.id+'" '+(canWrite()?'':'disabled')+'>恢复失败轮</button>');
 actions.push('<button class="text-button" data-entries="'+r.id+'">'+(selected?'取舍明细 ✓':'取舍明细')+'</button>');
 if(r.dataset_id)actions.push('<a class="text-button" href="#/workbench">批次已开放试算 ↗</a>');
 return '<article class="round-card"><div><strong>第 '+r.round_no+' 轮</strong> <span class="status '+esc(r.status)+'">'+esc(SyncStatus[r.status]||r.status)+(r.paused?' · 已暂停':'')+'</span>'
  +'<p>接续 '+r.cursor+' / '+r.cutoff+' · 分页 '+r.pages_done+' / '+r.pages_expected+' · 入账 '+r.applied+' · 拒绝 '+r.rejected+'</p>'
  +'<small>截止点 '+r.cutoff+' · 开轮 '+date(r.created_at)+(r.finished_at?' · 完成 '+date(r.finished_at):'')+'</small>'
  +(r.block_reason?'<p class="block-reason">'+esc(r.block_reason)+'</p>':'')
  +(r.error?'<p class="block-reason">'+esc(r.error)+'</p>':'')+'</div>'
  +'<div class="round-actions">'+actions.join('')+'</div>'
  +'<div class="bar"><i style="width:'+pct+'%"></i></div></article>';
}

export async function syncPage(){
 const [st,rounds,ledger,events]=await Promise.all([sync.status(),sync.rounds(),sync.ledger(),erp.events()]);
 const active=st.active_round;
 const selectedId=workspace.syncRound||(active?active.id:null)||(rounds[0]?rounds[0].id:null);
 const detail=selectedId?await sync.round(selectedId):null;
 workspace.syncRound=selectedId;
 const entryRows=(detail?detail.entries:[]).map(e=>({...e,kind_label:e.kind==='revoke'?'撤销':'更正',decision_label:SyncDecision[e.decision]||e.decision,at_label:date(e.at)}));
 const ledgerRows=ledger.map(l=>({...l,state:l.revoked?'已撤销':'有效',token:l.revocation_token||'—'}));
 const eventRows=events.map(e=>({...e,kind_label:e.kind==='revoke'?'撤销':'更正',state:e.hidden?'缺页中':(e.withdrawn?'已撤回':'可送达'),token:e.revocation_token||'—'}));
 const counts=st.counts;
 return heading('03 / ERP SYNC','ERP 变更源同步','按来源凭证与版本接续领用日历，撤销凭据留痕；缺页或版本冲突先阻断，整轮对账通过才开放试算，下轮更正另生批次。',
  '<div class="sync-actions"><label><input type="checkbox" id="opt-concurrent" checked>同轮并发补发演练</label><button class="button primary" id="start-sync" '+(canWrite()?'':'disabled')+'>开始同步 ↗</button><button class="button" id="refresh-sync">刷新 ↻</button></div>')
 +'<section class="stat-cards"><div><span>源端事件头</span><strong>'+st.source.head+'</strong></div><div><span>已发布截止点</span><strong>'+st.state.last_published_cutoff+'</strong></div><div><span>待接续事件</span><strong>'+st.source.pending+'</strong></div><div><span>源端更正批次</span><strong>'+st.state.source_batches+'</strong></div></section>'
 +'<div class="chips">'+['syncing','reconciling','blocked','failed','published'].map(s=>'<span class="chip '+s+'">'+esc(SyncStatus[s])+' '+counts[s]+'</span>').join('')+(st.source.hidden?'<span class="chip blocked">源端缺页 '+st.source.hidden+' 条待修复</span>':'')+'</div>'
 +'<section class="panel"><div class="section-title"><h2>同步轮次</h2><span>'+(active?'第 '+active.round_no+' 轮进行中':'暂无进行中的轮次')+'</span></div>'
  +(rounds.length?rounds.map(r=>roundCard(r,r.id===selectedId)).join(''):'<div class="empty">源端有 '+st.source.pending+' 条待接续变更。点击「开始同步」开启第一轮。</div>')+'</section>'
 +'<div class="two-columns"><section class="panel"><div class="section-title"><h2>每条取舍'+(detail?' · 第 '+detail.round_no+' 轮':'')+'</h2><span>'+entryRows.length+' 条</span></div>'
  +table([{key:'event_id',label:'事件'},{key:'voucher',label:'来源凭证'},{key:'version',label:'版本'},{key:'kind_label',label:'类型'},{key:'decision_label',label:'取舍'},{key:'reason',label:'说明'},{key:'at_label',label:'时间'}],entryRows,'选择一轮同步查看每条源端事件的入账取舍。')+'</section>'
 +'<section class="panel"><div class="section-title"><h2>凭证台账</h2><span>撤销凭据留痕 · '+ledgerRows.length+' 张</span></div>'
  +table([{key:'voucher',label:'来源凭证'},{key:'version',label:'版本'},{key:'part',label:'备件'},{key:'day',label:'领用日'},{key:'demand',label:'更正量'},{key:'state',label:'状态'},{key:'token',label:'撤销凭据'}],ledgerRows,'同步入账后形成凭证台账。')+'</section></div>'
 +'<section class="panel"><div class="section-title"><h2>源端演练与事件日志</h2><span>本地模拟 ERP · 每日补发更正</span></div>'
  +'<form id="advance-form" class="sync-actions"><label>演练场景<select name="scenario"><option value="normal">正常补发今日更正</option><option value="missing_page">源端缺页（阻断后需修复）</option><option value="conflict">同版本内容冲突（阻断后需修复）</option></select></label><button type="submit" class="button" '+(canWrite()?'':'disabled')+'>源端补发更正 ↗</button><button type="button" class="button" id="repair-source" '+(canWrite()?'':'disabled')+'>修复源端（恢复缺页 / 撤回错发）</button></form>'
  +table([{key:'id',label:'序号'},{key:'batch_no',label:'批次'},{key:'voucher',label:'凭证'},{key:'version',label:'版本'},{key:'kind_label',label:'类型'},{key:'part',label:'备件'},{key:'day',label:'领用日'},{key:'demand',label:'量'},{key:'token',label:'撤销凭据'},{key:'state',label:'状态'}],eventRows,'尚无源端事件。')+'</section>';
}

export function bindSync(refresh){
 const act=async fn=>{try{await fn();}catch(e){notify(e.message,true);}await refresh();};
 document.querySelector('#refresh-sync').onclick=refresh;
 document.querySelector('#start-sync').onclick=()=>act(async()=>{const r=await sync.start({simulate_concurrent:document.querySelector('#opt-concurrent').checked});notify('第 '+r.round_no+' 轮同步已开轮，截止点 '+r.cutoff);});
 document.querySelectorAll('[data-pause]').forEach(b=>b.onclick=()=>act(async()=>{await sync.pause(b.dataset.pause);notify('已暂停接续');}));
 document.querySelectorAll('[data-resume]').forEach(b=>b.onclick=()=>act(async()=>{await sync.resume(b.dataset.resume);notify('已恢复接续');}));
 document.querySelectorAll('[data-entries]').forEach(b=>b.onclick=()=>{workspace.syncRound=Number(b.dataset.entries);refresh();});
 document.querySelector('#advance-form').addEventListener('submit',e=>{e.preventDefault();act(async()=>{const r=await erp.advance({scenario:new FormData(e.target).get('scenario')});notify('源端已补发 '+r.events.length+' 条更正事件');});});
 document.querySelector('#repair-source').onclick=()=>act(async()=>{const r=await erp.repair();notify('源端修复完成：恢复缺页 '+r.restored+' 条，撤回错发 '+r.withdrawn+' 条');});
 sync.status().then(st=>{const a=st.active_round;if(a&&!a.paused&&a.status==='syncing')setTimeout(()=>{if(route().page==='sync')refresh();},1500);}).catch(()=>{});
}
