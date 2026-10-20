"""Batch HTTP authorization on loopback only; all originals are fixtures."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import urlencode
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import server
from tests.test_server import Client,RemoteHandler
from tests import test_batch_export as fixtures


class BatchHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BatchExportTests('test_folder_requires_owner');self.fixture.setUp()
        self.addCleanup(self.fixture.temp.cleanup)
        self.local=self.fixture.local;self.instances=[]
        self.host,self.owner=self.instance(server.Handler)
        self.host.workspace.active=self.fixture.snapshot
        self.remote_host,self.guest=self.instance(RemoteHandler)
        self.remote_host.workspace=self.host.workspace
        for client in (self.owner,self.guest):client.set_context(self.fixture.snapshot)
        self.owner.token=self.host.token

    def tearDown(self):
        for instance,thread in self.instances:
            instance.shutdown();instance.server_close();thread.join(5)
        self.fixture.tearDown()

    def instance(self,handler):
        instance=server.LocalServer(('127.0.0.1',0),handler)
        with mock.patch.object(server,'local_interfaces',return_value=[]):server.configure(instance,self.local,resources=ROOT)
        thread=threading.Thread(target=instance.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        self.instances.append((instance,thread));return instance,Client(instance)

    def login(self,client,name):
        status,user=client.request('POST','/api/login',{'code':self.fixture.snapshot.store.access['code'],'nickname':name})
        self.assertEqual(status,200,user);client.token=user['csrf'];client.set_context(self.fixture.snapshot)

    def preview(self,client):
        status,data=client.request('POST','/api/batch-export/preview',self.fixture.body(),context=True)
        self.assertEqual(status,200,data);return data

    def start(self,client,form='zip',directory=None):
        data=self.fixture.body();data.update(expectedVersion=self.preview(client)['markVersion'],format=form)
        if directory:data['directory']=str(directory)
        return client.request('POST','/api/batch-export/start',data,context=True)

    def wait(self,client,job_id):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            status,job=client.request('GET','/api/batch-export/job?id='+job_id,context=True)
            self.assertEqual(status,200,job)
            if job['status']!='running':return job
            time.sleep(.01)
        self.fail('Export did not complete')

    def test_remote_zip_is_authenticated_actor_private_and_snapshot_guarded(self):
        self.assertEqual(self.guest.request('POST','/api/batch-export/preview',self.fixture.body(),context=True)[0],401)
        self.login(self.guest,'Reviewer A')
        self.assertEqual(self.start(self.guest,'folder',self.fixture.output)[0],403)
        status,created=self.start(self.guest);self.assertEqual(status,202,created)
        job=self.wait(self.guest,created['jobId']);self.assertEqual(job['status'],'done',job)
        self.assertNotIn(str(self.local),json.dumps(job))
        status,content=self.guest.request('GET',job['result']['downloadUrl']);self.assertEqual(status,200)
        with zipfile.ZipFile(io.BytesIO(content)) as reader:self.assertTrue(any(name.endswith('/report.json') for name in reader.namelist()))
        self.assertEqual(self.owner.request('GET','/api/batch-export/job?id='+created['jobId'],context=True)[0],403)
        self.assertEqual(self.owner.request('GET',job['result']['downloadUrl'])[0],403)
        self.assertEqual(self.guest.request('GET','/api/batch-export/job?id='+created['jobId'],headers={'X-Dataset-Id':'old','X-Index-Id':'old'})[0],409)

    def test_owner_folder_and_missing_output_error(self):
        status,result=self.start(self.owner,'folder',self.local/'not-existing')
        self.assertEqual(status,400,result);self.assertIn('输出目录不存在',result['error'])
        exports=self.local/'exports';exports.mkdir()
        status,result=self.start(self.owner,'folder',exports);self.assertEqual(status,202,result)
        job=self.wait(self.owner,result['jobId']);self.assertEqual(job['status'],'done',job)
        self.assertTrue(Path(job['result']['batchDirectory']).is_dir())

    def test_stale_mark_version_and_source_output_are_rejected(self):
        data=self.fixture.body();data.update(expectedVersion=-1,format='zip')
        self.assertEqual(self.owner.request('POST','/api/batch-export/start',data,context=True)[0],409)
        self.assertEqual(self.start(self.owner,'folder',Path(self.fixture.config['methods'][0]['root']))[0],400)


    def test_normal_shutdown_requires_waiting_or_cancelling_active_batch(self):
        exports=self.local/'exports';exports.mkdir()
        entered=threading.Event();release=threading.Event();real=self.host.batch_exports._copy
        def copy_file(*args):entered.set();release.wait(3);return real(*args)
        with mock.patch.object(self.host.batch_exports,'_copy',side_effect=copy_file):
            status,created=self.start(self.owner,'folder',exports);self.assertEqual(status,202,created)
            self.assertTrue(entered.wait(2))
            status,error=self.owner.request('POST','/api/shutdown',{})
            self.assertEqual(status,409,error);self.assertIn('批量导出',error['error'])
            self.assertEqual(self.owner.request('POST','/api/batch-export/cancel',{'jobId':created['jobId']},context=True)[0],200)
            release.set();self.assertEqual(self.wait(self.owner,created['jobId'])['status'],'cancelled')


if __name__=='__main__':unittest.main()
