'use strict';
// Pixel geometry has no dependency on the viewport, screen size, CSS or devicePixelRatio.
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.RGBT_EXPORT_LAYOUT=api})(typeof globalThis!=='undefined'?globalThis:this,()=>{
const FONT='"Times New Roman", SimSun, "Songti SC", serif';
const DEFAULTS=Object.freeze({mode:'native',width:3200,gapX:16,gapY:16,padding:24,showTitles:true,showIds:true,titleHeight:44,titleFont:24,idHeight:32,idFont:18,roi:false});
class LayoutError extends Error{constructor(message,code='invalid',details=null){super(message);this.name='LayoutError';this.code=code;this.details=details}}
function integer(value,name,min,max){const n=Number(value);if(!Number.isInteger(n)||n<min||n>max)throw new LayoutError(`${name}应为 ${min}～${max} 的整数`);return n}
function options(input={}){
  const o={...DEFAULTS,...input};if(!['native','custom'].includes(o.mode))throw new LayoutError('请选择原始像素或自定义总宽模式');
  for(const [key,name,max] of [['gapX','横向间距',256],['gapY','纵向间距',256],['padding','外边距',512],['titleHeight','标题区域高度',256],['idHeight','编号区域高度',256]])o[key]=integer(o[key],name,0,max);
  o.titleFont=integer(o.titleFont,'标题字号',8,96);o.idFont=integer(o.idFont,'编号字号',8,96);
  o.showTitles=!!o.showTitles;o.showIds=!!o.showIds;o.roi=!!o.roi;
  if(o.showTitles&&o.titleHeight<o.titleFont+8)throw new LayoutError('方法标题区域高度至少应为标题字号 + 8 px，或关闭方法标题');
  if(o.showIds&&o.idHeight<o.idFont+8)throw new LayoutError('图片编号区域高度至少应为编号字号 + 8 px，或关闭图片编号');
  if(o.mode==='custom')o.width=integer(o.width,'自定义总宽',300,16384);
  return o;
}
function cropRect(width,height,roi=null){
  width=integer(width,'原图宽度',1,1000000);height=integer(height,'原图高度',1,1000000);
  if(!roi)return {x:0,y:0,width,height};
  const {x,y,w,h}=roi;if(![x,y,w,h].every(Number.isFinite)||x<0||y<0||w<=0||h<=0||x+w>1+1e-9||y+h>1+1e-9)throw new LayoutError('局部区域无效，请重新框选');
  const left=Math.min(width-1,Math.max(0,Math.floor(x*width+1e-9))),top=Math.min(height-1,Math.max(0,Math.floor(y*height+1e-9)));
  const right=Math.min(width,Math.max(left+1,Math.ceil((x+w)*width-1e-9))),bottom=Math.min(height,Math.max(top+1,Math.ceil((y+h)*height-1e-9)));
  return {x:left,y:top,width:right-left,height:bottom-top};
}
function memoryBudget(deviceMemory){const ram=Number(deviceMemory);return Number.isFinite(ram)&&ram>0&&ram<=2?12000000:Number.isFinite(ram)&&ram>0&&ram<=4?24000000:48000000}
function planFigure(samples,methods,input={},limits={}){
  const o=options(input),maxPixels=limits.maxPixels||48000000,maxDimension=limits.maxDimension||16384;
  if(!samples.length||!methods.length)throw new LayoutError('请选择至少一个样本和一个方法');
  if(samples.length>24||samples.length*methods.length>120)throw new LayoutError('单张拼接图最多 24 个样本 / 120 个图像位置，请使用拆分导出','budget');
  const title=o.showTitles?o.titleHeight:0,id=o.showIds?o.idHeight:0;
  const prepared=samples.map((sample,row)=>{
    if(o.roi&&!sample.roi)throw new LayoutError('区域导出要求每个所选样本都已框选局部区域');
    return methods.map((method,col)=>{
      const meta=sample.cells[col]||{},valid=Number.isInteger(meta.width)&&meta.width>0&&Number.isInteger(meta.height)&&meta.height>0;
      if(valid&&meta.width*meta.height>(limits.maxSourcePixels||maxPixels))throw new LayoutError(`单张原图 ${meta.width} × ${meta.height} px 超过当前安全解码限制，请选择其他图像或在外部生成单独的预览副本。`,'source-budget');
      const source=valid?{width:meta.width,height:meta.height}:null;
      const crop=valid?cropRect(meta.width,meta.height,o.roi?sample.roi:null):null;
      return {row,col,si:sample.si,mi:method.mi,method:method.name,sample:sample.label,source,crop,status:meta.status||(!valid?'missing':'ok'),error:meta.error||''};
    });
  });
  const fallbacks=samples.map(sample=>cropRect(sample.fallbackWidth||320,sample.fallbackHeight||240,o.roi?sample.roi:null));
  let columns;
  if(o.mode==='native')columns=methods.map((_,col)=>Math.max(1,...prepared.map((row,i)=>row[col].crop?.width||fallbacks[i].width)));
  else{
    const available=o.width-2*o.padding-(methods.length-1)*o.gapX;if(available<methods.length*16)throw new LayoutError('总宽不足以容纳当前方法和间距，请增加宽度或减少方法');
    const base=Math.floor(available/methods.length),remainder=available%methods.length;columns=methods.map((_,col)=>base+(col<remainder?1:0));
  }
  const rowHeights=prepared.map((row,i)=>Math.max(1,...row.map((cell,col)=>{
    if(!cell.crop){const fw=fallbacks[i].width,fh=fallbacks[i].height;return o.mode==='native'?fh:Math.ceil(fh*columns[col]/fw)}
    return o.mode==='native'?cell.crop.height:Math.ceil(cell.crop.height*columns[col]/cell.crop.width);
  })));
  const width=o.mode==='native'?2*o.padding+columns.reduce((sum,n)=>sum+n,0)+(methods.length-1)*o.gapX:o.width;
  const height=2*o.padding+title+rowHeights.reduce((sum,n)=>sum+n+id,0)+(samples.length-1)*o.gapY,pixels=width*height,rgbaBytes=pixels*4;
  if(!Number.isSafeInteger(pixels)||width>maxDimension||height>maxDimension||pixels>maxPixels)throw new LayoutError(`拼接图 ${width} × ${height} px（${(pixels/1000000).toFixed(2)} MP；仅 RGBA 画布约 ${Math.ceil(rgbaBytes/1048576)} MiB）超过当前限制 ${Math.round(maxPixels/1000000)} MP / 单边 ${maxDimension} px。请减少样本或方法、按行拆分；自定义总宽模式会缩放图像。`,'budget',{width,height,pixels,rgbaBytes,maxPixels,maxDimension});
  const columnRects=[];let x=o.padding;columns.forEach((w,col)=>{columnRects.push({x,width:w,mi:methods[col].mi,name:methods[col].name});x+=w+o.gapX});
  const rows=[];let y=o.padding+title;const rects=[];
  prepared.forEach((row,ri)=>{
    rows.push({y,height:rowHeights[ri],si:samples[ri].si,label:samples[ri].label});
    row.forEach((cell,col)=>{
      const slot={x:columnRects[col].x,y:y+id,width:columns[col],height:rowHeights[ri]};
      const scale=cell.crop?(o.mode==='native'?1:Math.min(slot.width/cell.crop.width,slot.height/cell.crop.height)):1;
      const dw=cell.crop?cell.crop.width*scale:0,dh=cell.crop?cell.crop.height*scale:0;
      const out={x:slot.x+Math.max(0,Math.floor((slot.width-dw)/2+1e-7)),y:slot.y+Math.max(0,Math.floor((slot.height-dh)/2+1e-7)),width:dw,height:dh};
      rects.push({...cell,slot,out,scale});
    });
    y+=rowHeights[ri]+id+o.gapY;
  });
  return {version:1,mode:o.mode,options:o,width,height,pixels,rgbaBytes,maxPixels,maxDimension,columns:columnRects,rows,rects,images:samples.length*methods.length};
}
function drawImage(ctx,img,rect){
  if(!rect.crop||rect.status!=='ok')return;
  const c=rect.crop,out=rect.out;ctx.save();
  // Native mode is exactly an integer-aligned 1:1 copy; custom mode uses one uniform scale.
  ctx.imageSmoothingEnabled=rect.scale!==1;ctx.imageSmoothingQuality='high';ctx.translate(out.x,out.y);ctx.scale(rect.scale,rect.scale);
  ctx.drawImage(img,c.x,c.y,c.width,c.height,0,0,c.width,c.height);ctx.restore();
}
return {DEFAULTS,FONT,LayoutError,options,cropRect,memoryBudget,planFigure,drawImage};
});
