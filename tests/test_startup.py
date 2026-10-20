"""Startup policy regression tests; sockets, browsers, and processes are mocked."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server


class StartupPolicyTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'local'/'test-tmp';parent.mkdir(parents=True,exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(prefix='startup-policy-',dir=str(parent))
        self.addCleanup(self.temporary.cleanup)
        self.local=Path(self.temporary.name).resolve()
        self.project=hashlib.sha256(str(self.local).encode('utf-8')).hexdigest()[:16]
        self.port=48770
        self.args=['--workspace',str(self.local),'--port',str(self.port),'--no-browser']

    def run_policy(self,existing_lan,existing_subnets,extra=(),release_sequence=None,existing_version=None):
        health={'app':server.APP,'version':existing_version or server.VERSION,'project':self.project,'lanEnabled':existing_lan,
                'allowedSubnets':existing_subnets}
        calls=[]
        def urlopen(request,timeout):
            url=request if isinstance(request,str) else request.full_url
            calls.append((url,request))
            if url.endswith('/health'):payload=health
            elif url.endswith('/api/info'):payload={'owner':True,'token':'fixture-token'}
            elif url.endswith('/api/shutdown'):payload={'ok':True}
            else:raise AssertionError('Unexpected HTTP request: '+url)
            return io.BytesIO(json.dumps(payload).encode('utf-8'))
        instance=mock.MagicMock();instance.server_port=self.port
        with mock.patch('urllib.request.urlopen',side_effect=urlopen), \
                mock.patch.object(server,'LocalServer',return_value=instance) as factory, \
                mock.patch.object(server,'configure') as configure, \
                mock.patch.object(server,'atomic_json'), \
                mock.patch.object(server.webbrowser,'open') as browser, \
                mock.patch.object(server.socket,'create_connection',side_effect=release_sequence or [OSError('closed')]) as connect, \
                mock.patch.object(server.time,'sleep') as sleep, \
                contextlib.redirect_stdout(io.StringIO()):
            result=server.main(self.args+list(extra))
        return {'result':result,'calls':calls,'factory':factory,'configure':configure,
                'browser':browser,'connect':connect,'sleep':sleep,'instance':instance}

    def assert_restart(self,result,lan):
        self.assertEqual([url.rsplit('/',1)[-1] for url,_ in result['calls']],['health','info','shutdown'])
        self.assertEqual(result['calls'][2][1].get_method(),'POST')
        self.assertEqual(result['calls'][2][1].get_header('X-viewer-token'),'fixture-token')
        result['factory'].assert_called_once_with(('0.0.0.0' if lan else '127.0.0.1',self.port),server.Handler)
        result['instance'].serve_forever.assert_called_once()
        result['browser'].assert_not_called()

    def test_lan_to_default_local_restarts_and_binds_loopback(self):
        result=self.run_policy(True,['192.168.1.0/24'])
        self.assert_restart(result,False)

    def test_older_application_version_is_restarted_without_changing_network_scope(self):
        result=self.run_policy(False,[],existing_version='2.0.0')
        self.assert_restart(result,False)

    def test_local_to_lan_restarts(self):
        result=self.run_policy(False,[],['--lan','--allow-subnet','192.168.1.0/24'])
        self.assert_restart(result,True)

    def test_explicit_narrower_subnet_restarts_instead_of_reusing_broad_scope(self):
        result=self.run_policy(True,['192.168.0.0/16'],['--lan','--allow-subnet','192.168.1.0/24'])
        self.assert_restart(result,True)
        self.assertEqual(result['configure'].call_args.args[3],['192.168.1.0/24'])

    def test_explicit_added_subnet_restarts(self):
        result=self.run_policy(True,['192.168.1.0/24'],
                               ['--lan','--allow-subnet','192.168.1.0/24','--allow-subnet','10.20.0.0/16'])
        self.assert_restart(result,True)

    def test_same_local_policy_reuses_without_shutdown(self):
        result=self.run_policy(False,[])
        self.assertEqual(result['result'],0)
        self.assertEqual(len(result['calls']),1)
        result['factory'].assert_not_called()
        result['connect'].assert_not_called()

    def test_same_subnet_set_reuses_regardless_of_order_or_duplicates(self):
        result=self.run_policy(True,['10.20.0.0/16','192.168.1.0/24'],
                               ['--lan','--allow-subnet','192.168.1.0/24','--allow-subnet','10.20.0.0/16',
                                '--allow-subnet','192.168.1.0/24'])
        self.assertEqual(result['result'],0)
        self.assertEqual(len(result['calls']),1)
        result['factory'].assert_not_called()

    def test_old_health_without_subnet_information_is_not_reused_for_explicit_scope(self):
        result=self.run_policy(True,None,['--lan','--allow-subnet','192.168.1.0/24'])
        self.assert_restart(result,True)

    def test_rebind_waits_until_old_socket_is_released(self):
        connection=mock.MagicMock()
        result=self.run_policy(True,['192.168.1.0/24'],release_sequence=[connection,connection,OSError('closed')])
        self.assert_restart(result,False)
        self.assertEqual(result['connect'].call_count,3)
        self.assertEqual(result['sleep'].call_count,2)

    def test_invalid_requested_scope_does_not_stop_existing_service(self):
        with mock.patch('urllib.request.urlopen') as urlopen, \
                mock.patch.object(server,'LocalServer') as factory:
            with self.assertRaises(ValueError):
                server.main(self.args+['--lan','--allow-subnet','0.0.0.0/0'])
        urlopen.assert_not_called();factory.assert_not_called()

    def test_macos_launcher_creates_new_app_process_so_new_arguments_are_parsed(self):
        script=(ROOT/'Start-macOS.command').read_text(encoding='utf-8')
        line=next(line.strip() for line in script.splitlines() if '/usr/bin/open' in line)
        command=shlex.split(line)
        self.assertEqual(command[:3],['exec','/usr/bin/open','-n'])
        self.assertIn('--args',command)
        self.assertIn('$@',command)


    def test_version_restart_respects_active_export_shutdown_conflict(self):
        from urllib.error import HTTPError
        health={'app':server.APP,'version':'old-version','project':self.project,'lanEnabled':False,'allowedSubnets':[]}
        responses=[io.BytesIO(json.dumps(health).encode()),io.BytesIO(b'{"owner":true,"token":"fixture"}'),
                   HTTPError('http://127.0.0.1/api/shutdown',409,'Conflict',None,io.BytesIO(json.dumps({'error':'有批量导出正在运行'}).encode()))]
        with mock.patch('urllib.request.urlopen',side_effect=responses),mock.patch.object(server,'LocalServer') as factory,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'取消或等待批次完成'):
                server.main(self.args)
        factory.assert_not_called()


if __name__=='__main__':unittest.main()
