'use strict';
(() => {
const {M,state,prefs,url,toast}=RGBT;
class LoadQueue {
  constructor(){this.jobs=[];this.active=new Map();this.peak=0;this.completed=0}
  add(view){if(view.disposed||view.loaded||this.active.has(view)||this.jobs.includes(view))return;this.jobs.push(view);this.pump()}
  cancel(view){this.jobs=this.jobs.filter(v=>v!==view);const finish=this.active.get(view);if(finish){view.controller?.abort();view.img.removeAttribute('src');finish(false)} }
  pump(){
    while(this.active.size<4&&this.jobs.length){
      const view=this.jobs.shift();if(view.disposed||!view.visible)continue;
      let done=false,timer;
      const finish=ok=>{if(done)return;done=true;clearTimeout(timer);view.img.onload=view.img.onerror=null;this.active.delete(view);if(!view.disposed&&view.visible){if(ok){view.loaded=true;view.message.hidden=true;view.fit();this.completed++;view.onLoad?.(view)}else view.fail(view.errorText)}this.pump()};
      this.active.set(view,finish);this.peak=Math.max(this.peak,this.active.size);view.message.textContent='加载原图…';
      timer=setTimeout(()=>{view.controller?.abort();finish(false)},25000);
      view.img.onload=()=>finish(true);view.img.onerror=()=>finish(false);
      if(state.service){
        // Revocable Blob URLs give each visible viewport explicit ownership of its pixel resource.
        view.controller=new AbortController();
        const forceReload=view.forceReload===true;view.forceReload=false;
        fetch(url(view.si,view.mi),{signal:view.controller.signal,cache:forceReload?'reload':'default'}).then(response=>{if(response.status===409){view.errorText='数据集或索引已更新，请刷新网页';RGBT.stale(view.errorText)}if(!response.ok)throw new Error('Image unavailable');return response.blob()}).then(blob=>{if(done||view.disposed||!view.visible)return;view.blobURL=URL.createObjectURL(blob);view.img.src=view.blobURL}).catch(()=>{if(!done)finish(false)});
      }else view.img.src=url(view.si,view.mi);
    }
  }
}
const queue=new LoadQueue();
class ImageView {
  constructor(si,mi,{group='matrix',eager=false,onLoad=null}={}){
    this.si=si;this.mi=mi;this.group=group;this.onLoad=onLoad;this.view={z:1,cx:.5,cy:.5};this.loaded=false;this.visible=eager;this.disposed=false;
    this.cell=document.createElement('div');this.cell.className='image-cell';this.cell.dataset.sample=si;this.cell.dataset.method=mi;
    this.area=document.createElement('div');this.area.className='viewport';this.area.tabIndex=0;this.area.setAttribute('aria-label',`${M.methods[mi].name} ${M.samples[si].name}，Ctrl或Command加滚轮缩放，方向键微调视野`);
    this.img=new Image();this.img.alt=M.methods[mi].name+' / '+M.samples[si].name;this.img.draggable=false;this.img.decoding='async';this.area.append(this.img);
    this.message=document.createElement('div');this.message.className='placeholder skeleton';this.message.textContent=M.samples[si].images[mi]?'等待进入可见区域':'Missing · 未匹配图片';this.area.append(this.message);
    this.roiBox=document.createElement('div');this.roiBox.className='roi-box';this.roiBox.hidden=true;this.area.append(this.roiBox);
    const tools=document.createElement('div');tools.className='cell-tools';this.scaleLabel=document.createElement('span');this.scaleLabel.textContent='适应';tools.append(this.scaleLabel);
    for(const [label,title,fn] of [['−','缩小',()=>this.zoom(1/1.25) ],['+','放大',()=>this.zoom(1.25)],['1:1','原始像素比例',()=>this.set({z:1/this.fitScale,cx:.5,cy:.5})],['适应','适应容器',()=>this.set({z:1,cx:.5,cy:.5})],['↗','大图详情',()=>RGBT.openDetail?.(si,mi)]]){const b=document.createElement('button');b.textContent=label;b.title=title;b.onclick=fn;tools.append(b)}
    this.cell.append(this.area,tools);state.views.add(this);
    this.observer=new ResizeObserver(()=>this.fit());this.observer.observe(this.area);
    this.area.addEventListener('wheel',e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();const r=this.area.getBoundingClientRect();this.zoom(Math.exp(-e.deltaY*.002),e.clientX-r.left,e.clientY-r.top)},{passive:false});
    this.area.addEventListener('dblclick',()=>this.set({z:1,cx:.5,cy:.5}));
    this.area.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','0'].includes(e.key)){e.preventDefault();e.stopPropagation();if(e.key==='0')this.set({z:1,cx:.5,cy:.5});else if('+=-'.includes(e.key))this.zoom(e.key==='-'?.8:1.25);else this.set({...this.view,cx:this.view.cx+(e.key==='ArrowLeft'?-.03:e.key==='ArrowRight'?.03:0),cy:this.view.cy+(e.key==='ArrowUp'?-.03:e.key==='ArrowDown'?.03:0)})}});
    this.area.addEventListener('pointerdown',e=>this.down(e));this.area.addEventListener('pointermove',e=>this.move(e));this.area.addEventListener('pointerup',e=>this.up(e));this.area.addEventListener('pointercancel',()=>{this.drag=null});
    if(eager&&M.samples[si].images[mi])queue.add(this);
  }
  load(){if(this.disposed||!M.samples[this.si].images[this.mi])return;this.visible=true;if(!this.loaded)queue.add(this)}
  unload(){this.visible=false;queue.cancel(this);this.loaded=false;this.img.removeAttribute('src');if(this.blobURL){URL.revokeObjectURL(this.blobURL);this.blobURL=null}this.message.hidden=false;this.message.textContent=M.samples[this.si].images[this.mi]?'等待进入可见区域':'Missing · 未匹配图片'}
  fail(text='图片加载失败 / 解码失败'){this.loaded=false;this.img.removeAttribute('src');if(this.blobURL){URL.revokeObjectURL(this.blobURL);this.blobURL=null}this.message.hidden=false;this.message.className='placeholder error';this.message.textContent=text;const b=document.createElement('button');b.textContent='重试这一张';b.onclick=e=>{e.stopPropagation();this.message.className='placeholder skeleton';this.forceReload=true;queue.add(this)};this.message.append(b)}
  fit(){if(!this.loaded)return;const reference=M.methods.findIndex(m=>m.id===M.referenceId);if(this.group==='matrix'&&(this.mi===(reference>=0?reference:0)||!M.samples[this.si]._displayRatio)){const ratio=this.img.naturalWidth/this.img.naturalHeight;if(M.samples[this.si]._displayRatio!==ratio){M.samples[this.si]._displayRatio=ratio;RGBT.updateRowAspect?.()}}this.fitScale=Math.min(this.area.clientWidth/this.img.naturalWidth,this.area.clientHeight/this.img.naturalHeight);this.apply()}
  apply(){
    if(!this.loaded||!this.fitScale)return;
    const w=this.img.naturalWidth*this.fitScale*this.view.z,h=this.img.naturalHeight*this.fitScale*this.view.z,cw=this.area.clientWidth,ch=this.area.clientHeight;
    this.view.cx=w<=cw?.5:Math.max(cw/(2*w),Math.min(1-cw/(2*w),this.view.cx));this.view.cy=h<=ch?.5:Math.max(ch/(2*h),Math.min(1-ch/(2*h),this.view.cy));
    this.img.style.width=w+'px';this.img.style.height=h+'px';this.img.style.left=(cw/2-this.view.cx*w)+'px';this.img.style.top=(ch/2-this.view.cy*h)+'px';
    this.scaleLabel.textContent=Math.round(this.fitScale*this.view.z*100)+'%';this.scaleLabel.title=`相对适应 ${Math.round(this.view.z*100)}%；原始像素缩放上限800%，适应视图可小于25%`;
    const roi=state.rois.get(this.si);this.roiBox.hidden=!roi;
    if(roi){this.roiBox.style.left=(cw/2-this.view.cx*w+roi.x*w)+'px';this.roiBox.style.top=(ch/2-this.view.cy*h+roi.y*h)+'px';this.roiBox.style.width=roi.w*w+'px';this.roiBox.style.height=roi.h*h+'px'}
  }
  set(value,broadcast=true){if(!Number.isFinite(value.z))return;this.view={...value};this.area.dataset.zoom=value.z.toFixed(5);this.area.dataset.centerX=value.cx.toFixed(5);this.area.dataset.centerY=value.cy.toFixed(5);this.apply();if(broadcast){for(const other of state.views){if(other===this||other.group!==this.group)continue;const sync=this.group==='pair'||(this.group==='matrix'&&prefs.sync&&(prefs.scope==='page'||other.si===this.si));if(sync)other.set(value,false)}}}
  zoom(factor,x=this.area.clientWidth/2,y=this.area.clientHeight/2){if(!this.loaded)return;const v=this.view,nz=Math.min(8/this.fitScale,Math.max(Math.min(.25/this.fitScale,1),v.z*factor));const w=this.img.naturalWidth*this.fitScale,h=this.img.naturalHeight*this.fitScale;this.set({z:nz,cx:v.cx+(x-this.area.clientWidth/2)/w*(1/v.z-1/nz),cy:v.cy+(y-this.area.clientHeight/2)/h*(1/v.z-1/nz)})}
  normalized(e){const r=this.area.getBoundingClientRect(),w=this.img.naturalWidth*this.fitScale*this.view.z,h=this.img.naturalHeight*this.fitScale*this.view.z;return {x:Math.min(1,Math.max(0,this.view.cx+(e.clientX-r.left-r.width/2)/w)),y:Math.min(1,Math.max(0,this.view.cy+(e.clientY-r.top-r.height/2)/h))}}
  down(e){if(e.button!==0||!this.loaded)return;e.preventDefault();this.area.focus();this.area.setPointerCapture(e.pointerId);this.drag={x:e.clientX,y:e.clientY,view:{...this.view},start:this.normalized(e),roi:state.rois.get(this.si),mode:this.group==='matrix'?state.mode:'pan'}}
  move(e){if(!this.drag)return;const d=this.drag;if(d.mode==='pan'){this.set({...d.view,cx:d.view.cx-(e.clientX-d.x)/(this.img.naturalWidth*this.fitScale*d.view.z),cy:d.view.cy-(e.clientY-d.y)/(this.img.naturalHeight*this.fitScale*d.view.z)})}else{const p=this.normalized(e);let roi;if(d.mode==='roi')roi={x:Math.min(p.x,d.start.x),y:Math.min(p.y,d.start.y),w:Math.abs(p.x-d.start.x),h:Math.abs(p.y-d.start.y)};else if(d.roi)roi={...d.roi,x:Math.max(0,Math.min(1-d.roi.w,d.roi.x+p.x-d.start.x)),y:Math.max(0,Math.min(1-d.roi.h,d.roi.y+p.y-d.start.y))};if(roi){state.rois.set(this.si,roi);for(const view of state.views)if(view.si===this.si)view.apply()}}}
  up(){if(!this.drag)return;const mode=this.drag.mode;this.drag=null;if(mode==='roi'){const r=state.rois.get(this.si);if(r&&r.w>.005&&r.h>.005){const z=Math.min(8/this.fitScale,1/Math.max(r.w,r.h));for(const view of state.views)if(view.si===this.si&&view.group===this.group)view.set({z,cx:r.x+r.w/2,cy:r.y+r.h/2},false);toast('已在同一样本的所有方法中放大该归一化区域')}else{state.rois.delete(this.si);this.apply()}}}
  dispose(){this.disposed=true;this.unload();this.observer.disconnect();state.views.delete(this);this.cell.remove()}
}
RGBT.ImageView=ImageView;RGBT.queue=queue;
})();
