"""Bounded original-byte exports. No image decoding, resizing, or arbitrary reads."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import threading
import time
import unicodedata
import zipfile

from collaboration import Conflict

CHUNK=1024*1024
MAX_FILES=250000
MAX_ZIP_BYTES=8*1024**3
MAX_FOLDER_BYTES=256*1024**3
RESERVE=64*1024**2
FINAL={'done','cancelled','error'}
REPORT_NAMES={'report.json','readme.md','manifest.csv','paths.txt','mulimgviewer.csv','mulimg-relative.csv'}


def safe_name(value,limit=70):
    text=unicodedata.normalize('NFC',str(value))
    text=''.join('_' if ch in '<>:"/\\|?*' or unicodedata.category(ch).startswith('C') else ch for ch in text)
    text=text.strip(' .')[:limit].rstrip(' .') or 'unnamed'
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?:\..*)?',text):text='_'+text
    return text


def unique_names(values,reserved=()):
    """Stable IDs disambiguate case/NFC/illegal-character collisions on both OSes."""
    bases=[safe_name(name) for _,name in values]
    bases=['_'+base if base.casefold() in reserved else base for base in bases]
    counts={}
    for base in bases:counts[base.casefold()]=counts.get(base.casefold(),0)+1
    result=[];seen=set()
    for (identity,_),base in zip(values,bases):
        name=base if counts[base.casefold()]==1 else base+'__'+hashlib.sha256(identity.encode('utf-8')).hexdigest()[:10]
        suffix=0
        while name.casefold() in seen:
            suffix+=1;name=base+'__'+hashlib.sha256((identity+str(suffix)).encode('utf-8')).hexdigest()[:12]
        seen.add(name.casefold());result.append(name)
    return result


def _linked(path):
    info=path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&0x400)


def _source(snapshot,si,mi):
    method=snapshot.manifest['methods'][mi];record=snapshot.manifest['samples'][si]['images'][mi]
    if not record:raise FileNotFoundError('Missing indexed image')
    root=Path(method['root'])
    if _linked(root):raise ValueError('Source root changed into a link')
    canonical=root.resolve(strict=True)
    if canonical!=root:raise ValueError('Source ancestor changed into a link')
    root=canonical;relative=Path(record['relative'])
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe indexed image path')
    current=root
    for component in relative.parts:
        current=current/component
        if _linked(current):raise ValueError('Source links/junctions are not exportable')
    resolved=snapshot.image_path(si,mi)
    if resolved!=current.resolve(strict=True):raise ValueError('Indexed source identity changed')
    info=resolved.stat()
    if not stat.S_ISREG(info.st_mode):raise ValueError('Source is not a regular file')
    return resolved,info


def output_parent(value,snapshot,local,resources=None):
    if not isinstance(value,str) or not value or not Path(value).expanduser().is_absolute():raise ValueError('请选择已存在、可写的绝对输出目录')
    raw=Path(value).expanduser()
    try:
        if _linked(raw):raise ValueError('输出目录不能是符号链接或 junction')
        parent=raw.resolve(strict=True)
    except FileNotFoundError:raise ValueError('输出目录不存在，请选择已存在目录')
    except PermissionError:raise ValueError('输出目录无法访问，请检查当前用户的目录权限')
    except OSError:raise ValueError('无法访问输出目录，请检查目录或磁盘连接')
    if not parent.is_dir():raise ValueError('输出目录不存在')
    sources=[Path(m['root']).resolve() for m in snapshot.manifest['methods']]
    if any(parent==root or root in parent.parents for root in sources):raise ValueError('输出目录不能位于原始图片目录内部')
    local=Path(local).resolve();exports=local/'exports'
    allowed_exports=parent==exports or exports in parent.parents
    project=Path(resources or Path(__file__).resolve().parent).resolve()
    if not allowed_exports and (parent==local or local in parent.parents or parent==project or project in parent.parents):raise ValueError('请选择工作区 exports 子目录或项目以外的输出目录，不能写入索引、数据库或源码目录')
    if not os.access(str(parent),os.W_OK):raise ValueError('输出目录不可写')
    return parent


def selection(snapshot,body):
    filters=body.get('filter',{})
    if not isinstance(filters,dict):raise ValueError('Invalid filter')
    mode=filters.get('mode','all');query=filters.get('query','')
    minimum=filters.get('minFavorites',2)
    if mode not in ('favorites','consensus','notes','unreviewed','all'):raise ValueError('Invalid team filter')
    if not isinstance(query,str) or len(query)>300:raise ValueError('Query must contain at most 300 characters')
    if type(minimum) is not int or minimum<1:raise ValueError('共识人数 N 必须是任意正整数')
    methods=body.get('methods')
    if not isinstance(methods,list) or not methods or len(methods)>len(snapshot.manifest['methods']) or any(type(mi) is not int or not 0<=mi<len(snapshot.manifest['methods']) for mi in methods) or len(set(methods))!=len(methods):raise ValueError('请选择不重复的有效方法列')
    with snapshot.store.connect() as db:
        db.execute('BEGIN')
        version=db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0]
        aggregates={row['sample']:dict(row) for row in db.execute("SELECT sample,SUM(favorite) favorites,SUM(reviewed) reviewed,SUM(CASE WHEN note!='' OR tags!='[]' THEN 1 ELSE 0 END) notes FROM marks GROUP BY sample")}
    query=query.strip().lower();chosen=[]
    for si,sample in enumerate(snapshot.manifest['samples']):
        totals=aggregates.get(sample['id'],{'favorites':0,'reviewed':0,'notes':0})
        match=(mode=='all' or mode=='favorites' and totals['favorites']>=1 or mode=='consensus' and totals['favorites']>=minimum or mode=='notes' and totals['notes']>0 or mode=='unreviewed' and not totals['reviewed'])
        if match and (not query or query in sample['name'].lower()):chosen.append((si,totals))
    chosen.sort(key=lambda item:(-item[1]['favorites'],-item[1]['notes'],item[0]))
    names=unique_names([(m['id'],m['name']) for m in snapshot.manifest['methods']],reserved=REPORT_NAMES)
    folders=[{'method':mi,'id':snapshot.manifest['methods'][mi]['id'],'name':snapshot.manifest['methods'][mi]['name'],'folder':names[mi],'relativePath':names[mi]} for mi in methods]
    stems=unique_names([(s['id'],Path(s['name']).stem) for s in snapshot.manifest['samples']])
    entries=[];total=0;missing=0;files=0
    for si,_ in chosen:
        sample=snapshot.manifest['samples'][si]
        for method in folders:
            mi=method['method'];image=sample['images'][mi]
            if image:
                suffix=Path(image['relative']).suffix
                # Extensions originate only from the indexer's fixed image allowlist.
                if not re.fullmatch(r'\.[A-Za-z0-9]{1,8}',suffix):raise ValueError('Unsafe image extension')
                relative=method['folder']+'/'+stems[si]+suffix;size=max(0,int(image.get('bytes',0)))
                total+=size;files+=1
            else:relative='';size=0;missing+=1
            entries.append({'sample':sample['id'],'si':si,'mi':mi,'methodId':method['id'],'methodName':method['name'],'folder':method['folder'],'relative':relative,'sourceName':Path(image['relative']).name if image else '', 'bytes':size,'status':'pending' if image else 'missing'})
    preview={'count':len(chosen),'markVersion':version,'files':files,'bytes':total,'missing':missing,'methodFolders':folders,
             'sampleIds':[snapshot.manifest['samples'][si]['id'] for si,_ in chosen],
             'filter':{'mode':mode,'query':query,'minFavorites':minimum},'selection':'team-aggregates',
             'limits':{'maxFiles':MAX_FILES,'maxZipBytes':MAX_ZIP_BYTES,'maxFolderBytes':MAX_FOLDER_BYTES,'maxActiveJobs':1,'maxJobsPerUser':20,'maxJobsPerWorkspace':200}}
    return preview,entries


class Cancelled(Exception):pass


class Manager:
    _guard=threading.RLock();_registries={};_active=None
    def __init__(self,local,resources=None):
        self.local=Path(local).resolve();self.base=self.local/'batch-exports'
        self.resources=Path(resources or Path(__file__).resolve().parent).resolve()
        with self._guard:
            self.jobs=self._registries.setdefault(str(self.local),{})
            if not self.jobs:self._recover()

    def _recover(self):
        if not self.base.is_dir() or _linked(self.base):return
        for folder in list(self.base.iterdir())[:200]:
            if not re.fullmatch('[a-f0-9]{24}',folder.name) or not folder.is_dir() or _linked(folder):continue
            try:
                job=json.loads((folder/'job.json').read_text(encoding='utf-8'))
                if job.get('jobId')!=folder.name or job.get('status') not in FINAL|{'running'}:continue
                if job['status']=='running':
                    job.update(status='error',interrupted=True,error='服务在批次完成前中断；已生成文件保留，请核对原批次后重新导出')
                    summary={'format':job.get('format'),'partial':True,'batchName':job.get('batchName'),
                             'files':job.get('progress',{}).get('filesDone',0),'archiveReady':False}
                    if job.get('format')=='folder' and isinstance(job.get('destination'),str):summary['batchDirectory']=job['destination']
                    job['result']=summary
                    self._save(job)
                self.jobs[folder.name]=job
            except (OSError,ValueError):continue

    def preview(self,snapshot,user,body):
        data,_=selection(snapshot,body);data['canFolder']=bool(user['owner']);return data

    def active(self):
        with self._guard:return Manager._active is not None

    def start(self,snapshot,user,body):
        form=body.get('format','zip')
        if form not in ('folder','zip'):raise ValueError('Unknown export format')
        if form=='folder' and not user['owner']:raise PermissionError('远程筛选人仅允许下载 ZIP')
        with self._guard:
            if self._active is not None:raise Conflict('已有一个批量导出正在运行，请等待完成或取消')
            if len(self.jobs)>=200:raise ValueError('当前工作区已保留 200 个批次，请由主机先备份并管理旧批次')
            if sum(job.get('actor')==user['id'] for job in self.jobs.values())>=20:raise ValueError('该筛选人的批次已达 20 个，请由主机管理已保留的批次')
            preview,entries=selection(snapshot,body)
            if type(body.get('expectedVersion')) is not int or body['expectedVersion']!=preview['markVersion']:raise Conflict('团队标记已变化，请重新预览后导出')
            if not preview['count']:raise ValueError('当前团队筛选没有符合的样本')
            if len(entries)>MAX_FILES or preview['bytes']>(MAX_ZIP_BYTES if form=='zip' else MAX_FOLDER_BYTES):raise ValueError('导出超过文件数或字节限额，请缩小筛选范围或改用本机文件夹导出')
            parent=output_parent(body.get('directory'),snapshot,self.local,self.resources) if form=='folder' else self.base
            self.base.mkdir(parents=True,exist_ok=True)
            if _linked(self.base) or self.base.resolve().parent!=self.local:raise ValueError('Unsafe export workspace')
            report_budget=RESERVE+len(entries)*2048
            required=(preview['bytes']+report_budget)*(2 if form=='zip' else 1)
            if shutil.disk_usage(parent).free<required:raise ValueError('目标磁盘可用空间不足（包含报告与安全余量）')
            job_id=secrets.token_hex(12);batch='Comparison-'+time.strftime('%Y%m%d-%H%M%S')+'-'+job_id[:8]
            private=self.base/job_id
            destination=parent/batch if form=='folder' else private/'files'
            if os.name=='nt' and max((len(str(destination/entry['relative'])) for entry in entries if entry['relative']),default=len(str(destination)))>240:
                raise ValueError('输出路径过长，请选择更短的输出目录；ZIP 模式请主机使用更短工作区路径')
            private.mkdir(parents=True,exist_ok=False)
            destination.mkdir(exist_ok=False)
            for method in preview['methodFolders']:(destination/method['folder']).mkdir(exist_ok=False)
            job={'jobId':job_id,'actor':user['id'],'datasetId':snapshot.dataset_id,'indexId':snapshot.index_id,'status':'running','format':form,
                 'created':int(time.time()),'batchName':batch,'preview':preview,
                 'progress':{'samplesDone':0,'totalSamples':preview['count'],'filesDone':0,'totalFiles':preview['files'],'bytesDone':0,'totalBytes':preview['bytes'],'missing':preview['missing'],'failed':0}}
            if form=='folder':job['destination']=str(destination)
            self.jobs[job_id]=job;Manager._active=job_id;event=threading.Event();job['_cancel']=event
            try:
                self._save(job)
                threading.Thread(target=self._work,args=(job,snapshot,entries,destination,private,event),name='original-byte-export',daemon=True).start()
            except Exception:
                self.jobs.pop(job_id,None);Manager._active=None;raise
            return {'jobId':job_id}

    def _save(self,job):
        folder=self.base/job['jobId'];temp=folder/('job-'+secrets.token_hex(4)+'.tmp')
        if _linked(self.base) or _linked(folder) or folder.resolve().parent!=self.base:raise ValueError('Unsafe job metadata directory')
        data={key:value for key,value in job.items() if not key.startswith('_')}
        with temp.open('x',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False)
        os.replace(str(temp),str(folder/'job.json'))

    def _owned(self,snapshot,user,job_id):
        if not isinstance(job_id,str) or not re.fullmatch('[a-f0-9]{24}',job_id):raise ValueError('Invalid export job')
        job=self.jobs.get(job_id)
        if not job or job.get('actor')!=user['id']:raise PermissionError('此批次不属于当前筛选人')
        if job['datasetId']!=snapshot.dataset_id or job['indexId']!=snapshot.index_id:raise Conflict('数据集或索引已更换，请返回原工作区查看该批次')
        return job

    def get(self,snapshot,user,job_id):
        with self._guard:
            job=self._owned(snapshot,user,job_id)
            return json.loads(json.dumps({key:value for key,value in job.items() if not key.startswith('_') and key not in ('actor','preview')}))

    def cancel(self,snapshot,user,job_id):
        with self._guard:
            job=self._owned(snapshot,user,job_id)
            if job['status']=='running':job['_cancel'].set()
            return {'ok':True,'jobId':job_id,'status':job['status']}

    def download(self,snapshot,user,job_id):
        with self._guard:
            job=self._owned(snapshot,user,job_id)
            if job['status'] not in FINAL or job['format']!='zip' or not job.get('result',{}).get('downloadUrl'):raise Conflict('ZIP 尚未准备完成')
            folder=self.base/job_id;path=folder/(job['batchName']+'.zip')
            if _linked(folder) or _linked(path) or path.resolve().parent!=folder.resolve():raise ValueError('Unsafe export archive')
            return path

    def _copy(self,snapshot,entry,target,event,expected_root):
        source,before=_source(snapshot,entry['si'],entry['mi'])
        if event.is_set():raise Cancelled()
        if _linked(target.parent) or target.parent.resolve().parent!=expected_root:raise ValueError('Unsafe output directory')
        flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)
        handle=os.open(str(source),flags);created=None;digest=hashlib.sha256();written=0
        try:
            with os.fdopen(handle,'rb') as reader:
                opened=os.fstat(reader.fileno())
                if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino):raise OSError('Source identity changed')
                if opened.st_size!=entry['bytes']:raise OSError('Source byte size differs from index; rebuild the image index before exporting')
                with target.open('xb') as writer:
                    created=os.fstat(writer.fileno())
                    while True:
                        if event.is_set():raise Cancelled()
                        block=reader.read(CHUNK)
                        if not block:break
                        if written+len(block)>opened.st_size:raise OSError('Source grew beyond its indexed byte size during export')
                        writer.write(block);digest.update(block);written+=len(block)
                after=os.fstat(reader.fileno())
                if (after.st_size,after.st_mtime_ns)!=(opened.st_size,opened.st_mtime_ns) or written!=opened.st_size:raise OSError('Source changed while being copied')
            return written,digest.hexdigest()
        except Exception:
            try:
                if created and not _linked(target) and (target.stat().st_dev,target.stat().st_ino)==(created.st_dev,created.st_ino):target.unlink()
            except OSError:pass
            raise

    def _work(self,job,snapshot,entries,destination,private,event):
        copied=[];status='done';fatal=None;previous=None;expected_root=destination.resolve()
        try:
            for entry in entries:
                if event.is_set():status='cancelled';break
                if previous is not None and previous!=entry['si']:job['progress']['samplesDone']+=1
                previous=entry['si']
                if entry['status']=='missing':continue
                target=destination/entry['relative']
                try:
                    if _linked(destination) or destination.resolve()!=expected_root:raise OSError('Output batch directory changed')
                    size,digest=self._copy(snapshot,entry,target,event,expected_root)
                    entry.update(status='copied',bytes=size,sha256=digest);copied.append(entry)
                    job['progress']['filesDone']+=1;job['progress']['bytesDone']+=size
                except Cancelled:status='cancelled';break
                except (OSError,ValueError) as error:
                    entry['status']='failed';entry['error']='Source unavailable, changed, unsafe, or output could not be written'
                    if 'index' in str(error) or 'Source grew' in str(error):entry['error']='原图大小与索引不同或复制时发生变化，请更新图片索引后重新导出'
                    job['progress']['failed']+=1
                if len(copied)%20==0:self._save(job)
            if status=='done':job['progress']['samplesDone']=job['progress']['totalSamples']
        except Exception:
            status='error';fatal='Export interrupted; completed original-byte copies were retained'
        for entry in entries:
            if entry['status']=='pending':entry['status']='not-copied'
        partial=status!='done' or bool(job['progress']['failed'] or job['progress']['missing'])
        result={'format':job['format'],'partial':partial,'batchName':job['batchName'],'count':job['progress']['totalSamples'],
                'files':len(copied),'missing':job['progress']['missing'],'failed':job['progress']['failed'],
                'methodFolders':job['preview']['methodFolders'],'report':'report.json','csv':'manifest.csv','paths':'paths.txt'}
        supported={'.png','.jpg','.jpeg','.bmp','.tif','.tiff'}
        by_sample={sample:{} for sample in job['preview']['sampleIds']}
        for entry in copied:by_sample[entry['sample']][entry['mi']]=entry
        rows=[]
        for sample in job['preview']['sampleIds']:
            current=[by_sample[sample].get(method['method']) for method in job['preview']['methodFolders']]
            if all(entry and Path(entry['relative']).suffix.lower() in supported for entry in current):rows.append([entry['relative'] for entry in current])
        result.update(mulimgRows=rows,mulimgCompleteRows=len(rows),mulimgExcludedRows=result['count']-len(rows),mulimgCsv='MulimgViewer.csv' if job['format']=='folder' else 'mulimg-relative.csv')
        if job['format']=='folder':
            result['batchDirectory']=str(destination)
            result['methodFolders']=[dict(method,path=str(destination/method['folder'])) for method in result['methodFolders']]
        try:
            job['progress']['phase']='packing' if job['format']=='zip' else 'reporting'
            if job['format']=='zip':
                archive=private/(job['batchName']+'.zip')
                # ZIP_STORED preserves image bytes, without image recompression.
                with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_STORED,allowZip64=True) as output:
                    for entry in copied:
                        if event.is_set():raise Cancelled()
                        path=destination/entry['relative']
                        if _linked(path) or path.resolve().parent!=path.parent.resolve():raise ValueError('Unsafe staged image')
                        with path.open('rb') as reader,output.open(job['batchName']+'/'+entry['relative'],'w',force_zip64=True) as writer:
                            while True:
                                if event.is_set():raise Cancelled()
                                block=reader.read(CHUNK)
                                if not block:break
                                writer.write(block)
                    self._reports(destination,job,entries,result,status,fatal)
                    for name in ('report.json','README.md','manifest.csv','paths.txt','mulimg-relative.csv'):
                        output.write(destination/name,job['batchName']+'/'+name)
                result['archiveName']=archive.name
                result['downloadUrl']='/api/batch-export/download?id='+job['jobId']+'&dataset='+job['datasetId']+'&index='+job['indexId']
            else:self._reports(destination,job,entries,result,status,fatal)
        except Cancelled:
            status='cancelled';result['partial']=True;result['archiveReady']=False
            result['message']='ZIP 已取消；完整复制的原图保留在主机受控批次目录，不提供不完整 ZIP 下载'
            try:
                if archive.is_file() and not _linked(archive) and archive.resolve().parent==private:archive.unlink()
                self._reports(destination,job,entries,result,status,None)
            except (OSError,ValueError):fatal='Cancelled export retained copies, but its final report could not be completed'
        except (OSError,ValueError,zipfile.BadZipFile):
            status='error';result['partial']=True;fatal='Export files retained, but report/archive finalization failed'
            try:
                report_path=destination/'report.json'
                if report_path.exists() and not _linked(report_path):
                    report=json.loads(report_path.read_text(encoding='utf-8'));report.update(status='error',partial=True,error=fatal)
                    temporary=destination/('report-'+secrets.token_hex(4)+'.tmp')
                    with temporary.open('x',encoding='utf-8') as file:json.dump(report,file,ensure_ascii=False,indent=2)
                    os.replace(str(temporary),str(report_path))
                elif not report_path.exists():self._reports(destination,job,entries,result,status,fatal)
            except (OSError,ValueError):pass
        finally:
            with self._guard:
                job.update(status=status,result=result)
                if fatal:job['error']=fatal
                try:self._save(job)
                finally:Manager._active=None

    def _reports(self,destination,job,entries,result,status,error):
        report={'schema':1,'dataset':job['datasetId'],'indexId':job['indexId'],'markVersion':job['preview']['markVersion'],
                'filter':job['preview']['filter'],'status':status,'partial':result['partial'],'count':result['count'],
                'files':result['files'],'missing':result['missing'],'failed':result['failed'],
                'methodFolders':job['preview']['methodFolders'],'entries':[{key:value for key,value in entry.items() if key not in ('si','mi')} for entry in entries]}
        if error:report['error']=error
        if _linked(destination) or destination.resolve()!=destination:raise ValueError('Unsafe report directory')
        with (destination/'report.json').open('x',encoding='utf-8') as file:json.dump(report,file,ensure_ascii=False,indent=2)
        with (destination/'manifest.csv').open('x',encoding='utf-8-sig',newline='') as file:
            writer=csv.writer(file);writer.writerow(['sample_id','method_id','method_name','method_folder','relative_output','source_filename','status','bytes','sha256'])
            for entry in entries:writer.writerow([entry['sample'],entry['methodId'],entry['methodName'],entry['folder'],entry['relative'],entry['sourceName'],entry['status'],entry['bytes'],entry.get('sha256','')])
        # Relative method paths deliberately avoid leaking host source roots.
        with (destination/'paths.txt').open('x',encoding='utf-8') as file:file.write('\n'.join(str(destination/method['folder']) if job['format']=='folder' else method['folder'] for method in job['preview']['methodFolders'])+'\n')
        with (destination/('MulimgViewer.csv' if job['format']=='folder' else 'mulimg-relative.csv')).open('x',encoding='utf-8',newline='') as file:
            writer=csv.writer(file)
            for row in result['mulimgRows']:writer.writerow([str(destination/value) for value in row] if job['format']=='folder' else row)
        with (destination/'README.md').open('x',encoding='utf-8') as file:file.write('# 原始检测结果批量导出\n\n图片按原始字节复制，未缩放、未重绘、未改变检测框，也未修改源文件。\n\n'+
            '同一样本在各方法目录使用一致主文件名，保留各自真实扩展名；重名或非法名称使用稳定标识消歧。原显示名称与安全目录名称映射见 report.json。\n\n'+
            'manifest.csv 是带表头的审计清单，不是 MulimgViewer 导入 CSV。MulimgViewer 专用 CSV 无表头、UTF-8 无 BOM，每行仅包含所有所选方法均成功且格式受支持的同一样本。\n\n'+
            '本机文件夹提供绝对路径 MulimgViewer.csv；ZIP 仅含 mulimg-relative.csv 参考表，不能直接假定第三方工具按 CSV 所在目录解析相对路径。请在网页填写实际已解压批次目录，再下载重新定位后的绝对路径 CSV。\n\n'+
            'paths.txt 为相对于本批次的目录；解压后在自己的电脑选择实际目录。Missing、失败、取消及未复制项目均记录在报告中。partial=true 表示本批次不完整，不能据此宣称全部导出成功。\n')
