'use strict';
// Reproduce a 200 response containing a damaged image, then repair it on the host.
// The actual ImageView retry button and LoadQueue run with an HTTP cache mock.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
class Element {
  constructor(){this.children=[];this.dataset={};this.style={};this.clientWidth=240;this.clientHeight=200;this.hidden=false}
  append(...children){this.children.push(...children)}
  set textContent(text){this.text=String(text);this.children=[]}
  get textContent(){return this.text||''}
  setAttribute(){}
  addEventListener(){}
  remove(){}
}
const blobs=new Map();let blobId=0;
class MockImage extends Element {
  constructor(){super();this.naturalWidth=320;this.naturalHeight=320;this._src=''}
  set src(value){this._src=value;const blob=blobs.get(value);queueMicrotask(()=>{if(this._src!==value)return;if(blob?.content==='valid-png')this.onload?.();else this.onerror?.()})}
  get src(){return this._src}
  removeAttribute(name){if(name==='src')this._src=''}
}
async function main(){
  let hostFile='damaged-png';const httpCache=new Map(),requests=[];
  const state={service:true,views:new Set(),rois:new Map()},RGBT={M:{referenceId:'reference',methods:[{id:'reference',name:'Input'}],samples:[{name:'sample.png',images:[{relative:'sample.png'}]}]},state,prefs:{sync:false},url:()=>'/image/0/0?dataset=a&index=b',toast:()=>{}};
  const context={RGBT,document:{createElement:()=>new Element()},Image:MockImage,ResizeObserver:class{observe(){}disconnect(){}},AbortController,URL:{createObjectURL(blob){const key='blob:test-'+(++blobId);blobs.set(key,blob);return key},revokeObjectURL:key=>blobs.delete(key)},setTimeout:()=>1,clearTimeout:()=>{},fetch:async(url,options)=>{requests.push({url,cache:options.cache});if(options.cache==='reload'||!httpCache.has(url))httpCache.set(url,hostFile);const content=httpCache.get(url);return {ok:true,status:200,blob:async()=>({content})}}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../js/viewer.js'),'utf8'),context);
  const flush=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve))};
  const view=new RGBT.ImageView(0,0);view.load();await flush();
  assert.equal(requests[0].cache,'default');assert.equal(view.loaded,false);assert.equal(view.message.className,'placeholder error');assert.equal(RGBT.queue.active.size,0);
  console.log('PASS initial ordinary request uses default cache and damaged 200 response fails decoding');
  hostFile='valid-png';assert.equal(httpCache.get(requests[0].url),'damaged-png');
  const retry=view.message.children.find(element=>element.textContent==='重试这一张');assert.ok(retry,'Retry button must be present');retry.onclick({stopPropagation(){}});await flush();
  assert.equal(requests[1].cache,'reload');assert.equal(view.loaded,true);assert.equal(view.forceReload,false);assert.equal(httpCache.get(requests[0].url),'valid-png');
  console.log('PASS clicking retry bypasses damaged HTTP cache, replaces it, and decodes repaired source');
  view.unload();view.load();await flush();assert.equal(requests[2].cache,'default');assert.equal(view.loaded,true);assert.equal(requests.length,3);assert.equal(RGBT.queue.active.size,0);
  console.log('PASS force reload is consumed once and subsequent ordinary loading retains caching');
  view.dispose();assert.equal(blobs.size,0);assert.equal(state.views.size,0);
  console.log('PASS retry lifecycle releases Blob URLs and viewport resources');
  console.log('4 viewer retry regression checks passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1});
