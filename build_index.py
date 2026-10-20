"""Read-only portable image indexer. Never decodes or changes source images."""
import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import time
import unicodedata

from dataset_config import normalize_config

ROOT = Path(__file__).resolve().parent
EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".avif"}
KEYS = ("relative", "name", "stem")


def dimensions(path):
    """Read a bounded header only; unknown/unsupported headers return None."""
    try:
        with open(str(path), "rb") as stream:
            header = stream.read(32)
            size = None
            if header[:8] == b"\x89PNG\r\n\x1a\n":
                size = list(struct.unpack(">II", header[16:24]))
            elif header[:6] in (b"GIF87a", b"GIF89a"):
                size = list(struct.unpack("<HH", header[6:10]))
            elif header[:2] == b"BM":
                size = [abs(value) for value in struct.unpack("<ii", header[18:26])]
            elif header[:2] == b"\xff\xd8":
                stream.seek(2)
                while stream.tell() < 262144:
                    marker = stream.read(1)
                    if not marker:
                        break
                    if marker != b"\xff":
                        continue
                    while marker == b"\xff" and stream.tell() < 262144:
                        marker = stream.read(1)
                    if not marker or marker in (b"\xda", b"\xd9") or stream.tell() + 2 > 262144:
                        break
                    if marker[0] in (0x01, 0xd8) or 0xd0 <= marker[0] <= 0xd7:
                        continue
                    length = struct.unpack(">H", stream.read(2))[0]
                    if marker[0] in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
                        if length < 7 or stream.tell() + 5 > 262144:
                            break
                        height, width = struct.unpack(">HH", stream.read(5)[1:5])
                        size = [width, height]
                        break
                    if length < 2:
                        break
                    stream.seek(length - 2, 1)
            elif header[:4] == b"RIFF" and header[8:12] == b"WEBP":
                if header[12:16] == b"VP8X":
                    size = [1 + int.from_bytes(header[24:27], "little"), 1 + int.from_bytes(header[27:30], "little")]
                elif header[12:16] == b"VP8 ":
                    stream.seek(26)
                    size = [value & 0x3fff for value in struct.unpack("<HH", stream.read(4))]
                elif header[12:16] == b"VP8L":
                    value = int.from_bytes(header[21:25], "little")
                    size = [(value & 0x3fff) + 1, ((value >> 14) & 0x3fff) + 1]
            return size if size and min(size) > 0 else None
    except (OSError, ValueError, struct.error, IndexError):
        return None


def natural(value):
    # Typed components avoid comparing int with str for dissimilar filenames.
    return [(0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r"(\d+)", value)] + [(2, value)]


def scan(method):
    """List names/stats recursively, skipping symlinks and Windows junctions."""
    root = Path(method["root"])
    records, errors = [], []
    pending = [root]
    while pending:
        parent = pending.pop()
        try:
            with os.scandir(str(parent)) as entries:
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                            errors.append("Skipped symbolic link/junction: " + str(Path(entry.path).relative_to(root)))
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            pending.append(Path(entry.path))
                        elif stat.S_ISREG(info.st_mode):
                            path = Path(entry.path)
                            if path.suffix.lower() not in EXTENSIONS:
                                continue
                            records.append({"name": entry.name, "stem": path.stem,
                                            "relative": path.relative_to(root).as_posix(),
                                            "path": str(path), "bytes": info.st_size,
                                            "mtimeNs": info.st_mtime_ns, "size": None})
                    except OSError as exc:
                        errors.append("{}: {}".format(entry.name, exc))
        except OSError as exc:
            errors.append("{}: {}".format(parent, exc))
    records.sort(key=lambda record: natural(record["relative"]))
    selected = {int(index * (len(records) - 1) / 31) for index in range(32)} if records else set()
    selected.update(sorted(range(len(records)), key=lambda index: records[index]["bytes"], reverse=True)[:4])
    for index in selected:
        records[index]["headerChecked"] = True
        records[index]["size"] = dimensions(records[index]["path"])
    return records, errors


def _nfc(value):
    return unicodedata.normalize("NFC", value)


def lookup(records):
    tables = {kind: {key: collections.defaultdict(list) for key in KEYS}
              for kind in ("exact", "normalized", "portable")}
    for record in records:
        for key in KEYS:
            raw = record[key]
            tables["exact"][key][raw].append(record)
            tables["normalized"][key][_nfc(raw)].append(record)
            tables["portable"][key][_nfc(raw).casefold()].append(record)
    return tables


def match(source, tables):
    """Use relative/name/stem priority; ambiguity stops instead of guessing.

    Unique Unicode NFC-equivalent spelling is safe on macOS. Case-only spelling
    differences are never silently matched. Case/normalization collisions are
    rejected even where an exact spelling also exists in that candidate group.
    """
    case_mismatch = False
    for key in KEYS:
        raw = source[key]
        portable = tables["portable"][key].get(_nfc(raw).casefold(), [])
        if len(portable) > 1:
            return None, "conflict-" + key
        candidates = tables["exact"][key].get(raw, [])
        if len(candidates) == 1:
            return candidates[0], key
        normalized = tables["normalized"][key].get(_nfc(raw), [])
        if len(normalized) == 1:
            return normalized[0], "unicode-" + key
        if portable:
            case_mismatch = True
    return None, "case-mismatch" if case_mismatch else "missing"


def _collisions(tables):
    return {key: {folded: [record["relative"] for record in group]
                  for folded, group in tables["portable"][key].items() if len(group) > 1}
            for key in KEYS}


def _notify(callback, **event):
    if callback:
        callback(event)


def _atomic_text(path, content):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(str(temporary), str(path))


def _audit_markdown(audit):
    def safe(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["# {} 数据审计".format(safe(audit["dataset"])), "",
             "生成时间：{}".format(audit["created"]), "",
             "基准方法：`{}`。匹配依次使用唯一相对文件名、完整文件名和主文件名；不会按排序位置配对。".format(audit["referenceId"]), "",
             "大小写不同不会自动匹配；Unicode NFC 等价名称仅在唯一时匹配。任何候选层的大小写／Unicode 冲突均拒绝匹配。", "",
             "| 方法 | 图片数 | 匹配 | 缺失（含冲突） | 冲突 | 格式 | 抽样尺寸 |",
             "|---|---:|---:|---:|---:|---|---|"]
    for method in audit["methods"]:
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            safe(method["name"]), method["images"], method["matched"], method["missing"],
            method["conflicts"], safe(method["extensions"]), safe(method["dimensions"])))
    lines.extend(["", "样本：{}；图片文件：{}；索引用时：{} 秒。".format(
        audit["samples"], audit["totalImages"], audit["seconds"]), "",
        "每组最多抽查 32 个均匀分布文件与 4 个最大文件的文件头，不解码像素。所有文件检查字节大小；未抽样文件的尺寸和完整性没有被全量验证。",
        "异常阈值：已抽样单边 >8192、像素 >4000 万，或任意文件 >50 MiB。TIFF 等格式可能不受当前浏览器解码器支持，失败时应显示占位并支持重试。", ""])
    for method in audit["methods"]:
        lines.extend(["## " + safe(method["name"]), "", "本机目录：`{}`".format(method["root"]), "",
                      "匹配统计：`{}`".format(method["matchKinds"]), "",
                      "名称冲突：", "```json", json.dumps(method["namingConflicts"], ensure_ascii=False, indent=2), "```", "",
                      "未知／损坏文件头：`{}`".format(method["unknownHeaders"]), "",
                      "异常大文件：`{}`".format(method["large"]), "",
                      "扫描异常：`{}`".format(method["errors"]), ""])
    if audit["missingSamples"]:
        lines.extend(["## 缺失与冲突样本", "", "```json",
                      json.dumps(audit["missingSamples"], ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def build(config, output_dir=None, progress=None):
    """Build an index and audit, returning (manifest, audit).

    progress receives small event dictionaries, never image pixels. The default
    output is local/indexes/<datasetId>; callers may provide another directory.
    """
    started = time.perf_counter()
    config = normalize_config(config)
    methods = config["methods"]
    output = Path(output_dir) if output_dir is not None else ROOT / "local" / "indexes" / config["datasetId"]
    output = output.resolve()
    for method in methods:
        source_root = Path(method["root"])
        if output == source_root or source_root in output.parents:
            raise ValueError("Index output must be outside every source image directory")
    all_records, audits, tables = [], [], []
    for index, method in enumerate(methods):
        _notify(progress, phase="scan", methodId=method["id"], completed=index,
                total=len(methods), message="Scanning " + method["name"])
        records, errors = scan(method)
        table = lookup(records)
        all_records.append(records)
        tables.append(table)
        sizes = collections.Counter(tuple(record["size"]) for record in records if record["size"])
        typical = list(sizes.most_common(1)[0][0]) if sizes else None
        naming_conflicts = _collisions(table)
        audits.append({
            "id": method["id"], "method": method["name"], "name": method["name"], "root": method["root"],
            "exists": True, "images": len(records),
            "extensions": dict(collections.Counter(Path(record["name"]).suffix.lower() for record in records)),
            "dimensions": dict(collections.Counter("{}x{}".format(*record["size"]) if record["size"] else "unknown"
                                                   for record in records if record.get("headerChecked"))),
            "typicalSize": typical,
            "headersChecked": sum(bool(record.get("headerChecked")) for record in records),
            "unknownHeaders": [record["relative"] for record in records if record.get("headerChecked") and not record["size"]],
            "nested": sum("/" in record["relative"] for record in records),
            "namingConflicts": naming_conflicts,
            "namingConflictGroups": sum(len(groups) for groups in naming_conflicts.values()),
            "duplicateStems": naming_conflicts["stem"],
            "large": [{"file": record["relative"], "size": record["size"], "bytes": record["bytes"]}
                      for record in records if record["bytes"] > 50 * 1024 * 1024 or (record["size"] and
                      (max(record["size"]) > 8192 or record["size"][0] * record["size"][1] > 40000000))],
            "errors": errors, "matched": 0, "missing": 0, "conflicts": 0, "matchKinds": {},
        })
    reference_index = next(index for index, method in enumerate(methods) if method["id"] == config["referenceId"])
    reference = all_records[reference_index]
    if not reference:
        raise ValueError("The reference directory contains no supported image files")
    typical = audits[reference_index]["typicalSize"]
    fallback_ratio = typical[0] / typical[1] if typical else 1
    samples = []
    _notify(progress, phase="match", completed=0, total=len(reference), message="Matching sample filenames")
    for sample_index, source in enumerate(reference):
        images, kinds = [], []
        for method_index, table in enumerate(tables):
            record, kind = (source, "reference") if method_index == reference_index else match(source, table)
            images.append({"relative": record["relative"], "size": record["size"], "bytes": record["bytes"]} if record else None)
            kinds.append(kind)
            method_audit = audits[method_index]
            method_audit["matched" if record else "missing"] += 1
            if kind.startswith("conflict-"):
                method_audit["conflicts"] += 1
            method_audit["matchKinds"][kind] = method_audit["matchKinds"].get(kind, 0) + 1
        samples.append({"id": source["relative"], "name": source["name"], "stem": source["stem"],
                        "aspectRatio": source["size"][0] / source["size"][1] if source["size"] else fallback_ratio,
                        "images": images, "matches": kinds,
                        "missing": [methods[index]["id"] for index, image in enumerate(images) if image is None]})
        if sample_index % 500 == 0:
            _notify(progress, phase="match", completed=sample_index + 1, total=len(reference), message="Matching sample filenames")
    created = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    fingerprint = hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    for method, records in zip(methods, all_records):
        fingerprint.update(method["id"].encode("utf-8"))
        for record in records:
            fingerprint.update(json.dumps([record["relative"], record["bytes"], str(record["mtimeNs"])], ensure_ascii=False).encode("utf-8"))
    index_id = fingerprint.hexdigest()[:24]
    audit = {
        "schema": 2, "dataset": config["dataset"], "datasetId": config["datasetId"],
        "referenceId": config["referenceId"], "created": created, "indexId": index_id,
        "samples": len(samples), "totalImages": sum(len(records) for records in all_records),
        "methods": audits, "seconds": round(time.perf_counter() - started, 3),
        "matched": sum(method["matched"] for method in audits),
        "missing": sum(method["missing"] for method in audits),
        "conflicts": sum(method["conflicts"] for method in audits),
        "matching": "Unique relative filename, then unique full filename, then unique stem; exact case or unique NFC equivalent; ambiguity rejected; never sort position",
        "headerPolicy": "Up to 32 evenly distributed + 4 largest image headers per method; no pixel decoding; every file byte size checked",
        "missingSamples": [{"id": sample["id"], "methods": sample["missing"],
                            "reasons": {methods[index]["id"]: kind for index, kind in enumerate(sample["matches"]) if sample["images"][index] is None}}
                           for sample in samples if sample["missing"]],
    }
    manifest = {"version": 2, "datasetId": config["datasetId"], "dataset": config["dataset"],
                "referenceId": config["referenceId"], "indexId": index_id, "created": created,
                "methods": methods, "samples": samples,
                "audit": {key: audit[key] for key in ("totalImages", "seconds", "matched", "missing", "conflicts")}}
    manifest["audit"]["methods"] = [{key: method[key] for key in ("id", "name", "images", "matched", "missing", "conflicts")}
                                     for method in audits]
    _notify(progress, phase="write", completed=len(reference), total=len(reference), message="Writing local index")
    output.mkdir(parents=True, exist_ok=True)
    _atomic_text(output / "manifest.js", "window.RGBT_MANIFEST = " + json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + ";\n")
    _atomic_text(output / "index_audit.json", json.dumps(audit, ensure_ascii=False, indent=2))
    _atomic_text(output / "index_audit.md", _audit_markdown(audit))
    _notify(progress, phase="done", completed=len(reference), total=len(reference), message="Index ready")
    return manifest, audit


if __name__ == "__main__":
    # A Windows console or redirected pipe can inherit cp1252. Progress includes
    # user-provided Unicode names, so the CLI always emits UTF-8, even to pipes.
    # Keep this inside the entry point: importing/building in the GUI must not
    # change the host process's streams. Escape lone surrogates safely if present.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Build a read-only image comparison index from a local schema-2 configuration")
    parser.add_argument("--config", type=Path, required=True, help="Private dataset JSON configuration")
    parser.add_argument("--output", type=Path, help="Output directory (default: local/indexes/<datasetId>)")
    args = parser.parse_args()
    try:
        configuration = json.loads(args.config.read_text(encoding="utf-8-sig"))
        manifest, audit = build(configuration, args.output,
                                progress=lambda event: print(event["message"], flush=True))
        print("Samples: {}; images: {}; missing: {}; conflicts: {}; seconds: {}".format(
            audit["samples"], audit["totalImages"], audit["missing"], audit["conflicts"], audit["seconds"]))
    except (ValueError, OSError) as exc:
        parser.exit(2, "Index build failed: {}\n".format(exc))
