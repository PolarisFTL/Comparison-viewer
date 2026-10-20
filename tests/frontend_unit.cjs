'use strict';
// Dependency-free checks for cross-platform paths, dataset context and export geometry.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),dataSource=fs.readFileSync(path.join(root,'js/data.js'),'utf8');
let tests=0;
function check(name,fn){fn();tests++;console.log('PASS '+name)}
function workspace(roots){
  const manifest={dataset:'Synthetic test',datasetId:'dataset-a',indexId:'snapshot-a',referenceId:'method-a',methods:roots.map((root,i)=>({id:'method-'+String.fromCharCode(97+i),name:'Method '+i,root})),samples:[{id:'sample',name:'sample.jpg',aspectRatio:2,images:roots.map(()=>({relative:'子目录/sample #1.png'}))}]};
  const storage=new Map(),events=[],window={RGBT_MANIFEST:manifest,RGBT_BATCH:require('../js/batch-export.js'),dispatchEvent:e=>events.push(e)},document={getElementById:()=>({style:{}})};
  const sandbox={window,document,localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},setTimeout:()=>1,clearTimeout:()=>{},Event:class{constructor(type){this.type=type}},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},fetch:async()=>({ok:true,json:async()=>({ok:true})})};
  vm.createContext(sandbox);vm.runInContext(dataSource,sandbox);return {api:window.RGBT,sandbox,storage,events};
}
async function main(){
  const windows=workspace(['D:\\图像\\Input','D:\\图像\\Prediction']);
  check('Windows absolute paths preserve Unicode and separator',()=>assert.equal(windows.api.path(0,0),'D:\\图像\\Input\\子目录\\sample #1.png'));
  check('Variable method count is accepted',()=>assert.equal(windows.api.prefs.order.length,2));
  check('Windows file URL percent encodes filename',()=>assert.ok(windows.api.url(0,0).endsWith('/%E5%AD%90%E7%9B%AE%E5%BD%95/sample%20%231.png')));
  const mac=workspace(['/Users/YOUR_NAME/图像/Input','/Volumes/实验/Prediction','/Volumes/实验/GT']);
  check('macOS absolute paths preserve slash separator',()=>assert.equal(mac.api.path(0,0),'/Users/YOUR_NAME/图像/Input/子目录/sample #1.png'));
  check('macOS file URL has exactly three leading slashes',()=>assert.ok(mac.api.url(0,0).startsWith('file:///Users/')));
  mac.api.state.service=true;mac.api.state.owner=false;
  check('Remote paths expose only relative image names',()=>assert.equal(mac.api.path(0,0),'子目录/sample #1.png'));
  check('Service image URL pins dataset and index',()=>assert.equal(mac.api.url(0,0),'/image/0/0?dataset=dataset-a&index=snapshot-a'));
  check('Stored preferences are isolated by dataset ID',()=>{mac.api.save();assert.ok(mac.storage.has('rgbt-viewer-v2-dataset-a'))});
  let sent=null;mac.sandbox.fetch=async(route,options)=>{sent=options;return {ok:true,json:async()=>({ok:true})}};await mac.api.api('/api/mark',{});
  check('Write requests include dataset and index context',()=>{assert.equal(sent.headers['X-Dataset-Id'],'dataset-a');assert.equal(sent.headers['X-Index-Id'],'snapshot-a')});
  mac.sandbox.fetch=async()=>({ok:false,status:409,json:async()=>({error:'Dataset index changed'})});await assert.rejects(mac.api.api('/api/mark',{}));
  check('A stale context blocks further writes',()=>assert.equal(mac.api.state.stale,true));
  const layout=require('../js/export-layout.js'),methods=[{mi:0,name:'A'},{mi:1,name:'B'}],rows=[{si:0,label:'wide',cells:[{width:200,height:100},{width:200,height:100}]},{si:1,label:'tall',cells:[{width:100,height:200},{width:100,height:200}]}],options={mode:'custom',width:1200,gapX:16,gapY:16,padding:24,titleHeight:36,titleFont:24,idHeight:28,idFont:18};let g=layout.planFigure(rows,methods,options);
  check('Export uses a different height for each sample aspect ratio',()=>{assert.equal(g.rows[0].height,284);assert.equal(g.rows[1].height,1136);assert.equal(g.height,1576)});
  rows[0].roi={x:0,y:0,w:.5,h:.25};g=layout.planFigure([rows[0]],methods,{...options,roi:true});
  check('ROI export geometry follows the selected region aspect ratio',()=>assert.equal(g.rows[0].height,142));
  check('Oversized canvas is rejected before allocation',()=>assert.throws(()=>layout.planFigure([rows[0],rows[1],rows[0],rows[1],rows[0],rows[1],rows[0],rows[1]],methods,{...options,width:12000}),/超过当前限制/));
  console.log(tests+' frontend checks passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1});
