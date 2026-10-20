"""Portable tests use tiny generated images and never touch research datasets."""
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_index
from dataset_config import normalize_config


def png(path, width=8, height=4):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    content = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress((b"\x00" + bytes(width * 3)) * height)) + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def record(relative):
    path = Path(relative)
    return {"relative": relative, "name": path.name, "stem": path.stem}


class IndexerTests(unittest.TestCase):
    def setUp(self):
        temporary_parent = Path(__file__).resolve().parents[1] / "local" / "test-tmp"
        temporary_parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=str(temporary_parent))
        # macOS /var and /tmp can be linked; actual selected roots must be real.
        self.root = Path(self.temporary.name).resolve()
        self.prediction = self.root / "方法 A"
        self.reference = self.root / "reference images"
        self.prediction.mkdir()
        self.reference.mkdir()
        self.config = {"schema": 2, "dataset": "可视化测试", "datasetId": str(uuid.uuid4()),
                       "referenceId": "m-reference",
                       "methods": [{"id": "m-model", "name": "算法 A", "root": str(self.prediction)},
                                   {"id": "m-reference", "name": "Input", "root": str(self.reference)}]}
        self.output = self.root / "output"

    def tearDown(self):
        self.temporary.cleanup()

    def build(self):
        return build_index.build(self.config, self.output)

    def test_normalize_and_display_name_does_not_rename_directory(self):
        self.config["methods"][0]["name"] = " 新的论文标题 "
        result = normalize_config(self.config)
        self.assertEqual(result["methods"][0]["name"], "新的论文标题")
        self.assertEqual(result["methods"][0]["id"], "m-model")
        self.assertTrue(self.prediction.is_dir())

    def test_invalid_configuration_fields(self):
        changes = [("schema", 1), ("dataset", " "), ("dataset", "A" * 101),
                   ("datasetId", "not-a-uuid"), ("referenceId", "unknown")]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(self.config)
                data[key] = value
                with self.assertRaises(ValueError):
                    normalize_config(data)

    def test_method_count_id_and_name_validation(self):
        cases = [self.config["methods"][:1], self.config["methods"] * 13]
        duplicate = copy.deepcopy(self.config["methods"])
        duplicate[1]["id"] = duplicate[0]["id"]
        cases.append(duplicate)
        for field, value in [("id", "../escape"), ("name", ""), ("name", "A" * 61), ("name", "line\nname")]:
            invalid = copy.deepcopy(self.config["methods"])
            invalid[0][field] = value
            cases.append(invalid)
        for methods in cases:
            with self.subTest(methods=methods):
                data = copy.deepcopy(self.config)
                data["methods"] = methods
                with self.assertRaises(ValueError):
                    normalize_config(data)

    def test_no_relative_missing_or_filesystem_root(self):
        for value in ["relative/path", str(self.root / "does-not-exist"), self.root.anchor]:
            with self.subTest(path=value):
                data = copy.deepcopy(self.config)
                data["methods"][0]["root"] = value
                with self.assertRaises(ValueError):
                    normalize_config(data)

    def test_symlink_directory_rejected(self):
        linked = self.root / "linked"
        try:
            linked.symlink_to(self.prediction, target_is_directory=True)
        except OSError:
            self.skipTest("Current Windows account cannot create directory symlinks")
        data = copy.deepcopy(self.config)
        data["methods"][0]["root"] = str(linked)
        with self.assertRaises(ValueError):
            normalize_config(data)

    def test_canonical_ancestor_alias_allowed_like_macos_var(self):
        selected = self.root / "system-alias" / "actual-selection"
        data = copy.deepcopy(self.config)
        data["methods"][0]["root"] = str(selected)
        real_lstat, real_resolve = Path.lstat, Path.resolve

        def lstat(path, *args, **kwargs):
            if path == selected:
                return real_lstat(self.prediction)
            if path == selected.parent:
                raise AssertionError("A macOS system ancestor alias must not be rejected")
            return real_lstat(path, *args, **kwargs)

        def resolve(path, *args, **kwargs):
            return self.prediction if path == selected else real_resolve(path, *args, **kwargs)

        with mock.patch.object(Path, "lstat", lstat), mock.patch.object(Path, "resolve", resolve):
            result = normalize_config(data)
        self.assertEqual(result["methods"][0]["root"], str(self.prediction))

    def test_mounted_volume_root_rejected_like_macos_external_disk(self):
        # POSIX external volumes are mounted below /Volumes, not at Path.anchor.
        with mock.patch("dataset_config.os.path.ismount", return_value=True):
            with self.assertRaises(ValueError):
                normalize_config(self.config)

    def test_reference_may_be_any_column_and_unique_extension_fallback(self):
        png(self.reference / "001.jpg")
        png(self.prediction / "001.png")
        manifest, audit = self.build()
        self.assertEqual(manifest["referenceId"], "m-reference")
        self.assertEqual(manifest["samples"][0]["matches"], ["stem", "reference"])
        self.assertEqual(manifest["samples"][0]["aspectRatio"], 2)
        self.assertEqual(audit["methods"][0]["matched"], 1)
        self.assertEqual(audit["missing"], 0)

    def test_relative_match_precedes_duplicate_basename(self):
        png(self.reference / "a" / "same.png")
        png(self.prediction / "a" / "same.png")
        png(self.prediction / "b" / "same.png")
        manifest, audit = self.build()
        self.assertEqual(manifest["samples"][0]["images"][0]["relative"], "a/same.png")
        self.assertEqual(manifest["samples"][0]["matches"][0], "relative")
        self.assertTrue(audit["methods"][0]["namingConflicts"]["name"])

    def test_ambiguous_basename_is_missing_not_guessed_stem(self):
        png(self.reference / "sample.png")
        png(self.prediction / "a" / "sample.png")
        png(self.prediction / "b" / "sample.png")
        manifest, audit = self.build()
        self.assertIsNone(manifest["samples"][0]["images"][0])
        self.assertEqual(manifest["samples"][0]["matches"][0], "conflict-name")
        self.assertEqual(audit["methods"][0]["conflicts"], 1)

    def test_duplicate_extensions_ambiguous_stem(self):
        png(self.reference / "sample.jpeg")
        png(self.prediction / "sample.png")
        png(self.prediction / "sample.jpg")
        manifest, audit = self.build()
        self.assertIsNone(manifest["samples"][0]["images"][0])
        self.assertEqual(manifest["samples"][0]["matches"][0], "conflict-stem")

    def test_missing_never_matches_other_sorted_image(self):
        png(self.reference / "001.png")
        png(self.reference / "002.png")
        png(self.prediction / "001.png")
        png(self.prediction / "003.png")
        manifest, audit = self.build()
        self.assertIsNone(manifest["samples"][1]["images"][0])
        self.assertEqual(audit["methods"][0]["missing"], 1)

    def test_case_only_not_silently_matched(self):
        found, kind = build_index.match(record("car.jpg"), build_index.lookup([record("CAR.png")]))
        self.assertIsNone(found)
        self.assertEqual(kind, "case-mismatch")

    def test_case_collision_rejected_even_for_exact_spelling(self):
        found, kind = build_index.match(record("car.png"), build_index.lookup([record("car.png"), record("CAR.png")]))
        self.assertIsNone(found)
        self.assertEqual(kind, "conflict-relative")

    def test_unique_unicode_normalization_supported_but_collision_rejected(self):
        source = record("caf\u00e9.png")
        found, kind = build_index.match(source, build_index.lookup([record("cafe\u0301.png")]))
        self.assertEqual(kind, "unicode-relative")
        self.assertIsNotNone(found)
        found, kind = build_index.match(source, build_index.lookup([source, record("cafe\u0301.png")]))
        self.assertIsNone(found)
        self.assertEqual(kind, "conflict-relative")

    def test_source_bytes_untouched_and_outputs_are_local(self):
        png(self.reference / "中文 空格.png")
        png(self.prediction / "中文 空格.png")
        sources = [self.reference / "中文 空格.png", self.prediction / "中文 空格.png"]
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources]
        manifest, audit = self.build()
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources])
        self.assertEqual(set(path.name for path in self.output.iterdir()),
                         {"manifest.js", "index_audit.json", "index_audit.md"})
        payload = (self.output / "manifest.js").read_text(encoding="utf-8")
        restored = json.loads(payload[len("window.RGBT_MANIFEST = "):-2])
        self.assertEqual(restored["datasetId"], self.config["datasetId"])
        self.assertEqual(restored["samples"][0]["id"], "中文 空格.png")

    def test_index_fingerprint_changes_on_display_metadata_and_is_stable_otherwise(self):
        png(self.reference / "001.png")
        png(self.prediction / "001.png")
        first, _ = self.build()
        second, _ = self.build()
        self.assertEqual(first["indexId"], second["indexId"])
        self.config["methods"][0]["name"] = "Renamed only in UI"
        third, _ = self.build()
        self.assertNotEqual(first["indexId"], third["indexId"])
        self.assertEqual(first["datasetId"], third["datasetId"])

    def test_no_index_writes_inside_original_roots(self):
        png(self.reference / "001.png")
        with self.assertRaises(ValueError):
            build_index.build(self.config, self.prediction / "new-output")
        self.assertFalse((self.prediction / "new-output").exists())

    def test_empty_reference_rejected_and_other_empty_method_is_missing(self):
        with self.assertRaises(ValueError):
            self.build()
        png(self.reference / "001.png")
        manifest, audit = self.build()
        self.assertIsNone(manifest["samples"][0]["images"][0])
        self.assertEqual(audit["methods"][0]["images"], 0)

    def test_header_sampling_bounded_and_ratio_fallback(self):
        for index in range(80):
            png(self.reference / ("{:03d}.png".format(index)), 6, 2)
        records, errors = build_index.scan(self.config["methods"][1])
        self.assertLessEqual(sum(bool(item.get("headerChecked")) for item in records), 36)
        self.assertTrue(any(item["size"] is None for item in records))
        manifest, audit = self.build()
        self.assertTrue(all(sample["aspectRatio"] == 3 for sample in manifest["samples"]))
        self.assertEqual(audit["methods"][1]["typicalSize"], [6, 2])

    def test_corrupt_header_does_not_abort_index(self):
        (self.reference / "bad.png").write_bytes(b"not an image")
        (self.prediction / "bad.png").write_bytes(b"not an image")
        manifest, audit = self.build()
        self.assertEqual(manifest["samples"][0]["aspectRatio"], 1)
        self.assertEqual(audit["methods"][1]["unknownHeaders"], ["bad.png"])

    def test_malformed_jpeg_header_is_bounded(self):
        class TrackingStream(io.BytesIO):
            def __init__(self, content):
                super().__init__(content)
                self.bytes_read = 0

            def read(self, count=-1):
                value = super().read(count)
                self.bytes_read += len(value)
                return value

        stream = TrackingStream(b"\xff\xd8" + b"\xff" * 400000)
        with mock.patch("builtins.open", return_value=stream):
            self.assertIsNone(build_index.dimensions("malformed.jpg"))
        # Initial 32-byte probe overlaps the bounded JPEG marker pass by 30.
        self.assertLessEqual(stream.bytes_read, 262144 + 30)

    def test_progress_and_cli(self):
        png(self.reference / "001.png")
        events = []
        build_index.build(self.config, self.output, events.append)
        self.assertEqual(events[-1]["phase"], "done")
        self.assertEqual(events[-1]["completed"], 1)
        private = self.root / "config.json"
        private.write_text(json.dumps(self.config), encoding="utf-8")
        result = subprocess.run([sys.executable, str(Path(build_index.__file__)), "--config", str(private),
                                 "--output", str(self.root / "cli-output")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "cli-output" / "manifest.js").is_file())


if __name__ == "__main__":
    unittest.main()
