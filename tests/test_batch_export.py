"""Original-byte export tests. Generated tiny fixtures only; never research data."""
import copy
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from batch_export import Manager,output_parent,safe_name,unique_names
from build_index import build
from collaboration import Conflict
from workspace_state import Snapshot


class BatchExportTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'local'/'test-tmp';parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='b-',dir=str(parent));self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.local=self.root/'w';self.output=self.root/'out';self.output.mkdir()
        self.owner={'id':'owner','owner':True};self.guest={'id':'reviewer-a','owner':False}
        self.config={'schema':2,'dataset':'Fixture','datasetId':str(uuid.uuid4()),'referenceId':'a',
                     'methods':[{'id':'a','name':'Input','root':str(self.root/'a')},{'id':'b','name':'Model B','root':str(self.root/'b')}]}
        for method in self.config['methods']:Path(method['root']).mkdir()
        self.populate(5)
        self.manager=Manager(self.local,resources=self.root/'app')
        self.snapshot=self.rebuild()

    def tearDown(self):
        deadline=time.monotonic()+5
        while Manager._active and time.monotonic()<deadline:time.sleep(.01)

    def populate(self,count):
        for i in range(count):
            for mi,method in enumerate(self.config['methods']):
                # Pixel decoding is irrelevant to a byte-for-byte export.
                (Path(method['root'])/('sample-{:04d}.png'.format(i))).write_bytes(b'original-byte-fixture-'+str((i,mi)).encode())

    def rebuild(self):
        manifest,audit=build(self.config,self.local/'index')
        return Snapshot(manifest,audit,self.local/'index',self.local)

    def body(self,mode='all',minimum=2):return {'filter':{'mode':mode,'minFavorites':minimum,'query':''},'methods':[0,1]}

    def start(self,body=None,user=None,form='folder'):
        body=copy.deepcopy(body or self.body());user=user or self.owner
        body.update(expectedVersion=self.manager.preview(self.snapshot,user,body)['markVersion'],format=form)
        if form=='folder':body['directory']=str(self.output)
        return self.manager.start(self.snapshot,user,body)['jobId']

    def wait(self,job,user=None):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            result=self.manager.get(self.snapshot,user or self.owner,job)
            if result['status']!='running':return result
            time.sleep(.01)
        self.fail('Batch worker did not finish')

    def marks(self,rid,indices,**patch):
        entries=[{'sample':self.snapshot.manifest['samples'][i]['id'],'revision':0,'patch':patch} for i in indices]
        self.snapshot.store.write_many(rid,entries)

    def test_team_consensus_threshold_counts_distinct_people(self):
        self.marks('owner',range(5),favorite=True)
        self.marks('person-b',range(3),favorite=True)
        self.marks('person-c',range(2),favorite=True)
        self.assertEqual(self.manager.preview(self.snapshot,self.owner,self.body('consensus',3))['count'],2)
        self.assertEqual(self.manager.preview(self.snapshot,self.guest,self.body('favorites'))['count'],5)
        self.assertEqual(self.manager.preview(self.snapshot,self.owner,self.body('consensus',4))['count'],0)
        self.snapshot.store.write_many('person-c',[{'sample':self.snapshot.manifest['samples'][0]['id'],'revision':1,'patch':{'note':'Same person again'}}])
        self.assertEqual(self.manager.preview(self.snapshot,self.owner,self.body('consensus',4))['count'],0)

    def test_team_notes_unreviewed_and_name_query(self):
        self.marks('other-person',[1],tags=['occlusion'])
        self.marks('other-person',[2],reviewed=True)
        self.assertEqual(self.manager.preview(self.snapshot,self.owner,self.body('notes'))['count'],1)
        self.assertEqual(self.manager.preview(self.snapshot,self.owner,self.body('unreviewed'))['count'],4)
        body=self.body();body['filter']['query']=' SAMPLE-0002 '
        self.assertEqual(self.manager.preview(self.snapshot,self.owner,body)['count'],1)

    def test_all_matching_rows_exceed_two_hundred(self):
        self.populate(310);self.snapshot=self.rebuild()
        preview=self.manager.preview(self.snapshot,self.owner,self.body())
        self.assertEqual(preview['count'],310);self.assertEqual(preview['files'],620)
        self.assertEqual(len(preview['sampleIds']),310)

    def test_stale_mark_preview_is_rejected(self):
        body=self.body();body.update(expectedVersion=0,format='folder',directory=str(self.output))
        self.marks('owner',[0],favorite=True)
        with self.assertRaises(Conflict):self.manager.start(self.snapshot,self.owner,body)

    def test_folder_bytes_csv_and_mapping_are_exact(self):
        job=self.wait(self.start());self.assertEqual(job['status'],'done',job)
        result=job['result'];directory=Path(result['batchDirectory'])
        self.assertTrue(directory.name.startswith('Comparison-'))
        report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
        for entry in report['entries']:
            source=Path(self.config['methods'][0 if entry['methodId']=='a' else 1]['root'])/entry['sample']
            self.assertEqual((directory/entry['relative']).read_bytes(),source.read_bytes())
            self.assertEqual(entry['status'],'copied')
        csv_bytes=(directory/'MulimgViewer.csv').read_bytes();self.assertFalse(csv_bytes.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.reader(io.StringIO(csv_bytes.decode('utf-8'))))
        self.assertEqual(len(rows),5);self.assertTrue(all(len(row)==2 for row in rows))
        self.assertTrue(all(Path(value).is_file() for row in rows for value in row))
        self.assertNotIn(self.config['methods'][0]['root'],(directory/'report.json').read_text(encoding='utf-8'))
        self.assertFalse(result['partial'])

    def test_mixed_extensions_are_preserved_and_explicitly_mapped(self):
        original=Path(self.config['methods'][1]['root'])/'sample-0000.png'
        original.rename(original.with_suffix('.jpg'));self.snapshot=self.rebuild()
        result=self.wait(self.start())['result'];row=result['mulimgRows'][0]
        self.assertTrue(row[0].endswith('.png'));self.assertTrue(row[1].endswith('.jpg'))
        self.assertEqual(Path(row[0]).stem,Path(row[1]).stem)

    def test_missing_is_reported_without_replacement(self):
        (Path(self.config['methods'][1]['root'])/'sample-0001.png').unlink();self.snapshot=self.rebuild()
        preview=self.manager.preview(self.snapshot,self.owner,self.body());self.assertEqual(preview['missing'],1)
        result=self.wait(self.start())['result']
        self.assertTrue(result['partial']);self.assertEqual(result['files'],9)
        self.assertEqual(result['mulimgCompleteRows'],4);self.assertEqual(result['mulimgExcludedRows'],1)

    def test_safe_names_reserved_illegal_and_case_unicode_collisions(self):
        names=unique_names([('1','A/B'),('2','A:B'),('3','CON'),('4','café'),('5','cafe\u0301')])
        self.assertEqual(len({value.casefold() for value in names}),5)
        self.assertTrue(all('/' not in value and ':' not in value for value in names))
        self.assertEqual(names[2],'_CON');self.assertTrue(all(not value.endswith((' ','.')) for value in names))

    def test_output_source_workspace_and_static_directories_are_rejected(self):
        for path in [Path(self.config['methods'][0]['root']),self.local,self.local/'index',self.root/'app']:
            path.mkdir(parents=True,exist_ok=True)
            with self.subTest(path=path),self.assertRaises(ValueError):output_parent(str(path),self.snapshot,self.local,self.root/'app')
        exports=self.local/'exports';exports.mkdir()
        self.assertEqual(output_parent(str(exports),self.snapshot,self.local,self.root/'app'),exports)

    def test_folder_requires_owner(self):
        with self.assertRaises(PermissionError):self.start(user=self.guest)

    def test_zip_is_private_and_original_bytes_survive(self):
        job_id=self.start(user=self.guest,form='zip');job=self.wait(job_id,self.guest)
        self.assertEqual(job['status'],'done',job);result=job['result']
        self.assertNotIn('batchDirectory',result)
        self.assertNotIn(str(self.local),json.dumps(result))
        archive=self.manager.download(self.snapshot,self.guest,job_id)
        with zipfile.ZipFile(archive) as reader:
            entry=result['batchName']+'/'+result['mulimgRows'][0][0]
            self.assertEqual(reader.read(entry),(Path(self.config['methods'][0]['root'])/'sample-0000.png').read_bytes())
            report=reader.read(result['batchName']+'/report.json').decode('utf-8')
            self.assertNotIn(str(self.root),report)
        with self.assertRaises(PermissionError):self.manager.download(self.snapshot,self.owner,job_id)
        with self.assertRaises(PermissionError):self.manager.get(self.snapshot,{'id':'someone-else','owner':False},job_id)

    def test_old_index_job_is_rejected(self):
        job_id=self.start();self.wait(job_id)
        changed=copy.copy(self.snapshot);changed.index_id='other-index'
        with self.assertRaises(Conflict):self.manager.get(changed,self.owner,job_id)

    def test_completed_job_metadata_is_recoverable(self):
        job_id=self.start(form='zip');self.wait(job_id)
        with Manager._guard:Manager._registries.pop(str(self.local))
        recovered=Manager(self.local,resources=self.root/'app')
        self.assertEqual(recovered.get(self.snapshot,self.owner,job_id)['status'],'done')
        self.assertTrue(recovered.download(self.snapshot,self.owner,job_id).is_file())

    def test_interrupted_job_recovers_as_error_without_touching_output(self):
        job_id=self.start();self.wait(job_id)
        stored=self.local/'batch-exports'/job_id/'job.json'
        data=json.loads(stored.read_text(encoding='utf-8'));data['status']='running';stored.write_text(json.dumps(data),encoding='utf-8')
        directory=Path(data['destination']);before=(directory/'report.json').read_bytes()
        with Manager._guard:Manager._registries.pop(str(self.local))
        recovered=Manager(self.local,resources=self.root/'app')
        job=recovered.get(self.snapshot,self.owner,job_id)
        self.assertEqual(job['status'],'error');self.assertTrue(job['interrupted']);self.assertTrue(job['result']['partial'])
        self.assertEqual((directory/'report.json').read_bytes(),before)
        self.assertFalse(recovered.active())

    def test_unavailable_source_becomes_partial_not_false_success(self):
        (Path(self.config['methods'][1]['root'])/'sample-0000.png').unlink()
        result=self.wait(self.start())['result']
        self.assertTrue(result['partial']);self.assertEqual(result['failed'],1);self.assertEqual(result['files'],9)

    def test_source_size_change_cannot_bypass_the_preview_byte_budget(self):
        source=Path(self.config['methods'][0]['root'])/'sample-0000.png'
        old_size=source.stat().st_size;source.write_bytes(b'x'*(old_size+20000))
        result=self.wait(self.start(form='zip'))['result']
        self.assertTrue(result['partial']);self.assertEqual(result['failed'],1);self.assertEqual(result['files'],9)
        self.assertEqual(result['mulimgCompleteRows'],4)

    def test_source_growth_is_rejected_before_writing_beyond_budget(self):
        source=Path(self.config['methods'][0]['root'])/'sample-0000.png'
        real=os.fdopen;changed=[]
        class Reader:
            def __init__(self,wrapped):self.wrapped=wrapped
            def __enter__(self):return self
            def __exit__(self,*args):self.wrapped.close()
            def fileno(self):return self.wrapped.fileno()
            def read(self,count):
                if not changed:
                    with source.open('ab') as append:append.write(b'growth'*1000)
                    changed.append(True)
                return self.wrapped.read(count)
        with mock.patch('batch_export.os.fdopen',side_effect=lambda *args:Reader(real(*args))):
            result=self.wait(self.start())['result']
        self.assertTrue(result['partial']);self.assertGreaterEqual(result['failed'],1)
        self.assertFalse((Path(result['batchDirectory'])/'Input'/'sample-0000.png').exists())

    def test_cancel_retains_completed_copies_and_releases_global_slot(self):
        started=threading.Event();release=threading.Event();real=self.manager._copy
        def slow(*args):started.set();release.wait(3);return real(*args)
        with mock.patch.object(self.manager,'_copy',side_effect=slow):
            job_id=self.start();self.assertTrue(started.wait(2))
            with self.assertRaises(Conflict):self.start()
            self.manager.cancel(self.snapshot,self.owner,job_id);release.set();job=self.wait(job_id)
        self.assertEqual(job['status'],'cancelled');self.assertTrue(job['result']['partial'])
        self.assertIsNone(Manager._active)
        self.assertTrue((Path(job['result']['batchDirectory'])/'report.json').is_file())

    def test_disk_space_failure_does_not_create_a_batch(self):
        with mock.patch('batch_export.shutil.disk_usage',return_value=type('Usage',(),{'free':0})()):
            with self.assertRaises(ValueError):self.start()
        self.assertFalse(list(self.output.iterdir()))

    def test_missing_output_directory_has_actionable_validation(self):
        with self.assertRaisesRegex(ValueError,'输出目录不存在'):
            output_parent(str(self.root/'absent'),self.snapshot,self.local,self.root/'app')

    def test_method_names_cannot_collide_with_report_files(self):
        self.config['methods'][0]['name']='paths.txt';self.config['methods'][1]['name']='_paths.txt';self.snapshot=self.rebuild()
        job=self.wait(self.start());self.assertEqual(job['status'],'done',job)
        self.assertEqual(len({m['folder'].casefold() for m in job['result']['methodFolders']}),2)
        self.assertTrue((Path(job['result']['batchDirectory'])/'paths.txt').is_file())

    def test_global_slot_is_released_after_worker_metadata_io_error(self):
        real=self.manager._save;calls=[]
        def save(job):
            calls.append(job['status'])
            if job['status']!='running':raise OSError('Injected metadata disk failure')
            return real(job)
        # Suppress only the expected worker-thread error report, not test failures.
        with mock.patch.object(self.manager,'_save',side_effect=save),mock.patch('threading.excepthook'):
            job=self.wait(self.start())
            deadline=time.monotonic()+2
            while Manager._active and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNone(Manager._active)

    def test_cancel_mid_zip_chunk_never_serves_truncated_image_archive(self):
        entered=threading.Event();release=threading.Event();real=zipfile._ZipWriteFile.write
        def write(writer,data):
            result=real(writer,data)
            if not entered.is_set():entered.set();release.wait(3)
            return result
        with mock.patch.object(zipfile._ZipWriteFile,'write',write):
            job_id=self.start(user=self.guest,form='zip');self.assertTrue(entered.wait(3))
            self.manager.cancel(self.snapshot,self.guest,job_id);release.set();job=self.wait(job_id,self.guest)
        self.assertEqual(job['status'],'cancelled',job)
        self.assertNotIn('downloadUrl',job['result']);self.assertFalse(job['result']['archiveReady'])
        with self.assertRaises(Conflict):self.manager.download(self.snapshot,self.guest,job_id)
        report=self.local/'batch-exports'/job_id/'files'/'report.json'
        self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['status'],'cancelled')


if __name__=='__main__':unittest.main()
