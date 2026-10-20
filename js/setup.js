'use strict';
(() => {
const $=id=>document.getElementById(id);let token='',saved=null,config=null,busy=false,ready=false,dirty=false,maskPaths=false;
const clone=value=>JSON.parse(JSON.stringify(value));
function id(){return 'method-'+(crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10))}
function blank(){const first=id();return {schema:2,dataset:'我的图像对比',datasetId:crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=Math.random()*16|0;return (c==='x'?r:(r&3|8)).toString(16)}),referenceId:first,methods:[{id:first,name:'Input',root:''},{id:id(),name:'Method A',root:''}]}}
function message(value){$('error').hidden=!value;$('error').textContent=value||''}
function changed(){dirty=true;ready=false;$('audit').hidden=true;$('reuse').hidden=true}
function displayDirectory(value){return maskPaths&&value?'… / '+value.replace(/[\\/]$/,'').split(/[\\/]/).pop():value||''}
function lock(value){busy=value;for(const el of document.querySelectorAll('#setup-form input,#setup-form button'))el.disabled=value;if(!value)renderMethods()}
async function request(route,body){const response=await fetch(route,{cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Viewer-Token':token},body:JSON.stringify(body)})}),data=await response.json();if(!response.ok)throw new Error(data.error||'操作失败');return data}
function button(label,title,fn){const el=document.createElement('button');el.type='button';el.textContent=label;el.title=title;el.onclick=fn;return el}
function move(index,delta){const other=index+delta;if(other<0||other>=config.methods.length)return;[config.methods[index],config.methods[other]]=[config.methods[other],config.methods[index]];changed();renderMethods()}
function renderMethods(){
  const list=$('methods');list.replaceChildren();$('method-count').textContent=config.methods.length+' / 24';$('add-method').disabled=busy||config.methods.length>=24;
  config.methods.forEach((method,index)=>{
    const row=document.createElement('div');row.className='method-row';row.dataset.methodId=method.id;
    const referenceLabel=document.createElement('label'),radio=document.createElement('input');radio.type='radio';radio.name='reference';radio.checked=method.id===config.referenceId;radio.setAttribute('aria-label','将 '+method.name+' 设为样本基准');radio.title='以这个目录建立样本列表';radio.onchange=()=>{config.referenceId=method.id;changed()};referenceLabel.append(radio);
    const nameBox=document.createElement('div');nameBox.className='method-name';const name=document.createElement('input');name.value=method.name;name.maxLength=60;name.required=true;name.setAttribute('aria-label','方法 '+(index+1)+' 显示名称');name.oninput=()=>{method.name=name.value;changed()};const stable=document.createElement('small');stable.className='method-id';stable.textContent=method.id;stable.title='稳定方法标识；修改名称或排序不会改变标识';nameBox.append(name,stable);
    const directory=document.createElement('div');directory.className='directory-field';const input=document.createElement('input');input.value=displayDirectory(method.root);input.readOnly=maskPaths;input.required=true;input.placeholder=/mac|darwin/i.test($('platform').textContent)?'/Users/YOUR_NAME/experiments/method':'选择或粘贴图片目录的绝对路径';input.setAttribute('aria-label','方法 '+(index+1)+' 图片目录');input.oninput=()=>{method.root=input.value;changed()};
    const pick=button('选择目录','在主机上打开系统文件夹选择器',async()=>{if(busy)return;pick.disabled=true;pick.textContent='选择中…';message('');try{const result=await request('/api/setup/pick',{initial:method.root||''});if(result.path&&!result.cancelled){method.root=result.path;input.value=displayDirectory(result.path);changed()}}catch(e){message('无法打开系统目录选择器：'+e.message+'\n你也可以直接粘贴完整目录路径。')}finally{pick.disabled=false;pick.textContent='选择目录'}});directory.append(input,pick);
    const actions=document.createElement('div');actions.className='row-actions';const up=button('↑','上移 '+method.name,()=>move(index,-1)),down=button('↓','下移 '+method.name,()=>move(index,1)),remove=button('×','移除 '+method.name,()=>{if(config.methods.length<=2)return;config.methods.splice(index,1);if(config.referenceId===method.id)config.referenceId=config.methods[0].id;changed();renderMethods()});up.disabled=index===0;down.disabled=index===config.methods.length-1;remove.disabled=config.methods.length<=2;remove.className='remove';actions.append(up,down,remove);row.append(referenceLabel,nameBox,directory,actions);list.append(row);
  });
}
function load(value){config=clone(value||blank());config.schema=2;if(!Array.isArray(config.methods)||config.methods.length<2)config=blank();config.methods.forEach(method=>{if(!method.id)method.id=id()});if(!config.methods.some(m=>m.id===config.referenceId))config.referenceId=config.methods[0].id;$('dataset').value=config.dataset||'';dirty=false;renderMethods();$('restore').hidden=!saved;message('')}
function auditTable(audit){
  $('audit').hidden=false;const methods=audit.methods||audit.summary?.methods||[],samples=audit.samples??audit.totalSamples??audit.sampleCount??audit.summary?.samples??audit.referenceCount;
  $('audit-heading').textContent='图片对应关系已建立';$('audit-summary').textContent=(typeof samples==='number'?samples+' 个基准样本 · ':'')+config.methods.length+' 个方法。请核对统计结果后进入工作台。';
  $('audit-methods').replaceChildren();let missing=0,ambiguous=0;
  for(const [i,method] of methods.entries()){const row=document.createElement('tr'),count=method.count??method.images??method.total??0,matched=method.matched??method.matches??0,lost=method.missing??0,uncertain=method.ambiguous??method.matchKinds?.ambiguous??0;missing+=Number(lost)||0;ambiguous+=Number(uncertain)||0;for(const value of [method.name||method.method||config.methods[i]?.name||'方法',count,matched,lost,uncertain]){const cell=document.createElement('td');cell.textContent=String(value);row.append(cell)}$('audit-methods').append(row)}
  const warnings=$('audit-warnings');warnings.replaceChildren();const note=document.createElement('p');note.className=missing||ambiguous?'audit-warning':'audit-note audit-good';note.textContent=missing||ambiguous?`有 ${missing} 个未匹配位置、${ambiguous} 个歧义位置。查看器将显示 Missing 占位，不会以其他样本代替。请检查命名后重建索引；也可以保留缺失进入浏览。`:'文件名匹配已完成；查看时仍会独立处理缺失、损坏或解码失败的图像。';warnings.append(note);
  const rawWarnings=audit.warnings||[];for(const text of rawWarnings.slice(0,8)){const p=document.createElement('p');p.className='audit-note';p.textContent=typeof text==='string'?text:JSON.stringify(text);warnings.append(p)}
  ready=true;$('enter').disabled=false;
}
async function poll(jobId){
  const job=await request('/api/setup/job?id='+encodeURIComponent(jobId)),progress=job.progress||{};$('progress-message').textContent=progress.message||'正在扫描目录与匹配文件名…';
  if(Number(progress.total)>0){$('progress').value=Math.min(100,100*Number(progress.current||0)/Number(progress.total));$('progress-count').textContent=(progress.current||0)+' / '+progress.total}else{$('progress').removeAttribute('value');$('progress-count').textContent=''}
  if(job.status==='running'||job.status==='pending'){setTimeout(()=>poll(jobId).catch(fail),650);return}
  if(job.status!=='done')throw new Error(job.error||'建立索引失败，原配置仍保留');
  $('progress').value=100;$('build-title').textContent='检查完成';$('progress-message').textContent='索引已保存。进入查看器前请核对下方统计。';if(job.datasetId)config.datasetId=job.datasetId;saved=clone(config);dirty=false;lock(false);auditTable(job.audit||await request('/api/setup/audit'));$('restore').hidden=false;$('audit').scrollIntoView({behavior:'smooth',block:'nearest'});
}
function fail(error){lock(false);ready=false;message(error.message);$('build-title').textContent='检查未完成';$('progress-message').textContent='请检查目录权限、基准目录中的图片数量及文件命名后重试。'}
$('mask-paths').onclick=()=>{maskPaths=!maskPaths;$('mask-paths').textContent=maskPaths?'显示完整路径':'隐藏完整路径';renderMethods()};
$('add-method').onclick=()=>{if(config.methods.length>=24)return;config.methods.push({id:id(),name:'Method '+String(config.methods.length),root:''});changed();renderMethods()};
$('dataset').oninput=()=>{config.dataset=$('dataset').value;changed()};$('restore').onclick=()=>{load(saved);$('audit').hidden=true;$('reuse').hidden=false;ready=true};
$('load-demo').onclick=async()=>{message('');try{const demo=await request('/api/setup/demo');load(demo.config||demo);changed()}catch(e){message(e.message)}};
$('reuse').onclick=$('enter').onclick=()=>{if(ready&&!dirty)location.assign('/viewer');else message('目录配置已更改，请先检查目录并建立索引。')};
$('setup-form').onsubmit=async event=>{event.preventDefault();if(busy)return;config.dataset=$('dataset').value.trim();config.methods.forEach(m=>{m.name=m.name.trim();m.root=m.root.trim()});if(!config.dataset||config.methods.some(m=>!m.name||!m.root)){message('请填写项目名称，并为每个方法提供显示名称和完整目录路径。');return}message('');ready=false;$('audit').hidden=true;$('build-status').hidden=false;$('build-title').textContent='正在检查目录';$('progress').removeAttribute('value');$('progress-message').textContent='提交配置…';lock(true);try{const result=await request('/api/setup/build',{config});await poll(result.jobId)}catch(e){fail(e)}};
async function init(){if(location.protocol==='file:'){$('loading').textContent='首次配置需要本地服务。请使用项目中的 Windows 或 macOS 启动器，再进入本页。';return}try{const info=await request('/api/setup');if(!info.owner){$('denied').hidden=false;return}token=info.token;saved=info.config?clone(info.config):null;ready=info.ready===true;$('platform').textContent=(info.platform||'本地主机')+' · 图片在本机处理';load(saved);$('setup-form').hidden=false;$('reuse').hidden=!ready;if(ready)try{auditTable(await request('/api/setup/audit'))}catch{/* Previous index remains usable even if audit is not available. */}}catch(e){$('denied').hidden=true;message('无法读取主机配置：'+e.message)}finally{$('loading').hidden=true}}
init();
})();
