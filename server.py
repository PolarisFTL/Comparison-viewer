"""Offline image comparison server. Standard library only; Python 3.9+."""
import argparse
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from collaboration import Conflict
from batch_export import Manager as BatchExportManager
from demo_data import generate_demo
from image_metadata import image_metadata
from platform_support import local_interfaces, picker_command, project_root, resource_root, reveal_command
from workspace_state import Workspace, atomic_json

APP='RGBT Comparison Viewer'
VERSION='2.2.1'
DEFAULT_PORT=8770


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address=False
    daemon_threads=True
    def server_bind(self):
        if hasattr(__import__('socket'),'SO_EXCLUSIVEADDRUSE'):
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


def validated_networks(values):
    networks=[]
    for value in values:
        network=ipaddress.ip_network(value,strict=True)
        if network.version!=4 or not network.is_private or network.prefixlen<16:
            raise ValueError('LAN access requires a private IPv4 subnet no broader than /16')
        networks.append(network)
    return networks


def configure(server,local,lan=False,allowed_subnets=None,resources=None):
    server.resources=Path(resources or resource_root()).resolve()
    server.workspace=Workspace(local)
    server.token=secrets.token_urlsafe(32)
    server.project=hashlib.sha256(str(server.workspace.local).encode('utf-8')).hexdigest()[:16]
    server.interfaces=local_interfaces()
    server.lan_enabled=bool(lan)
    networks=allowed_subnets if allowed_subnets is not None else [network for _,network in server.interfaces]
    server.allowed_networks=[]
    if lan:
        server.allowed_networks=validated_networks(networks)
        if not server.allowed_networks:
            raise ValueError('无法确定真实局域网掩码。请使用 --allow-subnet 指定可信网段，或先以本机模式启动。')
    server.allowed_hosts={host+':'+str(server.server_port) for host in ['127.0.0.1','localhost']+[ip for ip,_ in server.interfaces]}
    server.image_slots=threading.BoundedSemaphore(12)
    server.picker_lock=threading.Lock()
    server.login_lock=threading.Lock();server.login_attempts=[]
    server.batch_exports=BatchExportManager(server.workspace.local,server.resources)
    return server


def share_info(server,snapshot):
    addresses=[]
    if server.lan_enabled:
        addresses=['http://{}:{}/'.format(ip,server.server_port) for ip,_ in server.interfaces if any(ipaddress.ip_address(ip) in n for n in server.allowed_networks)]
    return {'enabled':server.lan_enabled,'addresses':addresses,'code':snapshot.store.access['code'],'port':server.server_port,
            'allowedSubnets':[str(n) for n in server.allowed_networks],'scope':', '.join(str(n) for n in server.allowed_networks) if server.lan_enabled else 'local-only',
            'database':str(snapshot.store.file)}


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def setup(self):
        super().setup();self.connection.settimeout(30)
    def log_message(self,*args):
        pass
    def security_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cross-Origin-Resource-Policy','same-origin')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
    def reply(self,status,body=b'',mime='application/json; charset=utf-8',cookie=None,location=None):
        if status>=400 and self.command=='POST':self.discard_small_body()
        self.send_response(status)
        self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
        self.security_headers()
        if cookie:self.send_header('Set-Cookie',cookie)
        if location:self.send_header('Location',location)
        if status>=400:self.send_header('Connection','close');self.close_connection=True
        self.end_headers()
        try:self.wfile.write(body)
        except (OSError,ConnectionError):pass
    def js(self,status,data,**kwargs):
        self.reply(status,json.dumps(data,ensure_ascii=False).encode('utf-8'),**kwargs)
    def redirect(self,path):self.reply(303,location=path)
    def valid_request(self):
        if self.headers.get('Host') not in self.server.allowed_hosts:
            self.js(403,{'error':'Host not allowed'});return False
        address=ipaddress.ip_address(self.client_address[0])
        if not address.is_loopback and (not self.server.lan_enabled or not any(address in network for network in self.server.allowed_networks)):
            self.js(403,{'error':'此地址不在允许的可信局域网范围内'});return False
        return True
    def owner(self):
        return ipaddress.ip_address(self.client_address[0]).is_loopback and self.headers.get('Host') in ('127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port))
    def cookie_name(self,snapshot):return 'rgbt_'+self.server.project+'_'+snapshot.dataset_id.replace('-','')[:12]
    def cookie_token(self,snapshot):
        try:
            cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''));name=self.cookie_name(snapshot)
            return cookie[name].value if name in cookie else ''
        except Exception:return ''
    def actor(self,snapshot):
        if self.owner():return {'id':'owner','nickname':'主机管理员','csrf':self.server.token,'owner':True}
        if snapshot is None:return None
        user=snapshot.store.session(self.cookie_token(snapshot))
        return dict(user,owner=False) if user else None
    def guard_dataset(self,snapshot,query=None):
        query=query or {}
        dataset=self.headers.get('X-Dataset-Id') or query.get('dataset',[None])[0]
        index=self.headers.get('X-Index-Id') or query.get('index',[None])[0]
        if not snapshot or dataset!=snapshot.dataset_id or index!=snapshot.index_id:
            self.js(409,{'error':'数据集或图片索引已更换，请重新打开查看器；未读取或覆盖其他数据集的标记。','reload':'/viewer'});return False
        return True
    def read_json(self,limit=32768):
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:raise ValueError('Invalid Content-Length')
        if not 0<length<=limit:raise ValueError('请求为空或超过大小限制')
        data=json.loads(self.read_body(length).decode('utf-8'))
        if not isinstance(data,dict):raise ValueError('JSON object required')
        return data
    def read_body(self,length,once=False):
        value=self.rfile.read1(length) if once else self.rfile.read(length)
        remaining=getattr(self,'_body_remaining',None)
        if remaining is not None:self._body_remaining=max(0,remaining-len(value))
        return value
    def discard_small_body(self):
        # Closing with unread TCP input can reset the connection before Windows
        # delivers our 403/409 JSON. Drain small requests only, with a hard total
        # deadline; never accept an unbounded/large unauthenticated upload here.
        remaining=getattr(self,'_body_remaining',None)
        if remaining is None or not 0<remaining<=65536:return
        original_timeout=self.connection.gettimeout();deadline=time.monotonic()+1
        try:
            while self._body_remaining:
                budget=deadline-time.monotonic()
                if budget<=0:break
                self.connection.settimeout(budget)
                if not self.read_body(min(self._body_remaining,8192),once=True):break
        except (OSError,TimeoutError):pass
        finally:self.connection.settimeout(original_timeout)
    def serve_file(self,path,image=False):
        if not path.is_file():self.js(404,{'error':'Resource missing'});return
        with path.open('rb') as file:
            self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(os.fstat(file.fileno()).st_size));self.send_header('Cache-Control','private, max-age=3600' if image else 'no-cache');self.security_headers();self.end_headers()
            try:
                while True:
                    block=file.read(262144)
                    if not block:break
                    self.wfile.write(block)
            except (OSError,ConnectionError):pass
    def do_GET(self):
        try:self.get()
        except (ValueError,KeyError,TypeError,UnicodeError) as error:self.js(400,{'error':str(error)})
        except (sqlite3.Error,OSError):self.js(503,{'error':'本地资源暂不可用，请检查目录权限或稍后重试'})
    def get(self):
        if not self.valid_request():return
        parsed=urlsplit(self.path);path=unquote(parsed.path);query=parse_qs(parsed.query)
        workspace=self.server.workspace;snapshot=workspace.snapshot();user=self.actor(snapshot)
        if path=='/health':
            self.js(200,{'app':APP,'version':VERSION,'project':self.server.project,'ready':bool(snapshot),'samples':len(snapshot.manifest['samples']) if snapshot else 0,'lanEnabled':self.server.lan_enabled,'allowedSubnets':[str(network) for network in self.server.allowed_networks]});return
        if path in ('/','/index.html'):
            self.redirect('/setup' if self.owner() else '/viewer');return
        if path in ('/setup','/setup.html'):
            if not self.owner():self.js(403,{'error':'目录配置仅允许在主机上操作'});return
            self.serve_file(self.server.resources/'setup.html');return
        if path in ('/login','/login.html'):
            self.serve_file(self.server.resources/'login.html');return
        if path in ('/viewer','/viewer.html'):
            if not snapshot:
                if self.owner():self.redirect('/setup')
                else:self.js(503,{'error':'主机尚未配置数据集，请联系管理员'})
                return
            if not user:self.serve_file(self.server.resources/'login.html');return
            html=(self.server.resources/'index.html').read_text(encoding='utf-8')
            html=html.replace('src="manifest.js"','src="/manifest.js?dataset='+snapshot.dataset_id+'&amp;index='+snapshot.index_id+'"')
            self.reply(200,html.encode('utf-8'),'text/html; charset=utf-8');return
        if re.fullmatch(r'/(js|css)/[a-zA-Z0-9_.-]+\.(js|css)',path) or path in ('/assets/brand.png','/assets/favicon.ico'):
            self.serve_file(self.server.resources/path.lstrip('/'));return
        if path.startswith('/api/setup'):
            if not self.owner():self.js(403,{'error':'目录配置仅允许在主机上操作'});return
            if path=='/api/setup':
                self.js(200,{'app':APP,'version':VERSION,'token':self.server.token,'owner':True,'config':workspace.config,'ready':bool(snapshot),'platform':sys.platform,'capabilities':{'picker':True,'configure':True},'error':workspace.error});return
            if path=='/api/setup/job':self.js(200,workspace.job(query.get('id',[''])[0]));return
            if path=='/api/setup/audit':self.js(200,snapshot.audit if snapshot else {});return
            if path=='/api/setup/demo':self.js(200,{'config':generate_demo(workspace.local/'demo')});return
            self.js(404,{'error':'Route not allowed'});return
        if path=='/api/info':
            if not user:self.js(401,{'error':'请先登录'});return
            self.js(200,{'app':APP,'version':VERSION,'token':user['csrf'],'owner':user['owner'],'collaboration':True,'lanEnabled':self.server.lan_enabled,'platform':sys.platform,'separator':os.sep,
                'user':{'id':user['id'],'nickname':user['nickname']},'dataset':snapshot.manifest['dataset'] if snapshot else None,'datasetId':snapshot.dataset_id if snapshot else None,'indexId':snapshot.index_id if snapshot else None,
                'samples':len(snapshot.manifest['samples']) if snapshot else 0,'capabilities':{'reveal':user['owner'] and sys.platform in ('win32','darwin'),'paths':user['owner'],'configure':user['owner']},
                **({'exports':str(workspace.local/'exports')} if user['owner'] else {})});return
        if not user:self.js(401,{'error':'请先输入访问口令与昵称登录'});return
        if not snapshot:self.js(409,{'error':'请先在主机配置目录'});return
        if path in ('/api/batch-export/job','/api/batch-export/download'):
            if not self.guard_dataset(snapshot,query):return
            try:
                job_id=query.get('id',[''])[0]
                if path.endswith('/job'):self.js(200,self.server.batch_exports.get(snapshot,user,job_id))
                else:
                    archive=self.server.batch_exports.download(snapshot,user,job_id)
                    with archive.open('rb') as file:
                        self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Length',str(os.fstat(file.fileno()).st_size));self.send_header('Cache-Control','no-store');self.send_header('Content-Disposition','attachment; filename="'+archive.name+'"');self.security_headers();self.end_headers()
                        try:
                            while True:
                                block=file.read(1024*1024)
                                if not block:break
                                self.wfile.write(block)
                        except (OSError,ConnectionError):pass
            except PermissionError as error:self.js(403,{'error':str(error)})
            except Conflict as error:self.js(409,{'error':str(error)})
            return
        if path=='/api/admin/share':
            if not user['owner']:self.js(403,{'error':'仅限主机管理员'});return
            self.js(200,share_info(self.server,snapshot));return
        if path=='/manifest.js':
            if not self.guard_dataset(snapshot,query):return
            self.reply(200,snapshot.owner_js if user['owner'] else snapshot.public_js,'application/javascript; charset=utf-8');return
        if path=='/api/image-metadata':
            if not self.guard_dataset(snapshot,query):return
            if not self.server.image_slots.acquire(timeout=10):self.js(503,{'error':'主机忙，请稍后重试'});return
            try:
                try:
                    indexed=snapshot.image_path(int(query.get('sample',[''])[0]),int(query.get('method',[''])[0]))
                except FileNotFoundError:
                    self.js(404,{'error':'Missing · 索引图片不存在'});return
                result=image_metadata(indexed)
                if result is None:self.js(422,{'error':'无法从有限文件头识别尺寸，可尝试浏览器读取原图'});return
                self.js(200,result);return
            finally:self.server.image_slots.release()
        match=re.fullmatch(r'/image/(\d+)/(\d+)',path)
        if match:
            if not self.guard_dataset(snapshot,query):return
            if not self.server.image_slots.acquire(timeout=10):self.js(503,{'error':'主机忙，请稍后重试'});return
            try:
                try:self.serve_file(snapshot.image_path(int(match[1]),int(match[2])),True)
                except (OSError,ValueError):self.js(404,{'error':'Missing indexed image'})
            finally:self.server.image_slots.release()
            return
        if path in ('/api/workspace','/api/reviewer','/api/sample','/api/team-export'):
            if not self.guard_dataset(snapshot):return
            store=snapshot.store
            if path=='/api/workspace':self.js(200,store.workspace(user['id'],query.get('version',[None])[0]));return
            if path=='/api/reviewer':self.js(200,store.reviewer_marks(query.get('id',[''])[0]));return
            if path=='/api/sample':self.js(200,{'marks':store.sample_marks(query.get('id',[''])[0])});return
            if path=='/api/team-export':self.js(200,store.export());return
        self.js(404,{'error':'Route not allowed'})
    def do_POST(self):
        try:self._body_remaining=int(self.headers.get('Content-Length','0'))
        except ValueError:self._body_remaining=None
        if self._body_remaining is not None and not 0<=self._body_remaining<=100*1024*1024:self._body_remaining=None
        try:self.post()
        except PermissionError as error:self.js(401,{'error':str(error)})
        except Conflict as error:self.js(409,{'error':str(error)})
        except (ValueError,KeyError,TypeError,UnicodeError) as error:self.js(400,{'error':str(error)})
        except (sqlite3.Error,OSError):self.js(503,{'error':'保存失败：主机资源或数据库暂不可用，请重试'})
    def post(self):
        if not self.valid_request():return
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+self.headers.get('Host',''):
            self.js(403,{'error':'Same-origin request required'});return
        route=urlsplit(self.path).path;workspace=self.server.workspace;snapshot=workspace.snapshot()
        if route=='/api/login':
            if not snapshot:self.js(503,{'error':'主机尚未准备数据集'});return
            now=time.time();address=self.client_address[0]
            with self.server.login_lock:
                attempts=self.server.login_attempts;attempts[:]=[(ip,t) for ip,t in attempts if now-t<300]
                if sum(ip==address for ip,t in attempts)>=12 or len(attempts)>=120:self.js(429,{'error':'登录尝试过于频繁，请 5 分钟后重试'});return
                attempts.append((address,now))
            data=self.read_json(4096);info=snapshot.store.login(data.get('code'),data.get('nickname'),data.get('recovery',''))
            with self.server.login_lock:self.server.login_attempts[:]=[(ip,t) for ip,t in self.server.login_attempts if ip!=address]
            cookie=self.cookie_name(snapshot)+'='+info.pop('session')+'; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000'
            self.js(200,info,cookie=cookie);return
        user=self.actor(snapshot)
        if not user:self.js(401,{'error':'登录已过期，请保留草稿并重新登录'});return
        if self.headers.get('X-Viewer-Token')!=user['csrf']:
            self.js(403,{'error':'Session token required'});return
        if route.startswith('/api/setup/'):
            if not user['owner']:self.js(403,{'error':'目录配置仅允许在主机上操作'});return
            data=self.read_json(65536)
            if route=='/api/setup/build':
                try:self.js(202,{'jobId':workspace.start_build(data['config'])})
                except RuntimeError as error:self.js(409,{'error':str(error)})
                return
            if route=='/api/setup/pick':
                if not self.server.picker_lock.acquire(blocking=False):self.js(409,{'error':'已有目录选择窗口打开，请先完成或取消'});return
                try:
                    initial=data.get('initial','')
                    if not isinstance(initial,str) or len(initial)>4096:raise ValueError('Invalid initial directory')
                    output=workspace.local/'tmp'/('picker-'+secrets.token_hex(12)+'.json');output.parent.mkdir(parents=True,exist_ok=True)
                    options={'stdout':subprocess.PIPE,'stderr':subprocess.PIPE,'timeout':300}
                    if sys.platform=='win32':options['creationflags']=subprocess.CREATE_NO_WINDOW
                    try:
                        subprocess.run(picker_command(initial,str(output)),**options)
                        if not output.is_file():raise ValueError('系统选择器不可用，请在页面粘贴绝对路径')
                        result=json.loads(output.read_text(encoding='utf-8'))
                        output.unlink()
                        if 'error' in result:self.js(503,result)
                        else:self.js(200,result)
                    except subprocess.TimeoutExpired:self.js(408,{'error':'目录选择已超时，可重试或直接粘贴目录路径'})
                finally:self.server.picker_lock.release()
                return
            self.js(404,{'error':'Route not allowed'});return
        if route=='/api/shutdown':
            if not user['owner']:self.js(403,{'error':'仅限主机管理员'});return
            if self.server.batch_exports.active():self.js(409,{'error':'有批量导出正在运行，请先取消或等待完成后退出服务'});return
            self.read_json(4096);self.js(200,{'ok':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
        if not self.guard_dataset(snapshot):return
        store=snapshot.store
        if route.startswith('/api/batch-export/'):
            data=self.read_json(32768)
            try:
                if route=='/api/batch-export/preview':self.js(200,self.server.batch_exports.preview(snapshot,user,data))
                elif route=='/api/batch-export/start':self.js(202,self.server.batch_exports.start(snapshot,user,data))
                elif route=='/api/batch-export/cancel':self.js(200,self.server.batch_exports.cancel(snapshot,user,data.get('jobId')))
                else:self.js(404,{'error':'Route not allowed'})
            except PermissionError as error:self.js(403,{'error':str(error)})
            return
        if route=='/api/mark':self.js(200,store.write_many(user['id'],[self.read_json()]));return
        if route=='/api/marks/import':self.js(200,store.write_many(user['id'],self.read_json(24*1024*1024).get('entries')));return
        if route=='/api/logout':
            self.read_json(4096);store.logout(self.cookie_token(snapshot));self.js(200,{'ok':True},cookie=self.cookie_name(snapshot)+'=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0');return
        if not user['owner']:self.js(403,{'error':'此操作仅限主机管理员；远程用户请下载到自己的电脑'});return
        if route=='/api/admin/rotate-code':
            self.read_json(4096);store.rotate_access();self.js(200,share_info(self.server,snapshot));return
        if route=='/api/reveal':
            data=self.read_json(4096);path=snapshot.image_path(int(data['sample']),int(data['method']))
            subprocess.Popen(reveal_command(path));self.js(200,{'ok':True});return
        exports=workspace.local/'exports';exports.mkdir(exist_ok=True)
        if route=='/api/export':
            length=int(self.headers.get('Content-Length','0'))
            if not 8<length<=100*1024*1024:self.js(413,{'error':'PNG must be at most 100 MiB'});return
            signature=self.read_body(8)
            if signature!=b'\x89PNG\r\n\x1a\n':raise ValueError('PNG required')
            output=exports/('comparison-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)+'.png')
            remaining=length-8
            try:
                with output.open('xb') as file:
                    file.write(signature)
                    while remaining:
                        chunk=self.read_body(min(remaining,262144))
                        if not chunk:raise OSError('Incomplete PNG upload')
                        file.write(chunk);remaining-=len(chunk)
            except Exception:
                if output.is_file():output.unlink()
                raise
            self.js(200,{'path':str(output),'bytes':length});return
        if route in ('/api/team-backup','/api/marks-export'):
            data=self.read_json(24*1024*1024 if route=='/api/marks-export' else 4096)
            if route=='/api/team-backup':data=store.export();prefix='team-marks-'
            else:
                if data.get('datasetId')!=snapshot.dataset_id or not isinstance(data.get('marks'),dict):raise ValueError('Backup belongs to another dataset')
                prefix='marks-'
            output=exports/(prefix+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)+'.json')
            atomic_json(output,data);self.js(200,{'path':str(output)});return
        self.js(404,{'error':'Route not allowed'})


def main(argv=None):
    if sys.version_info<(3,9):raise RuntimeError('Python 3.9+ is required. Use a packaged desktop build or a newer Python.')
    parser=argparse.ArgumentParser(description=APP)
    parser.add_argument('--port',type=int,default=DEFAULT_PORT)
    parser.add_argument('--workspace',type=Path,default=project_root()/'local')
    parser.add_argument('--lan',action='store_true')
    parser.add_argument('--allow-subnet',action='append',default=None)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--demo',action='store_true')
    args=parser.parse_args(argv)
    if not 0<=args.port<=65535:parser.error('Port must be 0..65535')
    requested_networks={str(network) for network in validated_networks(args.allow_subnet)} if args.lan and args.allow_subnet is not None else None
    local=args.workspace.expanduser().resolve();local.mkdir(parents=True,exist_ok=True)
    if sys.stdout is None:
        sys.stdout=(local/'server.log').open('a',encoding='utf-8',buffering=1)
    if sys.stderr is None:sys.stderr=sys.stdout
    project=hashlib.sha256(str(local).encode('utf-8')).hexdigest()[:16]
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    existing=None
    if args.port:
        try:
            info=json.load(urlopen('http://127.0.0.1:{}/health'.format(args.port),timeout=1))
            if info.get('app')==APP and info.get('project')==project:existing=info
        except (OSError,ValueError):pass
    if existing:
        base='http://127.0.0.1:{}/'.format(args.port)
        mode_changed=bool(args.lan)!=bool(existing.get('lanEnabled'))
        scope_changed=args.lan and requested_networks is not None and requested_networks!=set(existing.get('allowedSubnets') or [])
        version_changed=existing.get('version')!=VERSION
        if mode_changed or scope_changed or version_changed:
            print('Restarting the existing workspace service to apply the requested version/network mode/scope.',flush=True)
            info=json.load(urlopen(base+'api/info',timeout=2))
            req=Request(base+'api/shutdown',b'{}',headers={'Content-Type':'application/json','X-Viewer-Token':info['token']})
            try:urlopen(req,timeout=2).close()
            except HTTPError as error:
                if error.code!=409:raise
                try:detail=json.loads(error.read().decode('utf-8')).get('error','有批量导出正在运行')
                except (ValueError,UnicodeError):detail='有批量导出正在运行'
                raise RuntimeError('旧服务未关闭：'+detail+'；请在旧页面取消或等待批次完成，再重新启动。')
            # Wait for the old listening socket to close. A fixed delay can race
            # the HTTP server's shutdown loop, especially on a busy Windows host.
            deadline=time.monotonic()+6
            while True:
                try:
                    with socket.create_connection(('127.0.0.1',args.port),timeout=.25):pass
                except OSError:break
                if time.monotonic()>=deadline:
                    raise RuntimeError('旧服务尚未释放端口，请关闭旧服务后重新启动；未复用原来的网络开放范围。')
                time.sleep(.05)
        else:
            print('Reusing '+base+'setup',flush=True)
            if not args.no_browser:webbrowser.open(base+'setup')
            return 0
    server=LocalServer(('0.0.0.0' if args.lan else '127.0.0.1',args.port),Handler)
    try:configure(server,local,args.lan,args.allow_subnet)
    except Exception:server.server_close();raise
    if args.demo and not server.workspace.snapshot():
        config=generate_demo(local/'demo');job=server.workspace.start_build(config)
        while server.workspace.job(job)['status']=='running':time.sleep(.1)
        if server.workspace.job(job)['status']=='error':raise RuntimeError(server.workspace.job(job)['error'])
    address='http://127.0.0.1:{}/setup'.format(server.server_port)
    atomic_json(local/'service.json',{'app':APP,'version':VERSION,'project':project,'pid':os.getpid(),'port':server.server_port,'lanEnabled':args.lan,'address':address})
    print(address,flush=True)
    if not args.no_browser:webbrowser.open(address)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0


if __name__=='__main__':sys.exit(main())
