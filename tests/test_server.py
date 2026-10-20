"""Portable localhost integration tests. Only generated fixtures are indexed."""
import copy
import hashlib
import http.client
import json
import select
import socket
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server
from demo_data import generate_demo
from workspace_state import Workspace


class RemoteHandler(server.Handler):
    """Exercise remote permissions without binding to a LAN interface."""
    def owner(self):
        return False


class Client:
    def __init__(self, instance):
        self.server = instance
        self.cookie = ''
        self.token = ''
        self.dataset = None
        self.index = None

    def request(self, method, route, body=None, context=False, headers=None):
        request_headers = {}
        if self.cookie:
            request_headers['Cookie'] = self.cookie
        if self.token:
            request_headers['X-Viewer-Token'] = self.token
        if context:
            request_headers.update({'X-Dataset-Id': self.dataset or '', 'X-Index-Id': self.index or ''})
        if body is not None:
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            request_headers['Content-Type'] = 'application/json'
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            connection.request(method, route, body=body, headers=request_headers)
            response = connection.getresponse()
            content = response.read()
            cookie = response.getheader('Set-Cookie')
            if cookie:
                self.cookie = cookie.split(';', 1)[0]
            try:
                payload = json.loads(content.decode('utf-8'))
            except (UnicodeError, ValueError):
                payload = content
            return response.status, payload
        finally:
            connection.close()

    def set_context(self, snapshot):
        self.dataset, self.index = snapshot.dataset_id, snapshot.index_id


class ServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        private = ROOT / 'local' / 'test-tmp'
        private.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='server-integration-', dir=str(private))
        cls.folder = Path(cls.temporary.name)
        cls.demo = generate_demo(cls.folder / 'source 图片', count=2)
        cls.original_hashes = {str(file): hashlib.sha256(file.read_bytes()).hexdigest()
                               for method in cls.demo['methods'] for file in Path(method['root']).glob('*.png')}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.local = self.folder / self._testMethodName
        self.instances = []
        self.owner_server = self.instance(server.Handler)
        self.owner = Client(self.owner_server)
        self.owner.token = self.owner_server.token
        self.config = copy.deepcopy(self.demo)
        self.config['methods'] = self.config['methods'][:2]

    def tearDown(self):
        for instance, thread in reversed(self.instances):
            instance.shutdown()
            instance.server_close()
            thread.join(5)

    def instance(self, handler):
        instance = server.LocalServer(('127.0.0.1', 0), handler)
        with mock.patch.object(server, 'local_interfaces', return_value=[]):
            server.configure(instance, self.local, resources=ROOT)
        thread = threading.Thread(target=instance.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        self.instances.append((instance, thread))
        return instance

    def remote(self):
        instance = self.instance(RemoteHandler)
        instance.workspace = self.owner_server.workspace
        client = Client(instance)
        if instance.workspace.snapshot():
            client.set_context(instance.workspace.snapshot())
        return client

    def build(self, config=None):
        status, job = self.owner.request('POST', '/api/setup/build', {'config': config or self.config})
        self.assertEqual(status, 202, job)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status, result = self.owner.request('GET', '/api/setup/job?id=' + job['jobId'])
            self.assertEqual(status, 200)
            if result['status'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(result['status'], 'done', result)
        self.owner.set_context(self.owner_server.workspace.snapshot())
        return result

    def login(self, client, nickname, recovery=''):
        code = self.owner_server.workspace.snapshot().store.access['code']
        status, result = client.request('POST', '/api/login', {'code': code, 'nickname': nickname, 'recovery': recovery})
        self.assertEqual(status, 200, result)
        client.token = result['csrf']
        client.set_context(self.owner_server.workspace.snapshot())
        return result

    def image_route(self, client, sample=0, method=0):
        return '/image/{}/{}?{}'.format(sample, method, urlencode({'dataset': client.dataset, 'index': client.index}))

    def test_initial_setup_and_owner_navigation(self):
        status, result = self.owner.request('GET', '/api/setup')
        self.assertEqual(status, 200)
        self.assertTrue(result['owner'])
        self.assertFalse(result['ready'])
        self.assertEqual(result['token'], self.owner.token)
        self.assertEqual(self.owner.request('GET', '/')[0], 303)
        self.assertEqual(self.owner.request('GET', '/viewer')[0], 303)

    def test_fragmented_rejected_post_preserves_json_error(self):
        self.build()
        snapshot=self.owner_server.workspace.snapshot()
        payload=json.dumps({'sample':snapshot.manifest['samples'][0]['id'],
                            'revision':0,'patch':{'favorite':True}}).encode('utf-8')
        for token,dataset,index,expected in [
            (self.owner.token,'stale-dataset','stale-index',409),
            ('incorrect-token',snapshot.dataset_id,snapshot.index_id,403),
        ]:
            with self.subTest(status=expected):
                connection=socket.create_connection(('127.0.0.1',self.owner_server.server_port),timeout=3)
                try:
                    headers=('POST /api/mark HTTP/1.1\r\nHost: 127.0.0.1:{}\r\n'
                             'X-Viewer-Token: {}\r\nX-Dataset-Id: {}\r\nX-Index-Id: {}\r\n'
                             'Content-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n').format(
                                 self.owner_server.server_port,token,dataset,index,len(payload))
                    connection.sendall(headers.encode('ascii')+payload[:1])
                    # A fragmented upload must be consumed before an error closes
                    # the socket; unread TCP data can discard that error on Windows.
                    readable,_,_=select.select([connection],[],[],.15)
                    self.assertFalse(readable,'Server replied/closed while the small JSON body was still pending')
                    connection.sendall(payload[1:])
                    response=http.client.HTTPResponse(connection);response.begin()
                    self.assertEqual(response.status,expected)
                    self.assertIn('error',json.loads(response.read().decode('utf-8')))
                finally:connection.close()
        self.assertFalse(snapshot.store.workspace('owner')['marks'])

    def test_large_rejected_upload_is_not_drained(self):
        self.build()
        connection=socket.create_connection(('127.0.0.1',self.owner_server.server_port),timeout=3)
        try:
            headers=('POST /api/export HTTP/1.1\r\nHost: 127.0.0.1:{}\r\n'
                     'X-Viewer-Token: incorrect-token\r\nContent-Type: image/png\r\n'
                     'Content-Length: 104857600\r\nConnection: close\r\n\r\n').format(self.owner_server.server_port)
            connection.sendall(headers.encode('ascii'))
            response=http.client.HTTPResponse(connection);response.begin()
            self.assertEqual(response.status,403)
            self.assertIn('error',json.loads(response.read().decode('utf-8')))
        finally:connection.close()
        self.assertFalse((self.local/'exports').exists())

    def test_stalled_post_drain_is_bounded(self):
        self.build()
        connection=socket.create_connection(('127.0.0.1',self.owner_server.server_port),timeout=5)
        try:
            headers=('POST /api/mark HTTP/1.1\r\nHost: 127.0.0.1:{}\r\n'
                     'X-Viewer-Token: incorrect-token\r\nContent-Type: application/json\r\n'
                     'Content-Length: 64\r\nConnection: close\r\n\r\n').format(self.owner_server.server_port)
            connection.sendall(headers.encode('ascii')+b'{')
            response=http.client.HTTPResponse(connection);response.begin()
            self.assertEqual(response.status,403)
            self.assertIn('error',json.loads(response.read().decode('utf-8')))
        finally:connection.close()
        self.assertEqual(self.owner.request('GET','/health')[0],200)

    def test_remote_cannot_read_setup_or_select_paths(self):
        self.build()
        remote = self.remote()
        for path in ('/setup', '/api/setup', '/api/setup/audit', '/api/setup/demo'):
            self.assertEqual(remote.request('GET', path)[0], 403)
        self.login(remote, 'Reviewer A')
        self.assertEqual(remote.request('POST', '/api/setup/pick', {'initial': '/'})[0], 403)
        self.assertEqual(remote.request('POST', '/api/setup/build', {'config': self.config})[0], 403)

    def test_async_index_build_supports_two_then_three_methods(self):
        result = self.build()
        self.assertEqual(result['audit']['samples'], 2)
        self.assertEqual(len(result['audit']['methods']), 2)
        self.config['methods'].append(copy.deepcopy(self.demo['methods'][2]))
        result = self.build()
        self.assertEqual(len(result['audit']['methods']), 3)
        self.assertTrue(all(method['matched'] == 2 for method in result['audit']['methods']))
        self.assertEqual(self.owner.request('GET', '/api/setup/audit')[1]['samples'], 2)

    def test_concurrent_build_reports_busy_without_breaking_connection(self):
        entered, release = threading.Event(), threading.Event()
        import workspace_state
        original = workspace_state.build_index.build
        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Test indexing release timed out')
            return original(*args, **kwargs)
        with mock.patch.object(workspace_state.build_index, 'build', side_effect=delayed):
            first_status, first = self.owner.request('POST', '/api/setup/build', {'config': self.config})
            self.assertEqual(first_status, 202)
            self.assertTrue(entered.wait(5))
            try:
                status, result = self.owner.request('POST', '/api/setup/build', {'config': self.config})
                self.assertEqual(status, 409, result)
                self.assertIn('error', result)
                self.assertEqual(self.owner.request('GET', '/health')[0], 200)
            finally:
                release.set()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = self.owner.request('GET', '/api/setup/job?id=' + first['jobId'])[1]
                if result['status'] != 'running':
                    break
                time.sleep(.01)
            self.assertEqual(result['status'], 'done', result)

    def test_original_image_bytes_and_source_hashes_are_unchanged(self):
        self.build()
        snapshot = self.owner_server.workspace.snapshot()
        for si in range(2):
            for mi in range(2):
                status, body = self.owner.request('GET', self.image_route(self.owner, si, mi))
                self.assertEqual(status, 200)
                self.assertEqual(body, snapshot.image_path(si, mi).read_bytes())
        for name, digest in self.original_hashes.items():
            self.assertEqual(hashlib.sha256(Path(name).read_bytes()).hexdigest(), digest)

    def test_image_and_workspace_require_matching_context(self):
        self.build()
        self.assertEqual(self.owner.request('GET', '/image/0/0')[0], 409)
        self.assertEqual(self.owner.request('GET', '/image/0/0?dataset=wrong&index=' + self.owner.index)[0], 409)
        self.assertEqual(self.owner.request('GET', '/image/0/0?dataset=' + self.owner.dataset + '&index=wrong')[0], 409)
        self.assertEqual(self.owner.request('GET', '/api/workspace')[0], 409)
        self.assertEqual(self.owner.request('GET', '/api/workspace', context=True)[0], 200)

    def test_export_metadata_is_bounded_indexed_and_snapshot_guarded(self):
        self.build()
        route='/api/image-metadata?sample=0&method=0'
        self.assertEqual(self.owner.request('GET',route)[0],409)
        status, metadata=self.owner.request('GET',route,context=True)
        self.assertEqual(status,200,metadata)
        self.assertEqual((metadata['width'],metadata['height']),(320,320))
        self.assertNotIn('path',metadata)
        self.assertEqual(self.owner.request('GET','/api/image-metadata?sample=999999&method=0',context=True)[0],400)
        remote=self.remote()
        self.assertEqual(remote.request('GET',route,context=True)[0],401)
        self.login(remote,'Metadata reviewer')
        self.assertEqual(remote.request('GET',route,context=True)[0],200)
        with mock.patch.object(server,'image_metadata',return_value=None):
            self.assertEqual(self.owner.request('GET',route,context=True)[0],422)

    def test_missing_prediction_is_indexed_as_missing(self):
        partial = self.local / 'partial prediction'
        partial.mkdir(parents=True)
        shutil.copyfile(Path(self.config['methods'][1]['root']) / 'scene-0001.png', partial / 'scene-0001.png')
        self.config['methods'][1]['root'] = str(partial)
        result = self.build()
        self.assertEqual(result['audit']['methods'][1]['missing'], 1)
        self.assertIsNone(self.owner_server.workspace.snapshot().manifest['samples'][1]['images'][1])
        self.assertEqual(self.owner.request('GET', self.image_route(self.owner, 1, 1))[0], 404)

    def test_http_routes_do_not_expose_arbitrary_files(self):
        self.build()
        for path in ('/server.py', '/local/config.json', '/../../server.py', '/%2e%2e/server.py', '/api/file?path=C:/Windows/win.ini', '/image/999999/0?dataset=' + self.owner.dataset + '&index=' + self.owner.index):
            self.assertEqual(self.owner.request('GET', path)[0], 404, path)
        status, result = self.owner.request('GET', self.image_route(self.owner) + '&path=../../server.py')
        self.assertEqual(status, 200)
        self.assertTrue(result.startswith(b'\x89PNG'))

    def test_snapshot_rejects_record_escaping_its_method_root(self):
        self.build()
        snapshot = self.owner_server.workspace.snapshot()
        image = snapshot.manifest['samples'][0]['images'][0]
        original = image['relative']
        try:
            image['relative'] = '../outside.png'
            with self.assertRaises((ValueError, OSError)):
                snapshot.image_path(0, 0)
        finally:
            image['relative'] = original

    def test_remote_requires_login_and_manifest_redacts_roots(self):
        self.build()
        remote = self.remote()
        self.assertEqual(remote.request('GET', '/api/info')[0], 401)
        self.assertEqual(remote.request('GET', self.image_route(remote))[0], 401)
        self.login(remote, 'Reviewer A')
        query = '?' + urlencode({'dataset': remote.dataset, 'index': remote.index})
        status, body = remote.request('GET', '/manifest.js' + query)
        self.assertEqual(status, 200)
        manifest = json.loads(body.decode('utf-8').split('=', 1)[1].strip().rstrip(';'))
        self.assertTrue(all('root' not in method for method in manifest['methods']))
        status, owner_body = self.owner.request('GET', '/manifest.js' + query)
        self.assertEqual(status, 200)
        self.assertIn(b'"root":', owner_body)
        info = remote.request('GET', '/api/info')[1]
        self.assertFalse(info['capabilities']['paths'])
        self.assertNotIn('exports', info)

    def test_multiple_reviewers_mark_same_sample_independently(self):
        self.build()
        one, two = self.remote(), self.remote()
        identity_one, identity_two = self.login(one, 'Reviewer A'), self.login(two, 'Reviewer B')
        sample = self.owner_server.workspace.snapshot().manifest['samples'][0]['id']
        for client, note in ((one, 'small objects'), (two, 'dense objects')):
            status, result = client.request('POST', '/api/mark', {'sample': sample, 'revision': 0, 'patch': {'favorite': True, 'note': note}}, context=True)
            self.assertEqual(status, 200, result)
        self.assertEqual(one.request('GET', '/api/workspace', context=True)[1]['marks'][sample]['note'], 'small objects')
        self.assertEqual(two.request('GET', '/api/workspace', context=True)[1]['marks'][sample]['note'], 'dense objects')
        aggregate = self.owner.request('GET', '/api/workspace', context=True)[1]['aggregates'][sample]
        self.assertEqual(aggregate['favorites'], 2)
        self.assertNotEqual(identity_one['id'], identity_two['id'])

    def test_existing_nickname_requires_correct_recovery_code(self):
        self.build()
        original = self.remote()
        identity = self.login(original, 'Reviewer A')
        visitor = self.remote()
        code = self.owner_server.workspace.snapshot().store.access['code']
        for recovery in ('', 'incorrect-recovery'):
            status, _ = visitor.request('POST', '/api/login', {'code': code, 'nickname': 'Reviewer A', 'recovery': recovery})
            self.assertEqual(status, 409)
        restored = self.login(visitor, 'Reviewer A', identity['recovery'])
        self.assertEqual(identity['id'], restored['id'])
        self.assertIsNone(restored['recovery'])

    def test_session_csrf_and_same_origin_are_enforced(self):
        self.build()
        remote = self.remote()
        self.login(remote, 'Reviewer A')
        sample = self.owner_server.workspace.snapshot().manifest['samples'][0]['id']
        body = {'sample': sample, 'revision': 0, 'patch': {'favorite': True}}
        self.assertEqual(remote.request('POST', '/api/mark', body, context=True, headers={'X-Viewer-Token': 'incorrect'})[0], 403)
        self.assertEqual(remote.request('POST', '/api/mark', body, context=True, headers={'Origin': 'http://untrusted.invalid'})[0], 403)
        self.assertEqual(remote.request('POST', '/api/mark', body, context=True)[0], 200)

    def test_remote_cannot_invoke_host_administration(self):
        self.build()
        remote = self.remote()
        self.login(remote, 'Reviewer A')
        self.assertEqual(remote.request('GET', '/api/admin/share')[0], 403)
        for route in ('/api/reveal', '/api/export', '/api/team-backup', '/api/shutdown', '/api/admin/rotate-code'):
            self.assertEqual(remote.request('POST', route, {}, context=True)[0], 403, route)

    def test_baseline_change_creates_new_dataset_and_rejects_old_tab(self):
        self.build()
        old_dataset, old_index = self.owner.dataset, self.owner.index
        old_snapshot = self.owner_server.workspace.snapshot()
        sample = old_snapshot.manifest['samples'][0]['id']
        self.assertEqual(self.owner.request('POST', '/api/mark', {'sample': sample, 'revision': 0, 'patch': {'favorite': True}}, context=True)[0], 200)
        self.config['methods'][0]['root'] = self.demo['methods'][3]['root']
        self.build()
        self.assertNotEqual(self.owner.dataset, old_dataset)
        self.assertEqual(self.owner.request('POST', '/api/mark', {'sample': sample, 'revision': 1, 'patch': {'favorite': False}}, headers={'X-Dataset-Id': old_dataset, 'X-Index-Id': old_index})[0], 409)
        self.assertEqual(self.owner.request('GET', '/api/workspace', context=True)[1]['marks'], {})
        self.assertTrue(old_snapshot.store.workspace('owner')['marks'][sample]['favorite'])

    def test_display_name_change_preserves_ids_directories_and_sources(self):
        self.build()
        before = copy.deepcopy(self.owner_server.workspace.config)
        self.config['methods'][1]['name'] = 'My model / 自定义名称'
        self.build()
        after = self.owner_server.workspace.config
        self.assertEqual(before['datasetId'], after['datasetId'])
        self.assertEqual(before['methods'][1]['id'], after['methods'][1]['id'])
        self.assertEqual(before['methods'][1]['root'], after['methods'][1]['root'])
        self.assertEqual(after['methods'][1]['name'], 'My model / 自定义名称')
        for name, digest in self.original_hashes.items():
            self.assertEqual(hashlib.sha256(Path(name).read_bytes()).hexdigest(), digest)

    def test_reopening_workspace_restores_config_index_and_marks(self):
        self.build()
        sample = self.owner_server.workspace.snapshot().manifest['samples'][0]['id']
        self.assertEqual(self.owner.request('POST', '/api/mark', {'sample': sample, 'revision': 0, 'patch': {'favorite': True, 'reviewed': True, 'tags': ['small']}}, context=True)[0], 200)
        reopened = Workspace(self.local)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.snapshot().dataset_id, self.owner.dataset)
        self.assertEqual(reopened.snapshot().index_id, self.owner.index)
        self.assertTrue(reopened.snapshot().store.workspace('owner')['marks'][sample]['reviewed'])

    def test_failed_build_keeps_previous_usable_index(self):
        self.build()
        before = self.owner_server.workspace.snapshot()
        empty = self.local / 'empty-source'
        empty.mkdir()
        bad = copy.deepcopy(self.config)
        bad['methods'][0]['root'] = str(empty)
        status, result = self.owner.request('POST', '/api/setup/build', {'config': bad})
        self.assertEqual(status, 202)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.owner.request('GET', '/api/setup/job?id=' + result['jobId'])[1]
            if result['status'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(result['status'], 'error')
        self.assertIs(self.owner_server.workspace.snapshot(), before)
        self.assertEqual(self.owner.request('GET', self.image_route(self.owner))[0], 200)

    def test_native_picker_uses_separate_process_and_private_result_file(self):
        selected = self.config['methods'][0]['root']
        def run(command, **options):
            self.assertIn('--picker-output', command)
            output = Path(command[command.index('--picker-output') + 1])
            self.assertEqual(output.parent, self.local / 'tmp')
            self.assertNotIn('shell', options)
            output.write_text(json.dumps({'path': selected, 'cancelled': False}), encoding='utf-8')
            return mock.Mock(returncode=0)
        with mock.patch.object(server.subprocess, 'run', side_effect=run):
            status, result = self.owner.request('POST', '/api/setup/pick', {'initial': selected})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['path'], selected)
        self.assertFalse(list((self.local / 'tmp').glob('picker-*.json')))

    def test_logout_invalidates_remote_session(self):
        self.build()
        remote = self.remote()
        self.login(remote, 'Reviewer A')
        self.assertEqual(remote.request('POST', '/api/logout', {}, context=True)[0], 200)
        self.assertEqual(remote.request('GET', '/api/info')[0], 401)

    def test_host_allowlist_and_local_only_share_status(self):
        self.build()
        self.assertEqual(self.owner.request('GET', '/health', headers={'Host': 'evil.invalid'})[0], 403)
        status, info = self.owner.request('GET', '/api/admin/share')
        self.assertEqual(status, 200)
        self.assertFalse(info['enabled'])
        self.assertEqual(info['addresses'], [])
        self.assertEqual(info['scope'], 'local-only')


if __name__ == '__main__':
    unittest.main(verbosity=2)
