"""Atomic dataset selection and asynchronous metadata-only indexing."""
import hashlib
import json
import os
import secrets
import shutil
import threading
import time
import uuid
from pathlib import Path
from collaboration import Store
from dataset_config import normalize_config
import build_index


def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+secrets.token_hex(4)+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(str(temporary),str(path))


class Snapshot:
    def __init__(self,manifest,audit,folder,local):
        self.manifest=manifest;self.audit=audit;self.folder=Path(folder)
        self.dataset_id=manifest['datasetId'];self.index_id=manifest['indexId']
        self.store=Store(Path(local)/'workspaces'/self.dataset_id/'collaboration',[s['id'] for s in manifest['samples']],manifest['dataset'],self.dataset_id)
        self.owner_js=('window.RGBT_MANIFEST = '+json.dumps(manifest,ensure_ascii=False,separators=(',',':'))+';').encode('utf-8')
        public={k:v for k,v in manifest.items() if k!='audit'}
        public['methods']=[{k:v for k,v in method.items() if k not in ('root','audit')} for method in manifest['methods']]
        self.public_js=('window.RGBT_MANIFEST = '+json.dumps(public,ensure_ascii=False,separators=(',',':'))+';').encode('utf-8')

    def image_path(self,si,mi):
        methods=self.manifest['methods'];samples=self.manifest['samples']
        if si<0 or si>=len(samples) or mi<0 or mi>=len(methods):raise ValueError('Invalid indexed image')
        record=samples[si]['images'][mi]
        if not record:raise FileNotFoundError('Missing indexed image')
        root=Path(methods[mi]['root']).resolve();path=(root/record['relative']).resolve()
        if os.path.commonpath([str(path),str(root)])!=str(root) or not path.is_file():raise FileNotFoundError('Indexed image unavailable')
        return path


class Workspace:
    def __init__(self,local):
        self.local=Path(local).resolve();self.local.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.jobs={};self.active=None;self.config=None;self.error=None
        config_file=self.local/'config.json'
        if config_file.exists():
            try:
                self.config=json.loads(config_file.read_text(encoding='utf-8'))
                config=normalize_config(self.config)
                pointer=json.loads((self.local/'active.json').read_text(encoding='utf-8'))
                if pointer['datasetId']!=config['datasetId'] or not isinstance(pointer['indexId'],str) or not all(c in '0123456789abcdef' for c in pointer['indexId']) or len(pointer['indexId'])>64:raise ValueError('Saved index pointer is invalid')
                folder=self.local/'indexes'/config['datasetId']/pointer['indexId']
                manifest=json.loads((folder/'manifest.js').read_text(encoding='utf-8').split('=',1)[1].strip().rstrip(';'))
                if manifest.get('datasetId')!=config['datasetId'] or manifest.get('indexId')!=pointer['indexId'] or manifest.get('dataset')!=config['dataset']:
                    raise ValueError('Saved manifest identity differs from active configuration')
                if manifest['methods']!=config['methods'] or manifest['referenceId']!=config['referenceId']:raise ValueError('Saved directories differ from index; rebuild required')
                audit=json.loads((folder/'index_audit.json').read_text(encoding='utf-8'))
                self.active=Snapshot(manifest,audit,folder,self.local);self.config=config
            except (OSError,ValueError,KeyError,TypeError) as error:
                self.error='上次目录或索引暂不可用，请检查配置并重新构建：'+str(error)

    def snapshot(self):
        with self.lock:return self.active

    def start_build(self,data):
        config=normalize_config(data)
        registry_file=self.local/'datasets.json'
        try:registry=json.loads(registry_file.read_text(encoding='utf-8'))
        except (OSError,ValueError):registry={}
        if not isinstance(registry,dict):registry={}
        reference=next(m for m in config['methods'] if m['id']==config['referenceId'])
        identity=os.path.normcase(str(Path(reference['root']).resolve()))
        previous=registry.get(config['datasetId'])
        if previous and previous!=identity:
            config['datasetId']=next((key for key,value in registry.items() if value==identity),str(uuid.uuid4()))
        with self.lock:
            if any(job['status']=='running' for job in self.jobs.values()):raise RuntimeError('已有索引任务正在进行，请等待完成')
            job_id=secrets.token_hex(12)
            self.jobs[job_id]={'jobId':job_id,'status':'running','progress':{'message':'准备扫描目录','current':0,'total':len(config['methods'])}}
            if len(self.jobs)>8:
                for old in list(self.jobs):
                    if old!=job_id and self.jobs[old]['status']!='running':del self.jobs[old];break
        def work():
            temporary=self.local/'tmp'/('build-'+job_id)
            def clean_temporary():
                if temporary.is_dir() and not temporary.is_symlink() and temporary.resolve().parent==(self.local/'tmp').resolve() and temporary.name=='build-'+job_id:
                    shutil.rmtree(str(temporary.resolve()))
            try:
                def progress(event):
                    with self.lock:
                        self.jobs[job_id]['progress']={'message':event.get('message','正在构建'),'current':event.get('completed',event.get('current',0)),'total':event.get('total',len(config['methods']))}
                manifest,audit=build_index.build(config,temporary,progress=progress)
                for method in audit.get('methods',[]):
                    method.setdefault('name',method.get('method',''));method.setdefault('count',method.get('images',0))
                    method.setdefault('ambiguous',method.get('conflicts',sum(n for kind,n in method.get('matchKinds',{}).items() if str(kind).startswith(('ambiguous','conflict-')))))
                atomic_json(temporary/'index_audit.json',audit)
                folder=self.local/'indexes'/config['datasetId']/manifest['indexId'];folder.parent.mkdir(parents=True,exist_ok=True)
                if folder.exists():
                    clean_temporary()
                else:
                    os.replace(str(temporary),str(folder))
                snapshot=Snapshot(manifest,audit,folder,self.local)
                registry[config['datasetId']]=identity
                with self.lock:
                    atomic_json(registry_file,registry)
                    atomic_json(self.local/'config.json',config)
                    atomic_json(self.local/'active.json',{'datasetId':config['datasetId'],'indexId':manifest['indexId']})
                    self.active=snapshot;self.config=config;self.error=None
                    self.jobs[job_id].update({'status':'done','audit':audit,'datasetId':config['datasetId'],'progress':{'message':'检查完成，可以进入查看器','current':len(config['methods']),'total':len(config['methods'])}})
            except Exception as error:
                with self.lock:self.jobs[job_id].update({'status':'error','error':str(error)})
                # Only this generated directory can be removed; no source folder operation.
                clean_temporary()
        threading.Thread(target=work,name='metadata-indexer',daemon=True).start()
        return job_id

    def job(self,job_id):
        with self.lock:
            if job_id not in self.jobs:raise KeyError('索引任务不存在')
            return json.loads(json.dumps(self.jobs[job_id]))
