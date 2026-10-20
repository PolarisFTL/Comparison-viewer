"""Public archives must not accidentally include local research workspaces."""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'public_package', Path(__file__).resolve().parents[1] / 'scripts' / 'package_public.py')
public_package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(public_package)


class PublicPackageTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / 'local' / 'test-tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(temp_root))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('server.py', 'index.html', 'setup.html', 'README.md', 'LICENSE',
                     'Start-Windows.bat', 'Start-macOS.command'):
            (self.root / name).write_text('public source\n', encoding='utf-8')

    def test_runtime_data_and_unlisted_assets_are_not_packaged(self):
        for name in ('local/config.json', 'local/workspaces/db.sqlite3',
                     'assets/private-experiment.png', 'exports/private.png',
                     'tests/private-result.json'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('private marker', encoding='utf-8')
        archive, count, digest = public_package.package(self.root)
        with zipfile.ZipFile(archive) as reader:
            members = reader.namelist()
            self.assertEqual(count, 7)
            self.assertFalse(any('local/' in name or 'private' in name for name in members))
            command = reader.getinfo('RGBT-Comparison-Viewer/Start-macOS.command')
            self.assertEqual((command.external_attr >> 16) & 0o777, 0o755)
        self.assertEqual(len(digest), 64)
        self.assertTrue(archive.with_suffix('.zip.sha256').is_file())

    def test_private_path_in_public_source_is_rejected(self):
        path = 'D:' + '\\' + 'phd' + '\\' + 'private-research'
        (self.root / 'server.py').write_text(path, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Potential private content'):
            public_package.collect(self.root)

    def test_actual_user_profile_is_rejected_but_template_allowed(self):
        template = self.root / 'examples' / 'config.example.json'
        template.parent.mkdir()
        template.write_text('{"root":"/Users/YOUR_NAME/YOUR_DATA/Input"}', encoding='utf-8')
        public_package.collect(self.root)
        template.write_text('/' + 'Users/' + 'ActualPerson/private-data', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Potential private content'):
            public_package.collect(self.root)

    def test_missing_startup_entry_is_rejected(self):
        (self.root / 'Start-macOS.command').unlink()
        with self.assertRaisesRegex(ValueError, 'Required public file missing'):
            public_package.collect(self.root)

    def test_file_protocol_is_not_mistaken_for_a_windows_drive(self):
        (self.root/'README.md').write_text('file:///Users/YOUR_NAME/images\nfile:///Users/',encoding='utf-8')
        public_package.collect(self.root)

    def test_copied_access_card_is_rejected(self):
        value = '{"code":"' + 'a' * 6 + '-' + 'b' * 6 + '"}'
        (self.root / 'README.md').write_text(value, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Potential private content'):
            public_package.collect(self.root)


if __name__ == '__main__':
    unittest.main()
