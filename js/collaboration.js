'use strict';
(() => {
const {M,$,state,prefs,toast,save,api,downloadJSON}=RGBT;
let version=null,refreshing=null,writes=Promise.resolve(),pending=0,selected='self',otherMarks={},legacyMarks={},ready=false,needsPaint=false;
const sampleById=new Map(M.samples.map((s,i)=>[s.id,i]));
async function get(route){const r=await fetch(route,{cache:'no-store',headers:RGBT.contextHeaders()}),data=await r.json();if(!r.ok){if(r.status===401)window.dispatchEvent(new Event('rgbt-auth-expired'));if(r.status===409)RGBT.stale(data.error);const error=new Error(data.error||'服务读取失败');error.status=r.status;throw error}return data}
function status(text,error=false){const el=$('collab-status');if(el){el.textContent=text;el.classList.toggle('sync-error',error)}}
function paintMarks(){
  if(!RGBT.filter)return;
  if(!['all','complete','missing'].includes(prefs.filter)){const views=new Map([...state.views].filter(v=>v.group==='matrix').map(v=>[v.si+':'+v.mi,{...v.view}]));RGBT.filter(false);for(const v of state.views){const old=views.get(v.si+':'+v.mi);if(v.group==='matrix'&&old)v.set(old,false)}return}
  for(const label of document.querySelectorAll('.row-label')){
    const si=Number(label.dataset.sample),id=M.samples[si].id,own=state.marks[id]||{},shown=RGBT.selectedMark(si),star=label.querySelector('.star'),review=label.querySelector('.review-toggle'),team=label.querySelector('.team-count');
    if(star){star.classList.toggle('active',!!own.favorite);star.textContent=own.favorite?'★':'☆'}if(review){review.classList.toggle('reviewed',!!own.reviewed);review.textContent=own.reviewed?'✓ 已审':'标为已审'}
    if(team){const counts=state.team?.aggregates?.[id]||{};team.textContent=`★ ${counts.favorites||0} 人 · 已审 ${counts.reviewed||0}`}
    label.querySelector('.row-note')?.remove();label.querySelector('.tags')?.remove();if(shown.note)label.append(text('div',shown.note,'row-note'));if(shown.tags?.length)label.append(text('div',shown.tags.join(' · '),'tags'));
  }
}
function refreshSelectors(){
  const select=$('mark-view');if(!select)return;select.replaceChildren(new Option('我的收藏与备注','self'),new Option('团队收藏汇总','team'));
  for(const r of state.team.reviewers)if(r.id!==state.user.id)select.add(new Option(r.nickname+' 的标记',r.id));
  if(![...select.options].some(o=>o.value===selected))selected='self';select.value=selected;
}
async function refresh(force=false,render=true){
  if(!state.collaboration)return;
  if(refreshing){await refreshing;if(!force)return;}
  refreshing=(async()=>{
    const data=await get('/api/workspace'+(!force&&version!==null?'?version='+version:''));
    if(!data.unchanged){state.marks=data.marks;state.team=data;version=data.version;needsPaint=true;refreshSelectors();if(!['self','team'].includes(selected))otherMarks=(await get('/api/reviewer?id='+encodeURIComponent(selected))).marks}
    if(render&&needsPaint&&!document.querySelector('dialog[open]')&&![...state.views].some(v=>v.drag)){paintMarks();needsPaint=false}
    ready=true;state.expired=false;status('已同步到主机 · '+new Date().toLocaleTimeString());
  })();
  try{await refreshing}finally{refreshing=null}
}
RGBT.refreshCollaboration=refresh;
RGBT.selectedMark=si=>{
  const id=M.samples[si].id;
  if(!state.collaboration||selected==='self')return state.marks[id]||{};
  if(selected==='team')return {favorite:(state.team?.aggregates?.[id]?.favorites||0)>0,note:state.marks[id]?.note||'',tags:state.marks[id]?.tags||[]};
  return otherMarks[id]||{};
};
RGBT.updateMark=(si,patch,expectedRevision=null)=>{
  if(!state.collaboration){state.marks[M.samples[si].id]={...(state.marks[M.samples[si].id]||{}),...patch};save();RGBT.filter(false);return Promise.resolve(true)}
  pending++;let saved=false;status('正在保存到主机…');
  const task=writes.then(async()=>{
    if(!ready||state.expired)throw new Error('尚未连接协作服务；请保留未保存备注，重新登录或刷新后再试');
    const sample=M.samples[si].id,result=await api('/api/mark',{sample,revision:expectedRevision??(state.marks[sample]?.revision||0),patch});
    Object.assign(state.marks,result.marks);saved=true;
    try{await refresh(true,false)}catch(e){status('标记已保存，汇总同步暂不可用',true)}
    paintMarks();needsPaint=false;return true;
  }).catch(async error=>{toast('标记未保存：'+error.message);if(error.status===409)try{await refresh(true,false)}catch{}status('保存失败，请重试；未显示为已保存',true);return false}).finally(()=>{pending--;if(saved&&!pending&&ready&&!state.expired)status('已同步到主机 · '+new Date().toLocaleTimeString())});
  writes=task.catch(()=>{});return task;
};
RGBT.importMarks=async marks=>{
  if(!Object.keys(marks).length)return;
  if(!state.collaboration){Object.assign(state.marks,marks);save();return}
  await writes;if(!ready||state.expired)throw new Error('协作服务尚未连接');pending++;
  try{const entries=Object.entries(marks).map(([sample,patch])=>({sample,patch,revision:state.marks[sample]?.revision||0}));await api('/api/marks/import',{entries});await refresh(true,false)}finally{pending--}
};
RGBT.saveFigure=async(blob,name)=>{
  if(state.owner)return api('/api/export',blob,true);
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);return {path:'浏览器下载目录 / '+name};
};
RGBT.decorateRow=(si,label,actions)=>{
  const id=M.samples[si].id,reviewed=document.createElement('button');reviewed.className='review-toggle'+(state.marks[id]?.reviewed?' reviewed':'');reviewed.textContent=state.marks[id]?.reviewed?'✓ 已审':'标为已审';reviewed.title='切换我的已审状态';reviewed.onclick=async()=>{reviewed.disabled=true;await RGBT.updateMark(si,{reviewed:!state.marks[id]?.reviewed});reviewed.disabled=false};label.append(reviewed);
  if(state.collaboration){const a=state.team?.aggregates?.[id]||{},button=document.createElement('button');button.className='team-count';button.textContent=`★ ${a.favorites||0} 人 · 已审 ${a.reviewed||0}`;button.title='查看团队对该样本的独立标记';button.onclick=()=>openSample(si);label.append(button);if(selected!=='self'){const hint=document.createElement('small');hint.className='hint';hint.textContent='收藏与标记按钮始终修改我自己的记录';label.append(hint)}}
};
function dialog(id,title,body){const d=document.createElement('dialog');d.id=id;d.className='collab-dialog';const head=document.createElement('div');head.className='dialog-head';const strong=document.createElement('strong');strong.textContent=title;const close=document.createElement('button');close.textContent='×';close.onclick=()=>d.close();head.append(strong,close);d.append(head);d.insertAdjacentHTML('beforeend',body);document.body.append(d);return d}
function text(tag,value,cls){const el=document.createElement(tag);el.textContent=value;if(cls)el.className=cls;return el}
function locate(si){prefs.search=M.samples[si].name;$('search').value=prefs.search;$('filter').value='all';RGBT.filter();for(const d of document.querySelectorAll('dialog[open]'))d.close()}
async function openSample(si){
  const d=$('sample-team-dialog');d.querySelector('strong').textContent='团队标记 · '+M.samples[si].name;const box=$('sample-team-body');box.replaceChildren(text('p','读取中…'));if(!d.open)d.showModal();
  try{const data=await get('/api/sample?id='+encodeURIComponent(M.samples[si].id));box.replaceChildren();for(const mark of data.marks){if(!mark.favorite&&!mark.reviewed&&!mark.note&&!mark.tags.length)continue;const card=document.createElement('article');card.className='review-card';card.append(text('strong',mark.nickname),text('span',(mark.favorite?'★ 收藏':'未收藏')+' · '+(mark.reviewed?'已审阅':'未标为已审'),'badge'),text('p',mark.note||'暂无备注'),text('div',mark.tags.join(' · '),'tags'));box.append(card)}if(!box.children.length)box.append(text('p','暂无团队标记。'));const jump=text('button','定位到此样本','primary');jump.onclick=()=>locate(si);box.append(jump)}catch(e){box.replaceChildren(text('p',e.message,'sync-error'))}
}
function syncThreshold(){for(const id of ['favorite-threshold','team-favorite-threshold']){const input=$(id);if(input){input.value=prefs.favoriteThreshold;input.removeAttribute('aria-invalid')}}for(const option of document.querySelectorAll('option[value="consensus"]'))option.textContent='至少 '+prefs.favoriteThreshold+' 人收藏'}
RGBT.bindFavoriteThreshold=()=>{for(const id of ['favorite-threshold','team-favorite-threshold']){const input=$(id);if(!input||input.dataset.bound)continue;input.dataset.bound='true';input.oninput=()=>{const n=window.RGBT_BATCH.parseThreshold(input.value);if(n===null){input.setAttribute('aria-invalid','true');return}prefs.favoriteThreshold=n;save();syncThreshold();if(RGBT.filter)RGBT.filter(false);if($('team-dialog')?.open)teamTable()};input.onchange=()=>{if(window.RGBT_BATCH.parseThreshold(input.value)===null){toast('收藏阈值请输入 1 以上的整数');syncThreshold()}}}syncThreshold()};
RGBT.teamFilter=()=>({mode:$('team-filter')?.value||'favorites',query:$('team-search')?.value.trim()||'',minFavorites:prefs.favoriteThreshold});
function teamTable(){
  const team=state.team;if(!team)return;const counts=Object.values(team.aggregates),voted=counts.filter(c=>c.favorites>0).length,reviewed=counts.filter(c=>c.reviewed>0).length;
  $('team-stats').textContent=`${M.samples.length} 个样本 · ${team.reviewers.length} 个身份 · ${reviewed} 个已被审阅 · ${voted} 个有人收藏 · ${counts.filter(c=>c.favorites>=prefs.favoriteThreshold).length} 个至少 ${prefs.favoriteThreshold} 人收藏`;
  const reviewers=$('team-reviewers');reviewers.replaceChildren();for(const r of team.reviewers){const card=document.createElement('div');card.className='reviewer-stat';card.append(text('strong',r.nickname),text('small',`已审 ${r.reviewed} / ${M.samples.length} · 收藏 ${r.favorites} · 有备注 ${r.notes}`));reviewers.append(card)}
  const rows=window.RGBT_BATCH.teamRows(M.samples,team.aggregates,RGBT.teamFilter());
  const tbody=$('team-samples');tbody.replaceChildren();for(const {s,si,a} of rows.slice(0,200)){const tr=document.createElement('tr');for(const value of [s.name,a.favorites,a.reviewed,a.notes])tr.append(text('td',String(value)));const td=document.createElement('td'),inspect=text('button','查看标记'),jump=text('button','定位');inspect.onclick=()=>openSample(si);jump.onclick=()=>locate(si);td.append(inspect,jump);tr.append(td);tbody.append(tr)}$('team-result-count').textContent=`符合条件 ${rows.length} 个。`+(rows.length>200?'汇总表仅显示前 200 行；批量原图包含全部匹配样本。':'')+'团队 JSON 保留全部标记作备份。';
}
async function share(){try{const info=await get('/api/admin/share');$('share-text').value=info.enabled===false?'当前为本机模式，其他电脑暂不能访问。\n请先关闭当前服务，再使用 Start-LAN-Windows.bat 或 Start-LAN-macOS.command 启动协作模式。\n按启动器提示指定允许访问的协作者 IP 或可信网段，然后重新打开“邀请协作者”。\n仅连接同一校园网不保证互通，网络隔离可能阻止访问。':'Comparison Viewer · 图像协作筛选 · '+M.dataset+'\n访问地址：'+(info.addresses.join('\n')||'未检测到局域网 IPv4，请检查网络后重启协作服务')+'\n访问口令：'+info.code+'\n访问范围：'+(info.scope||'请向主机管理员确认')+'\n浏览器填写口令和昵称即可加入。请保存首次生成的身份恢复码。';$('share-dialog').showModal()}catch(e){toast(e.message)}}
RGBT.connectCollaboration=async info=>{
  if(!info.collaboration)return;state.user=info.user;legacyMarks=state.marks;state.marks={};state.team={aggregates:{},reviewers:[]};
  const panel=$('collaboration-panel');panel.hidden=false;panel.innerHTML='<div class="section-label">协作筛选</div><strong id="reviewer-name"></strong><p id="collab-status" class="hint">连接主机中…</p><label>收藏 / 备注视图<select id="mark-view"></select></label><div class="side-buttons"><button id="sync-now">刷新标记</button><button id="share-open" hidden>邀请协作者</button><button id="logout" hidden>退出身份</button><button id="migrate-marks" hidden>导入本机旧标记</button></div>';
  $('reviewer-name').textContent=info.user.nickname;$('team-open').hidden=false;$('share-open').hidden=!state.owner;$('logout').hidden=state.owner;
  $('migrate-marks').hidden=!state.owner||!Object.values(legacyMarks).some(m=>m.favorite||m.reviewed||m.note||m.tags?.length);
  dialog('team-dialog','团队筛选汇总','<p id="team-stats"></p><div id="team-reviewers"></div><div class="detail-toolbar"><input id="team-search" placeholder="按文件名搜索汇总"><select id="team-filter"><option value="favorites">有人收藏</option><option value="consensus">至少 N 人收藏</option><option value="notes">有备注 / 标签</option><option value="unreviewed">无人审阅</option><option value="all">全部样本</option></select><label class="team-threshold-label">收藏阈值 N<input id="team-favorite-threshold" type="number" min="1" step="1" value="2" inputmode="numeric" aria-label="团队收藏人数阈值 N"></label><button id="team-refresh">刷新</button><button id="team-export">导出团队 JSON</button><button id="team-batch-export" class="primary">批量导出原图</button></div><p id="team-result-count" class="hint"></p><div class="team-table"><table><thead><tr><th>样本</th><th>收藏人数</th><th>已审人数</th><th>备注人数</th><th>操作</th></tr></thead><tbody id="team-samples"></tbody></table></div>');
  dialog('sample-team-dialog','团队标记','<div id="sample-team-body"></div>');
  dialog('share-dialog','邀请协作者参与筛选','<p class="hint">将以下信息发给处于可达局域网的同学；主机应保持开机并运行协作服务。</p><textarea id="share-text" readonly rows="7"></textarea><button id="share-copy">复制邀请信息</button><details><summary>更换访问口令</summary><p class="hint">会退出所有远程会话，保留全部标记和昵称。请先通知正在筛选的同学。</p><label><input id="rotate-confirm" type="checkbox">我了解远程用户需要重新登录</label><button id="rotate-code" disabled>更换口令并退出远程会话</button></details>');
  $('mark-view').onchange=async()=>{const value=$('mark-view').value;try{if(!['self','team'].includes(value))otherMarks=(await get('/api/reviewer?id='+encodeURIComponent(value))).marks;selected=value;RGBT.filter(false)}catch(e){$('mark-view').value=selected;toast(e.message)}};
  $('sync-now').onclick=async()=>{try{await refresh(true)}catch(e){status('无法连接主机：'+e.message,true)}};
  $('team-open').onclick=async()=>{try{await refresh(true,false);teamTable();$('team-dialog').showModal()}catch(e){toast(e.message)}};
  $('team-refresh').onclick=async()=>{try{await refresh(true,false);teamTable()}catch(e){toast(e.message)}};
  $('team-search').oninput=$('team-filter').onchange=teamTable;RGBT.bindFavoriteThreshold();const batch=window.RGBT_BATCH.init(RGBT);$('team-batch-export').onclick=()=>batch?.open(RGBT.teamFilter());
  $('team-export').onclick=async()=>{try{if(state.owner){const result=await api('/api/team-backup',{});toast('团队标记已保存：'+result.path)}else downloadJSON(await get('/api/team-export'),(M.dataset||'dataset')+'-team-marks.json')}catch(e){toast(e.message)}};
  $('share-open').onclick=share;$('share-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('share-text').value);toast('已复制邀请信息')}catch{$('share-text').focus();$('share-text').select();if(document.execCommand('copy'))toast('已复制邀请信息');else toast('请按 Ctrl+C 复制邀请信息')}};
  $('rotate-confirm').onchange=()=>$('rotate-code').disabled=!$('rotate-confirm').checked;
  $('rotate-code').onclick=async()=>{try{await api('/api/admin/rotate-code',{});$('share-dialog').close();$('rotate-confirm').checked=false;$('rotate-code').disabled=true;await share();toast('口令已更换，已退出远程会话；全部标记保留')}catch(e){toast(e.message)}};
  $('logout').onclick=async()=>{try{await writes;await api('/api/logout',{});location.assign('/login')}catch(e){toast(e.message)}};
  $('migrate-marks').onclick=async()=>{try{const cleaned={};for(const [id,m] of Object.entries(legacyMarks))if(sampleById.has(id))cleaned[id]={favorite:m.favorite===true,reviewed:m.reviewed===true,note:typeof m.note==='string'?m.note.slice(0,2000):'',tags:Array.isArray(m.tags)?m.tags.filter(t=>typeof t==='string').slice(0,30).map(t=>t.slice(0,64)):[]};await RGBT.importMarks(cleaned);$('migrate-marks').hidden=true;RGBT.filter(false);toast('本机旧标记已导入主机管理员身份，浏览器原备份保留')}catch(e){toast('导入失败：'+e.message)}};
  if(!state.owner){$('detail-copy').textContent='复制图片相对路径';$('detail-path').setAttribute('aria-label','图片相对路径')}
  await refresh(true,false);
  setInterval(()=>{if(!document.hidden&&!pending&&!state.expired)refresh(false).catch(e=>status('未同步，请检查主机连接：'+e.message,true))},15000);
};
window.addEventListener('rgbt-auth-expired',()=>{state.expired=true;ready=false;status('登录已过期；未保存内容请先复制，再重新登录',true);if(!$('relogin-link')){const a=document.createElement('a');a.id='relogin-link';a.href='/login';a.textContent='重新登录';$('collaboration-panel')?.append(a)}toast('登录已过期。未保存备注请先复制，再重新登录。')});
})();

window.addEventListener('rgbt-index-stale',()=>{const {state,$}=RGBT;state.expired=true;const panel=$('collaboration-panel');if(panel){const warning=document.createElement('p');warning.className='sync-error';warning.textContent='主机已更新数据集或索引。请复制未保存备注，再刷新页面；当前页停止写入。';panel.prepend(warning)}});
