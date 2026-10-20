# -*- coding: utf-8 -*-
"""Project-local SQLite collaboration storage; no access to image pixels."""
import json, sqlite3, secrets, hashlib, hmac, time, unicodedata, threading
from pathlib import Path
from contextlib import contextmanager

class Conflict(Exception):
    pass

class Store:
    _locks={}
    _locks_guard=threading.Lock()
    def __init__(self, folder, sample_ids, dataset='Image Comparison', dataset_id=''):
        self.dataset=dataset; self.dataset_id=dataset_id
        self.folder=Path(folder); self.folder.mkdir(parents=True,exist_ok=True)
        self.file=self.folder/'workspace.sqlite3'; self.ids=set(sample_ids)
        self.access_file=self.folder/'access.json'
        with self._locks_guard:
            self.lock=self._locks.setdefault(str(self.folder.resolve()),threading.RLock())
        with self.lock:
            if not self.access_file.exists(): self.rotate_access(first=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
            INSERT OR IGNORE INTO meta VALUES('version',0);
            CREATE TABLE IF NOT EXISTS reviewers(id TEXT PRIMARY KEY,nickname TEXT NOT NULL,norm TEXT UNIQUE NOT NULL,recovery TEXT NOT NULL,created INTEGER NOT NULL);
            INSERT OR IGNORE INTO reviewers VALUES('owner','主机管理员','__owner__','',0);
            CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,reviewer TEXT NOT NULL,csrf TEXT NOT NULL,expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS marks(reviewer TEXT NOT NULL,sample TEXT NOT NULL,favorite INTEGER NOT NULL DEFAULT 0,reviewed INTEGER NOT NULL DEFAULT 0,note TEXT NOT NULL DEFAULT '',tags TEXT NOT NULL DEFAULT '[]',revision INTEGER NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(reviewer,sample));
            CREATE INDEX IF NOT EXISTS marks_sample ON marks(sample);
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(str(self.file),timeout=10); db.row_factory=sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback(); raise
        finally: db.close()

    @staticmethod
    def digest(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()

    @property
    def access(self):
        return json.loads(self.access_file.read_text(encoding='utf-8'))

    def rotate_access(self,first=False):
        with self.lock:return self._rotate_access(first)

    def _rotate_access(self,first=False):
        code=secrets.token_hex(3)+'-'+secrets.token_hex(3)
        salt=secrets.token_hex(24)
        value={'salt':salt,'hash':hashlib.pbkdf2_hmac('sha256',code.encode(),bytes.fromhex(salt),180000).hex(),'code':code}
        temp=self.access_file.with_suffix('.tmp'); temp.write_text(json.dumps(value),encoding='utf-8'); temp.replace(self.access_file)
        if not first:
            with self.connect() as db: db.execute('DELETE FROM sessions')
        return code

    def verify_code(self,code):
        if not isinstance(code,str) or len(code)>128: return False
        access=self.access
        digest=hashlib.pbkdf2_hmac('sha256',code.strip().encode(),bytes.fromhex(access['salt']),180000).hex()
        return hmac.compare_digest(digest,access['hash'])

    def login(self,code,nickname,recovery=''):
        with self.lock:return self._login(code,nickname,recovery)

    def _login(self,code,nickname,recovery=''):
        if not self.verify_code(code): raise PermissionError('访问口令不正确')
        if not isinstance(nickname,str): raise ValueError('请输入筛选人昵称')
        nickname=unicodedata.normalize('NFKC',nickname).strip()
        if not 2<=len(nickname)<=24 or any(unicodedata.category(c).startswith('C') for c in nickname): raise ValueError('昵称须为 2～24 个可见字符')
        norm=nickname.casefold()
        if norm in ('__owner__','主机管理员'): raise ValueError('此昵称保留给主机管理员')
        if not isinstance(recovery,str) or len(recovery)>128: raise ValueError('恢复码格式无效')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM reviewers WHERE norm=?',(norm,)).fetchone()
            new_recovery=None
            if row:
                if not recovery or not hmac.compare_digest(self.digest(recovery.strip()),row['recovery']): raise Conflict('昵称已被使用；请填写该昵称的恢复码，或换一个新昵称')
                rid=row['id']; nickname=row['nickname']
            else:
                if db.execute('SELECT COUNT(*) FROM reviewers').fetchone()[0]>=101: raise ValueError('筛选人数量已达上限，请联系主机管理员')
                if recovery: raise ValueError('未找到这个昵称，请清空恢复码后创建新身份')
                rid=secrets.token_hex(12); new_recovery=secrets.token_urlsafe(18)
                db.execute('INSERT INTO reviewers VALUES(?,?,?,?,?)',(rid,nickname,norm,self.digest(new_recovery),int(time.time())))
                db.execute("UPDATE meta SET value=value+1 WHERE key='version'")
            session=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(self.digest(session),rid,csrf,int(time.time())+30*86400))
        return {'id':rid,'nickname':nickname,'csrf':csrf,'session':session,'recovery':new_recovery}

    def session(self,token):
        if not token or len(token)>128: return None
        with self.connect() as db:
            row=db.execute('SELECT r.id,r.nickname,s.csrf FROM sessions s JOIN reviewers r ON r.id=s.reviewer WHERE s.hash=? AND s.expires>?',(self.digest(token),int(time.time()))).fetchone()
            return dict(row) if row else None

    def logout(self,token):
        with self.connect() as db: db.execute('DELETE FROM sessions WHERE hash=?',(self.digest(token),))

    @staticmethod
    def mark(row):
        return {'favorite':bool(row['favorite']),'reviewed':bool(row['reviewed']),'note':row['note'],'tags':json.loads(row['tags']),'revision':row['revision'],'updated':row['updated']}

    def validate(self,sample,patch):
        if sample not in self.ids: raise ValueError('索引中不存在此样本')
        if not isinstance(patch,dict) or not patch or set(patch)-{'favorite','reviewed','note','tags'}: raise ValueError('无效的标记字段')
        for key in ('favorite','reviewed'):
            if key in patch and not isinstance(patch[key],bool): raise ValueError('标记状态必须为布尔值')
        if 'note' in patch and (not isinstance(patch['note'],str) or len(patch['note'])>2000): raise ValueError('备注最多 2000 字')
        if 'tags' in patch:
            if not isinstance(patch['tags'],list) or len(patch['tags'])>30 or any(not isinstance(t,str) or len(t)>64 for t in patch['tags']): raise ValueError('最多 30 个标签，每个最多 64 字')
            patch={**patch,'tags':list(dict.fromkeys(t.strip() for t in patch['tags'] if t.strip()))}
        return patch

    def write_many(self,rid,entries):
        if not isinstance(entries,list) or not 1<=len(entries)<=len(self.ids): raise ValueError('无效的导入数量')
        checked=[]; seen=set()
        for entry in entries:
            if not isinstance(entry,dict): raise ValueError('无效的标记')
            sample=entry.get('sample'); revision=entry.get('revision')
            if not isinstance(sample,str) or sample in seen or type(revision) is not int or revision<0: raise ValueError('无效或重复的样本版本')
            seen.add(sample); checked.append((sample,revision,self.validate(sample,entry.get('patch'))))
        result={}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for sample,revision,patch in checked:
                row=db.execute('SELECT * FROM marks WHERE reviewer=? AND sample=?',(rid,sample)).fetchone()
                if (row['revision'] if row else 0)!=revision: raise Conflict('同一身份的其他标签页已更新标记，请刷新后再试；未覆盖已有内容')
                mark=self.mark(row) if row else {'favorite':False,'reviewed':False,'note':'','tags':[]}
                mark.update(patch); mark['revision']=revision+1; mark['updated']=int(time.time())
                db.execute('INSERT OR REPLACE INTO marks VALUES(?,?,?,?,?,?,?,?)',(rid,sample,int(mark['favorite']),int(mark['reviewed']),mark['note'],json.dumps(mark['tags'],ensure_ascii=False),mark['revision'],mark['updated']))
                result[sample]=mark
            db.execute("UPDATE meta SET value=value+1 WHERE key='version'")
            version=db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0]
        return {'marks':result,'version':version}

    def workspace(self,rid,since=None):
        with self.connect() as db:
            db.execute('BEGIN')
            version=db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0]
            if since is not None and str(version)==str(since): return {'unchanged':True,'version':version}
            mine={r['sample']:self.mark(r) for r in db.execute('SELECT * FROM marks WHERE reviewer=?',(rid,)) if r['sample'] in self.ids}
            aggregates={r['sample']:{'favorites':r['favorites'],'reviewed':r['reviewed'],'notes':r['notes']} for r in db.execute("SELECT sample,SUM(favorite) favorites,SUM(reviewed) reviewed,SUM(CASE WHEN note!='' OR tags!='[]' THEN 1 ELSE 0 END) notes FROM marks GROUP BY sample") if r['sample'] in self.ids}
            reviewers=[]
            for r in db.execute('SELECT id,nickname FROM reviewers ORDER BY created,nickname'):
                rows=list(db.execute('SELECT sample,favorite,reviewed,note,tags FROM marks WHERE reviewer=?',(r['id'],)))
                rows=[m for m in rows if m['sample'] in self.ids]
                reviewers.append({'id':r['id'],'nickname':r['nickname'],'favorites':sum(m['favorite'] for m in rows),'reviewed':sum(m['reviewed'] for m in rows),'notes':sum(bool(m['note'] or m['tags']!='[]') for m in rows)})
        return {'version':version,'marks':mine,'aggregates':aggregates,'reviewers':reviewers}

    def reviewer_marks(self,rid):
        with self.connect() as db:
            row=db.execute('SELECT id,nickname FROM reviewers WHERE id=?',(rid,)).fetchone()
            if not row: raise ValueError('筛选人不存在')
            return {'reviewer':dict(row),'marks':{r['sample']:self.mark(r) for r in db.execute('SELECT * FROM marks WHERE reviewer=?',(rid,)) if r['sample'] in self.ids}}

    def sample_marks(self,sample):
        if sample not in self.ids: raise ValueError('样本不存在')
        with self.connect() as db:
            return [dict(self.mark(r),reviewer=r['reviewer'],nickname=r['nickname']) for r in db.execute('SELECT m.*,r.nickname FROM marks m JOIN reviewers r ON r.id=m.reviewer WHERE sample=? ORDER BY r.nickname',(sample,))]

    def export(self):
        with self.connect() as db:
            db.execute('BEGIN')
            return {'schema':2,'dataset':self.dataset,'datasetId':self.dataset_id,'created':int(time.time()),'reviewers':[{'id':r['id'],'nickname':r['nickname'],'marks':{m['sample']:self.mark(m) for m in db.execute('SELECT * FROM marks WHERE reviewer=?',(r['id'],)) if m['sample'] in self.ids}} for r in db.execute('SELECT id,nickname FROM reviewers ORDER BY nickname')]}
