"""Private state identity and shared credential revocation regression tests."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collaboration import Store
from demo_data import generate_demo
from workspace_state import Snapshot, Workspace


class StateIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        private = ROOT / 'local' / 'test-tmp'
        private.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='state-integration-', dir=str(private))
        cls.folder = Path(cls.temporary.name)
        cls.demo = generate_demo(cls.folder / 'source-fixtures', count=2)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.local = self.folder / self._testMethodName

    def workspace(self):
        workspace = Workspace(self.local)
        config = copy.deepcopy(self.demo)
        config['methods'] = config['methods'][:2]
        job_id = workspace.start_build(config)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = workspace.job(job_id)
            if job['status'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(job['status'], 'done', job)
        return workspace

    def test_two_store_instances_share_rotation_and_session_revocation(self):
        folder = self.local / 'collaboration'
        one = Store(folder, ['sample-a'], dataset='Fixture', dataset_id='fixture-a')
        two = Store(folder, ['sample-a'], dataset='Fixture', dataset_id='fixture-a')
        self.assertIs(one.lock, two.lock)
        old_code = one.access['code']
        identity = two.login(old_code, 'Reviewer A')
        one.write_many(identity['id'], [{'sample': 'sample-a', 'revision': 0, 'patch': {'favorite': True, 'note': 'Keep this note'}}])
        self.assertIsNotNone(one.session(identity['session']))
        new_code = one.rotate_access()
        self.assertNotEqual(new_code, old_code)
        self.assertEqual(two.access['code'], new_code)
        self.assertIsNone(two.session(identity['session']))
        with self.assertRaises(PermissionError):
            two.login(old_code, 'Reviewer B')
        restored = two.login(new_code, 'Reviewer A', identity['recovery'])
        self.assertEqual(restored['id'], identity['id'])
        self.assertEqual(two.workspace(identity['id'])['marks']['sample-a']['note'], 'Keep this note')

    def test_login_waiting_on_another_instance_rotation_uses_new_code(self):
        folder = self.local / 'collaboration'
        one = Store(folder, ['sample-a'])
        two = Store(folder, ['sample-a'])
        old_code = one.access['code']
        started, finished = threading.Event(), threading.Event()
        outcome = []
        def login():
            started.set()
            try:
                two.login(old_code, 'Reviewer A')
                outcome.append('accepted')
            except PermissionError:
                outcome.append('revoked')
            finally:
                finished.set()
        with one.lock:
            worker = threading.Thread(target=login)
            worker.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(finished.wait(.05))
            one.rotate_access()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, ['revoked'])

    def test_repeated_snapshots_share_fresh_access_and_keep_records(self):
        workspace = self.workspace()
        first = workspace.snapshot()
        second = Snapshot(copy.deepcopy(first.manifest), copy.deepcopy(first.audit), first.folder, self.local)
        self.assertIs(first.store.lock, second.store.lock)
        identity = first.store.login(first.store.access['code'], 'Reviewer A')
        sample = first.manifest['samples'][0]['id']
        first.store.write_many(identity['id'], [{'sample': sample, 'revision': 0, 'patch': {'reviewed': True}}])
        new_code = second.store.rotate_access()
        self.assertEqual(first.store.access['code'], new_code)
        self.assertIsNone(first.store.session(identity['session']))
        self.assertTrue(second.store.workspace(identity['id'])['marks'][sample]['reviewed'])
        reopened = Workspace(self.local)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.snapshot().store.access['code'], new_code)

    def test_manifest_with_wrong_identity_is_rejected_on_reopen(self):
        workspace = self.workspace()
        snapshot = workspace.snapshot()
        manifest_file = snapshot.folder / 'manifest.js'
        original = manifest_file.read_bytes()
        changes = {'datasetId': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                   'indexId': '000000000000000000000000',
                   'dataset': 'Copied from another dataset'}
        try:
            for field, value in changes.items():
                with self.subTest(field=field):
                    changed = copy.deepcopy(snapshot.manifest)
                    changed[field] = value
                    manifest_file.write_text('window.RGBT_MANIFEST = ' + json.dumps(changed) + ';', encoding='utf-8')
                    reopened = Workspace(self.local)
                    self.assertIsNone(reopened.snapshot())
                    self.assertIn('identity', reopened.error)
        finally:
            manifest_file.write_bytes(original)
        self.assertIsNotNone(Workspace(self.local).snapshot())

    def test_active_pointer_copied_from_other_dataset_is_rejected(self):
        workspace = self.workspace()
        pointer = self.local / 'active.json'
        original = pointer.read_bytes()
        changed = {'datasetId': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'indexId': workspace.snapshot().index_id}
        try:
            pointer.write_text(json.dumps(changed), encoding='utf-8')
            reopened = Workspace(self.local)
            self.assertIsNone(reopened.snapshot())
            self.assertIn('pointer', reopened.error)
        finally:
            pointer.write_bytes(original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
