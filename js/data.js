'use strict';
window.RGBT = (() => {
  const M=window.RGBT_MANIFEST;
  if(!M?.samples?.length)throw new Error('未找到可用图片索引，请返回目录配置页面建立索引');
  const $=id=>document.getElementById(id),key='rgbt-viewer-v2-'+(M.datasetId||M.indexId||M.dataset);
  const defaults={page:0,rows:4,order:M.methods.map((_,i)=>i),hidden:[],width:240,gap:8,theme:'light',sync:true,scope:'row',search:'',filter:'all',favoriteThreshold:2};
  let stored={},marks={},storage=true;
  try{stored=JSON.parse(localStorage.getItem(key)||'{}');marks=JSON.parse(localStorage.getItem(key+'-marks')||'{}')}catch{storage=false}
  const prefs={...defaults,...stored},count=M.methods.length;prefs.favoriteThreshold=window.RGBT_BATCH.parseThreshold(prefs.favoriteThreshold)??2;
  if(![1,2,3,4,6,8].includes(prefs.rows))prefs.rows=4;
  if(!Array.isArray(prefs.order)||prefs.order.length!==count||new Set(prefs.order).size!==count||prefs.order.some(i=>!Number.isInteger(i)||i<0||i>=count))prefs.order=[...defaults.order];
  prefs.hidden=Array.isArray(prefs.hidden)?prefs.hidden.filter(i=>Number.isInteger(i)&&i>=0&&i<count):[];
  prefs.width=Math.min(540,Math.max(160,Number(prefs.width)||240));prefs.gap=Math.min(24,Math.max(0,Number(prefs.gap)||8));
  prefs.search=typeof prefs.search==='string'?prefs.search.slice(0,300):'';
  if(!['all','complete','missing','favorites','reviewed','unreviewed','team-favorites','consensus','team-unreviewed'].includes(prefs.filter))prefs.filter='all';
  if(!marks||Array.isArray(marks)||typeof marks!=='object')marks={};
  const state={prefs,marks,storage,filtered:M.samples.map((_,i)=>i),current:[],views:new Set(),rois:new Map(),generation:0,service:false,token:null,owner:false,collaboration:false,capabilities:{},mode:'pan',lastRenderMs:0,stale:false};
  let toastTimer;
  function toast(message){$('toast').textContent=message;$('toast').style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').style.display='none',6000)}
  function save(){try{localStorage.setItem(key,JSON.stringify(prefs));if(!state.collaboration)localStorage.setItem(key+'-marks',JSON.stringify(state.marks))}catch{state.storage=false;toast('浏览器未允许持久化；协作标记仍保存于主机，布局偏好可能无法恢复。')}}
  function path(si,mi){const image=M.samples[si]?.images[mi];if(!image)return '';const relative=image.relative.replace(/\\/g,'/'),root=M.methods[mi].root;if(!root||state.service&&!state.owner)return relative;const separator=/^[A-Za-z]:[\\/]|^\\\\/.test(root)?'\\':'/';return root.replace(/[\\/]$/,'')+separator+relative.replace(/\//g,separator)}
  function url(si,mi){if(state.service)return `/image/${si}/${mi}?dataset=${encodeURIComponent(M.datasetId||'')}&index=${encodeURIComponent(M.indexId||M.created)}`;const p=path(si,mi).replace(/\\/g,'/');return (p.startsWith('/')?'file://':'file:///')+p.split('/').map((part,i)=>i===0?part:encodeURIComponent(part)).join('/')}
  function visibleMethods(){return prefs.order.filter(i=>!prefs.hidden.includes(i))}
  function contextHeaders(){return {'X-Dataset-Id':M.datasetId||'', 'X-Index-Id':M.indexId||''}}
  function stale(message){if(state.stale)return;state.stale=true;window.dispatchEvent(new CustomEvent('rgbt-index-stale',{detail:message}));toast(message||'数据集或索引已切换。请先复制未保存备注，然后刷新页面。')}
  async function api(route,body,raw=false){if(state.stale)throw new Error('页面数据集已过时，请刷新后再操作');const response=await fetch(route,{method:'POST',headers:{...contextHeaders(),'X-Viewer-Token':state.token,'Content-Type':raw?'image/png':'application/json'},body:raw?body:JSON.stringify(body)});const result=await response.json();if(!response.ok){if(response.status===401)window.dispatchEvent(new Event('rgbt-auth-expired'));if(response.status===409&&/dataset|index|数据集|索引/i.test((result.error||'')+' '+(result.code||'')))stale(result.error);const error=new Error(result.error||'服务操作失败');error.status=response.status;throw error}return result}
  function sampleRatio(si){const s=M.samples[si],reference=M.methods.findIndex(m=>m.id===M.referenceId),size=s.images[reference>=0?reference:0]?.size;const ratio=s._displayRatio||Number(s.aspectRatio)||(size?.[0]/size?.[1]);return Number.isFinite(ratio)&&ratio>0?ratio:4/3}
  function downloadJSON(obj,name){const blob=new Blob([JSON.stringify(obj,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000)}
  return {M,$,state,prefs,toast,save,path,url,visibleMethods,api,downloadJSON,contextHeaders,stale,sampleRatio};
})();
