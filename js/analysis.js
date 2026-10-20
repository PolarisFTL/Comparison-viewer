'use strict';
(() => {
const {M,$,state,prefs,ImageView,toast,save,path,url,api,visibleMethods}=RGBT;
let detail=null,noteSample=null,noteRevision=0,pairViews=[],exportCanvas=null,exportGeneration=0,exportSingle=null,exportBusy=false,splitPlan=null;
const disposeGroup=group=>{for(const v of [...state.views])if(v.group===group)v.dispose()};
RGBT.openDetail=(si,mi)=>{
  disposeGroup('detail');detail={si,mi};const s=M.samples[si];$('detail-title').textContent=M.methods[mi].name+' · '+s.name;$('detail-meta').textContent='读取原始图片…';$('detail-path').value=path(si,mi)||'Missing';$('detail-reveal').disabled=!state.service||!state.owner||state.capabilities.reveal===false||!s.images[mi];
  if(!$('detail-dialog').open)$('detail-dialog').showModal();
  const view=new ImageView(si,mi,{group:'detail',eager:true,onLoad:v=>$('detail-meta').textContent=`原始分辨率 ${v.img.naturalWidth} × ${v.img.naturalHeight} · ${M.methods[mi].name} · 样本 ${si+1}/${M.samples.length}`});$('detail-image').replaceChildren(view.cell);detail.view=view;
  if(!s.images[mi])$('detail-meta').textContent='Missing · 当前方法未匹配到此样本';
};
$('detail-dialog').addEventListener('close',()=>{disposeGroup('detail');detail=null});
for(const [id,delta] of [['detail-prev',-1],['detail-next',1]])$(id).onclick=()=>{if(!detail)return;const pos=state.filtered.indexOf(detail.si),target=pos>=0?state.filtered[pos+delta]:detail.si+delta;if(target!==undefined&&target>=0&&target<M.samples.length)RGBT.openDetail(target,detail.mi)};
$('detail-fit').onclick=()=>detail?.view.set({z:1,cx:.5,cy:.5});$('detail-native').onclick=()=>{if(detail?.view.loaded)detail.view.set({z:1/detail.view.fitScale,cx:.5,cy:.5})};
$('detail-copy').onclick=async()=>{const text=$('detail-path').value;if(!text||text==='Missing')return;try{await navigator.clipboard.writeText(text);toast(state.owner?'已复制原始图片绝对路径':'已复制图片相对路径')}catch{const input=$('detail-path');input.focus();input.select();if(document.execCommand('copy'))toast(state.owner?'已复制原始图片绝对路径':'已复制图片相对路径');else toast('路径已选中，请按 Ctrl+C')}};
$('detail-reveal').onclick=async()=>{try{await api('/api/reveal',{sample:detail.si,method:detail.mi})}catch(e){toast(e.message)}};
RGBT.openNote=si=>{noteSample=si;const mark=state.marks[M.samples[si].id]||{};noteRevision=mark.revision||0;$('note-title').textContent='标记 · '+M.samples[si].name;$('note-text').value=mark.note||'';$('note-tags').value=(mark.tags||[]).join(', ');$('note-dialog').showModal()};
$('note-save').onclick=async()=>{$('note-save').disabled=true;try{const ok=await RGBT.updateMark(noteSample,{note:$('note-text').value.trim(),tags:[...new Set($('note-tags').value.split(/[,，]/).map(t=>t.trim()).filter(Boolean))].slice(0,30)},noteRevision);if(ok){$('note-dialog').close();toast('备注和标签已保存')}}finally{$('note-save').disabled=false}};
$('marks-export').onclick=async()=>{const payload={schema:2,dataset:M.dataset,datasetId:M.datasetId,indexId:M.indexId,created:new Date().toISOString(),reviewer:state.user||null,marks:state.marks};try{if(state.service&&state.owner){const result=await api('/api/marks-export',payload);toast('标记已备份：\n'+result.path)}else if(window.showSaveFilePicker){const handle=await showSaveFilePicker({suggestedName:(M.dataset||'dataset')+'-marks.json',types:[{description:'JSON 标记',accept:{'application/json':['.json']}}]});const writer=await handle.createWritable();await writer.write(JSON.stringify(payload,null,2));await writer.close();toast('标记备份已保存到所选文件')}else{RGBT.downloadJSON(payload,(M.dataset||'dataset')+'-marks.json');toast('标记已导出，请保留浏览器保存的 JSON 文件')}}catch(e){if(e.name!=='AbortError')toast('备份失败：'+e.message)}};
$('marks-import').onclick=()=>$('marks-file').click();$('marks-file').onchange=async()=>{const file=$('marks-file').files[0];if(!file)return;try{if(file.size>24*1024*1024)throw new Error('JSON 文件超过24 MiB');const data=JSON.parse(await file.text());if(data.datasetId!==M.datasetId||!data.marks||typeof data.marks!=='object'||Array.isArray(data.marks))throw new Error('标记备份不属于当前数据集；请切换到原数据集后导入');let count=0;const imported={};for(const s of M.samples){if(!Object.prototype.hasOwnProperty.call(data.marks,s.id))continue;const m=data.marks[s.id];if(!m||typeof m!=='object')continue;imported[s.id]={favorite:m.favorite===true,reviewed:m.reviewed===true,note:typeof m.note==='string'?m.note.slice(0,2000):'',tags:Array.isArray(m.tags)?[...new Set(m.tags.filter(t=>typeof t==='string').map(t=>t.slice(0,64)))].slice(0,30):[]};count++}await RGBT.importMarks(imported);RGBT.filter();toast(`已合并 ${count} 个样本标记到当前身份` )}catch(e){toast('导入失败：'+e.message)}finally{$('marks-file').value=''}};

for(const id of ['pair-left','pair-right'])for(let mi=0;mi<M.methods.length;mi++){$(id).add(new Option(M.methods[mi].name,mi))}
$('pair-left').value=0;$('pair-right').value=Math.min(1,M.methods.length-1);
function pairMode(){const stage=$('pair-stage'),wipe=$('pair-mode').value==='wipe';if(wipe){if(pairViews.length!==2||pairViews.some(v=>!v.loaded)){stage.classList.remove('wipe');$('wipe-control').hidden=true;$('pair-warning').textContent='等待两张原图加载后检查尺寸。';return}const [a,b]=pairViews;if(a.img.naturalWidth!==b.img.naturalWidth||a.img.naturalHeight!==b.img.naturalHeight){$('pair-mode').value='side';stage.classList.remove('wipe');$('wipe-control').hidden=true;$('pair-warning').textContent='图像尺寸不同，已保持并排模式；不执行空间配准。';return}}stage.classList.toggle('wipe',wipe);$('wipe-control').hidden=!wipe;$('pair-warning').textContent=wipe?'尺寸一致，允许滑动对比。尺寸相同不等于已完成空间配准；请根据原始可视化确认相同视野。':'左右图使用相同归一化缩放与中心；不会改动或自动配准原图。';for(const v of pairViews)v.fit()}
function renderPair(){disposeGroup('pair');pairViews=[];$('pair-stage').replaceChildren();const si=Number($('pair-sample').value);for(const mi of [Number($('pair-left').value),Number($('pair-right').value)]){const view=new ImageView(si,mi,{group:'pair',eager:true,onLoad:v=>{const first=pairViews.find(other=>other!==v&&other.loaded);if(first)v.set(first.view,false);pairMode()}});pairViews.push(view);$('pair-stage').append(view.cell)}pairMode()}
$('pair-open').onclick=()=>{if(!state.current.length)return;$('pair-sample').replaceChildren();for(const si of state.current)$('pair-sample').add(new Option(M.samples[si].name,si));$('pair-dialog').showModal();renderPair()};
for(const id of ['pair-sample','pair-left','pair-right'])$(id).onchange=renderPair;$('pair-mode').onchange=pairMode;$('wipe').oninput=()=>$('pair-stage').style.setProperty('--wipe',$('wipe').value+'%');$('pair-dialog').addEventListener('close',()=>{disposeGroup('pair');pairViews=[]});

const EL=window.RGBT_EXPORT_LAYOUT,activeOriginals=new Set(),metadataRequests=new Set();
let exportPlan=null;
function clearCanvas(){splitPlan=null;exportPlan=null;if(exportCanvas){exportCanvas.width=1;exportCanvas.height=1;exportCanvas.remove();exportCanvas=null}$('export-preview-area').replaceChildren();$('export-save').disabled=true;$('export-plan-summary').hidden=true;$('export-diagnostics').hidden=true;$('export-diagnostic-rows').replaceChildren()}
function lockExport(lock){for(const control of document.querySelectorAll('#export-dialog .export-options input,#export-dialog .export-options select,#export-samples input'))control.disabled=lock;$('export-cancel').hidden=!lock}
function cancelExport(){exportGeneration++;for(const task of [...activeOriginals])task.cancel();for(const controller of metadataRequests)controller.abort();metadataRequests.clear();clearCanvas();$('export-progress').textContent='已取消生成，原始图片保持不变。'}
function exportCandidates(){const scope=$('export-scope').value;if(scope==='single')return [exportSingle??state.current[0]].filter(i=>i!==undefined);if(scope==='favorites')return M.samples.map((s,i)=>RGBT.selectedMark(i).favorite?i:-1).filter(i=>i>=0);return [...state.current]}
function sampleChoices(){clearCanvas();const box=$('export-samples');box.replaceChildren();const candidates=exportCandidates();if($('export-scope').value==='single'){const label=document.createElement('label');label.textContent='样本编号/完整文件名';const input=document.createElement('input');input.value=M.samples[candidates[0]]?.name||'';input.placeholder='完整文件名或主文件名';input.onchange=()=>{const text=input.value.trim().toLocaleLowerCase(),matches=M.samples.map((s,i)=>s.name.toLocaleLowerCase()===text||s.stem.toLocaleLowerCase()===text||s.id.toLocaleLowerCase()===text?i:-1).filter(i=>i>=0);if(matches.length===1){exportSingle=matches[0];sampleChoices()}else toast('未找到唯一对应样本，请输入完整文件名或主文件名')};label.append(input);box.append(label)}for(const [j,si] of candidates.slice(0,200).entries()){const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.value=si;check.className='export-sample-check';check.checked=j<Math.max(1,prefs.rows);check.onchange=clearCanvas;label.append(check,M.samples[si].name);box.append(label)}if(!candidates.length)box.textContent='暂无可导出样本。';if(candidates.length>200){const hint=document.createElement('span');hint.textContent='仅列出前200个收藏；可在主界面收藏筛选中分页，再导出当前页。';box.append(hint)}}
function exportOptions(){return EL.options({mode:$('export-mode').value,width:Number($('export-width').value),gapX:Number($('export-gap-x').value),gapY:Number($('export-gap-y').value),padding:Number($('export-padding').value),showTitles:$('export-titles').checked,showIds:$('export-ids').checked,titleHeight:Number($('export-title-height').value),titleFont:Number($('export-title-font').value),idHeight:Number($('export-id-height').value),idFont:Number($('export-id-font').value),roi:$('export-roi').checked})}
function modeHint(){const native=$('export-mode').value==='native';$('export-width-label').hidden=native;$('export-mode-hint').textContent=native?'每张图以原始像素 1:1 放入拼接图；按每列最大宽、每行最大高对齐，小图保持原尺寸。预览可缩小显示，下载像素不变。':'自定义总宽会对图像进行等比缩放和重新采样；不会拉伸变形。缩小后细节会减少，PNG 无损编码无法恢复已减少的像素。';clearCanvas()}
RGBT.openExport=(si=null)=>{if(exportBusy)return;exportSingle=Number.isInteger(si)?si:null;$('export-scope').value=exportSingle!==null?'single':'page';sampleChoices();$('export-save').textContent=state.owner?'保存 PNG 到项目 exports':'下载 PNG 到我的电脑';$('export-progress').textContent=state.service?'':'PNG 导出和预览需要通过 Windows 或 macOS 启动器使用本地服务。';$('export-dialog').showModal()};$('export-open').onclick=()=>RGBT.openExport();$('export-scope').onchange=sampleChoices;
for(const id of ['export-width','export-titles','export-ids','export-roi','export-gap-x','export-gap-y','export-padding','export-title-height','export-title-font','export-id-height','export-id-font'])$(id).onchange=clearCanvas;
$('export-mode').onchange=modeHint;$('export-cancel').onclick=cancelExport;$('export-preview-scale').onchange=()=>$('export-preview-area').classList.toggle('pixel-preview',$('export-preview-scale').value==='pixel');
function selectedSamples(){return [...document.querySelectorAll('.export-sample-check:checked')].map(e=>Number(e.value))}
function checkGeneration(generation){if(generation!==exportGeneration)throw new Error('已取消导出');if(state.stale)throw new Error('数据集或索引已更换，请重新打开查看器')}
function limits(){return {maxPixels:EL.memoryBudget(navigator.deviceMemory),maxDimension:16384,maxSourcePixels:EL.memoryBudget(navigator.deviceMemory)}}
function original(si,mi,generation){
  checkGeneration(generation);const img=new Image();img.decoding='async';
  return new Promise((resolve,reject)=>{let done=false,timer;const task={cancel:()=>finish(new Error('已取消导出'))};
    function finish(error){if(done)return;done=true;clearTimeout(timer);img.onload=img.onerror=null;activeOriginals.delete(task);if(error){img.removeAttribute('src');reject(error)}else resolve(img)}
    activeOriginals.add(task);timer=setTimeout(()=>finish(new Error('原图加载超时')),20000);img.onload=()=>{try{checkGeneration(generation);finish()}catch(e){finish(e)}};img.onerror=()=>finish(new Error('原图加载或解码失败'));img.src=url(si,mi);
  });
}
async function metadata(si,mi,generation){
  const controller=new AbortController();metadataRequests.add(controller);
  try{
    const response=await fetch(`/api/image-metadata?sample=${si}&method=${mi}`,{headers:RGBT.contextHeaders(),cache:'no-store',signal:controller.signal});
    if(response.status===409){RGBT.stale('数据集或索引已更换，请重新打开查看器');throw new Error('数据集或索引已更换，请重新打开查看器')}
    if(response.status===401){window.dispatchEvent(new Event('rgbt-auth-expired'));throw new Error('登录已过期，请重新登录')}
    if(response.ok){const result=await response.json();checkGeneration(generation);if(Number.isInteger(result.width)&&result.width>0&&Number.isInteger(result.height)&&result.height>0)return {width:result.width,height:result.height,status:'ok',orientation:result.orientation||1};throw new Error('原图尺寸信息无效')}
    if(response.status!==404&&response.status!==422)throw new Error('无法读取原图尺寸（HTTP '+response.status+'）');
  }finally{metadataRequests.delete(controller)}
  // Compatibility with earlier local servers: measure only this explicitly selected file.
  const record=M.samples[si].images[mi];if(record.size?.[0]*record.size?.[1]>limits().maxSourcePixels)throw new EL.LayoutError('单张原图超过当前安全解码限制','source-budget');
  if(record.bytes>100*1024*1024)throw new EL.LayoutError('单张文件超过 100 MiB，无法安全回退到浏览器解码测量尺寸','source-budget');
  let img;try{img=await original(si,mi,generation);return {width:img.naturalWidth,height:img.naturalHeight,status:'ok'}}finally{img?.removeAttribute('src')}
}
async function collectMetadata(samples,methods,options,generation){
  if(!samples.length||!methods.length)throw new Error('请选择至少一个样本和一个方法');
  if(options.roi&&samples.some(si=>!state.rois.has(si)))throw new Error('区域导出要求每个选中样本都已有框选区域');
  const rows=[];let done=0;
  for(const si of samples){const row={si,label:M.samples[si].name,roi:options.roi?{...state.rois.get(si)}:null,cells:[]};
    for(const mi of methods){checkGeneration(generation);$('export-progress').textContent=`正在读取所选图像尺寸 ${++done}/${samples.length*methods.length}（不预解码整个数据集）`;
      if(!M.samples[si].images[mi]){row.cells.push({status:'missing'});continue}
      try{const meta=await metadata(si,mi,generation);if(meta.width*meta.height>limits().maxSourcePixels)throw new EL.LayoutError(`单张原图 ${meta.width} × ${meta.height} px 超过当前安全解码限制；自定义总宽也不能免除源图解码内存。`,'source-budget');row.cells.push(meta)}catch(e){checkGeneration(generation);if(e.code==='source-budget'||/登录已过期/.test(e.message))throw e;row.cells.push({status:'error',error:e.message})}
    }
    const first=row.cells.find(cell=>cell.status==='ok');row.fallbackWidth=first?.width||320;row.fallbackHeight=first?.height||Math.round(320/RGBT.sampleRatio(si));rows.push(row);
  }
  return rows;
}
function pauseImages(){const visible=[...state.views].filter(v=>v.visible);for(const v of visible)v.unload();return ()=>{for(const v of visible)if(!v.disposed)v.load()}}
function textInRegion(ctx,text,x,y,width,height,font){ctx.save();ctx.beginPath();ctx.rect(x,y,width,height);ctx.clip();ctx.fillStyle='#172033';ctx.font=font;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,Math.floor(x+width/2),Math.floor(y+height/2));ctx.restore()}
function placeholder(ctx,rect,message){const r=rect.slot;ctx.fillStyle=rect.status==='missing'?'#eef2f7':'#fff0f0';ctx.fillRect(r.x,r.y,r.width,r.height);textInRegion(ctx,message,r.x,r.y,r.width,r.height,Math.max(10,Math.min(18,r.width/12))+'px '+EL.FONT)}
async function buildFigure(plan,generation){
  checkGeneration(generation);const canvas=document.createElement('canvas');canvas.width=plan.width;canvas.height=plan.height;const ctx=canvas.getContext('2d');if(!ctx){canvas.width=canvas.height=1;throw new Error('无法创建画布，请减少样本、拆分或改用较小总宽')}
  ctx.fillStyle='#fff';ctx.fillRect(0,0,plan.width,plan.height);const o=plan.options;
  if(o.showTitles)for(const col of plan.columns)textInRegion(ctx,col.name,col.x,o.padding,col.width,o.titleHeight,o.titleFont+'px '+EL.FONT);
  if(o.showIds)for(const row of plan.rows)textInRegion(ctx,row.label,o.padding,row.y,plan.width-o.padding*2,o.idHeight,o.idFont+'px '+EL.FONT);
  let done=0,errors=0;
  try{
    for(const rect of plan.rects){checkGeneration(generation);$('export-progress').textContent=`正在按${plan.mode==='native'?'原始像素':'自定义总宽'}绘制 ${++done}/${plan.rects.length} · ${plan.width} × ${plan.height} px`;
      if(rect.status!=='ok'){placeholder(ctx,rect,rect.status==='missing'?'Missing':'Load failed');errors++;continue}
      let img;
      try{img=await original(rect.si,rect.mi,generation);if(img.naturalWidth!==rect.source.width||img.naturalHeight!==rect.source.height){const changed=new Error('原图尺寸与检查结果不同（可能文件已更新或含不同方向信息），请重新生成预览；未按错误尺寸绘制。');changed.dimensionsChanged=true;throw changed}EL.drawImage(ctx,img,rect)}catch(e){checkGeneration(generation);if(e.dimensionsChanged)throw e;rect.status='error';rect.error=e.message;placeholder(ctx,rect,'Load failed');errors++}finally{img?.removeAttribute('src')}
    }
    canvas.dataset.failures=String(errors);canvas.dataset.samples=String(plan.rows.length);canvas.dataset.methods=String(plan.columns.length);canvas.dataset.layout=JSON.stringify(plan);return canvas;
  }catch(e){canvas.width=canvas.height=1;canvas.remove();throw e}
}
function diagnostics(plans){
  const summary=$('export-plan-summary');summary.hidden=false;const mode=plans[0].mode==='native'?'原始像素 1:1，图像内容不缩放':'自定义总宽，图像已等比重采样';summary.textContent=mode+'。\n'+plans.map((plan,i)=>`${plans.length>1?'第 '+(i+1)+' 张：':''}${plan.width} × ${plan.height} px · ${plan.rows.length} 样本 × ${plan.columns.length} 方法 · ${(plan.pixels/1000000).toFixed(2)} MP · 仅 RGBA 画布约 ${Math.ceil(plan.rgbaBytes/1048576)} MiB`).join('\n')+'\n预览适应窗口只改变 CSS 显示大小；PNG 像素不随屏幕、浏览器缩放或 DPR 改变。PNG 编码、源图解码和浏览器副本还会占用额外内存。';
  $('export-diagnostics').hidden=false;const body=$('export-diagnostic-rows');body.replaceChildren();
  for(const [part,plan] of plans.entries())for(const rect of plan.rects){const tr=document.createElement('tr');const source=rect.source?rect.source.width+' × '+rect.source.height:'—',crop=rect.crop?`(${rect.crop.x}, ${rect.crop.y}) ${rect.crop.width} × ${rect.crop.height}`:'—',output=rect.status==='ok'?`${Math.round(rect.out.width)} × ${Math.round(rect.out.height)} · ${(rect.scale*100).toFixed(rect.scale===1?0:2)}%`:rect.status==='missing'?'Missing':'Load failed';for(const value of [(plans.length>1?'['+(part+1)+'] ':'')+rect.sample+' / '+rect.method,source,crop,output,rect.status==='ok'?rect.out.x+', '+rect.out.y:'—']){const td=document.createElement('td');td.textContent=value;tr.append(td)}body.append(tr)}
}
function pngBlob(canvas){return new Promise((resolve,reject)=>{try{canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('PNG 编码失败，请降低尺寸或拆分')),'image/png')}catch(e){reject(e)}})}
async function exportTask(split=false){
  if(exportBusy)return;if(!state.service){toast('PNG 预览/导出需要本地服务，请使用项目中的 Windows 或 macOS 启动器。');return}
  exportBusy=true;clearCanvas();lockExport(true);const generation=++exportGeneration,restore=pauseImages();$('export-preview').disabled=$('export-split').disabled=true;
  try{
    const samples=selectedSamples(),methodIndices=visibleMethods(),methods=methodIndices.map(mi=>({mi,name:M.methods[mi].name})),options=exportOptions();
    if(!split&&(samples.length>24||samples.length*methods.length>120))throw new EL.LayoutError('单张最多 24 个样本 / 120 个图像位置，请使用按行拆分导出','budget');
    const rows=await collectMetadata(samples,methodIndices,options,generation);checkGeneration(generation);const plans=[];
    if(!split)plans.push(EL.planFigure(rows,methods,options,limits()));
    else{let position=0;while(position<rows.length){let count=Math.min(prefs.rows,24,Math.floor(120/methods.length)||1,rows.length-position),plan;while(count>=1){try{plan=EL.planFigure(rows.slice(position,position+count),methods,options,limits());break}catch(e){if(e.code!=='budget'||count===1)throw e;count--}}plans.push(plan);position+=count}}
    exportPlan=plans[0];exportCanvas=await buildFigure(exportPlan,generation);checkGeneration(generation);$('export-preview-area').replaceChildren(exportCanvas);if(split)splitPlan={plans,generation};diagnostics(plans);$('export-progress').textContent=(split?`拆分为 ${plans.length} 张，当前预览第 1 张。确认后逐张生成并保存。`:'预览已生成。确认布局后保存同一张原始分辨率 PNG。')+` 缺失 / 失败 ${exportCanvas.dataset.failures}。`;$('export-save').disabled=false;
  }catch(e){if(generation===exportGeneration){$('export-progress').textContent=e.message;toast(e.message)}}finally{restore();lockExport(false);exportBusy=false;$('export-preview').disabled=$('export-split').disabled=false}
}
$('export-preview').onclick=()=>exportTask(false);$('export-split').onclick=()=>exportTask(true);
$('export-save').onclick=async()=>{
  if(!exportCanvas||exportBusy)return;exportBusy=true;lockExport(true);$('export-save').disabled=true;const restore=pauseImages(),generation=exportGeneration;
  try{
    if(splitPlan){const plan=splitPlan;let saved=0,failures=0;for(let i=0;i<plan.plans.length;i++){checkGeneration(plan.generation);const canvas=i===0?exportCanvas:await buildFigure(plan.plans[i],plan.generation);try{const blob=await pngBlob(canvas);checkGeneration(plan.generation);await RGBT.saveFigure(blob,`comparison-${Date.now()}-${i+1}.png`);saved++;failures+=Number(canvas.dataset.failures)||0}finally{canvas.width=canvas.height=1;canvas.remove()}}clearCanvas();$('export-progress').textContent=`已保存 ${saved} 张原始分辨率 PNG ${state.owner?'到项目 exports':'到浏览器下载目录'}；缺失 / 失败位置共 ${failures} 个。`;toast($('export-progress').textContent)}
    else{const blob=await pngBlob(exportCanvas);checkGeneration(generation);const result=await RGBT.saveFigure(blob,`comparison-${Date.now()}.png`);$('export-progress').textContent='已保存 '+exportCanvas.width+' × '+exportCanvas.height+' px PNG：'+result.path;toast(state.owner?'PNG 已保存到项目 exports 文件夹':'PNG 已下载到你的电脑')}
  }catch(e){if(generation===exportGeneration){if(splitPlan){clearCanvas();$('export-progress').textContent='拆分中断，已写入文件保留。请重新生成预览。'}toast('保存失败：'+e.message)}}finally{restore();lockExport(false);exportBusy=false;if(exportCanvas)$('export-save').disabled=false}
};
$('export-dialog').addEventListener('close',cancelExport);
})();
